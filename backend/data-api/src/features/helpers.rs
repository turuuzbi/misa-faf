use axum::http::StatusCode;
use axum::Json;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use sqlx::PgPool;

pub type ApiResult = Result<Json<Value>, (StatusCode, Json<Value>)>;

pub fn ok(value: Value) -> ApiResult {
    Ok(Json(value))
}

pub fn err(status: StatusCode, code: &str) -> (StatusCode, Json<Value>) {
    (status, Json(json!({ "error": code })))
}

pub fn err_reason(status: StatusCode, code: &str, reason: &str) -> (StatusCode, Json<Value>) {
    (status, Json(json!({ "error": code, "reason": reason })))
}

pub fn now_utc() -> DateTime<Utc> {
    Utc::now()
}

#[allow(dead_code)]
pub fn now_iso() -> String {
    now_utc().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}

pub async fn read_config(pool: &PgPool, user_id: &uuid::Uuid) -> Option<Value> {
    let row: Option<(sqlx::types::Json<Value>,)> = sqlx::query_as(
        "SELECT config FROM profiles WHERE user_id = $1 AND disabled_at IS NULL",
    )
    .bind(user_id)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();
    row.map(|r| r.0 .0)
}

pub fn settings_of(config: Option<&Value>) -> Value {
    config
        .and_then(|c| c.get("settings"))
        .cloned()
        .unwrap_or_else(|| json!({}))
}

/// Owner-side switch check for `settings.<key>`.
///
/// The editor stores most switches as their content (`draw: "lines"`,
/// `tally: {q, options}`, `night: {tz, from, to}`), so "on" means "has real
/// content": `true`, a non-empty string, a non-empty array, or an object that
/// either says `enabled: true` or holds a non-empty string/array/`true` value.
/// Numbers inside objects (e.g. `night.from = 23`) do not switch a feature on,
/// and an empty string (`vigil: ""`, `draw: ""`) is off.
pub fn feature_enabled(settings: &Value, key: &str) -> bool {
    settings.get(key).map(has_content).unwrap_or(false)
}

fn has_content(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.trim().is_empty(),
        Value::Number(n) => n.as_f64().map(|v| v != 0.0).unwrap_or(false),
        Value::Array(arr) => arr.iter().any(|v| !matches!(v, Value::Null) && !matches!(v, Value::String(s) if s.trim().is_empty())),
        Value::Object(map) => {
            if let Some(Value::Bool(explicit)) = map.get("enabled") {
                return *explicit;
            }
            map.values().any(|v| match v {
                Value::Number(_) => false,
                other => has_content(other),
            })
        }
    }
}

/// Platform-level switch from the admin panel (`feature_flags.key = feature.<key>`).
/// A missing row or a failed read fails closed, per the spec's policy rules.
pub async fn global_enabled(pool: &PgPool, key: &str) -> bool {
    let flag = format!("feature.{key}");
    sqlx::query_scalar::<_, bool>("SELECT enabled FROM feature_flags WHERE key = $1")
        .bind(&flag)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten()
        .unwrap_or(false)
}

/// Admin-panel keys for each feature (spec keys), keyed by the editor's settings key.
pub fn global_key_for(settings_key: &str) -> &str {
    match settings_key {
        "asks" => "ask_anything",
        "reverse" => "other_side",
        "night" => "night_shift",
        "draw" => "daily_draw",
        "capsule" => "time_capsule",
        "doodles" => "chalkboard",
        "secret" => "secret_word",
        other => other,
    }
}

/// Effective access for a public read or write: admin switch AND owner switch.
/// Returns the owner's settings so callers can read feature config without a second query.
pub async fn feature_on(pool: &PgPool, user_id: &uuid::Uuid, settings_key: &str) -> (bool, Value) {
    let settings = settings_of(read_config(pool, user_id).await.as_ref());
    if !feature_enabled(&settings, settings_key) {
        return (false, settings);
    }
    (global_enabled(pool, global_key_for(settings_key)).await, settings)
}

/// Owner timezone shared by timed widgets: `settings.timezone`, then the night
/// shift zone, then UTC. Invalid names fall back to UTC.
pub fn owner_timezone(settings: &Value) -> chrono_tz::Tz {
    let candidates = [
        settings.get("timezone").and_then(|v| v.as_str()),
        settings.get("night").and_then(|n| n.get("tz")).and_then(|v| v.as_str()),
    ];
    candidates
        .into_iter()
        .flatten()
        .map(str::trim)
        .find(|name| !name.is_empty())
        .and_then(|name| name.parse::<chrono_tz::Tz>().ok())
        .unwrap_or(chrono_tz::UTC)
}

pub async fn get_aux(pool: &PgPool, user_id: &uuid::Uuid, feature: &str) -> Value {
    let row: Option<(sqlx::types::Json<Value>,)> = sqlx::query_as(
        "SELECT state FROM feature_aux WHERE user_id = $1 AND feature = $2",
    )
    .bind(user_id)
    .bind(feature)
    .fetch_optional(pool)
    .await
    .ok()
    .flatten();
    match row {
        Some(r) => r.0 .0,
        None => json!({}),
    }
}

pub async fn set_aux(pool: &PgPool, user_id: &uuid::Uuid, feature: &str, state: &Value) {
    let _ = sqlx::query(
        "INSERT INTO feature_aux (user_id, feature, state, updated_at) VALUES ($1,$2,$3,NOW())
         ON CONFLICT (user_id, feature) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()",
    )
    .bind(user_id)
    .bind(feature)
    .bind(state)
    .execute(pool)
    .await;
}

pub fn new_uuid() -> uuid::Uuid {
    uuid::Uuid::new_v4()
}

/// Short stable fingerprint of a source IP, hex-encoded (raw IP is never stored).
pub fn scope_key(ip: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(ip.as_bytes());
    let hex = format!("{:x}", hasher.finalize());
    hex.chars().take(16).collect()
}

pub fn new_public_id() -> String {
    let bytes = uuid::Uuid::new_v4();
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes.as_bytes())
}

/// Fixed-window rate limiter backed by `feature_rates`.
///
/// One atomic upsert: a row whose window has expired is reset to 1 instead of
/// being left stale (the previous version never reset an expired row, so a key
/// was only ever limited during its very first window).
/// Returns Ok(()) when a call is allowed, Err((429, json)) otherwise.
pub async fn rate_limit(
    pool: &PgPool,
    user_id: &uuid::Uuid,
    scope: &str,
    key: &str,
    window_ms: i64,
    max: i64,
) -> Result<(), (StatusCode, Json<Value>)> {
    let window_start = now_utc() - Duration::milliseconds(window_ms);
    let count: i32 = sqlx::query_scalar(
        "INSERT INTO feature_rates (user_id, scope, key, win_start, count) VALUES ($1,$2,$3,NOW(),1)
         ON CONFLICT (user_id, scope, key) DO UPDATE SET
            count = CASE WHEN feature_rates.win_start < $4 THEN 1 ELSE feature_rates.count + 1 END,
            win_start = CASE WHEN feature_rates.win_start < $4 THEN NOW() ELSE feature_rates.win_start END
         RETURNING count",
    )
    .bind(user_id)
    .bind(scope)
    .bind(key)
    .bind(window_start)
    .fetch_one(pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "rate_store_error"))?;
    if (count as i64) > max {
        return Err(err_reason(
            StatusCode::TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many attempts. Try again later.",
        ));
    }
    Ok(())
}
