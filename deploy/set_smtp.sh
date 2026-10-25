#!/usr/bin/env bash
# Настройка почты для кодов входа (2FA) на VPS: спрашивает данные ящика, пишет SMTP_* в /opt/rt/.env,
# перезапускает API и отправляет тестовое письмо. Пароль вводится скрыто и в истории команд не остаётся.
#   ssh -t root@193.233.247.129 "bash /opt/rt/deploy/set_smtp.sh"
set -euo pipefail
cd /opt/rt

echo "Почта для кодов входа. Нужен пароль приложения, а не пароль от ящика:"
echo "  Яндекс: id.yandex.ru → Безопасность → Пароли приложений → Почта"
echo "  Mail.ru: account.mail.ru → Безопасность → Пароли для внешних приложений"
read -rp "SMTP-сервер [smtp.yandex.ru]: " host; host=${host:-smtp.yandex.ru}
read -rp "Порт (465 — SSL, 587 — STARTTLS) [465]: " port; port=${port:-465}
read -rp "Логин (адрес ящика): " user
read -rsp "Пароль приложения: " pass; echo
read -rp "Отправитель [$user]: " from; from=${from:-$user}

touch .env
sed -i '/^SMTP_\(HOST\|PORT\|USER\|PASSWORD\|FROM\)=/d' .env
{
  echo "SMTP_HOST=$host"
  echo "SMTP_PORT=$port"
  echo "SMTP_USER=$user"
  echo "SMTP_PASSWORD=$pass"
  echo "SMTP_FROM=$from"
} >> .env
chmod 600 .env

docker compose -f docker-compose.prod.yml up -d api >/dev/null
read -rp "Куда отправить тестовое письмо [$user]: " to; to=${to:-$user}
docker compose -f docker-compose.prod.yml exec -T -e TO="$to" api python -c '
import os
from backend.app.auth import delivery
print("отправлено через", delivery.send_email(os.environ["TO"], *delivery.code_email("123456", "Проверка почты")))
' && echo "Готово: проверьте ящик $to (и папку «Спам»)." \
  || echo "Письмо не ушло — проверьте логин и пароль приложения и запустите скрипт ещё раз."
