use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const QUESTION_MAX: usize = 500;
pub const ANSWER_MAX: usize = 2000;
pub const CONTACT_MAX: usize = 200;
pub const RETENTION_PENDING: i64 = 400;
pub const RETENTION_DRAFT: i64 = 200;
pub const RETENTION_PUBLISHED: i64 = 200;
pub const RETENTION_REJECTED: i64 = 400;
pub const RATE_MAX: i64 = 25;
pub const RATE_WINDOW_MS: i64 = 600_000;

#[derive(Deserialize)]
pub struct Submit {
    question: Option<String>,
    contact: Option<String>,
    ip: Option<String>,
}

async fn enabled(pool: &PgPool, user_id: &Uuid) -> bool {
    feature_on(pool, user_id, "asks").await.0
}

pub async fn submit(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<Submit>,
) -> ApiResult {
    if !enabled(&pool, &user_id).await {
        return Err(err(StatusCode::FORBIDDEN, "feature_off"));
    }
    let accept_new = match read_config(&pool, &user_id).await {
        Some(c) => c
            .get("settings")
            .and_then(|s| s.get("asksAcceptNew"))
            .and_then(|v| v.as_bool())
            .unwrap_or(true),
        None => true,
    };
    if !accept_new {
        return Err(err(StatusCode::FORBIDDEN, "accept_new_off"));
    }
    let ip = body.ip.clone().unwrap_or_else(|| "?".to_string());
    rate_limit(&pool, &user_id, "asks_submit", &scope_key(&ip), RATE_WINDOW_MS, RATE_MAX).await?;

    let question = body.question.unwrap_or_default().trim().to_string();
    let contact = body.contact.unwrap_or_default().trim().to_string();
    if question.is_empty() || question.chars().count() > QUESTION_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_question",
            "Question is required.",
        ));
    }
    if contact.chars().count() > CONTACT_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_contact",
            "Contact is too long.",
        ));
    }

    let id = new_uuid();
    sqlx::query(
        "INSERT INTO feature_asks (id, user_id, status, question, contact) VALUES ($1,$2,'pending',$3,$4)",
    )
    .bind(id)
    .bind(user_id)
    .bind(&question)
    .bind(if contact.is_empty() { None } else { Some(contact.as_str()) })
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    // Retention trimming is a write; keep it on the submit path, not the public read path.
    trim_retention(&pool, &user_id).await;
    ok(json!({ "ok": true, "id": id }))
}

async fn trim_retention(pool: &PgPool, user_id: &Uuid) {
    for (status, cap) in [
        ("pending", RETENTION_PENDING),
        ("draft", RETENTION_DRAFT),
        ("published", RETENTION_PUBLISHED),
        ("rejected", RETENTION_REJECTED),
    ] {
        let _ = sqlx::query(
            "DELETE FROM feature_asks WHERE id IN (
                SELECT id FROM feature_asks WHERE user_id=$1 AND status=$2
                ORDER BY submitted_at DESC OFFSET $3
            )",
        )
        .bind(user_id)
        .bind(status)
        .bind(cap)
        .execute(pool)
        .await;
    }
}

