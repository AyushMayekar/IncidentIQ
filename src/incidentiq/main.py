from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from incidentiq.api.routes.incidents import router as incidents_router

app = FastAPI(title="IncidentIQ API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(incidents_router, prefix="/api/v1")


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}
