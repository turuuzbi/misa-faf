import re
from datetime import datetime
from pathlib import Path
from typing import Any, Annotated
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from httpx import HTTPError

from app.core.config import get_settings
from app.core.discord_live import public_presence_for_user
from app.core.og_card import fallback_favicon_png, render_og_png
from app.core.profile_sanitize import ASSET_KIND_TYPES, ASSET_KINDS, SECTION_ID, apply_badge_ownership, decode_data_url, merge_kept_profile, safe_asset_url, sanitize_profile_config
from app.core.profiles import default_public_profile, resolve_public_profile, stamp_join_date, unwrap_profile_config
from app.core.security import USERNAME_RE
from app.core.sessions import get_user_from_request
from app.core.rate_limit import client_ip, rate_limit
from app.core.r2_storage import get_r2_storage
from app.core.usernames import current_handle_for, username_redirect
from app.core.widgets import resolve_profile_widgets
from app.db import data_api, feature_api
from app.models import User

router = APIRouter(prefix="/profile", tags=["profiles"])


async def require_user(request: Request) -> User:
    user = await get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return user


def _media_response(url: str) -> Response | None:
    decoded = decode_data_url(url)
    if decoded:
        body, mime = decoded
        return Response(content=body, media_type=mime, headers={"Cache-Control": "no-store", "Accept-Ranges": "bytes"})
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
        return RedirectResponse(url, status_code=302)
    return None


ASSET_LIMITS = {
    "avatar": 25_000_000, "background": 40_000_000, "banner": 25_000_000,
    "ogImage": 25_000_000, "favicon": 5_000_000, "cursor": 5_000_000,
    "backgroundVideo": 110_000_000, "backgroundEffectVideo": 110_000_000,
    "audio": 40_000_000, "audioArtwork": 15_000_000,
    "clickSound": 400_000, "customFont": 2_000_000, "cover": 3_000_000,
    "socialIcon": 512_000, "entryIcon": 5_000_000,
}

def _asset_content_allowed(kind: str, content_type: str) -> bool:
    if kind in {"avatar", "background", "banner", "ogImage", "favicon", "audioArtwork", "cover", "socialIcon", "cursor", "entryIcon"}:
        return content_type in {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/x-icon", "image/vnd.microsoft.icon"}
    if kind in {"backgroundVideo", "backgroundEffectVideo"}:
        return content_type in {"video/mp4", "video/webm", "video/quicktime"}
    if kind in {"audio", "clickSound"}:
        return content_type.startswith("audio/")
    if kind == "customFont":
        return content_type.startswith("font/") or content_type in {"application/font-woff", "application/font-woff2", "application/octet-stream"}
    return False

def _safe_upload_name(filename: str | None) -> str:
    value = Path(filename or "upload").name
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return value[:100] or "upload"

@router.post("/assets")
async def upload_asset(
    kind: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    settings = Depends(get_settings),
    premium: Annotated[bool, Form()] = False,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    from app.core.premium import has_premium
    if (premium or kind == "entryIcon") and not await has_premium(user.id):
        raise HTTPException(403, "Premium is required for this upload.")
    if kind not in ASSET_LIMITS:
        raise HTTPException(status_code=400, detail="Unsupported asset type.")
    content_type = (file.content_type or "").lower()
    if not content_type or content_type == "application/octet-stream":
        content_type = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
            ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mp3": "audio/mpeg",
            ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
            ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
            ".otf": "font/otf",
        }.get(Path(file.filename or "").suffix.lower(), "application/octet-stream")
    if not _asset_content_allowed(kind, content_type):
        raise HTTPException(status_code=400, detail="That file type is not supported for this asset.")
    body = await file.read(ASSET_LIMITS[kind] + 1)
    if len(body) > ASSET_LIMITS[kind]:
        raise HTTPException(status_code=413, detail="That file is too large.")
    from app.core.upload_validation import validate_upload
    validate_upload(kind, body, content_type)
    storage = get_r2_storage(settings)
    if not storage.enabled:
        raise HTTPException(status_code=503, detail="R2 object storage is not configured.")
    name = _safe_upload_name(file.filename)
    key = f"profiles/{user.id}/{kind}/{uuid4().hex}-{name}"
    try:
        await storage.put(key, body, content_type)
    except Exception:
        raise HTTPException(status_code=502, detail="R2 object storage is temporarily unavailable.") from None
    return {"asset": {"url": storage.public_url(key), "name": name, "type": content_type, "key": key}}
@router.get("/limits")
async def profile_limits() -> dict[str, int]:
    settings = get_settings()
    return {
        "maxTracks": max(1, min(20, settings.max_profile_tracks)),
        "maxTrackBytes": max(500_000, settings.max_track_upload_bytes),
        "maxArtworkBytes": 15_000_000,
    }


@router.get("")
async def public_profile(username: Annotated[str, Query(min_length=3, max_length=24)], response: Response):
    response.headers["Cache-Control"] = "no-store"
    handle = username.strip().lower()
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile?username={alias}")
    profile = await resolve_public_profile(handle)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"profile": profile}


