"""Доставка кодов входа на почту: Resend по HTTPS или SMTP. Только стандартная библиотека.

Настройки — в .env (см. .env.example), первым срабатывает Resend:
  RESEND_API_KEY, RESEND_FROM — API resend.com по порту 443 (на VPS исходящие почтовые порты закрыты хостингом;
    без своего домена Resend доставляет только на почту владельца аккаунта, отправитель onboarding@resend.dev);
  SMTP_HOST, SMTP_PORT (465 — SSL, 587 — STARTTLS), SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
AUTH_DEV_MODE=1 — для локальной разработки: если почта не настроена, код пишется в консоль API.
"""
import html as _html
import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger("auth")


class DeliveryError(Exception):
    pass


def dev_mode() -> bool:
    return os.environ.get("AUTH_DEV_MODE", "") == "1"


def resend_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def mail_configured() -> bool:
    return resend_configured() or smtp_configured()


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'•' * max(len(name) - 2, 1)}@{domain}"


def send_email(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Отправляет письмо; возвращает 'resend', 'smtp' или 'console' (dev-режим без почты)."""
    if resend_configured():
        return _send_resend(to, subject, text, html)
    if not smtp_configured():
        if dev_mode():
            log.warning("[auth] DEV: почта не настроена, письмо для %s: %s\n%s", to, subject, text)
            return "console"
        raise DeliveryError("почта не настроена (RESEND_API_KEY или SMTP_HOST)")
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    user, password = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Ростелеком · Коммерческий блок", os.environ.get("SMTP_FROM") or user))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
                if user:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, password)
                s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        log.error("[auth] письмо на %s не отправлено: %s", to, e)
        raise DeliveryError("не удалось отправить письмо") from e
    return "smtp"


def _send_resend(to: str, subject: str, text: str, html: str | None) -> str:
    """POST https://api.resend.com/emails. Ошибки Resend (неверный ключ, чужой адрес без своего домена) — в лог API."""
    sender = os.environ.get("RESEND_FROM") or "onboarding@resend.dev"
    body = {"from": f"Ростелеком · Коммерческий блок <{sender}>", "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                                          "Content-Type": "application/json", "User-Agent": "rt-kommblok/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        log.error("[auth] Resend не принял письмо на %s: %s %s", to, e.code, detail)
        raise DeliveryError(f"Resend {e.code}") from e
    except OSError as e:
        log.error("[auth] Resend недоступен: %s", e)
        raise DeliveryError("Resend недоступен") from e
    return "resend"


def code_email(code: str, full_name: str) -> tuple[str, str, str]:
    subject = f"Код входа: {code}"
    text = (f"{full_name}, ваш код для входа в Коммерческий блок Ростелекома: {code}\n\n"
            "Код действует 5 минут. Никому его не сообщайте.\n"
            "Если вы не входили, смените пароль в профиле.")
    html = f"""<div style="font-family:Arial,sans-serif;color:#101828;font-size:15px;line-height:22px">
<p>{_html.escape(full_name)}, ваш код для входа в Коммерческий блок Ростелекома:</p>
<p style="font-size:32px;line-height:36px;font-weight:bold;letter-spacing:6px;color:#7700FF;margin:16px 0">{code}</p>
<p style="color:#575D68">Код действует 5 минут. Никому его не сообщайте.<br>Если вы не входили, смените пароль в профиле.</p>
</div>"""
    return subject, text, html
