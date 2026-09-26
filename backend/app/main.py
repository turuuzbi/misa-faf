from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.v1.router import api_router
from app.constellation_system.integration import install_constellations
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.profiles import resolve_public_profile
from app.core.public_profile_html import render_public_profile
from app.core.widgets import profile_widget_inputs
from app.core.security import RESERVED_USERNAMES, USERNAME_RE
from app.core.usernames import current_handle_for, username_redirect
from app.core.turnstile import TURNSTILE_ENABLED
from app.core.middleware import RequestContextMiddleware
from app.core.sessions import get_user_from_request
from app.db import admin_db, close_admin_db, close_data_api, close_dragonfly, init_admin_db, init_data_api, init_dragonfly

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
PAGES_DIR = TEMPLATES_DIR / "pages"
PRIVATE_PAGES = {"dashboard"}
GUEST_PAGES = {"login", "signup", "forgot-password"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging("DEBUG" if settings.debug else "INFO")
    init_dragonfly(settings.dragonfly_url)
    await init_data_api(settings.data_api_url, settings.data_api_key)
    await init_admin_db(settings.database_url, settings.admin_root_email)
    app.state.settings = settings
    yield
    await close_data_api()
    await close_admin_db()
    await close_dragonfly()


def page_file(name: str) -> Path:
    pages = PAGES_DIR.resolve()
    slug = name.removesuffix(".html") or "index"
    if slug != Path(slug).name or slug in {".", ".."}:
        raise HTTPException(status_code=404)
    path = (pages / slug / "index.html").resolve()
    if not path.is_relative_to(pages) or not path.is_file():
        raise HTTPException(status_code=404)
    return path


def html_response(name: str, status_code: int = 200) -> FileResponse:
    return FileResponse(page_file(name), status_code=status_code, media_type="text/html")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    install_constellations(application)

    def frontend_config_js() -> Response:
        current = get_settings()
        payload = json.dumps({
            "turnstileEnabled": TURNSTILE_ENABLED,
            "turnstileSiteKey": current.turnstile_site_key if TURNSTILE_ENABLED else "",
        })
        body = (
            f"window.MISA_CONFIG = {payload};"
            "window.MISA_TURNSTILE_SITE_KEY = window.MISA_CONFIG.turnstileSiteKey;"
        )
        return Response(
            body,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    # Register before the /js StaticFiles mount so this is not shadowed.
    application.add_api_route("/js/config.js", frontend_config_js, methods=["GET"])
    application.add_api_route("/config.js", frontend_config_js, methods=["GET"])

    application.mount("/css", StaticFiles(directory=TEMPLATES_DIR / "css"), name="css")
    application.mount("/js", StaticFiles(directory=TEMPLATES_DIR / "js"), name="js")
    application.mount("/icons", StaticFiles(directory=TEMPLATES_DIR / "icons"), name="icons")
    application.mount("/images", StaticFiles(directory=TEMPLATES_DIR / "images"), name="images")
    application.mount("/fonts", StaticFiles(directory=TEMPLATES_DIR / "fonts"), name="fonts")

    @application.get("/site.webmanifest")
    async def webmanifest() -> FileResponse:
        return FileResponse(TEMPLATES_DIR / "site.webmanifest", media_type="application/manifest+json")

    @application.get("/")
    async def home() -> FileResponse:
        return html_response("index.html")

    @application.get("/robots.txt")
    async def robots() -> FileResponse:
        return FileResponse(TEMPLATES_DIR / "robots.txt", media_type="text/plain")

    @application.get("/{page}", response_model=None)
    async def html_page(page: str, request: Request) -> FileResponse | RedirectResponse:
        slug = page.removesuffix(".html") or "index"
        if slug == "pricing":
            return RedirectResponse("/#pricing", status_code=307)
        if slug in PRIVATE_PAGES | GUEST_PAGES:
            user = await get_user_from_request(request)
            if slug in PRIVATE_PAGES and user is None:
                return RedirectResponse("/login", status_code=302)
            if slug in GUEST_PAGES and user is not None:
                return RedirectResponse(get_settings().dashboard_url, status_code=302)
            if slug == "dashboard":
                destination = get_settings().dashboard_url
                incoming = str(request.base_url).rstrip("/")
                if destination.startswith("http") and not destination.startswith(incoming):
                    return RedirectResponse(destination, status_code=302)
        if USERNAME_RE.fullmatch(slug) and slug not in RESERVED_USERNAMES | PRIVATE_PAGES | GUEST_PAGES:
            try:
                profile = await resolve_public_profile(slug)
            except Exception:
                return HTMLResponse(
                    "<!DOCTYPE html><title>Profile unavailable</title><h1>Profile unavailable</h1><p>Please try again in a moment.</p>",
                    status_code=502,
                )
            if profile:
                widgets = [{**item, "status": "empty", "title": item["type"], "subtitle": "Loading…"} for item in profile_widget_inputs(profile) if item.get("enabled")]
                default_fonts = await admin_db.list_default_fonts() if admin_db.has_pool() and (profile.get("settings") or {}).get("profileFont", "Inter") != "Inter" else []
                flags = await admin_db.public_flags()
                return HTMLResponse(render_public_profile(profile, request, widgets=widgets, default_fonts=default_fonts, feature_flags=flags), headers={"Cache-Control": "no-store"})
            alias = await current_handle_for(slug)
            if alias:
                return username_redirect(f"/{alias}")
        return html_response(f"{slug}.html")

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse | JSONResponse:
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if exc.status_code >= 500:
            return HTMLResponse(
                "<!DOCTYPE html><title>Server error</title><h1>Server error</h1>",
                status_code=exc.status_code,
            )
        return HTMLResponse(
            "<!DOCTYPE html><title>Not found</title><h1>Page not found</h1><p><a href='/'>Back home</a></p>",
            status_code=404,
        )

    return application


app = create_app()
