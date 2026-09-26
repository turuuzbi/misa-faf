use super::helpers::*;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use chrono::{DateTime, NaiveDate, NaiveDateTime, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const BODY_MAX: usize = 5000;
pub const LABEL_MAX: usize = 80;

/// Timezone for a capsule: `settings.capsule.tz`, then the owner's shared zone.
fn capsule_tz(cfg: &Value, settings: &Value) -> chrono_tz::Tz {
    cfg.get("tz")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .and_then(|name| name.parse::<chrono_tz::Tz>().ok())
        .unwrap_or_else(|| owner_timezone(settings))
}

/// Release instant for `settings.capsule.at`.
///
/// Accepts RFC 3339 with an offset, a naive `YYYY-MM-DDTHH:MM[:SS]`, or the
/// editor's date-only `YYYY-MM-DD` (00:00 in the capsule's timezone). The old
/// code only parsed RFC 3339, so every capsule saved by the editor stayed
/// sealed forever. Nonexistent local times (DST gaps) are rejected; an
/// ambiguous repeated time resolves to the earlier instant.
pub fn release_at(cfg: &Value, settings: &Value) -> Option<DateTime<Utc>> {
    let raw = cfg.get("at").and_then(|v| v.as_str())?.trim();
    if raw.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
        return Some(dt.with_timezone(&Utc));
    }
    let tz = capsule_tz(cfg, settings);
    let naive = NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S")
        .or_else(|_| NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M"))
        .ok()
        .or_else(|| {
            NaiveDate::parse_from_str(raw, "%Y-%m-%d")
                .ok()
                .and_then(|d| d.and_hms_opt(0, 0, 0))
        })?;
    tz.from_local_datetime(&naive)
        .earliest()
        .map(|dt| dt.with_timezone(&Utc))
}

async fn published(pool: &PgPool, user_id: &Uuid) -> bool {
    // Missing state means "published" so capsules saved before publish/unpublish existed keep working.
    !matches!(get_aux(pool, user_id, "capsule_published").await, Value::Number(n) if n.as_i64() == Some(0))
}

pub async fn public_view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let (enabled, settings) = feature_on(&pool, &user_id, "capsule").await;
    if !enabled || !published(&pool, &user_id).await {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let cfg = settings.get("capsule").cloned().unwrap_or_else(|| json!({}));
    let label: String = cfg
        .get("label")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .chars()
        .take(LABEL_MAX)
        .collect();
    let body_text = cfg.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let now = Utc::now();
    let release = release_at(&cfg, &settings);

    // Release depends only on server time: no background job, no "first opened"
    // marker. (The old marker also made a *new* capsule open instantly once the
    // previous one had been opened.) The client countdown is cosmetic.
    match release {
        Some(at) if now >= at => ok(json!({
            "state": "open",
            "label": label,
            "release_at": at.to_rfc3339(),
            "server_now": now.to_rfc3339(),
            "body": body_text,
        })),
        _ => ok(json!({
            "state": "sealed",
            "label": label,
            "release_at": release.map(|at| at.to_rfc3339()),
            "server_now": now.to_rfc3339(),
            "body": null,
        })),
    }
}

pub async fn publish(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let settings = settings_of(read_config(&pool, &user_id).await.as_ref());
    let capsule = settings.get("capsule").cloned().unwrap_or_else(|| json!({}));
    let body = capsule.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if body.trim().is_empty() {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "empty_capsule", "Write the capsule first."));
    }
    if body.chars().count() > BODY_MAX {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "payload_too_large", "Capsule body too large."));
    }
    let Some(at) = release_at(&capsule, &settings) else {
        return Err(err_reason(StatusCode::UNPROCESSABLE_ENTITY, "invalid_release", "Pick a real date and time for the capsule to open."));
    };
    set_aux(&pool, &user_id, "capsule_published", &json!(1)).await;
    ok(json!({ "ok": true, "state": "sealed", "release_at": at.to_rfc3339() }))
}

pub async fn unpublish(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    set_aux(&pool, &user_id, "capsule_published", &json!(0)).await;
    ok(json!({ "ok": true, "state": "unpublished" }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn date_only_opens_at_local_midnight() {
        let cfg = json!({ "at": "2026-12-24", "tz": "Asia/Ulaanbaatar" });
        let at = release_at(&cfg, &json!({})).unwrap();
        assert_eq!(at.to_rfc3339(), "2026-12-23T16:00:00+00:00");
    }

    #[test]
    fn rfc3339_is_respected() {
        let cfg = json!({ "at": "2026-12-24T10:00:00+02:00" });
        assert_eq!(release_at(&cfg, &json!({})).unwrap().to_rfc3339(), "2026-12-24T08:00:00+00:00");
    }

    #[test]
    fn nonexistent_dst_time_is_rejected() {
        // Europe/Berlin skips 02:00-03:00 on 2026-03-29.
        let cfg = json!({ "at": "2026-03-29T02:30", "tz": "Europe/Berlin" });
        assert!(release_at(&cfg, &json!({})).is_none());
    }

    #[test]
    fn owner_zone_is_the_fallback() {
        let cfg = json!({ "at": "2026-01-01" });
        let settings = json!({ "night": { "tz": "America/New_York" } });
        assert_eq!(release_at(&cfg, &settings).unwrap().to_rfc3339(), "2026-01-01T05:00:00+00:00");
    }
}
