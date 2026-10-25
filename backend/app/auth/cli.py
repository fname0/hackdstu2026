"""Учётные записи (саморегистрации нет — заводит администратор).

  python -m backend.app.auth.cli add ivanova@rt.ru "Иванова Анна Сергеевна" [--role admin] [--position "..."] [--phone "..."]
  python -m backend.app.auth.cli passwd ivanova@rt.ru        # новый пароль (сеансы завершаются)
  python -m backend.app.auth.cli list
  python -m backend.app.auth.cli disable ivanova@rt.ru       # и enable

Пароль спрашивается в консоли; пустой ввод — сгенерировать и показать один раз.
В Docker: docker compose run --rm api python -m backend.app.auth.cli ...
"""
import argparse
import getpass
import secrets
import sys

from backend.app.auth.core import ensure_schema, hash_password, password_problem
from backend.app.db import rows, write


def _password() -> str:
    if not sys.stdin.isatty():
        pw = sys.stdin.readline().strip()
    else:
        pw = getpass.getpass("Пароль (Enter — сгенерировать): ")
    if not pw:
        pw = f"Rt-{secrets.token_urlsafe(9)}"
        print(f"Сгенерирован пароль: {pw}   (покажите один раз, сохранять не нужно)")
    elif problem := password_problem(pw):
        sys.exit(problem)
    return pw


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Учётные записи Коммерческого блока")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("email")
    a.add_argument("full_name")
    a.add_argument("--role", choices=["manager", "admin"], default="manager")
    a.add_argument("--position", default="Менеджер по работе с корпоративными клиентами")
    a.add_argument("--phone", default="")
    for name in ("passwd", "disable", "enable"):
        sub.add_parser(name).add_argument("email")
    sub.add_parser("list")
    args = ap.parse_args()
    ensure_schema()
    email = getattr(args, "email", "").strip().lower()

    if args.cmd == "add":
        r = write("INSERT INTO auth.users (email, full_name, position, phone, role, password_hash) "
                  "VALUES (:e, :n, :p, :ph, :r, :h) ON CONFLICT (email) DO NOTHING RETURNING id",
                  e=email, n=args.full_name, p=args.position, ph=args.phone, r=args.role, h=hash_password(_password()))
        print(f"Создан пользователь {email} (id {r[0]['id']})" if r else f"{email} уже есть — используйте passwd")
    elif args.cmd == "passwd":
        r = write("UPDATE auth.users SET password_hash = :h, password_changed_at = now() WHERE email = :e RETURNING id",
                  e=email, h=hash_password(_password()))
        if r:
            write("UPDATE auth.sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL", u=r[0]["id"])
        print("Пароль изменён, сеансы завершены" if r else f"Нет пользователя {email}")
    elif args.cmd in ("disable", "enable"):
        r = write("UPDATE auth.users SET is_active = :a WHERE email = :e RETURNING id", e=email, a=args.cmd == "enable")
        print("Готово" if r else f"Нет пользователя {email}")
    else:
        for u in rows("SELECT id, email, full_name, role, is_active FROM auth.users ORDER BY id"):
            print(f"{u['id']:>3}  {u['email']:<30} {u['full_name']:<32} {u['role']:<8} {'' if u['is_active'] else 'ОТКЛЮЧЁН'}")


if __name__ == "__main__":
    main()
