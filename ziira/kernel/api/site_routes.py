"""Website content: the Super Admin's editing endpoints and the public, read-only content endpoint
(docs/platform-admin-content.md).

Operator side (`/api/v1/operator/site/...`): every route needs the `platform.content` permission, every change needs a
fresh second-factor confirmation (like all console changes) and leaves a line in the operator action trail.
Public side (`/api/v1/public/site`): no sign-in, only what was published, with an ETag and cache headers, and a
per-address rate limit. In a self-hosted deployment none of it exists.
"""

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operator_console as console
from ziira.kernel import operators, site_assets, site_content, site_hook, site_plans
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings
from ziira.kernel.errors import NotFound, TooManyRequests, ValidationFailed, ZiiraError

router = APIRouter(prefix="/api/v1/operator/site", tags=["Website content"])
public_router = APIRouter(prefix="/api/v1/public/site", tags=["Website (public)"])
WEB_ADMIN = "platform.content"


require_content = require(WEB_ADMIN)
require_view = require("platform.view")


def content_operator(operator: operators.Operator = Depends(require_content)) -> operators.Operator:
    """The signed-in operator, holding `platform.content`, in a deployment that has a website."""
    if not site_content.deployment_enabled():
        raise NotFound("The website is not part of a self-hosted deployment")
    return operator


content_operator.platform_permission = WEB_ADMIN                       # type: ignore[attr-defined]  # read by the role matrix test


def change[T](operator: operators.Operator, request: Request, action: str, target: str, work: Callable[[], T],
              detail: Callable[[T], dict[str, Any]] | None = None) -> T:
    """One change: needs a recent confirmation (password or code), and is written to the operator trail whether it
    worked or was refused.
    The trail keeps what changed, not the content (settings and page texts are in their own histories)."""
    ip = client_ip(request)
    if console.step_up_needed(operator):
        console.log_action(operator, action, target=target, outcome="refused", ip_address=ip,
                           detail={"why": console.step_up_why()})
        raise console.StepUpRequired(console.step_up_message())
    try:
        result = work()
    except ZiiraError as error:
        console.log_action(operator, action, target=target, outcome="refused", ip_address=ip,
                           detail={"why": error.message})
        raise
    except Exception as error:
        console.log_action(operator, action, target=target, outcome="failed", ip_address=ip,
                           detail={"error": type(error).__name__})
        raise
    console.log_action(operator, action, target=target, ip_address=ip, detail=detail(result) if detail else None)
    return result


# --------------------------------------------------------------------------- models
class SiteAvailability(BaseModel):
    available: bool = Field(description="False in a self-hosted deployment: there is no marketing site to manage")
    can_edit: bool = Field(description="The signed-in operator holds platform.content")
    hook_configured: bool


class SiteSettingField(BaseModel):
    key: str
    group: str
    kind: str
    required: bool
    max_len: int
    localised: bool


class SiteSettingsOut(BaseModel):
    fields: list[SiteSettingField]
    values: dict[str, Any] = Field(description="The working values; a localised one is {language: text}")
    changed: list[str] = Field(default=[], description="Keys changed by this call")


class SiteSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any] = Field(max_length=60, description="Key to new value; null or empty clears a setting")


class SitePageSummary(BaseModel):
    id: UUID
    slug: str
    locale: str
    kind: str
    title: str
    seo_title: str | None
    seo_description: str | None
    status: str = Field(description="draft | published (goes live with the next site publish)")
    state: str = Field(default="draft", description="draft | new | live | changed | unpublish_pending")
    version: int
    body_length: int = 0
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class SitePageOut(SitePageSummary):
    body_md: str = ""


class SitePageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(max_length=60)
    locale: str = Field(max_length=10)
    kind: str = Field(max_length=10, description="legal | content")
    title: str = Field(max_length=200)
    body_md: str = Field(default="", max_length=130_000)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=400)


class SitePageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, description="The version the editor loaded; a newer one is not overwritten")
    title: str = Field(max_length=200)
    body_md: str = Field(default="", max_length=130_000)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=400)
    note: str | None = Field(default=None, max_length=300)


