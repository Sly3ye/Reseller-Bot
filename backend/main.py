from fastapi import FastAPI

from backend.api.health import router as health_router

app = FastAPI(title="Reseller SaaS Backend", version="0.1.0")

app.include_router(health_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "reseller-backend"}
