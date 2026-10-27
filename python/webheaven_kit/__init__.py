"""Product contract for apps that run on their own and can link to a hub (see docs/contract.md)."""

from .admin import AdminProvider, admin_router
from .backup import BackupError, Backupper, restore_bundle
from .contract import CONTRACT_VERSION, LEVELS, allows
from .instance import Instance, InstanceStore
from .link import LinkError, Linker

from .version import KIT_VERSION as __version__  # noqa: E402
__all__ = ["AdminProvider", "admin_router", "BackupError", "Backupper", "restore_bundle", "CONTRACT_VERSION", "LEVELS",
           "allows", "Instance", "InstanceStore", "LinkError", "Linker"]