class SiteVersionSummary(BaseModel):
    version: int
    title: str
    status: str
    note: str | None
    created_at: datetime
    created_by: str | None
    body_length: int


class SiteVersionOut(BaseModel):
    version: int
    title: str
    body_md: str
    seo_title: str | None
    seo_description: str | None
    status: str
    note: str | None
    created_at: datetime
    created_by: str | None


class SiteDiffOut(BaseModel):
    older: int
    newer: int
    diff: str
    added: int
    removed: int


class SitePreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    markdown: str = Field(max_length=130_000)


class SitePreviewOut(BaseModel):
    html: str


class SiteStarter(BaseModel):
    slug: str
    locale: str
    title: str
    body_md: str


class SiteAssetOut(BaseModel):
    id: UUID
    asset_id: str = Field(description="The short name used in Markdown as asset:<id>")
    name: str
    alt: str
    content_type: str
    width: int
    height: int
    size_bytes: int
    hash: str
    file: str
    created_at: datetime


class SiteAltIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alt: str = Field(max_length=300)


class SiteIssue(BaseModel):
    code: str
    message: str
    where: str


class SiteReport(BaseModel):
    ok: bool
    errors: list[SiteIssue]
    warnings: list[SiteIssue]
    counts: dict[str, int]


class SitePendingChange(BaseModel):
    area: str
    ref: str
    change: str


class SitePublicationInfo(BaseModel):
    id: int
    published_at: datetime
    published_by: str
    note: str | None
    version_hash: str


class SitePublishStatus(BaseModel):
    live: SitePublicationInfo | None
    pending: list[SitePendingChange]
    hook_configured: bool


class SitePublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=300)


class SitePublishOut(BaseModel):
    id: int
    published_at: datetime
    published_by: str
    note: str | None
    version_hash: str
    hook_status: str
    pages: int
    warnings: list[SiteIssue]


class SitePublishLine(BaseModel):
    id: int
    published_at: datetime
    published_by: str
    note: str | None
    version_hash: str
    pages: int
    hook_status: str = Field(description="skipped | pending | ok | failed")
    hook_attempts: int
    hook_next_at: datetime | None
    hook_result: str | None


class SiteHookState(BaseModel):
    id: int
    hook_status: str
    hook_attempts: int
    hook_next_at: datetime | None
    hook_result: str | None


class SitePlansPreview(BaseModel):
    plans: list[dict[str, Any]]
    addons: list[dict[str, Any]]
    updated_at: str | None


# --------------------------------------------------------------------------- availability
@router.get("/availability", response_model=SiteAvailability)
def availability(operator: operators.Operator = Depends(require_view)) -> object:
    """Whether the Website area exists here and whether this operator may use it (the menu follows this)."""
    return {"available": site_content.deployment_enabled(), "can_edit": WEB_ADMIN in operator.permissions,
            "hook_configured": site_hook.configured()}


# --------------------------------------------------------------------------- settings
@router.get("/settings", response_model=SiteSettingsOut)
def read_settings(_: operators.Operator = Depends(content_operator)) -> object:
    return {"fields": site_content.schema(), "values": site_content.settings_values()}


@router.put("/settings", response_model=SiteSettingsOut)
def write_settings(body: SiteSettingsIn, request: Request,
                   operator: operators.Operator = Depends(content_operator)) -> object:
    """Check and save settings (all or nothing). A bad value answers 422 with `fields`: a message per setting."""
    changed = change(operator, request, "site.settings.save", "site settings",
                     lambda: site_content.save_settings(body.values, by=operator.name),
                     lambda keys: {"changed": keys})
    return {"fields": site_content.schema(), "values": site_content.settings_values(), "changed": changed}


