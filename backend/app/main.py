import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import auth, calc, gov, invest, radar
from backend.app.auth.core import ensure_schema, require_user

logging.basicConfig(level=logging.INFO)


class SiteJSON(JSONResponse):
    """Длинное и среднее тире в любых текстах API (в том числе из данных ETL) — обычный дефис, как во всём интерфейсе."""

    def render(self, content) -> bytes:
        return super().render(content).decode("utf-8").replace("—", "-").replace("–", "-").encode("utf-8")


app = FastAPI(title="Экосистема коммерческого блока РТК", version="0.1.0", default_response_class=SiteJSON)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=True)
# Модули открыты только после входа с кодом (2FA); вход и /api/health — без сеанса
app.include_router(auth.router)
app.include_router(radar.router, dependencies=[Depends(require_user)])
app.include_router(gov.router, dependencies=[Depends(require_user)])
app.include_router(invest.router, dependencies=[Depends(require_user)])
app.include_router(calc.router, dependencies=[Depends(require_user)])


@app.on_event("startup")
def startup():
    ensure_schema()


@app.get("/api/health")
def health():
    return {"ok": True}