def _public_media(url: str | None, kind: str) -> Response | None:
    safe = safe_asset_url(url, kind)
    return _media_response(safe) if safe else None


@router.get("/{username}/widgets")
async def public_profile_widgets(username: str, request: Request) -> dict[str, Any]:
    handle = username.strip().lower()
    if not USERNAME_RE.fullmatch(handle):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    await rate_limit(f"rl:widgets:{client_ip(request)}", 40, 60)
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/widgets")
    profile = await resolve_public_profile(handle)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"widgets": await resolve_profile_widgets(profile)}


@router.get("/{username}/discord-status")
async def public_discord_status(username: str, response: Response) -> dict[str, str | None]:
    response.headers["Cache-Control"] = "no-store"
    handle = username.strip().lower()
    if not USERNAME_RE.fullmatch(handle):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/discord-status")
    user = await data_api.find_user(username=handle)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"status": await public_presence_for_user(user)}


@router.get("/{username}/sections/{section_id}/cover")
async def public_section_cover(username: str, section_id: str) -> Response:
    handle = username.strip().lower()
    if not USERNAME_RE.fullmatch(handle) or not SECTION_ID.fullmatch(section_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/sections/{section_id}/cover")
    profile = await resolve_public_profile(handle)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    section = next((item for item in profile.get("sections") or [] if isinstance(item, dict) and item.get("id") == section_id and item.get("enabled")), None)
    cover = section.get("cover") if isinstance(section, dict) else None
    url = str((cover or {}).get("url") or "") if isinstance(cover, dict) else ""
    media = _public_media(url, "image")
    if media:
        return media
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")


@router.get("/{username}/assets/{kind}")
async def public_profile_asset(username: str, kind: str) -> Response:
    handle = username.strip().lower()
    if kind not in ASSET_KINDS or not USERNAME_RE.fullmatch(handle):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/assets/{kind}")
    media = _public_media(await data_api.get_public_asset_url(handle, kind), ASSET_KIND_TYPES[kind])
    if media:
        return media
    if kind == "favicon":
        media = _public_media(await data_api.get_public_asset_url(handle, "avatar"), "image")
        if media:
            return media
        bits = await data_api.get_share_card_bits(handle)
        if bits:
            identity = bits.get("identity") if isinstance(bits.get("identity"), dict) else {}
            settings = bits.get("settings") if isinstance(bits.get("settings"), dict) else {}
            initial = str(identity.get("displayName") or bits.get("username") or handle)[:1]
            return Response(
                content=fallback_favicon_png(initial, str(settings.get("accentColor") or "#9b87f5")),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=120"},
            )
    if kind in {"audio", "audioArtwork"}:
        fallback = "audio" if kind == "audio" else "artwork"
        media = _public_media(
            await data_api.get_public_track_asset_url(handle, "track-1", fallback),
            "audio" if fallback == "audio" else "image",
        )
        if media:
            return media
    profile = await resolve_public_profile(username)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    assets = profile.get("assets") or {}
    item = assets.get(kind)
    url = str((item or {}).get("url") or "") if isinstance(item, dict) else ""
    media = _public_media(url, ASSET_KIND_TYPES[kind])
    if media:
        return media
    if kind in {"audio", "audioArtwork"}:
        first = next((track for track in assets.get("tracks") or [] if isinstance(track, dict)), None)
        source = (first or {}).get("audio" if kind == "audio" else "artwork")
        media = _public_media(
            str((source or {}).get("url") or "") if isinstance(source, dict) else "",
            "audio" if kind == "audio" else "image",
        )
        if media:
            return media
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")


@router.get("/{username}/og.jpg")
@router.get("/{username}/og.png")
async def public_og_image(username: str) -> Response:
    handle = username.strip().lower()
    if not USERNAME_RE.fullmatch(handle):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/og.jpg")
    bits = await data_api.get_share_card_bits(handle)
    if bits is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    image = await render_og_png(bits)
    version = str(bits.get("version") or "0")
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=120, stale-while-revalidate=600",
            "ETag": f'W/"{handle}-{version}"',
        },
    )


