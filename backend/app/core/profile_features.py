"""Which living-profile features a public page shows, and the public data they need.

The owner switch lives in `profile.settings` (written by the page editor); the
platform switch is the admin panel's `feature.<key>` flag. A feature is offered
to the page only when both are on. The data-api re-checks both on every public
read and write, so this is only about not rendering (or polling) dead widgets.

Mirrored for the React renderer in frontend/lib/profile-features.ts.
"""

from __future__ import annotations

import json
from typing import Any

# settings key -> admin flag(s) that must be on
_FLAGS: dict[str, tuple[str, ...]] = {
    "presence": ("feature.alive", "feature.alive.presence"),
    "clock": ("feature.alive", "feature.alive.clock"),
    "hits": ("feature.alive", "feature.alive.hits"),
    "moon": ("feature.moon",),
    "night": ("feature.night_shift",),
    "draw": ("feature.daily_draw",),
    "capsule": ("feature.time_capsule",),
    "tally": ("feature.tally",),
    "asks": ("feature.ask_anything",),
    "guestbook": ("feature.guestbook",),
    "doodles": ("feature.chalkboard",),
    "neighbours": ("feature.neighbours",),
    "secret": ("feature.secret_word",),
    "reverse": ("feature.other_side",),
}


def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit] if isinstance(value, (str, int, float)) else ""


def _has_content(value: Any) -> bool:
    """Same rule as the data-api's `feature_enabled` (helpers.rs)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, list):
        return any(item is not None and not (isinstance(item, str) and not item.strip()) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("enabled"), bool):
            return value["enabled"]
        return any(_has_content(v) for v in value.values() if not isinstance(v, (int, float)) or isinstance(v, bool))
    return False


def _owner_timezone(settings: dict[str, Any]) -> str:
    night = settings.get("night") if isinstance(settings.get("night"), dict) else {}
    for candidate in (settings.get("timezone"), night.get("tz")):
        text = _text(candidate, 64)
        if text:
            return text
    return ""


def public_features_payload(
    config: dict[str, Any],
    flags: dict[str, bool] | None = None,
    *,
    preview: bool = False,
) -> dict[str, Any] | None:
    """Public, render-only description of the enabled features, or None when there are none."""
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    identity = config.get("profile") if isinstance(config.get("profile"), dict) else {}
    username = _text(identity.get("username"), 32)
    if not username:
        return None

    def allowed(key: str) -> bool:
        if flags is None:
            return True
        return all(flags.get(flag, False) for flag in _FLAGS[key])

    payload: dict[str, Any] = {}
    tz = _owner_timezone(settings)

    if _has_content(settings.get("presence")) and allowed("presence"):
        payload["presence"] = True
    clock = settings.get("clock")
    if _has_content(clock) and tz and allowed("clock"):
        payload["clock"] = {"tz": tz, "label": _text(settings.get("clockLabel"), 40), "h24": bool(settings.get("clock24"))}
    style = _text(settings.get("counterStyle"), 16).lower()
    if (settings.get("hits") is True or (style and style not in {"plain", "off"})) and allowed("hits"):
        payload["hits"] = {"style": style if style and style not in {"plain", "off"} else "odometer"}
    moon = settings.get("moon")
    if _has_content(moon) and allowed("moon"):
        hemisphere = moon.get("hemisphere") if isinstance(moon, dict) else None
        payload["moon"] = {"hemisphere": "south" if hemisphere == "south" else "north"}
    if _has_content(settings.get("night")) and allowed("night"):
        payload["night"] = True
    if _has_content(settings.get("draw")) and allowed("draw"):
        payload["draw"] = True
    capsule = settings.get("capsule") if isinstance(settings.get("capsule"), dict) else {}
    # Public configs carry only `sealed` (see feature_privacy); owner previews still have `text`.
    if (capsule.get("sealed") or _text(capsule.get("text"), 5000)) and allowed("capsule"):
        payload["capsule"] = {"label": _text(capsule.get("label"), 80)}
    tally = settings.get("tally") if isinstance(settings.get("tally"), dict) else {}
    if (_text(tally.get("q")) or tally.get("enabled") is True) and allowed("tally"):
        payload["tally"] = True
    if _has_content(settings.get("asks")) and allowed("asks"):
        payload["asks"] = {"prompt": _text(settings.get("asksPrompt"), 120)}
    if _has_content(settings.get("guestbook")) and allowed("guestbook"):
        payload["guestbook"] = {"heading": _text(settings.get("guestbookHeading"), 60)}
    if _has_content(settings.get("doodles")) and allowed("doodles"):
        payload["doodles"] = {"title": _text(settings.get("doodlesTitle"), 60)}
    if _has_content(settings.get("neighbours")) and allowed("neighbours"):
        payload["neighbours"] = True
    secret = settings.get("secret") if isinstance(settings.get("secret"), dict) else {}
    if (secret.get("configured") or (secret.get("word") and secret.get("url"))) and allowed("secret"):
        payload["secret"] = True
    reverse = settings.get("reverse") if isinstance(settings.get("reverse"), dict) else {}
    back_title, back_text = _text(reverse.get("title"), 80), _text(reverse.get("text"), 1200)
    if (back_title or back_text) and allowed("reverse"):
        payload["reverse"] = {"title": back_title, "text": back_text}

    if not payload:
        return None
    payload.update({
        "user": username,
        "name": _text(identity.get("displayName"), 64) or username,
        "accent": settings.get("accentColor") if isinstance(settings.get("accentColor"), str) else None,
        "preview": preview,
    })
    return payload


def features_markup(payload: dict[str, Any] | None) -> tuple[str, str]:
    """(container placed inside the card, assets placed before </body>)."""
    if not payload:
        return "", ""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    container = '<section class="misa-features" data-misa-features aria-label="On this page"></section>'
    assets = (
        f'<script type="application/json" id="misa-features-data">{data}</script>'
        '<link rel="stylesheet" href="/dashboard/profile-features.css?v=20260926">'
        '<script type="module" src="/dashboard/profile-features.mjs?v=20260926"></script>'
    )
    return container, assets
