# webheaven-kit (Python)

FastAPI side of the product contract: `InstanceStore` (instance id, mode, visibility, link) and
`admin_router` (health, info, usage, audit, users). See `../docs/contract.md`.

```python
from webheaven_kit import AdminProvider, InstanceStore, admin_router

class MyProvider(AdminProvider):
    product, version = "myapp", "1.0.0"
    features = frozenset({"usage"})
    def usage(self):
        return {"metrics": [{"key": "items", "label": "Items", "value": 42}], "period": "now"}

app.include_router(admin_router(MyProvider(), InstanceStore("/data"), prefix="/api/admin"))
```