@router.get("/{username}/tracks/{track_id}/{kind}")
async def public_track_asset(username: str, track_id: str, kind: str) -> Response:
    handle = username.strip().lower()
    if kind not in {"audio", "artwork"} or not USERNAME_RE.fullmatch(handle):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    alias = await current_handle_for(handle)
    if alias:
        return username_redirect(f"/api/v1/profile/{alias}/tracks/{track_id}/{kind}")
    media = _public_media(await data_api.get_public_track_asset_url(handle, track_id, kind), "audio" if kind == "audio" else "image")
    if media:
        return media
    if kind == "artwork":
        media = _public_media(await data_api.get_public_asset_url(handle, "avatar"), "image")
        if media:
            return media
    profile = await resolve_public_profile(username)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    assets = profile.get("assets") or {}
    track = next((item for item in assets.get("tracks") or [] if isinstance(item, dict) and item.get("id") == track_id), None)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    source = track.get("audio" if kind == "audio" else "artwork")
    url = str((source or {}).get("url") or "") if isinstance(source, dict) else ""
    media = _public_media(url, "audio" if kind == "audio" else "image")
    if media:
        return media
    if kind == "artwork":
        avatar = (assets.get("avatar") or {}).get("url") if isinstance(assets.get("avatar"), dict) else ""
        media = _public_media(str(avatar or ""), "image")
        if media:
            return media
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")


@router.get("/me")
async def my_profile(user: User = Depends(require_user)) -> dict[str, Any]:
    profile = unwrap_profile_config(await data_api.get_profile(user.id))
    grants = await data_api.list_user_badge_grants(user.id)
    if profile is None:
        if not user.username:
            return {"profile": None}
        cleaned = apply_badge_ownership(sanitize_profile_config(stamp_join_date(default_public_profile(user), user)), None, grants)
    else:
        cleaned = apply_badge_ownership(sanitize_profile_config(stamp_join_date(profile, user)), profile, grants)
    from app.db import achievements
    cleaned["rank"] = await achievements.current_rank_for_user(user.id)
    identity = cleaned.get("profile")
    if isinstance(identity, dict):
        identity["views"] = await data_api.get_profile_view_count(user.id)
    return {"profile": cleaned}


