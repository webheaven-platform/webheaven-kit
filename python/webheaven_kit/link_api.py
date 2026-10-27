"""Local endpoints to manage the link (contract: "Managing the link on the instance").

Never callable with the hub's service token. Who may change the link is the product's choice (`manage`):
open (local tool), password (header X-Admin-Password) or disabled."""

from __future__ import annotations

import hmac
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .contract import LEVELS
from .link import LinkError, Linker, clean_catalog

MANAGE = ("open", "password", "disabled")


class StartBody(BaseModel):
    hub_url: str
    name: str = ""
    base_url: str | None = None


class VisibilityBody(BaseModel):
    level: str


class CatalogBody(BaseModel):
    enabled: bool


def link_router(linker: Linker, *, prefix: str, local_access: Callable[[Request], bool],
                manage: str = "open", password: str | None = None, admin_path: str = "") -> APIRouter:
    if manage not in MANAGE:
        raise ValueError(f"manage must be one of {MANAGE}")
    if manage == "password" and not password:
        manage = "disabled"   # a password mode without a password must not be open
    router = APIRouter(prefix=prefix, tags=["admin"])

    def require_local(request: Request) -> None:
        if request.headers.get("authorization"):
            raise HTTPException(403, "the link can only be managed on the instance itself")
        if not local_access(request):
            raise HTTPException(401, "not authenticated")

    def require_manage(request: Request) -> None:
        require_local(request)
        if manage == "disabled":
            raise HTTPException(403, "linking is disabled on this instance")
        if manage == "password":
            given = request.headers.get("x-admin-password", "")
            if not hmac.compare_digest(given.encode(), password.encode()):
                raise HTTPException(403, "admin password required")

    def run(fn, *args):
        try:
            return fn(*args)
        except LinkError as e:
            raise HTTPException(502, str(e))

    @router.get("/link")
    def state(request: Request):
        require_local(request)
        return {**linker.state(), "manage": manage}

    @router.get("/link/traffic")
    def traffic(request: Request):
        require_local(request)
        return {"entries": linker.log.entries()}

    @router.post("/link/start")
    def start(request: Request, body: StartBody):
        require_manage(request)
        return {**run(linker.start, body.hub_url, body.name, body.base_url, admin_path), "manage": manage}

    @router.post("/link/poll")
    def poll(request: Request):
        require_local(request)   # finishing a link the owner approved on the hub needs no password
        return {"status": run(linker.poll), **linker.state(), "manage": manage}

    @router.post("/link/cancel")
    def cancel(request: Request):
        require_manage(request)
        linker.cancel()
        return {**linker.state(), "manage": manage}

    @router.post("/link/unlink")
    def unlink(request: Request):
        require_manage(request)
        linker.unlink()
        return {**linker.state(), "manage": manage}

    @router.post("/visibility")
    def visibility(request: Request, body: VisibilityBody):
        require_manage(request)
        if body.level not in LEVELS:
            raise HTTPException(422, f"level must be one of {LEVELS}")
        linker.store.set_visibility(body.level)
        return {**linker.state(), "manage": manage}

    @router.post("/catalog")
    def catalog(request: Request, body: CatalogBody):
        """Share the catalog with the hub or stop sharing it (the next heartbeat tells the hub)."""
        require_manage(request)
        if not linker.catalog:
            raise HTTPException(404, "this product has no catalog")
        linker.store.set_catalog(body.enabled)
        return {**linker.state(), "manage": manage}

    @router.get("/catalog")
    def catalog_preview(request: Request):
        """Exactly what the hub would get, so the owner can check it."""
        require_local(request)
        if not linker.catalog:
            raise HTTPException(404, "this product has no catalog")
        return {"enabled": linker.store.instance.catalog, "items": clean_catalog(linker.catalog())}

    return router
