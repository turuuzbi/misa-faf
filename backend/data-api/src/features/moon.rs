use super::helpers::*;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use serde_json::json;
use sqlx::PgPool;
use uuid::Uuid;

/// Lunar phase at a UTC instant.
///
/// Meeus, *Astronomical Algorithms* ch. 48 (low-precision phase angle from the
/// Moon's mean elongation and the Sun/Moon mean anomalies). Error in the lit
/// fraction is well under the spec's 2-point tolerance. The previous version
/// used a mean synodic month from a mistyped epoch (2000-01-01 23:14 instead of
/// the 2000-01-06 18:14 new moon), which put every phase ~4.8 days early.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Phase {
    /// Illuminated fraction, 0..1.
    pub lit: f64,
    /// True between new and full moon.
    pub waxing: bool,
}

pub fn phase_at(utc_secs: i64) -> Phase {
    let jd = utc_secs as f64 / 86_400.0 + 2_440_587.5;
    let t = (jd - 2_451_545.0) / 36_525.0;
    let d = 297.850_192_1 + 445_267.111_403_4 * t - 0.001_881_9 * t * t + t.powi(3) / 545_868.0 - t.powi(4) / 113_065_000.0;
    let m = 357.529_109_2 + 35_999.050_290_9 * t - 0.000_153_6 * t * t + t.powi(3) / 24_490_000.0;
    let mp = 134.963_396_4 + 477_198.867_505_5 * t + 0.008_741_4 * t * t + t.powi(3) / 69_699.0 - t.powi(4) / 14_712_000.0;
    let (d, m, mp) = (d.to_radians(), m.to_radians(), mp.to_radians());
    let i = 180.0 - d.to_degrees()
        - 6.289 * mp.sin()
        + 2.100 * m.sin()
        - 1.274 * (2.0 * d - mp).sin()
        - 0.658 * (2.0 * d).sin()
        - 0.214 * (2.0 * mp).sin()
        - 0.110 * d.sin();
    let i = i.rem_euclid(360.0).to_radians();
    Phase { lit: (1.0 + i.cos()) / 2.0, waxing: i.sin() > 0.0 }
}

/// Name buckets centred on the principal phases (the old code started "first
/// quarter" at the quarter instead of centring on it).
pub fn phase_name(p: Phase) -> &'static str {
    match (p.lit, p.waxing) {
        (l, _) if l < 0.02 => "New moon",
        (l, _) if l > 0.98 => "Full moon",
        (l, true) if (l - 0.5).abs() <= 0.03 => "First quarter",
        (l, false) if (l - 0.5).abs() <= 0.03 => "Last quarter",
        (l, true) if l < 0.5 => "Waxing crescent",
        (_, true) => "Waxing gibbous",
        (l, false) if l < 0.5 => "Waning crescent",
        (_, false) => "Waning gibbous",
    }
}

pub async fn view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let (enabled, settings) = feature_on(&pool, &user_id, "moon").await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let hemisphere = settings
        .get("moon")
        .and_then(|m| m.get("hemisphere"))
        .and_then(|v| v.as_str())
        .unwrap_or("north")
        .to_ascii_lowercase();
    let north = hemisphere != "south";
    let now = chrono::Utc::now();
    let p = phase_at(now.timestamp());
    let percent = (p.lit * 100.0).round() as i64;
    let phase = phase_name(p);
    // Northern-hemisphere convention: a waxing moon is lit on the right.
    let side = if p.waxing == north { "right" } else { "left" };
    ok(json!({
        "phase": phase,
        "illumination": (p.lit * 1000.0).round() / 1000.0,
        "percent": percent,
        "waxing": p.waxing,
        "waning": !p.waxing,
        "direction": if p.waxing { "waxing" } else { "waning" },
        "hemisphere": if north { "north" } else { "south" },
        "side": side,
        "label": format!("{}, {}% lit", phase, percent),
        "server_now": now.to_rfc3339(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(y: i32, mo: u32, d: u32, h: u32) -> i64 {
        chrono::Utc.with_ymd_and_hms(y, mo, d, h, 0, 0).unwrap().timestamp()
    }

    /// Fixtures from PyEphem (JPL-derived), tolerance 2 percentage points (spec 07.1).
    #[test]
    fn matches_ephemeris_fixtures() {
        let cases = [
            (at(2026, 9, 26, 13), 99.9, "Full moon"),
            (at(2026, 9, 19, 12), 56.3, "Waxing gibbous"),
            (at(2026, 10, 3, 12), 50.8, "Last quarter"),
            (at(2026, 10, 10, 12), 0.1, "New moon"),
            (at(2000, 1, 6, 18), 0.0, "New moon"),
        ];
        for (ts, expected, name) in cases {
            let p = phase_at(ts);
            assert!((p.lit * 100.0 - expected).abs() <= 2.0, "{ts}: got {:.1}, want {expected}", p.lit * 100.0);
            assert_eq!(phase_name(p), name, "{ts}");
        }
    }

    #[test]
    fn waxing_then_waning() {
        assert!(phase_at(at(2026, 9, 19, 12)).waxing);
        assert!(!phase_at(at(2026, 10, 3, 12)).waxing);
    }
}
