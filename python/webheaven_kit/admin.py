"""Admin API of the product contract: health, info, usage, audit, users (see docs/contract.md)."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Request

from .contract import CONTRACT_VERSION, SECTION_LEVEL, allows
from .instance import InstanceStore


class AdminProvider:
    """What a product fills in. Override the methods for the sections it supports and list them in `features`."""

    product: str = "product"
    version: str = "0.0.0"
    features: frozenset[str] = frozenset()   # subset of {"usage", "audit", "users"}
    releases_feed: str | None = None         # public JSON feed (see "Releases" in the contract)
    releases_page: str | None = None         # human page, shown when the feed cannot be fetched

    def checks(self) -> dict[str, str]:
        """Name -> "ok" or a short problem description."""
        return {}

    def info(self) -> dict:
        return {}

    def usage(self) -> dict:
        raise NotImplementedError

    def audit(self, limit: int) -> list[dict]:
        raise NotImplementedError

    def users(self) -> list[dict]:
        raise NotImplementedError


def _always(_: Request) -> bool:
    return True


def admin_router(provider: AdminProvider, store: InstanceStore, *, prefix: str = "/admin",
                 local_access: Callable[[Request], bool] = _always) -> APIRouter:
    """Router with the admin API. `local_access` is the product's own check for its own UI (level full);
    a hub authenticates with its service token and gets the instance's visibility level."""
    router = APIRouter(prefix=prefix, tags=["admin"])

    def level_of(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            if store.verify_service_token(auth[7:].strip()):
                return store.instance.visibility
            raise HTTPException(401, "invalid service token")
        if local_access(request):
            return "full"
        raise HTTPException(401, "not authenticated")

    def require(request: Request, section: str) -> None:
        if section != "overview" and section not in provider.features:
            raise HTTPException(404, f"{provider.product} has no {section} section")
        if not allows(level_of(request), SECTION_LEVEL[section]):
            raise HTTPException(403, f"visibility level does not allow {section}")

    def sections(level: str) -> list[str]:
        return [s for s in ("overview", "usage", "audit", "users")
                if (s == "overview" or s in provider.features) and allows(level, SECTION_LEVEL[s])]

    def instance_part(full: bool) -> dict:
        inst = store.instance
        part = {"id": inst.id, "mode": inst.mode}
        if full:
            part.update(visibility=inst.visibility, created=inst.created)
        return part

    @router.get("/health")
    def health(request: Request):
        level_of(request)
        checks = provider.checks()
        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        return {"contract": CONTRACT_VERSION, "product": provider.product, "version": provider.version,
                "status": status, "checks": checks, "instance": instance_part(full=False)}

    @router.get("/info")
    def info(request: Request):
        level = level_of(request)
        return {
            "contract": CONTRACT_VERSION, "product": provider.product, "version": provider.version,
            "instance": instance_part(full=True), "sections": sections(level),
            "releases": {"feed": provider.releases_feed, "page": provider.releases_page},
            "product_info": provider.info() if allows(level, "statistics") else None,
        }

    @router.get("/usage")
    def usage(request: Request):
        require(request, "usage")
        return provider.usage()

    @router.get("/audit")
    def audit(request: Request, limit: int = 50):
        require(request, "audit")
        return {"entries": provider.audit(max(1, min(limit, 500)))}

    @router.get("/users")
    def users(request: Request):
        require(request, "users")
        return {"users": provider.users()}

    return router
