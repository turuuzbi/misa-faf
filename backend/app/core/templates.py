import re
from typing import Any
from uuid import uuid4

from app.core.profile_sanitize import sanitize_profile_config

TEMPLATE_ASSET_KEYS = ("banner", "background", "cursor", "backgroundVideo", "audio", "audioArtwork", "customFont", "clickSound", "entryIcon")
PERSONAL_SETTINGS = (
    "ogTitle",
    "ogDescription",
    "ogOverlayAvatar",
    "ogOverlayName",
    "ogOverlayAddress",
    # Living-profile content and switches are the owner's, not part of a look: a
    # published template must not carry someone's sealed capsule, secret word,
    # poll, deck, neighbours or back-of-card note, and applying one must not
    # switch features on (or off) for the person who applies it.
    "capsule",
    "secret",
    "tally",
    "draw",
    "neighbours",
    "reverse",
    "night",
    "timezone",
    "clock",
    "clockLabel",
    "clock24",
    "guestbook",
    "guestbookHeading",
    "guestbookPaused",
    "guestbookPinning",
    "asks",
    "asksPrompt",
    "asksAcceptNew",
    "doodles",
    "doodlesTitle",
    "doodlesPaused",
    "moon",
    "presence",
    "hits",
    "vigil",
    "since",
    "replay",
    "remember",
    "archive",
)
SLUG_RE = re.compile(r"[^a-z0-9]+")
CREATOR_ROLE = "template_creator"
MAX_TEMPLATES_PER_CREATOR = 20
NAME_MAX = 48
DESCRIPTION_MAX = 200
PREVIEW_IMAGE_MAX_CHARS = 2_500_000
VISIBILITIES = ("public", "private", "unlisted")


def slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", str(name or "").strip().lower()).strip("-")[:48]
    return slug or f"template-{uuid4().hex[:8]}"


def unique_slug_candidate(name: str) -> str:
    return f"{slugify(name)}-{uuid4().hex[:6]}"


def snapshot_template_config(profile: dict[str, Any]) -> dict[str, Any]:
    cleaned = sanitize_profile_config(profile if isinstance(profile, dict) else {})
    settings = dict(cleaned.get("settings") or {})
    for key in PERSONAL_SETTINGS:
        settings.pop(key, None)
    assets = cleaned.get("assets") if isinstance(cleaned.get("assets"), dict) else {}
    snapped: dict[str, Any] = {}
    for key in TEMPLATE_ASSET_KEYS:
        item = assets.get(key)
        snapped[key] = item if isinstance(item, dict) else {"url": None, "name": "", "type": ""}
    snapped["tracks"] = [track for track in assets.get("tracks") or [] if isinstance(track, dict)]
    snapped["audioTitle"] = str(assets.get("audioTitle") or "")[:80]
    snapped["audioEnabled"] = bool(assets.get("audioEnabled")) if "audioEnabled" in assets else True
    snapped["audioSource"] = str(assets.get("audioSource") or "")[:16]
    snapped["volume"] = assets.get("volume", 65)
    return {"settings": settings, "assets": snapped, "sections": cleaned.get("sections", [])}


def preview_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = snapshot.get("settings") if isinstance(snapshot.get("settings"), dict) else {}
    assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), dict) else {}
    background = assets.get("background") if isinstance(assets.get("background"), dict) else {}
    tracks = assets.get("tracks") if isinstance(assets.get("tracks"), list) else []
    return {
        "accentColor": str(settings.get("accentColor") or "#9b87f5"),
        "backgroundColor": str(settings.get("backgroundColor") or "#08080d"),
        "textColor": str(settings.get("textColor") or "#ffffff"),
        "layout": str(settings.get("layout") or "Modern"),
        "backgroundEffect": str(settings.get("backgroundEffect") or "None"),
        "profileFont": str(settings.get("profileFont") or "Inter"),
        "hasBackground": bool(background.get("url")),
        "hasAudio": _snapshot_has_audio(assets),
        "trackCount": len(tracks),
    }


