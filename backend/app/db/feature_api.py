"""Thin HTTP proxy from the Python API service to the Rust data-api feature endpoints.

All feature logic, validation and storage lives in the Rust `data-api`
(`/v1/features/{user_id}/...`). This module maps Python callers onto those
routes with the same conventions as `app.db.data_api`: 404 -> None, 409 ->
DataConflict, 401/uncodeable -> HTTPException.
"""

from typing import Any

from app.db.data_api import DataConflict, _request


async def _features(method: str, user_id: str, path: str = "", **kwargs: Any) -> dict | None:
    return await _request(method, f"/v1/features/{user_id}/{path}".rstrip("/"), **kwargs)


# ----- guestbook -------------------------------------------------------------

async def guestbook_submit(user_id: str, *, name: str, message: str, ip: str) -> dict | None:
    # The data-api field is `display_name` (it now also accepts `name`); sending
    # `name` alone made every guestbook submission fail validation.
    return await _features("POST", user_id, "guestbook", json={"display_name": name, "message": message, "ip": ip})


async def guestbook_list(user_id: str) -> dict | None:
    return await _features("GET", user_id, "guestbook")


async def guestbook_inbox(user_id: str, *, status: str | None = None) -> dict | None:
    params = {"status": status} if status else None
    return await _features("GET", user_id, "guestbook/inbox", params=params)


async def guestbook_moderate(user_id: str, entry_id: str, action: str) -> dict | None:
    return await _features("POST", user_id, f"guestbook/{entry_id}/{action}")


# ----- asks ------------------------------------------------------------------

async def asks_submit(user_id: str, *, question: str, contact: str | None, ip: str) -> dict | None:
    payload = {"question": question, "ip": ip}
    if contact:
        payload["contact"] = contact
    return await _features("POST", user_id, "asks", json=payload)


async def asks_list(user_id: str) -> dict | None:
    return await _features("GET", user_id, "asks")


async def asks_inbox(user_id: str) -> dict | None:
    return await _features("GET", user_id, "asks/inbox")


async def asks_action(user_id: str, ask_id: str, action: str, **body: Any) -> dict | None:
    url = f"asks/{ask_id}/{action}"
    if body:
        return await _features("POST", user_id, url, json=body)
    return await _features("POST", user_id, url)


# ----- drawings (chalkboard) -------------------------------------------------

async def drawings_submit(user_id: str, *, strokes: list[Any], description: str | None, schema_version: int = 1) -> dict | None:
    payload: dict[str, Any] = {"strokes": strokes, "schema_version": schema_version}
    if description:
        payload["description"] = description
    return await _features("POST", user_id, "drawings", json=payload)


async def drawings_gallery(user_id: str) -> dict | None:
    return await _features("GET", user_id, "drawings")


async def drawings_board(user_id: str) -> dict | None:
    return await _features("GET", user_id, "drawings/board")


async def drawings_action(user_id: str, entry_id: str, action: str) -> dict | None:
    return await _features("POST", user_id, f"drawings/{entry_id}/{action}")


# ----- neighbours -------------------------------------------------------------

async def neighbours_nominate(user_id: str, *, to_username: str) -> dict | None:
    return await _features("POST", user_id, "neighbours", json={"to_username": to_username})


async def neighbours_owner(user_id: str) -> dict | None:
    return await _features("GET", user_id, "neighbours")


async def neighbours_public(user_id: str) -> dict | None:
    return await _features("GET", user_id, "neighbours/public")


async def neighbours_remove(user_id: str, to_username: str) -> dict | None:
    return await _features("POST", user_id, f"neighbours/{to_username}/remove")


# ----- moon / night -----------------------------------------------------------

async def moon_view(user_id: str) -> dict | None:
    return await _features("GET", user_id, "moon")


async def night_view(user_id: str) -> dict | None:
    return await _features("GET", user_id, "night")


# ----- capsule ----------------------------------------------------------------

async def capsule_view(user_id: str) -> dict | None:
    return await _features("GET", user_id, "capsule")


async def capsule_publish(user_id: str) -> dict | None:
    return await _features("POST", user_id, "capsule/publish")


async def capsule_unpublish(user_id: str) -> dict | None:
    return await _features("POST", user_id, "capsule/unpublish")


# ----- tally -----------------------------------------------------------------