pub async fn list(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    if !enabled(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let rows: Vec<(String, String, Option<String>, chrono::DateTime<chrono::Utc>, i32)> = sqlx::query_as(
        "SELECT question, COALESCE(public_id, id::text), answer, published_at, order_idx
         FROM feature_asks WHERE user_id=$1 AND status='published' ORDER BY order_idx ASC",
    )
    .bind(user_id)
    .fetch_all(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(q, pid, ans, at, _idx)| {
            json!({ "id": pid, "question": q, "answer": ans, "published_at": at.to_rfc3339() })
        })
        .collect();
    ok(json!({ "asks": items }))
}

pub async fn inbox(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let rows: Vec<(Uuid, String, String, Option<String>, Option<String>, i32, chrono::DateTime<chrono::Utc>)> =
        sqlx::query_as(
            "SELECT id, status, question, answer, contact, order_idx, submitted_at
             FROM feature_asks WHERE user_id=$1 ORDER BY submitted_at DESC",
        )
        .bind(user_id)
        .fetch_all(&pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(id, status, q, ans, contact, idx, at)| {
            json!({ "id": id, "status": status, "question": q, "answer": ans, "contact": contact, "order_idx": idx, "submitted_at": at.to_rfc3339() })
        })
        .collect();
    ok(json!({ "asks": items }))
}

async fn load(pool: &PgPool, user_id: &Uuid, id: &Uuid) -> Result<(String, String, Option<String>, i32), (StatusCode, Json<Value>)> {
    let row: Option<(String, String, Option<String>, i32)> = sqlx::query_as(
        "SELECT status, question, answer, order_idx FROM feature_asks WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user_id)
    .fetch_optional(pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    row.ok_or_else(|| err(StatusCode::NOT_FOUND, "ask_not_found"))
}

pub async fn publish(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    let (status, question, answer, order_idx) = load(&pool, &user_id, &id).await?;
    if status == "published" {
        return ok(json!({ "ok": true, "id": id, "already": true }));
    }
    let answer_text = answer.clone().unwrap_or_default();
    if answer_text.is_empty() {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "answer_required",
            "Answer the question first.",
        ));
    }
    if answer_text.chars().count() > ANSWER_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "answer_too_long",
            "Answer is too long.",
        ));
    }
    if question.chars().count() > QUESTION_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "question_too_long",
            "Question is too long.",
        ));
    }
    let public_id = new_public_id();
    // MAX(order_idx) is INT4; decode it as i64 explicitly. Decoding INT4 straight into
    // i64 failed, `.ok()` swallowed the error, and every answer was published at order 0/1.
    let max_idx: i64 = sqlx::query_scalar(
        "SELECT COALESCE(MAX(order_idx), 0)::BIGINT FROM feature_asks WHERE user_id=$1 AND status='published'",
    )
    .bind(user_id)
    .fetch_one(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    // An answer that was published before (unpublished to edit) keeps its slot.
    let next_order = if order_idx > 0 { order_idx as i64 } else { max_idx + 1 };
    sqlx::query(
        "UPDATE feature_asks SET status='published', public_id=$3, order_idx=$4, version=version+1, published_at=NOW()
         WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user_id)
    .bind(&public_id)
    .bind(next_order)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    ok(json!({ "ok": true, "id": id, "public_id": public_id }))
}

pub async fn draft(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
    Json(body): Json<serde_json::Value>,
) -> ApiResult {
    let answer = body
        .get("answer")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let answer_text = answer.trim().to_string();
    if answer_text.chars().count() > ANSWER_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "answer_too_long",
            "Answer is too long.",
        ));
    }
    let affected = sqlx::query(
        "UPDATE feature_asks SET status='draft', answer=$3, version=version+1 WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user_id)
    .bind(if answer_text.is_empty() { None } else { Some(&answer_text) })
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if affected.rows_affected() == 0 {
        return Err(err(StatusCode::NOT_FOUND, "ask_not_found"));
    }
    ok(json!({ "ok": true, "id": id }))
}

pub async fn reject(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    set_status(&pool, &user_id, &id, "rejected").await
}

pub async fn remove(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    let affected = sqlx::query("DELETE FROM feature_asks WHERE id=$1 AND user_id=$2")
        .bind(id)
        .bind(user_id)
        .execute(&pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if affected.rows_affected() == 0 {
        return Err(err(StatusCode::NOT_FOUND, "ask_not_found"));
    }
    ok(json!({ "ok": true, "id": id }))
}

async fn set_status(
    pool: &PgPool,
    user_id: &Uuid,
    id: &Uuid,
    to: &str,
) -> ApiResult {
    let affected = sqlx::query("UPDATE feature_asks SET status=$3, version=version+1 WHERE id=$1 AND user_id=$2")
        .bind(id)
        .bind(user_id)
        .bind(to)
        .execute(pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if affected.rows_affected() == 0 {
        return Err(err(StatusCode::NOT_FOUND, "ask_not_found"));
    }
    ok(json!({ "ok": true, "id": id }))
}