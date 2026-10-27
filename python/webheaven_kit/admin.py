"""Admin API of the product contract: health, info, usage, audit, users (see docs/contract.md)."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Request

from .contract import CONTRACT_VERSION, SECTION_LEVEL, allows
from .instance import InstanceStore
from .backup import Backupper  # noqa: F401 - type in admin_router
from .link import Linker
from .link_api import link_router


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
                 local_access: Callable[[Request], bool] = _always, linker: Linker | None = None,
                 manage: str = "open", manage_password: str | None = None,
                 backupper: "Backupper | None" = None) -> APIRouter:
    """Router with the admin API. `local_access` is the product's own check for its own UI (level full);
    a hub authenticates with its service token and gets the instance's visibility level.
    With a `linker` the local link endpoints are added (see link_api: `manage`, `manage_password`), with a
    `backupper` also the online-backup endpoints."""
    router = APIRouter(prefix=prefix, tags=["admin"])
    if linker:
        router.include_router(link_router(linker, prefix="", local_access=local_access, manage=manage,
                                          password=manage_password, admin_path=prefix, backupper=backupper))

    def caller(request: Request) -> tuple[str, str]:
        """(who, level): the own UI ("local", full) or the hub ("hub", the instance's visibility)."""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            if store.verify_service_token(auth[7:].strip()):
                return "hub", store.instance.visibility
            raise HTTPException(401, "invalid service token")
        if local_access(request):
            return "local", "full"
        raise HTTPException(401, "not authenticated")

    def level_of(request: Request) -> str:
        return caller(request)[1]

    def require(request: Request, section: str) -> None:
        if section != "overview" and section not in provider.features:
            raise HTTPException(404, f"{provider.product} has no {section} section")
        if not allows(level_of(request), SECTION_LEVEL[section]):
            raise HTTPException(403, f"visibility level does not allow {section}")

    def sections(who: str, level: str) -> list[str]:
        out = [s for s in ("overview", "usage", "audit", "users")
               if (s == "overview" or s in provider.features) and allows(level, SECTION_LEVEL[s])]
        return out + ["link"] if linker and who == "local" else out   # the hub never manages the link

    def instance_part(full: bool) -> dict:
        inst = store.instance
        part = {"id": inst.id, "mode": inst.mode}
        if full:
            part.update(visibility=inst.visibility, created=inst.created)
        return part

    log = linker.log if linker else None

    def served(request: Request, build: Callable[[], dict], section: str | None = None) -> dict:
        """Run an endpoint; when the hub calls (service token), record exactly what it got in the traffic log."""
        from_hub = request.headers.get("authorization", "").lower().startswith("bearer ")
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        headers = {"authorization": request.headers.get("authorization")}
        try:
            if section:
                require(request, section)
            result = build()
        except HTTPException as e:
            if from_hub and log:
                log.record("from-hub", request.method, url, None, e.status_code, {"detail": e.detail}, headers)
            raise
        if from_hub and log:
            log.record("from-hub", request.method, url, None, 200, result, headers)
        return result

    @router.get("/health")
    def health(request: Request):
        def build():
            level_of(request)
            checks = provider.checks()
            status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
            return {"contract": CONTRACT_VERSION, "product": provider.product, "version": provider.version,
                    "status": status, "checks": checks, "instance": instance_part(full=False)}
        return served(request, build)

    @router.get("/info")
    def info(request: Request):
        def build():
            who, level = caller(request)
            return {
                "contract": CONTRACT_VERSION, "product": provider.product, "version": provider.version,
                "instance": instance_part(full=True), "sections": sections(who, level),
                "releases": {"feed": provider.releases_feed, "page": provider.releases_page},
                "product_info": provider.info() if allows(level, "statistics") else None,
            }
        return served(request, build)

    @router.get("/usage")
    def usage(request: Request):
        return served(request, provider.usage, "usage")

    @router.get("/audit")
    def audit(request: Request, limit: int = 50):
        return served(request, lambda: {"entries": provider.audit(max(1, min(limit, 500)))}, "audit")

    @router.get("/users")
    def users(request: Request):
        return served(request, lambda: {"users": provider.users()}, "users")

    return router