async def tally_current(user_id: str, *, voter: str | None = None) -> dict | None:
    params = {"voter": voter} if voter else None
    return await _features("GET", user_id, "tally", params=params)


async def tally_publish(user_id: str, poll: dict) -> dict | None:
    return await _features("POST", user_id, "tally", json={"poll": poll})


async def tally_vote(user_id: str, *, token: str, option: str, idem: str, poll_id: str | None = None) -> dict | None:
    payload: dict[str, Any] = {"token": token, "option": option, "idem": idem}
    if poll_id:
        payload["poll_id"] = poll_id
    return await _features("POST", user_id, "tally/vote", json=payload)


async def tally_action(user_id: str, action: str) -> dict | None:
    return await _features("POST", user_id, f"tally/{action}")


# ----- secret word -------------------------------------------------------------

async def secret_attempt(user_id: str, *, word: str, ip: str) -> dict | None:
    return await _features("POST", user_id, "secret", json={"word": word, "ip": ip})


async def secret_resolve(user_id: str, grant: str) -> dict | None:
    return await _features("GET", user_id, f"secret/grant/{grant}")


async def secret_set(user_id: str, *, word: str, url: str, label: str) -> dict | None:
    return await _features("POST", user_id, "secret/set", json={"word": word, "url": url, "label": label})


async def secret_clear(user_id: str) -> dict | None:
    return await _features("POST", user_id, "secret/clear")


# ----- archive ---------------------------------------------------------------

async def archive_list(user_id: str) -> dict | None:
    return await _features("GET", user_id, "archive")


async def archive_capture(user_id: str, snapshot: dict, *, reason: str | None = None) -> dict | None:
    payload: dict[str, Any] = {"snapshot": snapshot}
    if reason:
        payload["reason"] = reason
    return await _features("POST", user_id, "archive", json=payload)


async def archive_get(user_id: str, seq: int) -> dict | None:
    return await _features("GET", user_id, f"archive/{seq}")


async def archive_restore(user_id: str, seq: int) -> dict | None:
    return await _features("POST", user_id, f"archive/{seq}/restore", json={"seq": seq})


# ----- daily draw ------------------------------------------------------------

async def draw_view(user_id: str) -> dict | None:
    return await _features("GET", user_id, "draw")


# ----- presence / hits -------------------------------------------------------

async def alive_heartbeat(user_id: str, *, token: str, lease_seconds: int = 60) -> dict | None:
    return await _features("POST", user_id, "alive", json={"token": token, "lease_seconds": lease_seconds})


async def alive_count(user_id: str) -> dict | None:
    return await _features("GET", user_id, "alive/count")


async def alive_snuff(user_id: str) -> dict | None:
    return await _features("POST", user_id, "alive/snuff")


async def hits_record(user_id: str, *, token: str, ua: str = "", skip: bool = False) -> dict | None:
    return await _features("POST", user_id, "hits", json={"token": token, "ua": ua, "skip": skip})


async def hits_view(user_id: str) -> dict | None:
    return await _features("GET", user_id, "hits")


# ----- reverse (placements) ---------------------------------------------------

async def reverse_get(user_id: str) -> dict | None:
    return await _features("GET", user_id, "reverse")


async def reverse_set(user_id: str, placements: list[dict]) -> dict | None:
    return await _features("PUT", user_id, "reverse", json={"placements": placements})


__all__ = [
    "DataConflict",
    "guestbook_submit",
    "guestbook_list",
    "guestbook_inbox",
    "guestbook_moderate",
    "asks_submit",
    "asks_list",
    "asks_inbox",
    "asks_action",
    "drawings_submit",
    "drawings_gallery",
    "drawings_board",
    "drawings_action",
    "neighbours_nominate",
    "neighbours_owner",
    "neighbours_public",
    "neighbours_remove",
    "moon_view",
    "night_view",
    "capsule_view",
    "capsule_publish",
    "capsule_unpublish",
    "tally_current",
    "tally_publish",
    "tally_vote",
    "tally_action",
    "secret_attempt",
    "secret_resolve",
    "secret_set",
    "secret_clear",
    "archive_list",
    "archive_capture",
    "archive_get",
    "archive_restore",
    "draw_view",
    "alive_heartbeat",
    "alive_count",
    "alive_snuff",
    "hits_record",
    "hits_view",
    "reverse_get",
    "reverse_set",
]