from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import radar

app = FastAPI(title="Экосистема коммерческого блока РТК", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(radar.router)

@app.get("/api/health")
def health():
    return {"ok": True}
