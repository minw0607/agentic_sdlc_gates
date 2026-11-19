from fastapi import FastAPI

from app.dining.router import router as dining_router
from app.rides.router import router as rides_router

app = FastAPI(
    title="Park Operations (sample)",
    description="Sample service for agentic_sdlc_gates. Synthetic data only.",
    version="0.0.1",
)
app.include_router(rides_router)
app.include_router(dining_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
