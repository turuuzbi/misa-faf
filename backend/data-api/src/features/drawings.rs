use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const STROKES_MAX: usize = 100;
pub const POINTS_MAX: usize = 10_000;
pub const PAYLOAD_MAX: usize = 100 * 1024;
pub const DESC_MAX: usize = 280;
pub const PENDING_MAX: i64 = 100;
pub const PINNED_MAX: i64 = 3;
pub const GALLERY_MAX: i64 = 50;

#[derive(Deserialize)]
#[allow(dead_code)]
pub struct SubmitBody {
    strokes: Option<Value>,
    description: Option<String>,
    schema_version: Option<i64>,
    color: Option<String>,
    width: Option<f64>,
}

async fn config_values(pool: &PgPool, user_id: &Uuid) -> (bool, bool) {
    let (enabled, settings) = feature_on(pool, user_id, "doodles").await;
    let paused = settings
        .get("doodlesPaused")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    (enabled, paused)
}

fn validate_strokes(strokes: &Value) -> Result<(), (StatusCode, Json<Value>)> {
    let arr = match strokes {
        Value::Array(a) => a,
        _ => return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_strokes", "Expected an array of strokes.")),
    };
    if arr.is_empty() {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "empty_strokes", "A doodle needs at least one stroke."));
    }
    if arr.len() > STROKES_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "too_many_strokes", "Too many strokes."));
    }
    let mut points = 0usize;
    for stroke in arr {
        let points_arr = match stroke.get("points") {
            Some(Value::Array(p)) => p,
            _ => return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_points", "Stroke points missing.")),
        };
        points += points_arr.len();
        if points > POINTS_MAX {
            return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "too_many_points", "Too many points."));
        }
        for point in points_arr {
            let p = match point {
                Value::Array(arr2) if arr2.len() == 2 => arr2,
                Value::Array(arr2) if arr2.len() == 3 => arr2,
                _ => return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_point", "Point must be [x,y].")),
            };
            for c in p {
                let n = match c.as_f64() {
                    Some(n) => n,
                    None => return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_point", "Point value must be numeric.")),
                };
                if !n.is_finite() || !(0.0..=1.0).contains(&n) {
                    return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "out_of_range", "Point value out of range."));
                }
            }
        }
        if let Some(color) = stroke.get("color") {
            if let Some(s) = color.as_str() {
                let re = regex_color(s);
                if !re {
                    return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_color", "Color must be a hex value."));
                }
            }
        }
        if let Some(width) = stroke.get("width") {
            if let Some(w) = width.as_f64() {
                if !(1.0..=10.0).contains(&w) {
                    return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_width", "Width out of range."));
                }
            }
        }
    }
    Ok(())
}

fn regex_color(s: &str) -> bool {
    let h = s.strip_prefix('#').unwrap_or(s);
    (h.len() == 3 || h.len() == 6) && h.chars().all(|c| c.is_ascii_hexdigit())
}

pub async fn submit(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<SubmitBody>,
) -> ApiResult {
    let (enabled, paused) = config_values(&pool, &user_id).await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    if paused {
        return Err(err(StatusCode::FORBIDDEN, "intake_paused"));
    }
    if body.schema_version.is_some() && body.schema_version != Some(1) {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "bad_schema_version", "Unsupported schema version."));
    }
    let strokes = body.strokes.unwrap_or(Value::Null);
    validate_strokes(&strokes)?;

    let description = body.description.unwrap_or_default();
    if description.chars().count() > DESC_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "description_too_long", "Description too long."));
    }

    let payload_size = strokes.to_string().len() + description.len() + 64;
    if payload_size > PAYLOAD_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "payload_too_large", "Payload too large."));
    }

    let pending: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM feature_drawings WHERE user_id=$1 AND status='pending'")
            .bind(user_id)
            .fetch_one(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if pending >= PENDING_MAX {
        return Err(err_reason(StatusCode::FORBIDDEN, "board_full", "The board is full, come back later."));
    }

    let id = new_uuid();
    let public_id = new_public_id();
    sqlx::query(
        "INSERT INTO feature_drawings (id, user_id, status, public_id, strokes, description, payload_size)
         VALUES ($1,$2,'pending',$3,$4,$5,$6)",
    )
    .bind(id)
    .bind(user_id)
    .bind(&public_id)
    .bind(&strokes)
    .bind(if description.is_empty() { None } else { Some(&description) })
    .bind(payload_size as i32)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    ok(json!({ "ok": true, "id": id }))
}

