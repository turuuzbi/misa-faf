from typing import Any

import httpx
from fastapi import HTTPException, status

from app.models import User

_client: httpx.AsyncClient | None = None


class DataConflict(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def init_data_api(base_url: str, api_key: str) -> None:
    global _client
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-Data-Key"] = api_key
    _client = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=10.0)
    response = await _client.get("/health")
    response.raise_for_status()


async def close_data_api() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _client_or_raise() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("prostgres_db is not initialised")
    return _client


_RETRY_SAFE_METHODS = {"GET", "HEAD", "PUT", "DELETE"}


async def _request(method: str, path: str, **kwargs: Any) -> dict | None:
    response = await _client_or_raise().request(method, path, **kwargs)
    # Retry once on a server error, but only for idempotent methods: replaying a
    # POST (a guestbook entry, a vote, an AMA question) could store it twice.
    if response.status_code >= 500 and method.upper() in _RETRY_SAFE_METHODS:
        response = await _client_or_raise().request(method, path, **kwargs)
    if response.status_code == 404:
        return None
    if response.status_code == 409:
        payload = response.json() if response.content else {}
        raise DataConflict(str(payload.get("error") or "conflict"))
    if response.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The data API key is missing or wrong. Add DATA_API_KEY to .env and restart.",
        )
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()


async def get_user(user_id: str) -> User | None:
    payload = await _request("GET", f"/v1/users/{user_id}")
    return User.from_api(payload) if payload else None


async def find_user(**filters: str | None) -> User | None:
    params = {key: value for key, value in filters.items() if value}
    payload = await _request("GET", "/v1/users", params=params)
    return User.from_api(payload) if payload else None


async def create_user(**fields: Any) -> User:
    payload = await _request("POST", "/v1/users", json=fields)
    if payload is None:
        raise RuntimeError("prostgres_db did not return a user")
    return User.from_api(payload)


async def update_user(user_id: str, **fields: Any) -> User | None:
    payload = await _request("PATCH", f"/v1/users/{user_id}", json=fields)
    return User.from_api(payload) if payload else None


async def touch_login(user_id: str) -> User | None:
    return await update_user(user_id, touch_login=True)


async def get_user_discord_id(user_id: str) -> str | None:
    from app.db.admin_db import get_user_discord_id as db_get_user_discord_id, has_pool
    try:
        if has_pool():
            return await db_get_user_discord_id(user_id)
    except (RuntimeError, OSError, ValueError):
        return None
    return None


async def get_discord_link(user_id: str) -> dict | None:
    from app.db.admin_db import get_discord_link as db_get_discord_link, has_pool
    try:
        if has_pool():
            return await db_get_discord_link(user_id)
    except (RuntimeError, OSError, ValueError):
        return None
    return None


async def save_discord_link(user_id: str, **fields: Any) -> dict | None:
    from app.db.admin_db import has_pool, save_discord_link as db_save_discord_link
    if not has_pool():
        return None
    return await db_save_discord_link(user_id, **fields)


async def update_discord_prefs(user_id: str, **prefs: bool) -> dict | None:
    from app.db.admin_db import has_pool, update_discord_prefs as db_update_discord_prefs
    if not has_pool():
        return None
    return await db_update_discord_prefs(user_id, **prefs)


async def delete_discord_link(user_id: str) -> None:
    from app.db.admin_db import delete_discord_link as db_delete_discord_link, has_pool
    if has_pool():
        await db_delete_discord_link(user_id)


async def clear_user_discord_id(user_id: str) -> None:
    from app.db.admin_db import clear_user_discord_id as db_clear_user_discord_id, has_pool
    if has_pool():
        await db_clear_user_discord_id(user_id)
    try:
        await update_user(user_id, discord_id=None)
    except (HTTPError, RuntimeError, HTTPException, DataConflict):
        return


async def clear_user_provider(user_id: str, provider: str) -> User | None:
    from app.db.admin_db import clear_user_provider as db_clear_user_provider, has_pool
    if has_pool():
        await db_clear_user_provider(user_id, provider)
        return await get_user(user_id)
    payload = await _request("POST", f"/v1/users/{user_id}/providers/{provider}")
    return User.from_api(payload) if payload else None


async def get_user_id_by_username(username: str) -> str | None:
    from app.db.admin_db import get_user_id_by_username as db_get_user_id_by_username, has_pool
    try:
        if has_pool():
            return await db_get_user_id_by_username(username)
    except (RuntimeError, OSError, ValueError):
        return None
    user = await find_user(username=username)
    return user.id if user else None


