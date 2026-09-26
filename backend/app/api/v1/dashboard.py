"""Dashboard routes: the page editor's moderation surface and the public aliases it needs.

The dashboard page (`js/v2.js`) talks to `/api/v1/me/*` for guestbook, doodles,
asks, vigil, stats, replay and badge toggling. All feature moderation is proxied
to the Rust data-api via `feature_api`; stats/views come from the Python
analytics store via `data_api.analytics_window`.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.features import _bounce, _resolve
from app.api.v1.profile import require_user
from app.core.network_safety import probe_public_url
from app.core.profiles import unwrap_profile_config
from app.core.rate_limit import rate_limit
from app.db import data_api, feature_api
from app.models import User

router = APIRouter(tags=["dashboard"])

_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _epoch(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


def _squared(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _strokes_to_svg(strokes: Any) -> str:
    """Serialize chalkboard strokes into a safe inline SVG (100x100 viewBox).

    Stored points are normalized to [0, 1] (the data-api rejects anything else),
    so they are scaled to the 0-100 viewBox; without the scale every thumbnail
    was drawn inside the top-left 1% of the tile.
    """
    parts: list[str] = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img">']
    if isinstance(strokes, list):
        for stroke in strokes:
            points = stroke.get("points") if isinstance(stroke, dict) else None
            if not isinstance(points, list) or not points:
                continue
            coords = []
            valid = True
            for p in points:
                if not isinstance(p, list) or len(p) < 2:
                    valid = False
                    break
                x = max(0.0, min(1.0, _squared(p[0]))) * 100
                y = max(0.0, min(1.0, _squared(p[1]))) * 100
                coords.append(f"{x:.2f},{y:.2f}")
            if not valid or not coords:
                continue
            color = stroke.get("color") if isinstance(stroke, dict) else None
            stroke_color = color if isinstance(color, str) and _HEX_COLOR.fullmatch(color) else "#f2f2f0"
            width = _squared(stroke.get("width")) if isinstance(stroke, dict) else 3.0
            width = max(1.0, min(10.0, width))
            parts.append(
                f'<polyline points="{" ".join(coords)}" fill="none" stroke="{stroke_color}" stroke-width="{width:.1f}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _slip(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(entry.get("id") or ""),
        "line": str(entry.get("message") or ""),
        "name": str(entry.get("display_name") or ""),
        "at": _epoch(str(entry.get("submitted_at") or "")),
    }


def _tile(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(entry.get("id") or ""),
        "svg": _strokes_to_svg(entry.get("strokes")),
        "at": _epoch(str(entry.get("created_at") or "")),
    }


def _ask(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(entry.get("id") or ""),
        "q": str(entry.get("question") or ""),
        "at": _epoch(str(entry.get("submitted_at") or "")),
        "a": str(entry.get("answer") or ""),
    }


# ----- guestbook ------------------------------------------------------------

@router.get("/me/guestbook")
async def guestbook(user: User = Depends(require_user)) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    try:
        raw_pending = await feature_api.guestbook_inbox(user.id, status="pending")
        raw_approved = await feature_api.guestbook_inbox(user.id, status="approved")
    except Exception as ex:
        _bounce(ex)
    if raw_pending is not None:
        pending = [_slip(item) for item in raw_pending.get("entries", []) if isinstance(item, dict)]
    if raw_approved is not None:
        approved = [_slip(item) for item in raw_approved.get("entries", []) if isinstance(item, dict)]
    return {"pending": pending, "approved": approved}


@router.post("/me/guestbook/{entry_id}/approve")
async def guestbook_approve(entry_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.guestbook_moderate(user.id, entry_id, "approve")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.delete("/me/guestbook/{entry_id}")
async def guestbook_bin(entry_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.guestbook_moderate(user.id, entry_id, "remove")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- doodles / chalkboard --------------------------------------------------

@router.get("/me/doodles")
async def doodles(user: User = Depends(require_user)) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    try:
        raw = await feature_api.drawings_board(user.id)
    except Exception as ex:
        _bounce(ex)
    for item in (raw or {}).get("drawings", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") == "pending":
            pending.append(_tile(item))
        elif item.get("status") == "kept":
            approved.append(_tile(item))
    return {"pending": pending, "approved": approved}


@router.post("/me/doodles/{entry_id}/approve")
async def doodles_approve(entry_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.drawings_action(user.id, entry_id, "keep")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.delete("/me/doodles/{entry_id}")
async def doodles_bin(entry_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.drawings_action(user.id, entry_id, "reject")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- asks ------------------------------------------------------------------

@router.get("/me/asks")
async def asks(user: User = Depends(require_user)) -> dict[str, Any]:
    waiting: list[dict[str, Any]] = []
    answered: list[dict[str, Any]] = []
    try:
        raw = await feature_api.asks_inbox(user.id)
    except Exception as ex:
        _bounce(ex)
    for item in (raw or {}).get("asks", []):
        if not isinstance(item, dict):
            continue
        item_status = item.get("status")
        if item_status == "pending":
            waiting.append(_ask(item))
        elif item_status in {"published", "draft"}:
            answered.append(_ask(item))
    return {"waiting": waiting, "answered": answered}


@router.post("/me/asks/{ask_id}/answer")
async def asks_answer(ask_id: str, payload: dict[str, Any], user: User = Depends(require_user)) -> dict[str, Any]:
    answer = str(payload.get("answer", "")).strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Write an answer first.")
    if len(answer) > 2000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Answer too long.")
    try:
        draft = await feature_api.asks_action(user.id, ask_id, "draft", answer=answer)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
        result = await feature_api.asks_action(user.id, ask_id, "publish")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.delete("/me/asks/{ask_id}")
async def asks_bin(ask_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.asks_action(user.id, ask_id, "remove")
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- stats / replay / links ------------------------------------------------

@router.get("/me/stats")
async def my_stats(user: User = Depends(require_user)) -> dict[str, Any]:
    await rate_limit(f"rl:stats:{user.id}", 30, 60)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=13)
    window = await data_api.analytics_window(user.id, start, now)
    series = window.get("series") or []
    by_day = {str(item.get("day")): int(item.get("views") or 0) for item in series}
    start_date = start.date()
    today = now.date()
    daily: list[list[Any]] = []
    for i in range(14):
        day = start_date + timedelta(days=i)
        iso = day.isoformat()
        daily.append([iso, by_day.get(iso, 0)])
    today_views = by_day.get(today.isoformat(), 0)
    week_views = sum(v for _, v in daily[-7:])
    referrers = [[str(row["host"]), int(row["count"])] for row in window.get("referrers") or [] if str(row.get("host") or "") != "direct"]
    clicks = [[str(row["id"]), str(row["label"]), int(row["clicks"])] for row in window.get("socials") or []]
    return {
        "views": await data_api.get_profile_view_count(user.id),
        "today": today_views,
        "week": week_views,
        "daily": daily,
        "referrers": referrers,
        "clicks": clicks,
        "unavailable": False,
    }


@router.get("/me/replay")
async def replay(_user: User = Depends(require_user)) -> dict[str, Any]:
    return {"unavailable": True}


async def _web_url(value: str) -> str | None:
    stripped = value.strip()
    if "://" in stripped:
        return stripped
    if stripped.lower().startswith("www."):
        return "https://" + stripped
    return None


@router.post("/me/links/check")
async def links_check(user: User = Depends(require_user)) -> dict[str, Any]:
    await rate_limit(f"rl:links:{user.id}", 3, 600)
    profile = unwrap_profile_config(await data_api.get_profile(user.id)) or {}
    socials = profile.get("socials")
    targets: list[tuple[str, str]] = []
    if isinstance(socials, list):
        for social in socials:
            if not isinstance(social, dict) or social.get("enabled") is False:
                continue
            if social.get("displayMode") == "text":
                continue
            url = await _web_url(str(social.get("value") or ""))
            if url:
                targets.append((str(social.get("id") or ""), url[:300]))
    if not targets:
        return {"checked": 0, "results": []}
    results: list[dict[str, Any]] = []
    for social_id, url in targets[:20]:
        # SSRF guard: public hosts only, every redirect hop re-checked.
        ok, note = await probe_public_url(url)
        results.append({"id": social_id, "url": url, "ok": ok, "note": note})
    return {"checked": len(results), "results": results}


# ----- vigil / presence -------------------------------------------------------

@router.get("/vigil/{username}")
async def vigil_public(username: str) -> dict[str, Any]:
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.alive_count(user_id)
    except Exception as ex:
        _bounce(ex)
    active = int((payload or {}).get("active") or 0)
    return {"lit": list(range(active))}


@router.delete("/me/vigil")
async def vigil_snuff(user: User = Depends(require_user)) -> dict[str, Any]:
    try:
        result = await feature_api.alive_snuff(user.id)
    except Exception as ex:
        _bounce(ex)
    return result or {"ok": True, "cleared": 0}


# ----- neighbours --------------------------------------------------------------

@router.get("/neighbours/{username}")
async def neighbours_public(username: str) -> dict[str, Any]:
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.neighbours_public(user_id)
    except Exception as ex:
        _bounce(ex)
    return {"neighbours": (payload or {}).get("neighbours", [])}


# ----- badges ------------------------------------------------------------------

@router.patch("/me/badges/{badge_id}")
async def badge_toggle(badge_id: str, payload: dict[str, Any], user: User = Depends(require_user)) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", True))
    grants = await data_api.list_user_badge_grants(user.id)
    if not any(str(g.get("id")) == badge_id for g in grants):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    from app.db import achievements
    updated = await achievements.set_badge_visible(user.id, badge_id, enabled)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    try:
        existing = unwrap_profile_config(await data_api.get_profile(user.id)) or {}
        badges = existing.get("badges")
        if isinstance(badges, list):
            for badge in badges:
                if isinstance(badge, dict) and str(badge.get("id")) == badge_id:
                    badge["enabled"] = enabled
                    break
            await data_api.save_profile(user.id, existing)
    except (httpx.HTTPError, RuntimeError, ValueError, TimeoutError, OSError):
        # `HTTPError` was never imported here, so any failure raised NameError.
        pass
    return {"ok": True, "enabled": enabled}