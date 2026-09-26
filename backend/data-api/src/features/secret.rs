use super::helpers::*;
use axum::extract::{Json, Path, State};
use axum::http::StatusCode;
use base64::Engine;
use serde::Deserialize;
use serde_json::json;
use serde_json::Value;
use sqlx::PgPool;
use unicode_normalization::UnicodeNormalization;
use uuid::Uuid;

// Spec (feature 11): phrase 4-64 characters, label 80, URL 2,048.
pub const WORD_MIN: usize = 4;
pub const WORD_MAX: usize = 64;
pub const URL_MAX: usize = 2048;
pub const LABEL_MAX: usize = 80;
/// Guesses longer than this are rejected before the (deliberately slow) KDF runs.
pub const ATTEMPT_MAX: usize = 256;
pub const RATE_MAX: i64 = 10;
pub const RATE_WINDOW_MS: i64 = 600_000;
pub const GRANT_TTL_MIN: i64 = 5;
pub const SCRYPT_LOG_N: u8 = 14;
pub const SCRYPT_R: u32 = 8;
pub const SCRYPT_P: u32 = 1;
pub const SCRYPT_LEN: usize = 32;
/// Verifier format: 1 = trim + NFKC + lowercase (spec). Verifiers without the
/// marker were made from the trimmed, case-sensitive phrase.
const NORM_VERSION: i64 = 1;

#[derive(Deserialize)]
pub struct SetBody {
    word: Option<String>,
    url: Option<String>,
    label: Option<String>,
}

#[derive(Deserialize)]
pub struct TryBody {
    word: Option<String>,
    ip: Option<String>,
}

/// Documented matching rule: trim, Unicode NFKC, case-insensitive; inner spaces count.
pub fn normalize_word(raw: &str) -> String {
    raw.trim().nfkc().collect::<String>().to_lowercase()
}

/// Only plain web links may be revealed; `javascript:`, `data:` and friends are refused.
pub fn safe_destination(raw: &str) -> Option<String> {
    let url = raw.trim();
    if url.is_empty() || url.chars().count() > URL_MAX || url.chars().any(|c| c.is_control() || c.is_whitespace()) {
        return None;
    }
    let lower = url.to_ascii_lowercase();
    let rest = lower.strip_prefix("https://").or_else(|| lower.strip_prefix("http://"))?;
    let host = rest.split(['/', '?', '#']).next().unwrap_or("");
    if host.is_empty() || host.contains('@') || host.starts_with('.') {
        return None;
    }
    Some(url.to_string())
}

fn do_verifier(word: &str, salt: &[u8]) -> Vec<u8> {
    let params = scrypt::Params::new(SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN).expect("scrypt params");
    let mut out = vec![0u8; SCRYPT_LEN];
    scrypt::scrypt(word.as_bytes(), salt, &params, &mut out).expect("scrypt");
    out
}

async fn vget(pool: &PgPool, user_id: &Uuid) -> Value {
    get_aux(pool, user_id, "secret").await
}

/// Owner switch (`settings.secret`, written as `{configured, label}` by the
/// profile save) and the admin switch. Off rejects attempts and grants.
async fn secret_on(pool: &PgPool, user_id: &Uuid) -> bool {
    feature_on(pool, user_id, "secret").await.0
}

pub async fn set(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<SetBody>,
) -> ApiResult {
    let word = normalize_word(&body.word.unwrap_or_default());
    let len = word.chars().count();
    if !(WORD_MIN..=WORD_MAX).contains(&len) {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_word", "The word must be 4 to 64 characters."));
    }
    let Some(url) = safe_destination(&body.url.unwrap_or_default()) else {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_url", "Use an https:// or http:// link."));
    };
    let label = body.label.unwrap_or_default().trim().to_string();
    if label.chars().count() > LABEL_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_label", "Label length out of range."));
    }

    let state = vget(&pool, &user_id).await;
    let version = state.get("version").and_then(|v| v.as_i64()).unwrap_or(0) + 1;
    let salt: [u8; 16] = rand::random();
    let hash = do_verifier(&word, &salt);
    let hash_b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&hash);
    let salt_b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(salt);

    set_aux(
        &pool,
        &user_id,
        "secret",
        &json!({ "version": version, "norm": NORM_VERSION, "hash": hash_b64, "salt": salt_b64, "url": url, "label": label }),
    )
    .await;
    // rotation invalidates every outstanding grant
    let _ = sqlx::query("DELETE FROM feature_secret_grants WHERE user_id=$1")
        .bind(user_id)
        .execute(&pool)
        .await;
    ok(json!({ "ok": true, "version": version }))
}

pub async fn clear(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let _ = sqlx::query("DELETE FROM feature_secret_grants WHERE user_id=$1")
        .bind(user_id)
        .execute(&pool)
        .await;
    set_aux(&pool, &user_id, "secret", &json!({ "version": 0 })).await;
    ok(json!({ "ok": true }))
}

