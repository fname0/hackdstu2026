"""Вход с двумя факторами: пароль + одноразовый код на почту.

Пароль — scrypt (стандартная библиотека). Код — 6 цифр, в базе только HMAC(AUTH_SECRET), 5 минут, 5 попыток.
Сеанс — случайный токен в httpOnly-cookie `rt_session`, в базе sha256 токена; 12 часов, отзывается из профиля.
Зависимость require_user закрывает API модулей (backend/app/main.py).
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.app.db import engine, one, write

log = logging.getLogger("auth")

COOKIE = "rt_session"
SESSION_HOURS = 12
GUEST_HOURS = 4
MAX_GUESTS_HOUR = 30       # гостевых входов с одного IP за час
CODE_MINUTES = 5
CODE_ATTEMPTS = 5
RESEND_SECONDS = 30
MAX_CODES_15MIN = 6        # писем и сообщений с кодом на пользователя за 15 минут
MAX_FAILS_15MIN = 10       # неверных паролей на почту за 15 минут

_DEV_SECRET = "dev-only-secret-change-me"


def _secret() -> bytes:
    return os.environ.get("AUTH_SECRET", _DEV_SECRET).encode()


def ensure_schema() -> None:
    """Создаёт схему auth, если её нет. Под rt_reader DDL запрещён — тогда схема должна быть создана на VPS."""
    try:
        with engine.begin() as con:
            con.execute(text("SELECT pg_advisory_xact_lock(7420261)"))  # два воркера uvicorn стартуют одновременно
            con.exec_driver_sql((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
    except DBAPIError as e:
        if one("SELECT to_regclass('auth.users') AS t")["t"] is None:
            log.error("[auth] схема auth не создана и создать её нельзя: %s", e.orig)
        else:
            log.info("[auth] схема auth уже есть, DDL пропущен (нет прав)")
    if os.environ.get("AUTH_SECRET", _DEV_SECRET) == _DEV_SECRET:
        log.warning("[auth] AUTH_SECRET не задан — используется ключ для разработки")


# --- пароли ---

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # выравниваем время ответа, когда почты нет в базе


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "Пароль — не короче 8 символов"
    if password.isdigit() or password.isalpha():
        return "Пароль должен содержать и буквы, и цифры"
    return None


# --- коды ---

def new_code() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def code_hash(challenge_id: str, code: str) -> str:
    return hmac.new(_secret(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def new_challenge_id() -> str:
    return str(uuid.uuid4())


# --- запрос ---

def client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def event(kind: str, request: Request | None, user_id: int | None = None, email: str | None = None,
          ok: bool = True, detail: str | None = None) -> None:
    write("INSERT INTO auth.events (user_id, email, kind, ok, detail, ip, user_agent) "
          "VALUES (:u, :e, :k, :ok, :d, :ip, :ua)",
          u=user_id, e=email, k=kind, ok=ok, d=detail,
          ip=client_ip(request) if request else None, ua=user_agent(request) if request else None)


# --- сеансы ---

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def signup_enabled() -> bool:
    """Саморегистрация с подтверждением почты. Выключается AUTH_SIGNUP=0."""
    return os.environ.get("AUTH_SIGNUP", "1") != "0"


def signup_domains() -> list[str]:
    """AUTH_SIGNUP_DOMAINS=rt.ru,example.ru — регистрироваться можно только с этих доменов; пусто — с любого."""
    return [d.strip().lower().lstrip("@") for d in os.environ.get("AUTH_SIGNUP_DOMAINS", "").split(",") if d.strip()]


def guest_enabled() -> bool:
    """Вход гостем без пароля — для показа жюри. Выключается AUTH_GUEST=0."""
    return os.environ.get("AUTH_GUEST", "1") != "0"


def create_session(user_id: int, channel: str, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    hours = GUEST_HOURS if channel == "guest" else SESSION_HOURS
    write("INSERT INTO auth.sessions (token_hash, user_id, channel, ip, user_agent, expires_at) "
          f"VALUES (:t, :u, :c, :ip, :ua, now() + interval '{hours} hours')",
          t=_token_hash(token), u=user_id, c=channel, ip=client_ip(request), ua=user_agent(request))
    return token


# Короткий кэш проверки сеанса: при start.bat база на VPS, лишний запрос на каждый вызов API заметен
_cache: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 20


def forget_cached(token_hash: str | None = None) -> None:
    if token_hash is None:
        _cache.clear()
    else:
        _cache.pop(token_hash, None)


def session_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    th = _token_hash(token)
    hit = _cache.get(th)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    u = one("SELECT u.id, u.email, u.full_name, u.position, u.phone, u.role, s.id AS session_id "
            "FROM auth.sessions s JOIN auth.users u ON u.id = s.user_id "
            "WHERE s.token_hash = :t AND s.revoked_at IS NULL AND s.expires_at > now() AND u.is_active", t=th)
    if u:
        write("UPDATE auth.sessions SET last_seen_at = now() "
              "WHERE token_hash = :t AND last_seen_at < now() - interval '1 minute'", t=th)
        u["token_hash"] = th
        _cache[th] = (time.time(), u)
    else:
        _cache.pop(th, None)
    return u


def require_user(request: Request) -> dict:
    u = session_user(request)
    if not u:
        raise HTTPException(401, "Нужно войти")
    request.state.user = u
    return u


def require_member(request: Request) -> dict:
    """Настройки учётной записи — только сотрудникам, не гостю (у всех гостей одна общая запись)."""
    u = require_user(request)
    if u["role"] == "guest":
        raise HTTPException(403, "В гостевом режиме профиль не меняется. Войдите со своей учётной записью")
    return u
