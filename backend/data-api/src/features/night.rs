use super::helpers::*;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use chrono::{DateTime, Duration, NaiveTime, TimeZone, Timelike, Utc};
use serde_json::json;
use sqlx::PgPool;
use uuid::Uuid;

/// Minutes after local midnight for a night-shift boundary.
///
/// The editor stores whole hours (`from: 23`, `to: 5`); "HH:MM" strings are
/// also accepted. The old parser read a bare number as *minutes*, so the
/// default 23 -> 5 window became 00:23 -> 00:05 and was open almost all day.
fn parse_boundary(value: Option<&serde_json::Value>, default_hour: u32) -> u32 {
    let raw = match value {
        Some(serde_json::Value::Number(n)) => n.to_string(),
        Some(serde_json::Value::String(s)) => s.trim().to_string(),
        _ => return default_hour * 60,
    };
    if let Some((h, m)) = raw.split_once(':') {
        let h: u32 = h.trim().parse().unwrap_or(default_hour);
        let m: u32 = m.trim().parse().unwrap_or(0);
        return if h < 24 && m < 60 { h * 60 + m } else { default_hour * 60 };
    }
    match raw.parse::<f64>() {
        Ok(h) if (0.0..24.0).contains(&h) && h.fract() == 0.0 => (h as u32) * 60,
        _ => default_hour * 60,
    }
}

/// Start-inclusive, end-exclusive window in owner-local minutes; wraps midnight.
/// Equal start and end is rejected by the editor and treated as "never open" here.
pub fn in_window(minutes: u32, start: u32, end: u32) -> bool {
    if start == end {
        return false;
    }
    if start < end {
        minutes >= start && minutes < end
    } else {
        minutes >= start || minutes < end
    }
}

/// Next instant (UTC) at which the window opens or closes, using real zone rules.
fn next_transition(now: DateTime<Utc>, tz: chrono_tz::Tz, start: u32, end: u32) -> Option<DateTime<Utc>> {
    if start == end {
        return None;
    }
    let today = now.with_timezone(&tz).date_naive();
    let mut best: Option<DateTime<Utc>> = None;
    for offset in 0..3 {
        let day = today + Duration::days(offset);
        for boundary in [start, end] {
            let Some(time) = NaiveTime::from_hms_opt(boundary / 60, boundary % 60, 0) else { continue };
            // A boundary inside a DST gap never occurs that day; skip it.
            let Some(local) = tz.from_local_datetime(&day.and_time(time)).earliest() else { continue };
            let at = local.with_timezone(&Utc);
            if at > now && best.map(|b| at < b).unwrap_or(true) {
                best = Some(at);
            }
        }
    }
    best
}

pub async fn view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let (enabled, settings) = feature_on(&pool, &user_id, "night").await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let night_cfg = settings.get("night").cloned().unwrap_or_else(|| json!({}));
    let tz_name = night_cfg.get("tz").and_then(|v| v.as_str()).unwrap_or("UTC").trim().to_string();
    let tz: chrono_tz::Tz = tz_name.parse().unwrap_or(chrono_tz::UTC);
    let start = parse_boundary(night_cfg.get("from"), 23);
    let end = parse_boundary(night_cfg.get("to"), 5);

    let now_utc = Utc::now();
    let local = now_utc.with_timezone(&tz);
    let minutes = local.hour() * 60 + local.minute();
    let visible = in_window(minutes, start, end);

    ok(json!({
        "active": visible,
        "visible": visible,
        "valid": start != end,
        "timezone": tz.name(),
        "from": format!("{:02}:{:02}", start / 60, start % 60),
        "to": format!("{:02}:{:02}", end / 60, end % 60),
        "local": local.to_rfc3339(),
        "server_now": now_utc.to_rfc3339(),
        "next_transition_at": next_transition(now_utc, tz, start, end).map(|t| t.to_rfc3339()),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hours_are_hours() {
        assert_eq!(parse_boundary(Some(&json!(23)), 0), 23 * 60);
        assert_eq!(parse_boundary(Some(&json!("5")), 0), 5 * 60);
        assert_eq!(parse_boundary(Some(&json!("23:30")), 0), 23 * 60 + 30);
        assert_eq!(parse_boundary(Some(&json!(99)), 23), 23 * 60);
    }

    #[test]
    fn overnight_window_matches_spec_03_1() {
        let (s, e) = (23 * 60, 5 * 60);
        assert!(!in_window(22 * 60 + 59, s, e));
        assert!(in_window(23 * 60, s, e));
        assert!(in_window(4 * 60 + 59, s, e));
        assert!(!in_window(5 * 60, s, e));
    }

    #[test]
    fn equal_bounds_never_open() {
        assert!(!in_window(600, 600, 600));
    }

    #[test]
    fn next_transition_crosses_dst() {
        // Europe/Berlin springs forward at 02:00 on 2026-03-29.
        let tz: chrono_tz::Tz = "Europe/Berlin".parse().unwrap();
        let now = Utc.with_ymd_and_hms(2026, 3, 28, 22, 30, 0).unwrap(); // 23:30 local
        let next = next_transition(now, tz, 23 * 60, 5 * 60).unwrap();
        // 05:00 CEST (UTC+2) = 03:00 UTC
        assert_eq!(next.to_rfc3339(), "2026-03-29T03:00:00+00:00");
    }
}
