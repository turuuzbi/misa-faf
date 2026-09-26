"""Keep private feature material out of public payloads, and move it server-side on save.

The page editor stores feature configuration inside `profile.settings`, and the
public profile endpoints used to return `settings` verbatim. That published the
sealed time-capsule text, the secret word and its hidden link, and the owner's
one-way neighbour nominations to anyone who requested `/api/v1/profile?username=`
(and, through the Next.js profile route, in the page payload).

`public_feature_projection` is the public serializer for those keys.
`sync_private_features` runs on every owner save: it hands the secret word to the
data-api (which stores only a salted scrypt verifier), publishes the tally poll
and reconciles neighbour nominations, so the Rust feature services see what the
editor saved.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from fastapi import HTTPException, status
from httpx import HTTPError, HTTPStatusError

from app.db import feature_api

log = logging.getLogger(__name__)

NEIGHBOUR_SLOTS = 5


def public_feature_projection(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a profile config that is safe to send to any visitor."""
    if not isinstance(config, dict):
        return config
    result = deepcopy(config)
    settings = result.get("settings")
    if not isinstance(settings, dict):
        return result

    capsule = settings.get("capsule")
    if isinstance(capsule, dict):
        # The body is served by /features/capsule/{username} once it is due.
        settings["capsule"] = {
            key: capsule[key] for key in ("label", "at", "tz") if key in capsule
        } | {"sealed": bool(str(capsule.get("text") or "").strip())}

    secret = settings.get("secret")
    if secret is not None:
        # Neither the phrase, the destination nor the reveal label before a successful check.
        configured = bool(isinstance(secret, dict) and (secret.get("configured") or (secret.get("word") and secret.get("url"))))
        settings["secret"] = {"configured": configured}

    neighbours = settings.get("neighbours")
    if isinstance(neighbours, list):
        # Only mutual pairs are public, and those come from /features/neighbours/{username}.
        settings["neighbours"] = bool([name for name in neighbours if str(name or "").strip()])

    return result


def _settings(config: dict[str, Any] | None) -> dict[str, Any]:
    settings = (config or {}).get("settings") if isinstance(config, dict) else None
    return settings if isinstance(settings, dict) else {}


def _reason(exc: HTTPStatusError, fallback: str) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return fallback
    if isinstance(body, dict):
        return str(body.get("reason") or body.get("error") or fallback)
    return fallback


async def _sync_secret(user_id: str, settings: dict[str, Any], previous: dict[str, Any]) -> None:
    secret = settings.get("secret")
    if secret is None:
        return
    if not isinstance(secret, dict):
        settings["secret"] = {"configured": False, "label": ""}
        return
    prev = previous.get("secret") if isinstance(previous.get("secret"), dict) else {}
    was_configured = bool(prev.get("configured") or (prev.get("word") and prev.get("url")))
    word = str(secret.get("word") or "").strip()
    url = str(secret.get("url") or "").strip()
    label = str(secret.get("label") or "").strip()[:80]
    configured = was_configured
    if word and url:
        try:
            await feature_api.secret_set(user_id, word=word, url=url, label=label)
        except HTTPStatusError as exc:
            if exc.response.status_code == 422:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Secret word: {_reason(exc, 'check the word and link')}",
                ) from None
            raise
        configured = True
    elif secret.get("configured") is False and was_configured:
        await feature_api.secret_clear(user_id)
        configured = False
    # Never keep the plaintext phrase or link in the stored profile.
    settings["secret"] = {"configured": configured, "label": label}


async def _sync_tally(user_id: str, settings: dict[str, Any]) -> None:
    tally = settings.get("tally")
    if not isinstance(tally, dict):
        return
    question = str(tally.get("q") or "").strip()
    options = [str(option or "").strip() for option in tally.get("options") or []]
    options = [option for option in options if option]
    if not question or len(options) < 2:
        return
    poll: dict[str, Any] = {"q": question, "options": options}
    if tally.get("visibility") in {"always", "afterVote"}:
        poll["visibility"] = tally["visibility"]
    try:
        # Idempotent: an unchanged open poll is not republished.
        await feature_api.tally_publish(user_id, poll)
    except HTTPStatusError as exc:
        if exc.response.status_code == 422:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tally: {_reason(exc, 'check the question and answers')}",
            ) from None
        raise


async def _sync_neighbours(user_id: str, settings: dict[str, Any]) -> None:
    names = settings.get("neighbours")
    if not isinstance(names, list):
        return
    wanted: list[str] = []
    for name in names:
        handle = str(name or "").strip().lstrip("@").lower()
        if handle and handle not in wanted:
            wanted.append(handle)
    wanted = wanted[:NEIGHBOUR_SLOTS]
    current = await feature_api.neighbours_owner(user_id) or {}
    have = [str(item.get("username") or "").lower() for item in current.get("neighbours") or [] if isinstance(item, dict)]
    for handle in have:
        if handle and handle not in wanted:
            await feature_api.neighbours_remove(user_id, handle)
    for handle in wanted:
        if handle in have:
            continue
        try:
            await feature_api.neighbours_nominate(user_id, to_username=handle)
        except (HTTPStatusError, feature_api.DataConflict):
            # Unknown handle, self, duplicate or full: the editor shows the name as "waiting".
            continue


async def sync_private_features(user_id: str, config: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """Before the profile is stored: move the secret server-side and publish the poll.

    Validation failures raise 422 so the owner sees them and nothing is half-saved.
    A data-api outage while storing the secret raises too (the plaintext must not
    be kept); a tally outage is logged and the save continues.
    """
    settings = _settings(config)
    if not settings:
        return config
    await _sync_secret(user_id, settings, _settings(existing))
    try:
        await _sync_tally(user_id, settings)
    except HTTPException:
        raise
    except (HTTPError, feature_api.DataConflict, RuntimeError, ValueError) as exc:
        log.warning("tally sync skipped for %s: %s", user_id, exc)
    return config


async def sync_after_save(user_id: str, config: dict[str, Any]) -> None:
    """After the profile is stored (the data-api checks the saved switch): reconcile neighbours."""
    settings = _settings(config)
    try:
        await _sync_neighbours(user_id, settings)
    except (HTTPError, feature_api.DataConflict, RuntimeError, ValueError) as exc:
        log.warning("neighbour sync skipped for %s: %s", user_id, exc)
