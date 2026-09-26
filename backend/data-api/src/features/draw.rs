use super::helpers::*;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::PgPool;
use uuid::Uuid;

pub const CARDS_MAX: usize = 12;
pub const CARD_MAX: usize = 160;

pub fn cards_from_cfg(cfg: &Value) -> Vec<String> {
    let mut cards: Vec<String> = match cfg {
        Value::String(s) => s.lines().map(|l| l.trim().to_string()).collect(),
        Value::Array(arr) => arr
            .iter()
            .filter_map(|v| v.as_str().map(|s| s.trim().to_string()))
            .collect(),
        _ => Vec::new(),
    };
    cards.retain(|c| !c.is_empty() && c.chars().count() <= CARD_MAX);
    cards.truncate(CARDS_MAX);
    cards
}

fn frozen_cards(state: &Value, today: &str) -> Option<Vec<String>> {
    if state.get("day").and_then(|v| v.as_str()) != Some(today) {
        return None;
    }
    let cards: Vec<String> = state
        .get("cards")?
        .as_array()?
        .iter()
        .filter_map(|v| v.as_str().map(str::to_string))
        .collect();
    (!cards.is_empty()).then_some(cards)
}

/// Public deck for today.
///
/// The deck is frozen per owner-local calendar day: the first read of a day
/// records that day's cards, and edits made later in the day apply from the
/// next owner-local midnight (spec 04.2). The old version used the UTC date,
/// compared two differently formatted fingerprints (so it rewrote state on
/// every public read) and served mid-day edits immediately.
/// Card selection itself happens in the visitor's browser; nothing about who
/// got which card is sent or stored.
pub async fn view(
    State(pool): State<PgPool>,
    Path(user_id): Path<Uuid>,
) -> ApiResult {
    let (enabled, settings) = feature_on(&pool, &user_id, "draw").await;
    if !enabled {
        return Err(err(StatusCode::NOT_FOUND, "feature_off"));
    }
    let tz = owner_timezone(&settings);
    let now = Utc::now();
    let local_today = now.with_timezone(&tz).date_naive();
    let today = local_today.format("%Y-%m-%d").to_string();
    let next_midnight = (local_today + Duration::days(1))
        .and_hms_opt(0, 0, 0)
        .and_then(|naive| tz.from_local_datetime(&naive).earliest())
        .map(|dt| dt.with_timezone(&Utc).to_rfc3339());

    let state = get_aux(&pool, &user_id, "draw").await;
    let cards = match frozen_cards(&state, &today) {
        Some(cards) => cards,
        None => {
            let cards = cards_from_cfg(settings.get("draw").unwrap_or(&Value::Null));
            if cards.is_empty() {
                return Err(err_reason(StatusCode::NOT_FOUND, "no_deck", "No deck configured."));
            }
            set_aux(&pool, &user_id, "draw", &json!({ "day": today, "cards": cards })).await;
            cards
        }
    };

    ok(json!({
        "day": today,
        "timezone": tz.name(),
        "cards": cards,
        "server_now": now.to_rfc3339(),
        "next_change_at": next_midnight,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deck_is_trimmed_and_capped() {
        let raw = json!((0..20).map(|i| format!(" line {i} ")).collect::<Vec<_>>().join("\n"));
        let cards = cards_from_cfg(&raw);
        assert_eq!(cards.len(), CARDS_MAX);
        assert_eq!(cards[0], "line 0");
    }

    #[test]
    fn frozen_deck_only_for_the_same_day() {
        let state = json!({ "day": "2026-09-26", "cards": ["a", "b"] });
        assert_eq!(frozen_cards(&state, "2026-09-26"), Some(vec!["a".into(), "b".into()]));
        assert_eq!(frozen_cards(&state, "2026-09-27"), None);
        assert_eq!(frozen_cards(&json!({ "day": "2026-09-26", "fp": "x" }), "2026-09-26"), None);
    }
}
