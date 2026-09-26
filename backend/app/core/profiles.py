from typing import Any

from app.core.profile_sanitize import apply_badge_ownership, sanitize_profile_config
from app.db import data_api
from app.models import User


def default_public_profile(user: User) -> dict[str, Any]:
    username = user.username or "user"
    return {
        "profile": {
            "username": username,
            "displayName": user.display_name or username,
            "description": "",
            "location": "",
            "views": 0,
            "uid": user.id,
            "joinedAt": user.created_at or "",
        },
        "settings": {
            "accentColor": "#9b87f5",
            "usernameColor": "#ffffff",
            "usernameEffectColor": "#e11d48",
            "textColor": "#ffffff",
            "backgroundColor": "#08080d",
            "iconColor": "#d8d3ff",
            "profileOpacity": 10,
            "backgroundOpacity": 88,
            "profileBlur": 24,
            "profileRadius": 24,
            "profileFrameOpacity": 100,
            "profileGradient": True,
            "showViews": True,
            "showBadges": True,
            "showSocials": True,
            "showJoinDate": False,
            "showDiscordStatus": True,
            "showUsername": True,
            "socialAlign": "center",
            "cardAlign": "center",
            "showProfileFrame": True,
            "showAvatar": True,
            "showAvatarBorder": True,
            "showDisplayName": True,
            "profileFrameScale": 100,
            "profileFrameWidth": 430,
            "profileFrameHeight": 0,
            "profileFrameX": 0,
            "profileFrameY": 0,
            "layout": "Modern",
            "avatarShape": "circle",
            "bannerShape": "rounded",
            "buttonStyle": "glass",
            "profileFont": "Inter",
            "profileFontScope": "name",
            "fontSize": 16,
            "letterSpacing": 0,
            "bioTypewriter": False,
            "bioTypeMs": 55,
            "bioDeleteMs": 35,
            "bioPauseMs": 1200,
            "tabTitleAnimate": False,
            "borderColor": "#ffffff",
            "borderWidth": 1,
            "cardTilt": False,
            "entryScreen": True,
            "entryText": "click to enter...",
            "pageEnter": "Fade",
            "clickSound": False,
            "backgroundEffect": "None",
            "usernameEffect": "Glow",
            "usernameGlow": True,
            "socialGlow": True,
            "badgeGlow": True,
            "monochromeIcons": False,
            "widgetColorSwap": False,
            "ogTitle": "",
            "ogDescription": "",
            "ogOverlayAvatar": True,
            "ogOverlayName": True,
            "ogOverlayAddress": True,
        },
        "assets": {
            "avatar": {"url": user.avatar_url},
            "banner": {"url": None},
            "background": {"url": None},
            "backgroundVideo": {"url": None},
            "backgroundEffectVideo": {"url": None},
            "audio": {"url": None},
            "audioArtwork": {"url": None},
            "audioTitle": "",
            "tracks": [],
            "cursor": {"url": None},
            "ogImage": {"url": None},
            "favicon": {"url": None},
            "customFont": {"url": None},
            "clickSound": {"url": None},
            "audioEnabled": True,
            "audioSource": "video",
            "volume": 65,
        },
        "socials": [],
        "badges": [],
        "widgets": [],
        "sections": [],
    }


def starter_socials(username: str) -> list[dict[str, Any]]:
    handle = username or "user"
    return [
        {"id": "discord", "platform": "Discord", "label": "Discord", "value": handle, "enabled": True, "displayMode": "text", "clicks": 0, "action": "copy"},
        {"id": "instagram", "platform": "Instagram", "label": "Instagram", "value": f"instagram.com/{handle}", "enabled": True, "displayMode": "link", "clicks": 0, "action": "open"},
        {"id": "youtube", "platform": "YouTube", "label": "YouTube", "value": f"youtube.com/@{handle}", "enabled": True, "displayMode": "link", "clicks": 0, "action": "open"},
        {"id": "telegram", "platform": "Telegram", "label": "Telegram", "value": f"t.me/{handle}", "enabled": True, "displayMode": "link", "clicks": 0, "action": "open"},
        {"id": "github", "platform": "GitHub", "label": "GitHub", "value": f"github.com/{handle}", "enabled": True, "displayMode": "link", "clicks": 0, "action": "open"},
    ]


def stamp_join_date(config: dict[str, Any], user: User) -> dict[str, Any]:
    identity = config.get("profile")
    if not isinstance(identity, dict):
        identity = {}
        config["profile"] = identity
    if user.created_at:
        identity["joinedAt"] = str(user.created_at)
    return config


def unwrap_profile_config(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("config")
    if isinstance(nested, dict) and ("profile" in nested or "settings" in nested or "socials" in nested):
        return nested
    if "profile" in payload or "settings" in payload or "socials" in payload:
        return payload
    return None


async def resolve_public_profile(username: str) -> dict[str, Any] | None:
    user = await data_api.find_user(username=username.strip().lower())
    if user is None or not user.username:
        return None
    stored = unwrap_profile_config(await data_api.get_profile(user.id))
    config = stored or default_public_profile(user)
    identity = config.get("profile")
    if not isinstance(identity, dict):
        identity = {}
        config["profile"] = identity
    identity["username"] = user.username
    identity["uid"] = user.id
    stamp_join_date(config, user)
    if not str(identity.get("displayName") or "").strip():
        identity["displayName"] = user.display_name or user.username
    grants = await data_api.list_user_badge_grants(user.id)
    from app.core.premium import has_premium, public_projection
    config = public_projection(config, await has_premium(user.id))
    cleaned = apply_badge_ownership(sanitize_profile_config(config), stored, grants)
    from app.core.feature_privacy import public_feature_projection
    cleaned = public_feature_projection(cleaned)
    from app.db import achievements
    cleaned["rank"] = await achievements.current_rank_for_user(user.id)
    from app.core.discord_live import public_card_discord
    live = await public_card_discord(user)
    if live:
        cleaned["discord"] = live
    identity = cleaned.get("profile")
    if isinstance(identity, dict):
        identity["views"] = await data_api.get_profile_view_count(user.id)
    return cleaned