def apply_template_snapshot(current: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    base = dict(current) if isinstance(current, dict) else {}
    snap = snapshot if isinstance(snapshot, dict) else {}
    current_settings = dict(base.get("settings") or {}) if isinstance(base.get("settings"), dict) else {}
    snap_settings = dict(snap.get("settings") or {}) if isinstance(snap.get("settings"), dict) else {}
    for key in PERSONAL_SETTINGS:
        snap_settings.pop(key, None)
    merged_settings = {**current_settings, **snap_settings}
    for key in PERSONAL_SETTINGS:
        if key in current_settings:
            merged_settings[key] = current_settings[key]
    current_assets = dict(base.get("assets") or {}) if isinstance(base.get("assets"), dict) else {}
    snap_assets = dict(snap.get("assets") or {}) if isinstance(snap.get("assets"), dict) else {}
    for key in TEMPLATE_ASSET_KEYS:
        if key in snap_assets:
            current_assets[key] = snap_assets[key]
    if _snapshot_has_audio(snap_assets):
        current_assets["tracks"] = [track for track in snap_assets.get("tracks") or [] if isinstance(track, dict)]
        current_assets["audioTitle"] = str(snap_assets.get("audioTitle") or "")[:80]
        current_assets["audioEnabled"] = bool(snap_assets.get("audioEnabled"))
        if "volume" in snap_assets:
            current_assets["volume"] = snap_assets["volume"]
    merged = dict(base)
    merged["settings"] = merged_settings
    merged["assets"] = current_assets
    if "sections" in snap:
        merged["sections"] = snap["sections"]
    return sanitize_profile_config(merged)


def public_template_card(row: dict[str, Any]) -> dict[str, Any]:
    preview = row.get("preview")
    if not isinstance(preview, dict):
        preview = preview_from_snapshot(row.get("config") if isinstance(row.get("config"), dict) else {})
    return {
        "id": str(row.get("id") or ""),
        "slug": str(row.get("slug") or ""),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "tags": _template_tags(row.get("tags")),
        "previewImageUrl": str(row.get("preview_image_url") or "") or None,
        "preview": preview,
        "published": bool(row.get("published")),
        "visibility": str(row.get("visibility") or "public"),
        "is_favorite": bool(row.get("is_favorite")),
        "created_by": str(row.get("created_by") or "") or None,
        "creator_username": row.get("creator_username") or None,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "favorite_count": int(row.get("favorite_count") or 0),
        "week_favorite_count": int(row.get("week_favorite_count") or 0),
        "month_favorite_count": int(row.get("month_favorite_count") or 0),
    }


def _template_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    result: list[str] = []
    for item in values:
        tag = re.sub(r"[^a-zA-Z0-9 _-]", "", str(item or "")).strip().lower()
        if tag and tag not in result:
            result.append(tag[:24])
    return result[:8]


def official_seed_looks() -> list[dict[str, Any]]:
    empty_assets = {
        "banner": {"url": None, "name": "", "type": ""},
        "background": {"url": None, "name": "", "type": ""},
        "cursor": {"url": None, "name": "", "type": ""},
        "backgroundVideo": {"url": None, "name": "", "type": ""},
        "audio": {"url": None, "name": "", "type": ""},
        "audioArtwork": {"url": None, "name": "", "type": ""},
        "audioTitle": "",
        "tracks": [],
        "audioEnabled": True,
        "audioSource": "video",
        "volume": 65,
    }
    dummy = {
        "profile": {
            "username": "template",
            "displayName": "Template",
            "description": "",
            "location": "",
            "views": 0,
            "uid": "",
            "joinedAt": "",
        },
        "assets": empty_assets,
        "socials": [],
        "badges": [],
    }
    looks = (
        (
            "midnight",
            "Midnight",
            "Dark glass with a purple glow.",
            {
                "accentColor": "#9b87f5",
                "backgroundColor": "#08080d",
                "layout": "Modern",
                "backgroundEffect": "Stars",
                "usernameEffect": "Glow",
                "buttonStyle": "glass",
                "profileFont": "Inter",
            },
        ),
        (
            "aurora",
            "Aurora",
            "Soft gradients and drifting color.",
            {
                "accentColor": "#7ee0d6",
                "backgroundColor": "#0a1220",
                "iconColor": "#b8fff4",
                "layout": "Sleek",
                "backgroundEffect": "None",
                "usernameEffect": "Gradient",
                "buttonStyle": "glass",
                "profileFont": "Inter",
                "cardAlign": "center",
            },
        ),
        (
            "minimal",
            "Minimal",
            "Clean type and a centered layout.",
            {
                "accentColor": "#d4d4d8",
                "backgroundColor": "#0a0a0c",
                "iconColor": "#ececef",
                "layout": "Simplistic",
                "backgroundEffect": "None",
                "usernameEffect": "None",
                "usernameGlow": False,
                "socialGlow": False,
                "badgeGlow": False,
                "profileGradient": False,
                "buttonStyle": "outline",
                "profileFont": "Inter",
                "profileOpacity": 6,
                "borderWidth": 0,
            },
        ),
    )
    seeded: list[dict[str, Any]] = []
    for slug, name, description, settings in looks:
        snapshot = snapshot_template_config({**dummy, "settings": settings})
        seeded.append({
            "slug": slug,
            "name": name,
            "description": description,
            "config": snapshot,
            "preview": preview_from_snapshot(snapshot),
        })
    return seeded


def _snapshot_has_audio(assets: dict[str, Any]) -> bool:
    for track in assets.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        audio = track.get("audio") if isinstance(track.get("audio"), dict) else {}
        if audio.get("url"):
            return True
    return False


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
