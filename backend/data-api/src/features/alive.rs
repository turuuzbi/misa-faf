use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

const LEASE_MIN_S: i64 = 10;
const LEASE_MAX_S: i64 = 300;
const LEASE_DEFAULT_S: i64 = 60;

#[derive(Deserialize)]
#[allow(dead_code)]
pub struct HeartbeatBody {
    token: Option<String>,
    lease_seconds: Option<i64>,
}

/// Alive parent + presence child, admin and owner side (spec 10).
/// Parent off hides all three widgets; a child off affects only itself.
/// The vigil (candle shelf) reads the same leases, so it keeps them open too.
pub async fn presence_on(pool: &PgPool, user_id: &Uuid) -> bool {
    let settings = settings_of(read_config(pool, user_id).await.as_ref());
    if feature_enabled(&settings, "vigil") {
        return true;
    }
    feature_enabled(&settings, "presence")
        && global_enabled(pool, "alive").await
        && global_enabled(pool, "alive.presence").await
}

async fn active_count(pool: &PgPool, user_id: &Uuid) -> Result<i64, (StatusCode, Json<Value>)> {
    sqlx::query_scalar("SELECT COUNT(*) FROM feature_leases WHERE user_id=$1 AND expires_at > NOW()")
        .bind(user_id)
        .fetch_one(pool)
        .await
        // An outage must read as "unavailable", never as a fabricated zero (spec 10.1).
        .map_err(|_| err(StatusCode::SERVICE_UNAVAILABLE, "presence_unavailable"))
}

pub async fn heartbeat(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<HeartbeatBody>,
) -> ApiResult {
    if !presence_on(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let token = body.token.unwrap_or_default().trim().to_string();
    if token.is_empty() || token.len() > 128 {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "token_required",
            "A valid presence token is required.",
        ));
    }
    let lease = body
        .lease_seconds
        .map(|s| s.clamp(LEASE_MIN_S, LEASE_MAX_S))
        .unwrap_or(LEASE_DEFAULT_S);
    let expires = chrono::Utc::now() + chrono::Duration::seconds(lease);

    let was_alive: Option<bool> =
        sqlx::query_scalar("SELECT expires_at > NOW() FROM feature_leases WHERE user_id=$1 AND token=$2")
            .bind(user_id)
            .bind(&token)
            .fetch_optional(&pool)
            .await
            .map_err(|_| err(StatusCode::SERVICE_UNAVAILABLE, "presence_unavailable"))?;
    // One lease per page+browser token; a stale token starts a fresh visit.
    sqlx::query(
        "INSERT INTO feature_leases (id, user_id, token, first_seen, last_seen, expires_at)
         VALUES ($1,$2,$3,NOW(),NOW(),$4)
         ON CONFLICT (user_id, token) DO UPDATE SET
            first_seen = CASE WHEN feature_leases.expires_at <= NOW() THEN NOW() ELSE feature_leases.first_seen END,
            last_seen = NOW(),
            expires_at = EXCLUDED.expires_at",
    )
    .bind(new_uuid())
    .bind(user_id)
    .bind(&token)
    .bind(expires)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::SERVICE_UNAVAILABLE, "presence_unavailable"))?;
    let _ = sqlx::query("DELETE FROM feature_leases WHERE user_id=$1 AND expires_at <= NOW()")
        .bind(user_id)
        .execute(&pool)
        .await;
    let count = active_count(&pool, &user_id).await?;
    ok(json!({
        "ok": true,
        "renewed": was_alive == Some(true),
        "active": count,
        "expires_at": expires.to_rfc3339(),
    }))
}

pub async fn count(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    if !presence_on(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let count = active_count(&pool, &user_id).await?;
    ok(json!({ "active": count, "server_now": chrono::Utc::now().to_rfc3339() }))
}

pub async fn snuff(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let result = sqlx::query("DELETE FROM feature_leases WHERE user_id=$1")
        .bind(user_id)
        .execute(&pool)
        .await
        .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    ok(json!({ "ok": true, "cleared": result.rows_affected() }))
}