pub async fn gallery(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let (enabled, _) = config_values(&pool, &user_id).await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let rows: Vec<(String, Value, Option<String>, bool, i32)> = sqlx::query_as(
        "SELECT COALESCE(public_id, id::text), strokes, description, pinned, ord
         FROM feature_drawings WHERE user_id=$1 AND status='kept' ORDER BY pinned DESC, ord ASC LIMIT $2",
    )
    .bind(user_id)
    .bind(GALLERY_MAX as i64)
    .fetch_all(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(pid, strokes, desc, pinned, _ord)| json!({ "id": pid, "strokes": strokes, "description": desc, "pinned": pinned }))
        .collect();
    ok(json!({ "drawings": items }))
}

pub async fn board(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let rows: Vec<(Uuid, String, Value, Option<String>, bool, chrono::DateTime<chrono::Utc>)> = sqlx::query_as(
        "SELECT id, status, strokes, description, pinned, created_at FROM feature_drawings
         WHERE user_id=$1 ORDER BY created_at DESC",
    )
    .bind(user_id)
    .fetch_all(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let items: Vec<Value> = rows
        .into_iter()
        .map(|(id, status, strokes, desc, pinned, at)| {
            json!({ "id": id, "status": status, "strokes": strokes, "description": desc, "pinned": pinned, "created_at": at.to_rfc3339() })
        })
        .collect();
    ok(json!({ "drawings": items }))
}

async fn set_status(
    pool: &PgPool,
    user_id: &Uuid,
    id: &Uuid,
    to: &str,
) -> ApiResult {
    let affected = sqlx::query(
        "UPDATE feature_drawings SET status=$3, moderated_at=NOW() WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user_id)
    .bind(to)
    .execute(pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if affected.rows_affected() == 0 {
        return Err(err(StatusCode::NOT_FOUND, "entry_not_found"));
    }
    ok(json!({ "ok": true, "id": id }))
}

pub async fn keep(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    set_status(&pool, &user_id, &id, "kept").await
}

pub async fn reject(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    set_status(&pool, &user_id, &id, "rejected").await
}

pub async fn pin(
    State(pool): State<PgPool>,
    Path((user_id, id)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    let status: Option<String> =
        sqlx::query_scalar("SELECT status FROM feature_drawings WHERE id=$1 AND user_id=$2")
            .bind(id)
            .bind(user_id)
            .fetch_optional(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    match status.as_deref() {
        Some("kept") => {
            let pinned: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM feature_drawings WHERE user_id=$1 AND pinned=TRUE")
                    .bind(user_id)
                    .fetch_one(&pool)
                    .await
                    .unwrap_or(0);
            if pinned >= PINNED_MAX {
                return Err(err_reason(StatusCode::CONFLICT, "pin_cap", "Too many pinned drawings."));
            }
            let ord: i32 = sqlx::query_scalar("SELECT COALESCE(MAX(ord),0)+1 FROM feature_drawings WHERE user_id=$1 AND status='kept'")
                .bind(user_id)
                .fetch_one(&pool)
                .await
                .unwrap_or(1);
            sqlx::query(
                "UPDATE feature_drawings SET pinned=TRUE, ord=$3 WHERE id=$1 AND user_id=$2",
            )
            .bind(id)
            .bind(user_id)
            .bind(ord)
            .execute(&pool)
            .await
            .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
            ok(json!({ "ok": true, "id": id, "pinned": true }))
        }
        Some(_) => Err(err_reason(StatusCode::CONFLICT, "not_kept", "Only kept drawings can be pinned.")),
        None => Err(err(StatusCode::NOT_FOUND, "entry_not_found")),
    }
}