# --------------------------------------------------------------------------- pages
@router.get("/pages", response_model=list[SitePageSummary])
def pages(locale: str | None = Query(default=None, max_length=10),
          kind: str | None = Query(default=None, max_length=10),
          _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.list_pages(locale, kind)


@router.get("/pages/starters", response_model=list[SiteStarter])
def starters(locale: str = Query(max_length=10), _: operators.Operator = Depends(content_operator)) -> object:
    """Outlines for the legal pages in a language: not legal advice; the publish check refuses them until completed."""
    return site_content.starter_pages(locale)


@router.post("/pages", response_model=SitePageOut, status_code=201)
def create_page(body: SitePageIn, request: Request, operator: operators.Operator = Depends(content_operator)) -> object:
    return change(operator, request, "site.page.create", f"{body.locale}/{body.slug}",
                  lambda: site_content.create_page(by=operator.name, **body.model_dump()), None)


@router.get("/pages/{page_id}", response_model=SitePageOut)
def page(page_id: UUID, _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.get_page(page_id)


@router.put("/pages/{page_id}", response_model=SitePageOut)
def update_page(page_id: UUID, body: SitePageUpdate, request: Request,
                operator: operators.Operator = Depends(content_operator)) -> object:
    return change(operator, request, "site.page.update", str(page_id),
                  lambda: site_content.update_page(page_id, by=operator.name, **body.model_dump()),
                  lambda p: {"slug": p["slug"], "locale": p["locale"], "version": p["version"]})


@router.post("/pages/{page_id}/publish", response_model=SitePageOut)
def mark_published(page_id: UUID, request: Request, operator: operators.Operator = Depends(content_operator)) -> object:
    """Mark the page to go live with the next site publish."""
    return change(operator, request, "site.page.mark_published", str(page_id),
                  lambda: site_content.set_page_status(page_id, "published", by=operator.name),
                  lambda p: {"slug": p["slug"], "locale": p["locale"]})


@router.post("/pages/{page_id}/unpublish", response_model=SitePageOut)
def mark_draft(page_id: UUID, request: Request, operator: operators.Operator = Depends(content_operator)) -> object:
    """Take the page off the site with the next site publish (it stays here as a draft)."""
    return change(operator, request, "site.page.mark_draft", str(page_id),
                  lambda: site_content.set_page_status(page_id, "draft", by=operator.name),
                  lambda p: {"slug": p["slug"], "locale": p["locale"]})


@router.delete("/pages/{page_id}", status_code=204)
def delete_page(page_id: UUID, request: Request, operator: operators.Operator = Depends(content_operator)) -> Response:
    change(operator, request, "site.page.delete", str(page_id), lambda: site_content.delete_page(page_id), lambda p: p)
    return Response(status_code=204)


@router.get("/pages/{page_id}/versions", response_model=list[SiteVersionSummary])
def versions(page_id: UUID, _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.list_versions(page_id)


@router.get("/pages/{page_id}/versions/{version}", response_model=SiteVersionOut)
def version(page_id: UUID, version: int, _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.get_version(page_id, version)


@router.get("/pages/{page_id}/diff", response_model=SiteDiffOut)
def diff(page_id: UUID, older: int = Query(ge=1), newer: int = Query(ge=1),
         _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.diff_versions(page_id, older, newer)


@router.post("/pages/{page_id}/versions/{version}/restore", response_model=SitePageOut)
def restore(page_id: UUID, version: int, request: Request,
            operator: operators.Operator = Depends(content_operator)) -> object:
    """Make an old version's content the newest version (history keeps everything)."""
    return change(operator, request, "site.page.restore", str(page_id),
                  lambda: site_content.restore_version(page_id, version, by=operator.name),
                  lambda p: {"slug": p["slug"], "locale": p["locale"], "from_version": version,
                             "version": p["version"]})


@router.post("/preview", response_model=SitePreviewOut)
def preview(body: SitePreviewIn, _: operators.Operator = Depends(content_operator)) -> object:
    """The safe HTML a Markdown text becomes (nothing is saved)."""
    return {"html": site_content.preview(body.markdown)}


# --------------------------------------------------------------------------- pictures
@router.get("/assets", response_model=list[SiteAssetOut])
def assets(_: operators.Operator = Depends(content_operator)) -> object:
    return site_assets.listing()


@router.post("/assets", response_model=SiteAssetOut, status_code=201)
async def upload_asset(request: Request, name: str = Query(default="image", max_length=120),
                       alt: str = Query(default="", max_length=300),
                       operator: operators.Operator = Depends(content_operator)) -> object:
    """Add a picture: the image file is the request body (PNG, JPEG or WebP). It is checked and re-encoded, which
    removes camera and location data."""
    if not (request.headers.get("content-type", "").lower().startswith("image/")):
        raise ValidationFailed("Send the image as the request body with an image/* content type")
    raw = await request.body()
    return await run_in_threadpool(
        change, operator, request, "site.asset.upload", name,
        lambda: site_assets.save(raw, name=name, alt=alt, by=operator.name), lambda a: {"asset_id": a["asset_id"]})


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: UUID, _: operators.Operator = Depends(content_operator)) -> Response:
    """The stored picture, for the media library's own thumbnails (needs the operator's sign-in)."""
    data, content_type = site_assets.content(asset_id)
    return Response(data, media_type=content_type, headers={"Cache-Control": "private, max-age=300",
                                                            "X-Content-Type-Options": "nosniff"})


@router.put("/assets/{asset_id}", response_model=SiteAssetOut)
def update_asset(asset_id: UUID, body: SiteAltIn, request: Request,
                 operator: operators.Operator = Depends(content_operator)) -> object:
    return change(operator, request, "site.asset.update", str(asset_id),
                  lambda: site_assets.set_alt(asset_id, body.alt))


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(asset_id: UUID, request: Request,
                 operator: operators.Operator = Depends(content_operator)) -> Response:
    def work() -> None:
        used = site_content.asset_usage(asset_id)
        if used:
            raise ValidationFailed("This picture is still used: " + ", ".join(used[:8]), {"used_in": used})
        site_assets.remove(asset_id)

    change(operator, request, "site.asset.delete", str(asset_id), work)
    return Response(status_code=204)


# --------------------------------------------------------------------------- publishing
@router.get("/validate", response_model=SiteReport)
def validate(_: operators.Operator = Depends(content_operator)) -> object:
    """Whether the working copy could be published now, and why not."""
    return site_content.validate()


@router.get("/status", response_model=SitePublishStatus)
def status(_: operators.Operator = Depends(content_operator)) -> object:
    """What is live and what a publish would change."""
    live = site_content.current_publication()
    keys = ("id", "published_at", "published_by", "note", "version_hash")
    return {"live": {k: live[k] for k in keys} if live else None,
            "pending": site_content.pending_changes(), "hook_configured": site_hook.configured()}


@router.post("/publish", response_model=SitePublishOut, status_code=201)
def publish(body: SitePublishIn, request: Request, background: BackgroundTasks,
            operator: operators.Operator = Depends(content_operator)) -> object:
    """Make the working copy the live site content, then ask the site to rebuild (done after the reply)."""
    result = change(operator, request, "site.publish", "website",
                    lambda: site_content.publish(by=operator.name, note=body.note,
                                                 hook_configured=site_hook.configured()),
                    lambda r: {"publish_id": r["id"], "version_hash": r["version_hash"], "pages": r["pages"]})
    if result["hook_status"] == "pending":
        background.add_task(site_hook.attempt, result["id"])
    return result


@router.get("/publishes", response_model=list[SitePublishLine])
def publishes(limit: int = Query(default=50, ge=1, le=200),
              _: operators.Operator = Depends(content_operator)) -> object:
    return site_content.history(limit)


@router.post("/publishes/{publish_id}/retry-hook", response_model=SiteHookState)
def retry_hook(publish_id: int, request: Request, operator: operators.Operator = Depends(content_operator)) -> object:
    """Try the site rebuild again now (for a publish whose rebuild failed or is still waiting)."""
    return change(operator, request, "site.hook.retry", str(publish_id), lambda: site_hook.retry(publish_id),
                  lambda s: {"publish_id": publish_id, "hook_status": s["hook_status"]})


@router.get("/plans", response_model=SitePlansPreview)
def plans_preview(_: operators.Operator = Depends(content_operator)) -> object:
    """The public plans exactly as the website receives them (edited under Plans)."""
    return site_plans.public_plans()


# --------------------------------------------------------------------------- public
_hits: dict[str, deque[float]] = {}
_hits_lock = threading.Lock()


def _rate_limit(request: Request) -> None:
    """At most `ZIIRA_SITE_PUBLIC_RATE_PER_MINUTE` requests a minute from one address (counted in this process; put a
    proxy rate limit in front for anything stronger)."""
    limit = get_settings().site_public_rate_per_minute
    key = client_ip(request) or "unknown"
    now = time.monotonic()
    with _hits_lock:
        if len(_hits) > 5000:
            for stale in [k for k, q in _hits.items() if not q or now - q[-1] > 60]:
                del _hits[stale]
        queue = _hits.setdefault(key, deque())
        while queue and now - queue[0] > 60:
            queue.popleft()
        if len(queue) >= limit:
            raise TooManyRequests("Too many requests. Wait a minute and try again.",
                                  {"retry_after": max(1, int(60 - (now - queue[0])) + 1)})
        queue.append(now)


def reset_rate_limits() -> None:
    with _hits_lock:
        _hits.clear()


PUBLIC_CACHE = "public, max-age=60, stale-while-revalidate=300"


def public_payload() -> tuple[dict[str, Any], str]:
    """The public content and its ETag: only the newest publish's snapshot, the plans, and nothing else."""
    live = site_content.current_publication()
    plans = site_plans.public_plans()
    if live is None:
        body: dict[str, Any] = {"published": False, "settings": {}, "pages": [], "plans": plans["plans"],
                                "addons": plans["addons"], "assets": [], "published_at": None, "version_hash": None}
        seed = "none"
    else:
        snap = live["snapshot"]
        body = {"published": True, "settings": snap["settings"], "pages": snap["pages"], "plans": plans["plans"],
                "addons": plans["addons"], "assets": snap["assets"],
                "published_at": live["published_at"].isoformat(), "version_hash": live["version_hash"]}
        seed = live["version_hash"]
    tag = hashlib.sha256((seed + json.dumps(plans, sort_keys=True, default=str)).encode()).hexdigest()[:32]
    return body, f'"{tag}"'


def _not_modified(request: Request, tag: str) -> bool:
    sent = [t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")]
    return tag in sent or "*" in sent


@public_router.get("")
def public_site(request: Request) -> Response:
    """The published website content: settings, pages (HTML and Markdown), the plans, pictures. The static site's build
    fetches this. Cacheable; `If-None-Match` gives 304."""
    if not site_content.deployment_enabled():
        raise NotFound("Not found")
    _rate_limit(request)
    body, tag = public_payload()
    headers = {"ETag": tag, "Cache-Control": PUBLIC_CACHE, "X-Content-Type-Options": "nosniff"}
    if _not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    payload = json.dumps(body, default=str, separators=(",", ":"))
    return Response(payload, media_type="application/json", headers=headers)


@public_router.get("/assets/{name}")
def public_asset(name: str, request: Request) -> Response:
    """A picture that is part of the live site (never one that is only in the library). Named by its hash, so it may be
    cached for a year."""
    if not site_content.deployment_enabled():
        raise NotFound("Not found")
    _rate_limit(request)
    live = site_content.current_publication()
    allowed = {a["path"].rsplit("/", 1)[-1]: a for a in live["snapshot"]["assets"]} if live else {}
    entry = allowed.get(name)
    found = site_assets.content_by_hash_prefix(name.split(".")[0]) if entry else None
    if entry is None or found is None:
        raise NotFound("Not found")
    tag = f'"{entry["hash"][:32]}"'
    headers = {"ETag": tag, "Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
    if _not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    return Response(found[0], media_type=found[1], headers=headers)
