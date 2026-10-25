"""API входа и профиля: пароль → код на почту → сеанс; вход гостем; профиль, сеансы, журнал.

Шаги входа:
  POST /api/auth/login   {email, password}  → {challenge, to, ...}: код отправлен на почту
  POST /api/auth/resend  {challenge}        → новый код
  POST /api/auth/verify  {challenge, code}  → cookie rt_session + профиль
  POST /api/auth/guest                      → гостевой сеанс без пароля (выключается AUTH_GUEST=0)
  POST /api/auth/register {email, full_name, password} → код на почту; после verify учётная запись активна
Учётные записи: саморегистрация (AUTH_SIGNUP, AUTH_SIGNUP_DOMAINS) или администратор: python -m backend.app.auth.cli add <почта> "<ФИО>".
"""
import re
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.app.auth import core, delivery
from backend.app.auth.core import require_member
from backend.app.db import one, rows, write

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginReq(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class RegisterReq(BaseModel):
    email: str = Field(max_length=200)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=200)


class ResendReq(BaseModel):
    challenge: str


class VerifyReq(BaseModel):
    challenge: str
    code: str = Field(max_length=12)


class ProfileReq(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    position: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=40)


class PasswordReq(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


def _send_code(u: dict, request: Request) -> dict:
    """Создаёт код и отправляет письмом. Возвращает описание для экрана ввода кода."""
    recent = one("SELECT count(*) AS n FROM auth.challenges WHERE user_id = :u AND created_at > now() - interval '15 minutes'",
                 u=u["id"])["n"]
    if recent >= core.MAX_CODES_15MIN:
        raise HTTPException(429, "Слишком много кодов подряд. Подождите 15 минут")
    cid, code = core.new_challenge_id(), core.new_code()
    try:
        via = delivery.send_email(u["email"], *delivery.code_email(code, u["full_name"]))
    except delivery.DeliveryError as e:
        core.event("code_sent", request, u["id"], u["email"], ok=False, detail=str(e))
        raise HTTPException(503, "Не удалось отправить код на почту. Попробуйте позже или обратитесь к администратору")
    write("INSERT INTO auth.challenges (id, user_id, channel, code_hash, expires_at) "
          f"VALUES (:id, :u, 'email', :h, now() + interval '{core.CODE_MINUTES} minutes')",
          id=cid, u=u["id"], h=core.code_hash(cid, code))
    core.event("code_sent", request, u["id"], u["email"])
    return {"challenge": cid, "to": delivery.mask_email(u["email"]), "dev_console": via == "console",
            "expires_in": core.CODE_MINUTES * 60, "resend_in": core.RESEND_SECONDS}


def _user(user_id: int) -> dict:
    return one("SELECT * FROM auth.users WHERE id = :u", u=user_id)


@router.post("/login")
def login(req: LoginReq, request: Request):
    email = req.email.strip().lower()
    fails = one("SELECT count(*) AS n FROM auth.events WHERE email = :e AND kind = 'password' AND NOT ok "
                "AND at > now() - interval '15 minutes'", e=email)["n"]
    if fails >= core.MAX_FAILS_15MIN:
        raise HTTPException(429, "Слишком много неудачных попыток. Подождите 15 минут")
    u = one("SELECT * FROM auth.users WHERE email = :e AND is_active AND NOT pending AND role <> 'guest'", e=email)
    if not core.check_password(req.password, u["password_hash"] if u else core._DUMMY_HASH) or not u:
        core.event("password", request, u["id"] if u else None, email, ok=False)
        raise HTTPException(401, "Неверная почта или пароль")
    core.event("password", request, u["id"], email)
    return _send_code(u, request)


@router.post("/register")
def register(req: RegisterReq, request: Request):
    """Саморегистрация: создаём неподтверждённую запись и шлём код. Подтверждённую почту повторно занять нельзя."""
    if not core.signup_enabled():
        raise HTTPException(403, "Регистрация отключена — обратитесь к администратору")
    email = req.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-zа-я]{2,}", email):
        raise HTTPException(400, "Проверьте адрес почты")
    domains = core.signup_domains()
    if domains and email.split("@")[1] not in domains:
        raise HTTPException(400, "Регистрация только с рабочей почты: " + ", ".join("@" + d for d in domains))
    if problem := core.password_problem(req.password):
        raise HTTPException(400, problem)
    ip = core.client_ip(request)
    n = one("SELECT count(*) AS n FROM auth.events WHERE kind = 'register' AND ip = :ip AND at > now() - interval '1 hour'",
            ip=ip)["n"]
    if n >= 10:
        raise HTTPException(429, "Слишком много регистраций. Попробуйте через час")
    existing = one("SELECT id, pending FROM auth.users WHERE email = :e", e=email)
    if existing and not existing["pending"]:
        raise HTTPException(409, "Эта почта уже зарегистрирована — войдите или смените пароль через администратора")
    params = dict(e=email, n=req.full_name.strip(), h=core.hash_password(req.password))
    if existing:  # повторная попытка до подтверждения: обновляем имя и пароль
        write("UPDATE auth.users SET full_name = :n, password_hash = :h WHERE id = :u", u=existing["id"], **params)
        uid = existing["id"]
    else:
        uid = write("INSERT INTO auth.users (email, full_name, position, password_hash, pending) "
                    "VALUES (:e, :n, '', :h, true) RETURNING id", **params)[0]["id"]
    core.event("register", request, uid, email)
    return _send_code(_user(uid), request)