@router.put("/me")
async def save_my_profile(payload: dict[str, Any], user: User = Depends(require_user)) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid profile payload.")
    if not user.username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose a username before saving your profile.")
    profile = payload["profile"]
    if str(profile.get("username", "")).strip().lower() != user.username.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Profile username does not match the signed-in account.")
    profile["username"] = user.username
    profile["uid"] = user.id
    existing = unwrap_profile_config(await data_api.get_profile(user.id))
    payload = apply_badge_ownership(
        sanitize_profile_config(stamp_join_date(merge_kept_profile(payload, existing), user)),
        existing,
        await data_api.list_user_badge_grants(user.id),
    )
    from app.core.premium import protect_write, has_premium
    payload = protect_write(payload, existing, await has_premium(user.id))
    display_name = str(profile.get("displayName", "")).strip()
    if not display_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name cannot be empty.")
    try:
        updated = await data_api.update_user(user.id, display_name=display_name)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
        from app.core.feature_privacy import sync_after_save, sync_private_features
        payload = await sync_private_features(user.id, payload, existing)
        saved = await data_api.save_profile(user.id, payload)
        await sync_after_save(user.id, payload)
        from app.db import achievements
        await achievements.evaluate_user(user.id)
        if user.username:
            try:
                await feature_api.archive_capture(user.id, saved, reason="profile save")
            except Exception:
                pass
        response_profile = saved
        if isinstance(saved, dict):
            response_profile = apply_badge_ownership(
                sanitize_profile_config(saved),
                saved,
                await data_api.list_user_badge_grants(user.id),
            )
            response_profile["rank"] = await achievements.current_rank_for_user(user.id)
    except HTTPException:
        raise
    except (HTTPError, RuntimeError, ValueError, TimeoutError, OSError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Profile storage is temporarily unavailable. Please try again.") from None
    return {"profile": response_profile}


def _archive_epoch(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


def _redact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(snapshot)
    settings = redacted.get("settings")
    if isinstance(settings, dict):
        capsule = settings.get("capsule")
        if isinstance(capsule, dict):
            capsule = dict(capsule)
            capsule["text"] = ""
            settings["capsule"] = capsule
        secret = settings.get("secret")
        if isinstance(secret, dict):
            secret = dict(secret)
            secret["word"] = ""
            secret["url"] = ""
            settings["secret"] = secret
    return redacted


@router.get("/me/archive")
async def archive_list(user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        payload = await feature_api.archive_list(user.id)
    except Exception as ex:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Feature service is temporarily unavailable.") from ex
    days: list[int] = []
    for item in (payload or {}).get("archive", []):
        if isinstance(item, dict) and item.get("created_at"):
            days.append(_archive_epoch(str(item["created_at"])))
    return {"days": days}


@router.post("/me/archive/{sec}/restore")
async def archive_restore(sec: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        target = int(sec)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found.")
    try:
        payload = await feature_api.archive_list(user.id)
    except Exception as ex:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Feature service is temporarily unavailable.") from ex
    seq = None
    for item in (payload or {}).get("archive", []):
        if isinstance(item, dict) and item.get("created_at"):
            if _archive_epoch(str(item["created_at"])) == target:
                seq = item.get("seq")
                break
    if seq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found.")
    try:
        result = await feature_api.archive_restore(user.id, int(seq))
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found.")
        fetched = await feature_api.archive_get(user.id, int(seq))
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Feature service is temporarily unavailable.") from ex
    snapshot = (fetched or {}).get("snapshot")
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Revision could not be read.")
    try:
        saved = await data_api.save_profile(user.id, _redact_snapshot(snapshot))
        from app.db import achievements
        await achievements.evaluate_user(user.id)
        response_profile = apply_badge_ownership(
            sanitize_profile_config(saved),
            saved,
            await data_api.list_user_badge_grants(user.id),
        )
        response_profile["rank"] = await achievements.current_rank_for_user(user.id)
    except (HTTPError, RuntimeError, ValueError, TimeoutError, OSError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Profile storage is temporarily unavailable. Please try again.") from None
    return {"profile": response_profile}


@router.post("/me/preview")
async def preview(user: User = Depends(require_user)) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Page preview isn't wired up yet — save and open your live page instead.")
