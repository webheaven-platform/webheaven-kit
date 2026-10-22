"""Product contract for apps that run on their own and can link to a hub (see docs/contract.md)."""

from .admin import AdminProvider, admin_router
from .contract import CONTRACT_VERSION, LEVELS, allows
from .instance import Instance, InstanceStore

__version__ = "0.1.1"
__all__ = ["AdminProvider", "admin_router", "CONTRACT_VERSION", "LEVELS", "allows", "Instance", "InstanceStore"]
