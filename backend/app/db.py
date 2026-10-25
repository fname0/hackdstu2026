import os
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


def _env_from_file() -> None:
    """Запуск без Docker (start.bat): берём DATABASE_URL и прочее из корневого .env, если не заданы в окружении."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_env_from_file()

engine = create_engine(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://rt:rt_local_dev@localhost:5432/rt"),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)


def rows(sql: str, **params) -> list[dict]:
    with engine.connect() as con:
        return [dict(r._mapping) for r in con.execute(text(sql), params)]


def one(sql: str, **params) -> dict | None:
    r = rows(sql, **params)
    return r[0] if r else None


def write(sql: str, **params) -> list[dict]:
    """Запрос с изменением данных в своей транзакции; строки RETURNING, если есть."""
    with engine.begin() as con:
        res = con.execute(text(sql), params)
        return [dict(r._mapping) for r in res] if res.returns_rows else []