fn verify(word: &str, salt_b64: &str, hash_b64: &str) -> bool {
    let salt = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(salt_b64)
        .unwrap_or_default();
    let expected = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(hash_b64)
        .unwrap_or_default();
    if salt.is_empty() || expected.is_empty() {
        return false;
    }
    let actual = do_verifier(word, &salt);
    actual.len() == expected.len() && {
        let mut diff = 0u8;
        for (a, b) in actual.iter().zip(expected.iter()) {
            diff |= a ^ b;
        }
        diff == 0
    }
}

fn wrong() -> (StatusCode, Json<Value>) {
    // Identical for every failure so a response never hints at a partial match.
    err_reason(StatusCode::FORBIDDEN, "wrong_word", "Not unlocked.")
}

pub async fn attempt(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
    Json(body): Json<TryBody>,
) -> ApiResult {
    if !secret_on(&pool, &user_id).await {
        let _ = sqlx::query("DELETE FROM feature_secret_grants WHERE user_id=$1").bind(user_id).execute(&pool).await;
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let state = vget(&pool, &user_id).await;
    let hash = state.get("hash").and_then(|v| v.as_str()).unwrap_or("");
    if hash.is_empty() {
        return Err(err_reason(StatusCode::NOT_FOUND, "not_set", "No secret configured."));
    }
    // Brute-force limits apply before the expensive verifier (spec 11.3).
    let ip = body.ip.clone().unwrap_or_else(|| "?".to_string());
    rate_limit(&pool, &user_id, "secret_attempt", &scope_key(&ip), RATE_WINDOW_MS, RATE_MAX).await?;
    let raw = body.word.unwrap_or_default();
    if raw.chars().count() > ATTEMPT_MAX {
        return Err(wrong());
    }
    let candidate = if state.get("norm").and_then(|v| v.as_i64()) == Some(NORM_VERSION) {
        normalize_word(&raw)
    } else {
        raw.trim().to_string()
    };
    if !verify(&candidate, state.get("salt").and_then(|v| v.as_str()).unwrap_or(""), hash) {
        return Err(wrong());
    }
    let url = state.get("url").and_then(|v| v.as_str()).and_then(safe_destination);
    let Some(url) = url else {
        // A legacy record with an unsafe destination is never revealed.
        return Err(wrong());
    };
    let version = state.get("version").and_then(|v| v.as_i64()).unwrap_or(1);
    let grant = new_uuid();
    let expires = chrono::Utc::now() + chrono::Duration::minutes(GRANT_TTL_MIN);
    sqlx::query(
        "INSERT INTO feature_secret_grants (id, user_id, version, expires_at) VALUES ($1,$2,$3,$4)",
    )
    .bind(grant)
    .bind(user_id)
    .bind(version as i32)
    .bind(expires)
    .execute(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let label = state.get("label").and_then(|v| v.as_str()).unwrap_or("").to_string();
    ok(json!({ "grant": grant, "url": url, "label": label, "expires_at": expires.to_rfc3339() }))
}

pub async fn resolve(
    State(pool): State<PgPool>,
    Path((user_id, grant)): Path<(Uuid, Uuid)>,
) -> ApiResult {
    if !secret_on(&pool, &user_id).await {
        return Err(err_reason(StatusCode::GONE, "grant_stale", "Grant expired or invalidated."));
    }
    let state = vget(&pool, &user_id).await;
    let version = state.get("version").and_then(|v| v.as_i64()).unwrap_or(0);
    let row: Option<(i32,)> = sqlx::query_as(
        "SELECT version FROM feature_secret_grants WHERE id=$1 AND user_id=$2 AND expires_at > NOW()",
    )
    .bind(grant)
    .bind(user_id)
    .fetch_optional(&pool)
    .await
    .map_err(|_| err(StatusCode::INTERNAL_SERVER_ERROR, "store_error"))?;
    let url = state.get("url").and_then(|v| v.as_str()).and_then(safe_destination);
    match (row, url) {
        (Some((grant_version,)), Some(url)) if grant_version as i64 == version => {
            let label = state.get("label").and_then(|v| v.as_str()).unwrap_or("").to_string();
            // single-use: consume the grant
            let _ = sqlx::query("DELETE FROM feature_secret_grants WHERE id=$1")
                .bind(grant)
                .execute(&pool)
                .await;
            ok(json!({ "ok": true, "url": url, "label": label }))
        }
        _ => Err(err_reason(StatusCode::GONE, "grant_stale", "Grant expired or invalidated.")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalization_matches_the_spec() {
        assert_eq!(normalize_word("  Night Bus "), "night bus");
        assert_eq!(normalize_word("ＮＩＧＨＴ"), "night"); // full-width -> NFKC
        assert_ne!(normalize_word("night bus"), normalize_word("nightbus"));
    }

    #[test]
    fn only_web_links_are_revealed() {
        assert!(safe_destination("https://example.com/b-side").is_some());
        assert!(safe_destination("http://example.com").is_some());
        assert!(safe_destination("javascript:alert(1)").is_none());
        assert!(safe_destination("data:text/html,hi").is_none());
        assert!(safe_destination("https://user@evil.test").is_none());
        assert!(safe_destination("https:///nohost").is_none());
        assert!(safe_destination("https://exa mple.com").is_none());
    }
}