@router.post("/guest")
def guest(request: Request, response: Response):
    """Вход гостем без пароля и кода: всё смотреть и выгружать можно, профиль менять нельзя."""
    if not core.guest_enabled():
        raise HTTPException(403, "Гостевой вход отключён")
    ip = core.client_ip(request)
    n = one("SELECT count(*) AS n FROM auth.events WHERE kind = 'guest' AND ip = :ip AND at > now() - interval '1 hour'",
            ip=ip)["n"]
    if n >= core.MAX_GUESTS_HOUR:
        raise HTTPException(429, "Слишком много гостевых входов. Попробуйте через час")
    g = one("SELECT id FROM auth.users WHERE role = 'guest' AND is_active")
    if not g:
        raise HTTPException(403, "Гостевой вход отключён")
    token = core.create_session(g["id"], "guest", request)
    core.event("guest", request, g["id"])
    _set_cookie(response, request, token, core.GUEST_HOURS)
    return _me(g["id"], None)


def _set_cookie(response: Response, request: Request, token: str, hours: int) -> None:
    response.set_cookie(core.COOKIE, token, max_age=hours * 3600, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
                        path="/")


def _open_challenge(cid: str) -> dict:
    try:
        ch = one("SELECT * FROM auth.challenges WHERE id = :id", id=str(uuid.UUID(cid)))
    except ValueError:
        ch = None
    if not ch or ch["used_at"] is not None:
        raise HTTPException(410, "Код устарел. Войдите заново")
    return ch


@router.post("/resend")
def resend(req: ResendReq, request: Request):
    ch = _open_challenge(req.challenge)
    wait = one("SELECT :s - extract(epoch FROM now() - created_at) AS w FROM auth.challenges WHERE id = :id",
               s=core.RESEND_SECONDS, id=ch["id"])["w"]
    if wait > 0:
        raise HTTPException(429, f"Новый код можно запросить через {int(wait) + 1} с")
    write("UPDATE auth.challenges SET used_at = now() WHERE id = :id", id=ch["id"])
    return _send_code(_user(ch["user_id"]), request)


@router.post("/verify")
def verify(req: VerifyReq, request: Request, response: Response):
    ch = _open_challenge(req.challenge)
    code = "".join(c for c in req.code if c.isdigit())
    if ch["attempts"] >= core.CODE_ATTEMPTS or one("SELECT now() > :e AS x", e=ch["expires_at"])["x"]:
        write("UPDATE auth.challenges SET used_at = now() WHERE id = :id", id=ch["id"])
        raise HTTPException(410, "Код устарел. Запросите новый")
    if not secrets.compare_digest(core.code_hash(str(ch["id"]), code), ch["code_hash"]):
        left = core.CODE_ATTEMPTS - ch["attempts"] - 1
        write("UPDATE auth.challenges SET attempts = attempts + 1 WHERE id = :id", id=ch["id"])
        core.event("code", request, ch["user_id"], ok=False)
        if left <= 0:
            raise HTTPException(410, "Попытки закончились. Запросите новый код")
        raise HTTPException(400, f"Неверный код. Осталось попыток: {left}")
    # Одновременный повторный ввод того же кода: засчитывается только первый
    if not write("UPDATE auth.challenges SET used_at = now() WHERE id = :id AND used_at IS NULL RETURNING id", id=ch["id"]):
        raise HTTPException(410, "Код уже использован")
    write("UPDATE auth.users SET pending = false WHERE id = :u AND pending", u=ch["user_id"])  # почта подтверждена
    token = core.create_session(ch["user_id"], "email", request)
    core.event("login", request, ch["user_id"])
    _set_cookie(response, request, token, core.SESSION_HOURS)
    return _me(ch["user_id"], None)


@router.get("/options")
def options():
    """Что показать на экране входа: гостевой вход и регистрация."""
    return {"guest": core.guest_enabled(), "signup": core.signup_enabled(), "signup_domains": core.signup_domains()}


