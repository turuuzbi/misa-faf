use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use serde::Deserialize;
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

/// A browser counts again after this many minutes (spec 10: "at most one per
/// page/browser per rolling 30 minutes").
pub const DEDUP_MINUTES: i32 = 30;

#[derive(Deserialize)]
#[allow(dead_code)]
pub struct HitBody {
    token: Option<String>,
    skip: Option<bool>,
    ua: Option<String>,
}

fn dedup_key(user_id: &Uuid, token: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(user_id.as_bytes());
    hasher.update(token.as_bytes());
    format!("{:x}", hasher.finalize())
}

fn is_bot(ua: &str) -> bool {
    const PATTERNS: [&str; 8] = [
        "bot", "crawler", "spider", "slurp", "bingpreview", "facebookexternalhit", "headless", "prerender",
    ];
    let lower = ua.to_ascii_lowercase();
    PATTERNS.iter().any(|p| lower.contains(p))
}

/// Owner switch for the retro counter: a non-plain `counterStyle`
/// (odometer, lcd, flap, ...) or an explicit `hits: true`.
fn counter_style_on(settings: &Value) -> bool {
    if settings.get("hits").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    matches!(
        settings.get("counterStyle").and_then(|v| v.as_str()).map(|s| s.trim().to_ascii_lowercase()),
        Some(style) if !style.is_empty() && style != "plain" && style != "off"
    )
}

async fn hits_on(pool: &PgPool, user_id: &Uuid) -> bool {
    let settings = settings_of(read_config(pool, user_id).await.as_ref());
    counter_style_on(&settings) && global_enabled(pool, "alive").await && global_enabled(pool, "alive.hits").await
}

pub async fn record(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<HitBody>,
) -> ApiResult {
    if !hits_on(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    if body.skip.unwrap_or(false) {
        return ok(json!({ "ok": true, "counted": false, "reason": "skipped" }));
    }
    let ua = body.ua.unwrap_or_default();
    if is_bot(&ua) {
        return ok(json!({ "ok": true, "counted": false, "reason": "bot" }));
    }
    let token = body.token.unwrap_or_default().trim().to_string();
    if token.is_empty() || token.len() > 128 {
        return Err(err_reason(
            StatusCode::UNPROCESSABLE_ENTITY,
            "token_required",
            "A visitor token is required.",
        ));
    }
    let key = dedup_key(&user_id, &token);
    // Rolling window: a key older than DEDUP_MINUTES is refreshed and counts again.
    // (Previously the key never expired, so a browser counted once, ever, and the
    // table grew without bound.)
    let fresh = sqlx::query(
        "INSERT INTO feature_hit_dedup (key, user_id, at) VALUES ($1,$2,NOW())
         ON CONFLICT (key) DO UPDATE SET at = NOW()
         WHERE feature_hit_dedup.at < NOW() - make_interval(mins => $3)",
    )
    .bind(&key)
    .bind(user_id)
    .bind(DEDUP_MINUTES)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    if fresh.rows_affected() == 0 {
        return ok(json!({ "ok": true, "counted": false, "reason": "dup" }));
    }
    let count: i64 = sqlx::query_scalar(
        "INSERT INTO feature_hits (user_id, count, updated_at) VALUES ($1, 1, NOW())
         ON CONFLICT (user_id) DO UPDATE SET count = feature_hits.count + 1, updated_at = NOW()
         RETURNING count",
    )
    .bind(user_id)
    .fetch_one(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let _ = sqlx::query(
        "DELETE FROM feature_hit_dedup WHERE user_id=$1 AND at < NOW() - make_interval(mins => $2)",
    )
    .bind(user_id)
    .bind(DEDUP_MINUTES)
    .execute(&pool)
    .await;
    ok(json!({ "ok": true, "counted": true, "count": count }))
}

pub async fn view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    if !hits_on(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let count: Option<i64> = sqlx::query_scalar("SELECT count FROM feature_hits WHERE user_id=$1")
        .bind(user_id)
        .fetch_optional(&pool)
        .await
        .map_err(|_| err(StatusCode::SERVICE_UNAVAILABLE, "hits_unavailable"))?;
    ok(json!({ "count": count.unwrap_or(0) }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counter_switch() {
        assert!(!counter_style_on(&json!({})));
        assert!(!counter_style_on(&json!({ "counterStyle": "plain" })));
        assert!(counter_style_on(&json!({ "counterStyle": "odometer" })));
        assert!(counter_style_on(&json!({ "hits": true })));
    }
}
