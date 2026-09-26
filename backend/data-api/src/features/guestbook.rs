use super::helpers::*;
use axum::extract::{Json, Path, Query, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const NAME_MAX: usize = 40;
pub const MESSAGE_MAX: usize = 200;
pub const QUEUE_MAX: i64 = 500;
pub const VISIBLE_MAX: usize = 20;
pub const RATE_MAX: i64 = 30;
pub const RATE_WINDOW_MS: i64 = 600_000;

#[derive(Deserialize)]
pub struct Submit {
    // The FastAPI proxy historically sent `name`; accept both spellings.
    #[serde(alias = "name")]
    display_name: Option<String>,
    message: Option<String>,
    ip: Option<String>,
}

#[derive(Deserialize)]
pub struct ListQuery {
    page: Option<u32>,
    page_size: Option<u32>,
    status: Option<String>,
}

async fn config_values(pool: &PgPool, user_id: &Uuid) -> (bool, bool, bool) {
    let (enabled, settings) = feature_on(pool, user_id, "guestbook").await;
    let paused = settings
        .get("guestbookPaused")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let pinning = settings
        .get("guestbookPinning")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    (enabled, paused, pinning)
}

pub async fn submit(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<Submit>,
) -> ApiResult {
    let (enabled, paused, _) = config_values(&pool, &user_id).await;
    if !enabled {
        return Err(err(StatusCode::FORBIDDEN, "feature_off"));
    }
    if paused {
        return Err(err(StatusCode::FORBIDDEN, "intake_paused"));
    }
    let ip = body.ip.clone().unwrap_or_else(|| "?".to_string());
    let key = scope_key(&ip);
    rate_limit(&pool, &user_id, "guestbook_submit", &key, RATE_WINDOW_MS, RATE_MAX).await?;

    let name = body.display_name.unwrap_or_default().trim().to_string();
    let message = body.message.unwrap_or_default().trim().to_string();
    if name.is_empty() || name.chars().count() > NAME_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_display_name",
            "Display name is required.",
        ));
    }
    if message.is_empty() || message.chars().count() > MESSAGE_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_message",
            "Message is required.",
        ));
    }

    let pending: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM feature_guestbook WHERE user_id=$1 AND status='pending'")
            .bind(user_id)
            .fetch_one(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if pending >= QUEUE_MAX {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "queue_full",
            "The guestbook is full, come back later.",
        ));
    }

    let id = new_uuid();
    sqlx::query(
        "INSERT INTO feature_guestbook (id, user_id, status, display_name, message) VALUES ($1,$2,'pending',$3,$4)",
    )
    .bind(id)
    .bind(user_id)
    .bind(&name)
    .bind(&message)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    ok(json!({ "ok": true, "id": id }))
}

