"""Feature routes: public views keyed by username, owner actions keyed by session.

Everything is proxied to the Rust data-api; this router only resolves
username -> user id and applies session authorization for owner endpoints.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from httpx import HTTPError, HTTPStatusError

from app.api.v1.profile import require_user
from app.core.rate_limit import client_ip
from app.core.sessions import get_user_from_request
from app.db import data_api, feature_api
from app.models import User

router = APIRouter(prefix="/features", tags=["features"])

_FEATURE_OWNER_ACTIONS = {
    "approve": None,
    "reject": None,
    "remove": None,
    "pin": None,
    "publish": None,
    "draft": None,
}

# Rust moderation verbs differ from the /approve naming the API used before.
_DRAWING_ACTION_ALIASES = {
    "approve": "keep",
}


# Client-facing codes from the data-api that are safe to pass through. Anything
# else (5xx, transport errors) stays a generic 502.
_PASSTHROUGH_STATUS = {400, 403, 404, 409, 410, 413, 422, 429}


def _proxy_errors(exc: Exception) -> HTTPException | None:
    if isinstance(exc, feature_api.DataConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.code)
    if isinstance(exc, HTTPStatusError) and exc.response.status_code in _PASSTHROUGH_STATUS:
        # Validation errors, rate limits, "feature off" and stale grants used to
        # surface as "Feature service is temporarily unavailable" (502).
        code = exc.response.status_code
        try:
            body = exc.response.json()
        except ValueError:
            body = {}
        error = str(body.get("error") or "") if isinstance(body, dict) else ""
        reason = str(body.get("reason") or "") if isinstance(body, dict) else ""
        if error == "feature_off":
            # Generic, non-leaking answer for disabled features (spec p.19).
            return HTTPException(status_code=code, detail="FEATURE_UNAVAILABLE")
        headers = {"Retry-After": "600"} if code == 429 else None
        return HTTPException(status_code=code, detail=reason or error or "Request rejected.", headers=headers)
    if isinstance(exc, HTTPError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Feature service is temporarily unavailable.")
    return None


async def _resolve(user_id_or_username: str) -> str | None:
    """username or raw uuid -> data-api user id."""
    if len(user_id_or_username) == 36 and user_id_or_username.count("-") == 4:
        return user_id_or_username
    return await data_api.get_user_id_by_username(user_id_or_username)


async def _owner(request: Request) -> User:
    user = await get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return user


def _bounce(ex: Exception) -> None:
    proxy = _proxy_errors(ex)
    if proxy is not None:
        raise proxy
    raise ex


# ----- owner inboxes ---------------------------------------------------------
# Static owner paths must be registered before the public "/{username}" routes
# that share their prefix: Starlette matches in order, so "/guestbook/inbox"
# used to resolve to the public guestbook of a user called "inbox" (404).

@router.get("/guestbook/inbox")
async def guestbook_inbox(user: User = Depends(require_user)):
    try:
        payload = await feature_api.guestbook_inbox(user.id)
    except Exception as ex:
        _bounce(ex)
    return {"entries": (payload or {}).get("entries", [])}


@router.get("/asks/inbox")
async def asks_inbox(user: User = Depends(require_user)):
    try:
        payload = await feature_api.asks_inbox(user.id)
    except Exception as ex:
        _bounce(ex)
    return {"asks": (payload or {}).get("asks", [])}


@router.get("/drawings/board")
async def drawings_board(user: User = Depends(require_user)):
    try:
        payload = await feature_api.drawings_board(user.id)
    except Exception as ex:
        _bounce(ex)
    return {"drawings": (payload or {}).get("drawings", [])}


# ----- guestbook -------------------------------------------------------------

@router.get("/guestbook/{username}")
async def guestbook_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.guestbook_list(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"guestbook": payload.get("entries", [])}


@router.post("/guestbook/{username}")
async def guestbook_submit(username: str, request: Request, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        result = await feature_api.guestbook_submit(
            user_id,
            name=str(payload.get("name", "")),
            message=str(payload.get("message", "")),
            ip=client_ip(request),
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.post("/guestbook/inbox/{entry_id}/{action}")
async def guestbook_moderate(entry_id: str, action: str, user: User = Depends(require_user)):
    if action not in _FEATURE_OWNER_ACTIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    try:
        result = await feature_api.guestbook_moderate(user.id, entry_id, action)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- asks ------------------------------------------------------------------

@router.get("/asks/{username}")
async def asks_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.asks_list(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"asks": payload.get("asks", [])}


@router.post("/asks/{username}")
async def asks_submit(username: str, request: Request, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        result = await feature_api.asks_submit(
            user_id,
            question=str(payload.get("question", "")),
            contact=str(payload.get("contact", "")) or None,
            ip=client_ip(request),
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.post("/asks/inbox/{ask_id}/{action}")
async def asks_action(ask_id: str, action: str, request: Request, user: User = Depends(require_user)):
    if action not in _FEATURE_OWNER_ACTIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    body: dict[str, Any] = {}
    if action == "draft":
        raw = await request.json()
        body = {"answer": raw.get("answer", "")}
    try:
        result = await feature_api.asks_action(user.id, ask_id, action, **body)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- drawings --------------------------------------------------------------

@router.get("/drawings/{username}")
async def drawings_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.drawings_gallery(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"drawings": payload.get("drawings", [])}


@router.post("/drawings/{username}")
async def drawings_submit(username: str, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    strokes = payload.get("strokes") or []
    if not isinstance(strokes, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid strokes.")
    try:
        result = await feature_api.drawings_submit(
            user_id,
            strokes=strokes,
            description=str(payload.get("description", "")) or None,
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.post("/drawings/{entry_id}/{action}")
async def drawings_action(entry_id: str, action: str, user: User = Depends(require_user)):
    if action not in _FEATURE_OWNER_ACTIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    rust_action = _DRAWING_ACTION_ALIASES.get(action, action)
    try:
        result = await feature_api.drawings_action(user.id, entry_id, rust_action)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- neighbours ------------------------------------------------------------

@router.get("/neighbours/{username}")
async def neighbours_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.neighbours_public(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"neighbours": payload.get("neighbours", [])}


@router.get("/neighbours")
async def neighbours_owner(user: User = Depends(require_user)):
    try:
        payload = await feature_api.neighbours_owner(user.id)
    except Exception as ex:
        _bounce(ex)
    return payload or {"slots": 5, "neighbours": []}


@router.post("/neighbours")
async def neighbours_nominate(payload: dict[str, Any], user: User = Depends(require_user)):
    try:
        result = await feature_api.neighbours_nominate(user.id, to_username=str(payload.get("to_username", "")))
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.post("/neighbours/{to_username}/remove")
async def neighbours_remove(to_username: str, user: User = Depends(require_user)):
    try:
        result = await feature_api.neighbours_remove(user.id, to_username)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- moon / night ----------------------------------------------------------

@router.get("/moon/{username}")
async def moon_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.moon_view(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"moon": payload}


@router.get("/night/{username}")
async def night_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.night_view(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"night": payload}


# ----- capsule ---------------------------------------------------------------

@router.get("/capsule/{username}")
async def capsule_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.capsule_view(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"capsule": payload}


@router.post("/capsule/publish")
async def capsule_publish(user: User = Depends(require_user)):
    try:
        result = await feature_api.capsule_publish(user.id)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.post("/capsule/unpublish")
async def capsule_unpublish(user: User = Depends(require_user)):
    try:
        result = await feature_api.capsule_unpublish(user.id)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- tally -----------------------------------------------------------------

@router.get("/tally/{username}")
async def tally_public(username: str, voter: str | None = None):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.tally_current(user_id, voter=(voter or "")[:128] or None)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"tally": payload.get("poll"), "counts": payload.get("counts"), "voted": payload.get("voted")}


@router.post("/tally/{username}/vote")
async def tally_vote(username: str, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        result = await feature_api.tally_vote(
            user_id,
            token=str(payload.get("token", "")),
            option=str(payload.get("option", "")),
            idem=str(payload.get("idem", "")),
            poll_id=str(payload.get("poll_id") or "") or None,
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.post("/tally/publish")
async def tally_publish(payload: dict[str, Any], user: User = Depends(require_user)):
    poll = payload.get("poll")
    if not isinstance(poll, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid poll.")
    try:
        result = await feature_api.tally_publish(user.id, poll)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.post("/tally/{action}")
async def tally_action(action: str, user: User = Depends(require_user)):
    if action not in {"close", "reopen", "reset"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    try:
        result = await feature_api.tally_action(user.id, action)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- secret word ------------------------------------------------------------

@router.post("/secret/{username}/attempt")
async def secret_attempt(username: str, request: Request, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        result = await feature_api.secret_attempt(
            user_id,
            word=str(payload.get("word", "")),
            ip=client_ip(request),
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.get("/secret/grant/{grant}")
async def secret_resolve(grant: str, username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        result = await feature_api.secret_resolve(user_id, grant)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.post("/secret/set")
async def secret_set(payload: dict[str, Any], user: User = Depends(require_user)):
    try:
        result = await feature_api.secret_set(
            user.id,
            word=str(payload.get("word", "")),
            url=str(payload.get("url", "")),
            label=str(payload.get("label", "")),
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


@router.post("/secret/clear")
async def secret_clear(user: User = Depends(require_user)):
    try:
        result = await feature_api.secret_clear(user.id)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result


# ----- archive ----------------------------------------------------------------

@router.get("/archive")
async def archive_list(user: User = Depends(require_user)):
    try:
        payload = await feature_api.archive_list(user.id)
    except Exception as ex:
        _bounce(ex)
    return {"archive": (payload or {}).get("archive", [])}


@router.get("/archive/{seq}")
async def archive_get(seq: int, user: User = Depends(require_user)):
    try:
        payload = await feature_api.archive_get(user.id, seq)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found.")
    return payload


@router.post("/archive/{seq}/restore")
async def archive_restore(seq: int, user: User = Depends(require_user)):
    try:
        result = await feature_api.archive_restore(user.id, seq)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found.")
    return result


# ----- daily draw -------------------------------------------------------------

@router.get("/draw/{username}")
async def draw_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.draw_view(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return {"draw": payload}


# ----- presence / hits ---------------------------------------------------------

@router.post("/alive/{username}")
async def alive_heartbeat(username: str, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        try:
            lease_seconds = int(payload.get("lease_seconds", 60))
        except (TypeError, ValueError):
            lease_seconds = 60
        result = await feature_api.alive_heartbeat(
            user_id,
            token=str(payload.get("token", "")),
            lease_seconds=lease_seconds,
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.get("/alive/count/{username}")
async def alive_count(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.alive_count(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return payload


@router.post("/hits/{username}")
async def hits_record(username: str, request: Request, payload: dict[str, Any]):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    ua = request.headers.get("user-agent", "")
    try:
        result = await feature_api.hits_record(
            user_id,
            token=str(payload.get("token", "")),
            ua=ua,
            skip=bool(payload.get("skip", False)),
        )
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return result


@router.get("/hits/{username}")
async def hits_view(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.hits_view(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return payload


# ----- reverse ---------------------------------------------------------------

@router.get("/reverse/{username}")
async def reverse_public(username: str):
    user_id = await _resolve(username)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    try:
        payload = await feature_api.reverse_get(user_id)
    except Exception as ex:
        _bounce(ex)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return payload or {"placements": []}


@router.put("/reverse")
async def reverse_set(payload: dict[str, Any], user: User = Depends(require_user)):
    placements = payload.get("placements") or []
    if not isinstance(placements, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid placements.")
    try:
        result = await feature_api.reverse_set(user.id, placements)
    except Exception as ex:
        _bounce(ex)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return result
