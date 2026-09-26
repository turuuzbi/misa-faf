use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde_json::{json, Value};
use uuid::Uuid;

pub const MAX_PLACEMENTS: usize = 6;

async fn load(pool: &sqlx::PgPool, user_id: &Uuid) -> Value {
    let state = get_aux(pool, user_id, "reverse").await;
    state
        .get("placements")
        .cloned()
        .unwrap_or_else(|| json!([]))
}

pub async fn get(
    State(pool): State<sqlx::PgPool>,
    Path(user_id): Path<Uuid>,
) -> super::helpers::ApiResult {
    // Off or plan-locked: serve the front only; saved placements are kept.
    if !feature_on(&pool, &user_id, "reverse").await.0 {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let placements = load(&pool, &user_id).await;
    ok(json!({ "placements": placements }))
}

pub async fn set(
    State(pool): State<sqlx::PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<Value>,
) -> super::helpers::ApiResult {
    let placements = match body.get("placements") {
        Some(Value::Array(a)) => a,
        _ => {
            return Err(super::helpers::err_reason(
                StatusCode::UNPROCESSABLE_ENTITY,
                "invalid_placements",
                "Expected a placements array.",
            ))
        }
    };
    if placements.len() > MAX_PLACEMENTS {
        return Err(super::helpers::err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "too_many_placements",
            "Too many placements.",
        ));
    }
    let mut seen = std::collections::HashSet::new();
    for p in placements {
        let id = p.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let side = p.get("side").and_then(|v| v.as_str()).unwrap_or("");
        if id.is_empty()
            || uuid::Uuid::parse_str(id).is_err()
            || !matches!(side, "front" | "back")
        {
            return Err(super::helpers::err_reason(
                StatusCode::UNPROCESSABLE_ENTITY,
                "invalid_placement",
                "Placement needs a valid id and side.",
            ));
        }
        if !seen.insert(id.to_string()) {
            return Err(super::helpers::err_reason(
                StatusCode::UNPROCESSABLE_ENTITY,
                "duplicate_placement",
                "Duplicate placement id.",
            ));
        }
    }
    set_aux(&pool, &user_id, "reverse", &json!({ "placements": placements })).await;
    ok(json!({ "ok": true, "placements": placements }))
}