async def get_profile_view_count(user_id: str) -> int:
    from app.db.admin_db import get_profile_view_count as db_get_profile_view_count, has_pool
    try:
        if has_pool():
            return await db_get_profile_view_count(user_id)
    except (RuntimeError, OSError, ValueError):
        return 0
    return 0


async def record_profile_event(
    user_id: str,
    kind: str,
    *,
    social_id: str,
    social_label: str,
    referrer_host: str,
    country: str,
    device: str,
    visitor_hash: str,
) -> None:
    from app.db.admin_db import has_pool, record_profile_event as db_record_profile_event
    if has_pool():
        await db_record_profile_event(
            user_id,
            kind,
            social_id=social_id,
            social_label=social_label,
            referrer_host=referrer_host,
            country=country,
            device=device,
            visitor_hash=visitor_hash,
        )


async def analytics_window(user_id: str, start: Any, end: Any) -> dict[str, Any]:
    from app.db.admin_db import analytics_window as db_analytics_window, has_pool
    empty = {"views": 0, "clicks": 0, "series": [], "devices": {}, "referrers": [], "socials": [], "countries": []}
    try:
        if has_pool():
            return await db_analytics_window(user_id, start, end)
    except (RuntimeError, OSError, ValueError):
        return empty
    return empty


async def get_share_card_bits(username: str) -> dict[str, Any] | None:
    from app.db.admin_db import get_share_card_bits as db_get_share_card_bits, has_pool
    try:
        if has_pool():
            return await db_get_share_card_bits(username)
    except (RuntimeError, OSError, ValueError):
        return None
    return None


async def get_public_asset_url(username: str, kind: str) -> str | None:
    from app.db.admin_db import get_public_asset_url as db_get_public_asset_url, has_pool
    try:
        if has_pool():
            return await db_get_public_asset_url(username, kind)
    except (RuntimeError, OSError, ValueError):
        return None
    return None


async def get_public_track_asset_url(username: str, track_id: str, kind: str) -> str | None:
    from app.db.admin_db import get_public_track_asset_url as db_get_public_track_asset_url, has_pool
    try:
        if has_pool():
            return await db_get_public_track_asset_url(username, track_id, kind)
    except (RuntimeError, OSError, ValueError):
        return None
    return None


async def get_profile(user_id: str) -> dict | None:
    from app.db.admin_db import get_profile as db_get_profile, has_pool
    if has_pool():
        stored = await db_get_profile(user_id)
        if stored is not None:
            return stored
    return await _request("GET", f"/v1/profiles/{user_id}")


async def list_user_badge_grants(user_id: str) -> list[dict]:
    from app.db.admin_db import has_pool, list_user_badge_grants as db_list_user_badge_grants
    try:
        if has_pool():
            return await db_list_user_badge_grants(user_id)
        payload = await _request("GET", f"/v1/users/{user_id}/badges")
        if isinstance(payload, dict) and isinstance(payload.get("badges"), list):
            return [item for item in payload["badges"] if isinstance(item, dict)]
    except (HTTPError, RuntimeError, HTTPException):
        return []
    return []


async def save_profile(user_id: str, config: dict) -> dict:
    from app.core.profiles import unwrap_profile_config
    from app.core.premium import has_premium, protect_write
    existing = unwrap_profile_config(await get_profile(user_id))
    config = protect_write(config, existing, await has_premium(user_id))
    from app.db.admin_db import has_pool, save_profile as db_save_profile
    if has_pool():
        saved = await db_save_profile(user_id, config)
        return unwrap_profile_config(saved) or config
    payload = await _request("PUT", f"/v1/profiles/{user_id}", json={"config": config})
    if payload is None:
        raise RuntimeError("Profile storage did not return a profile")
    return unwrap_profile_config(payload) or config


async def oauth_upsert(
    *,
    provider: str,
    provider_id: str,
    email: str | None = None,
    email_verified: bool = False,
    display_name: str | None = None,
    avatar_url: str | None = None,
    telegram_username: str | None = None,
    current_user_id: str | None = None,
) -> User:
    payload = await _request(
        "POST",
        "/v1/users/oauth",
        json={
            "provider": provider,
            "provider_id": provider_id,
            "email": email,
            "email_verified": email_verified,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "telegram_username": telegram_username,
            "current_user_id": current_user_id,
        },
    )
    if payload is None:
        raise RuntimeError("prostgres_db did not return a user")
    return User.from_api(payload)