pub async fn list(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Query(q): Query<ListQuery>,
) -> ApiResult {
    let (enabled, _, _) = config_values(&pool, &user_id).await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let page_size = q.page_size.map(|v| v.clamp(1, VISIBLE_MAX as u32) as usize).unwrap_or(VISIBLE_MAX);
    let page = q.page.unwrap_or(1).max(1);
    let offset = ((page - 1) as i64) * (page_size as i64);
    let total: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM feature_guestbook WHERE user_id=$1 AND status='approved'")
            .bind(user_id)
            .fetch_one(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let rows: Vec<(String, String, String, bool, chrono::DateTime<chrono::Utc>, i32)> = sqlx::query_as(
        "SELECT display_name, message, COALESCE(public_id, id::text), pinned, approved_at, order_idx
         FROM feature_guestbook WHERE user_id=$1 AND status='approved'
         ORDER BY pinned DESC, approved_at ASC
         LIMIT $2 OFFSET $3",
    )
    .bind(user_id)
    .bind(page_size as i64)
    .bind(offset)
    .fetch_all(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(name, message, pid, pinned, at, _idx)| {
            json!({ "id": pid, "display_name": name, "message": message, "pinned": pinned, "approved_at": at.to_rfc3339() })
        })
        .collect();
    ok(json!({
        "entries": items,
        "page": page,
        "page_size": page_size,
        "pages": ((total as usize + page_size - 1) / page_size),
        "total": total,
    }))
}

pub async fn inbox(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Query(q): Query<ListQuery>,
) -> ApiResult {
    let status_filter = q.status.unwrap_or_else(|| "pending".to_string());
    let statuses = ["pending", "approved", "rejected", "removed"];
    if !statuses.contains(&status_filter.as_str()) {
        return Err(err(StatusCode::UNPROCESSABLE_ENTITY, "bad_status"));
    }
    let rows: Vec<(Uuid, String, String, bool, i32, chrono::DateTime<chrono::Utc>)> = sqlx::query_as(
        "SELECT id, display_name, message, pinned, order_idx, submitted_at
         FROM feature_guestbook WHERE user_id=$1 AND status=$2 ORDER BY submitted_at DESC",
    )
    .bind(user_id)
    .bind(&status_filter)
    .fetch_all(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(id, name, message, pinned, idx, at)| {
            json!({ "id": id, "display_name": name, "message": message, "pinned": pinned, "order_idx": idx, "submitted_at": at.to_rfc3339() })
        })
        .collect();
    ok(json!({ "entries": items }))
}

async fn moderate_one(
    pool: &PgPool,
    user_id: &Uuid,
    id: &Uuid,
    to_status: &str,
) -> ApiResult {
    let (enabled, _, _pinning) = config_values(pool, user_id).await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let row: Option<(String, bool)> =
        sqlx::query_as("SELECT status, pinned FROM feature_guestbook WHERE id=$1 AND user_id=$2")
            .bind(id)
            .bind(user_id)
            .fetch_optional(pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let Some((current, _pinned)) = row else {
        return Err(err(StatusCode::NOT_FOUND, "entry_not_found"));
    };
    if to_status == "approved" {
        if current == "approved" {
            return ok(json!({ "ok": true, "id": id, "already": true }));
        }
        let public_id = new_public_id();
        let version: i32 = sqlx::query_scalar(
            "SELECT version FROM feature_guestbook WHERE id=$1 AND user_id=$2",
        )
        .bind(id)
        .bind(user_id)
        .fetch_one(pool)
        .await
        .unwrap_or(1);
        sqlx::query(
            "UPDATE feature_guestbook SET status='approved', pinned=FALSE, public_id=$3,
             approved_at=NOW(), removed_at=NULL, version=$4 WHERE id=$1 AND user_id=$2",
        )
        .bind(id)
        .bind(user_id)
        .bind(&public_id)
        .bind(version + 1)
        .execute(pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
        ok(json!({ "ok": true, "id": id, "public_id": public_id }))
    } else if to_status == "rejected" {
        sqlx::query(
            "UPDATE feature_guestbook SET status='rejected', pinned=FALSE, approved_at=NULL WHERE id=$1 AND user_id=$2",
        )
        .bind(id)
        .bind(user_id)
        .execute(pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
        ok(json!({ "ok": true, "id": id }))
    } else if to_status == "removed" {
        sqlx::query(
            "UPDATE feature_guestbook SET status='removed', pinned=FALSE, approved_at=NULL, removed_at=NOW() WHERE id=$1 AND user_id=$2",
        )
        .bind(id)
        .bind(user_id)
        .execute(pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
        ok(json!({ "ok": true, "id": id }))
    } else {
        Err(err(StatusCode::UNPROCESSABLE_ENTITY, "bad_action"))
    }
}

pub async fn approve(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    moderate_one(&pool, &user_id, &id, "approved").await
}

pub async fn reject(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    moderate_one(&pool, &user_id, &id, "rejected").await
}

pub async fn remove(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    moderate_one(&pool, &user_id, &id, "removed").await
}

pub async fn pin(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    let (enabled, _, pinning) = config_values(&pool, &user_id).await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    if !pinning {
        return Err(err(StatusCode::CONFLICT, "pinning_off"));
    }
    let status: Option<String> =
        sqlx::query_scalar("SELECT status FROM feature_guestbook WHERE id=$1 AND user_id=$2")
            .bind(id)
            .bind(user_id)
            .fetch_optional(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    match status.as_deref() {
        Some("approved") => {
            sqlx::query(
                "UPDATE feature_guestbook SET pinned=TRUE, order_idx=0 WHERE id=$1 AND user_id=$2",
            )
            .bind(id)
            .bind(user_id)
            .execute(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
            ok(json!({ "ok": true, "id": id, "pinned": true }))
        }
        Some(_) => Err(err_reason(
            StatusCode::CONFLICT,
            "not_approved",
            "Only approved entries can be pinned.",
        )),
        None => Err(err(StatusCode::NOT_FOUND, "entry_not_found")),
    }
}