@router.post("/logout")
def logout(request: Request, response: Response):
    u = core.session_user(request)
    if u:
        write("UPDATE auth.sessions SET revoked_at = now() WHERE id = :s", s=u["session_id"])
        core.forget_cached(u["token_hash"])
        core.event("logout", request, u["id"])
    response.delete_cookie(core.COOKIE, path="/")
    return {"ok": True}


# --- профиль ---

def _me(user_id: int, session_id: int | None) -> dict:
    u = _user(user_id)
    return {
        "id": u["id"], "email": u["email"], "full_name": u["full_name"], "position": u["position"],
        "phone": u["phone"], "role": u["role"], "created_at": u["created_at"],
        "password_changed_at": u["password_changed_at"],
        "email_delivery": "smtp" if delivery.mail_configured() else ("console" if delivery.dev_mode() else None),
        "session_id": session_id,
        # Первый вход (или гость) — сайт предлагает пройти подсказки
        "first_login": u["role"] == "guest" or one(
            "SELECT count(*) AS n FROM auth.events WHERE user_id = :u AND kind = 'login' AND ok", u=user_id)["n"] <= 1,
    }


@router.get("/me")
def me(request: Request):
    """Профиль или null, если не вошли (200, а не 401: экран входа — нормальное состояние, не ошибка в консоли)."""
    u = core.session_user(request)
    return _me(u["id"], u["session_id"]) if u else None


@router.patch("/me")
def update_me(req: ProfileReq, request: Request, u: dict = Depends(require_member)):
    data = req.model_dump(exclude_none=True)
    if data:
        sets = ", ".join(f"{k} = :{k}" for k in data)
        write(f"UPDATE auth.users SET {sets} WHERE id = :u", u=u["id"], **{k: v.strip() for k, v in data.items()})
        core.forget_cached()
        core.event("profile", request, u["id"], detail=", ".join(data))
    return _me(u["id"], u["session_id"])


@router.post("/password")
def change_password(req: PasswordReq, request: Request, u: dict = Depends(require_member)):
    full = _user(u["id"])
    if not core.check_password(req.current, full["password_hash"]):
        core.event("password_change", request, u["id"], ok=False)
        raise HTTPException(400, "Текущий пароль неверен")
    if problem := core.password_problem(req.new):
        raise HTTPException(400, problem)
    write("UPDATE auth.users SET password_hash = :h, password_changed_at = now() WHERE id = :u",
          h=core.hash_password(req.new), u=u["id"])
    # Остальные устройства выходят: если пароль меняют из-за утечки, старые сеансы не должны жить
    write("UPDATE auth.sessions SET revoked_at = now() WHERE user_id = :u AND id <> :s AND revoked_at IS NULL",
          u=u["id"], s=u["session_id"])
    core.forget_cached()
    core.event("password_change", request, u["id"])
    return {"ok": True}


@router.get("/sessions")
def sessions(u: dict = Depends(require_member)):
    return rows("SELECT id, ip, user_agent, created_at, last_seen_at, expires_at, id = :s AS current "
                "FROM auth.sessions WHERE user_id = :u AND revoked_at IS NULL AND expires_at > now() "
                "ORDER BY id = :s DESC, last_seen_at DESC", u=u["id"], s=u["session_id"])


@router.delete("/sessions/{session_id}")
def end_session(session_id: int, request: Request, u: dict = Depends(require_member)):
    if session_id == u["session_id"]:
        raise HTTPException(400, "Чтобы завершить текущий сеанс, нажмите «Выйти»")
    write("UPDATE auth.sessions SET revoked_at = now() WHERE id = :s AND user_id = :u", s=session_id, u=u["id"])
    core.forget_cached()
    core.event("session_end", request, u["id"], detail=str(session_id))
    return {"ok": True}


@router.post("/sessions/end-others")
def end_other_sessions(request: Request, u: dict = Depends(require_member)):
    n = write("UPDATE auth.sessions SET revoked_at = now() WHERE user_id = :u AND id <> :s AND revoked_at IS NULL "
              "RETURNING id", u=u["id"], s=u["session_id"])
    core.forget_cached()
    core.event("session_end", request, u["id"], detail=f"остальные: {len(n)}")
    return {"ended": len(n)}


@router.get("/events")
def events(u: dict = Depends(require_member)):
    return rows("SELECT kind, ok, detail, ip, user_agent, at FROM auth.events "
                "WHERE user_id = :u AND kind IN ('password', 'code', 'login', 'logout', 'password_change', 'session_end') "
                "ORDER BY at DESC LIMIT 20", u=u["id"])
