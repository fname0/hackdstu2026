#!/usr/bin/env bash
# Коды входа через Resend (HTTPS, порт 443): на этом VPS исходящие почтовые порты 25/465/587 закрыты хостингом.
# Спрашивает API-ключ (ввод скрыт), пишет RESEND_* в /opt/rt/.env, перезапускает API и шлёт тестовое письмо.
#   ssh -t root@193.233.247.129 "bash /opt/rt/deploy/set_resend.sh"
# Без своего домена в Resend письма доходят только на почту владельца аккаунта Resend.
set -euo pipefail
cd /opt/rt

echo "Ключ: resend.com → API Keys → Create API Key (права Sending access)."
read -rsp "API-ключ Resend (re_...): " key; echo
read -rp "Отправитель [onboarding@resend.dev]: " from; from=${from:-onboarding@resend.dev}

touch .env
sed -i '/^RESEND_\(API_KEY\|FROM\)=/d' .env
{ echo "RESEND_API_KEY=$key"; echo "RESEND_FROM=$from"; } >> .env
chmod 600 .env

docker compose -f docker-compose.prod.yml up -d api >/dev/null
sleep 3
read -rp "Куда отправить тестовое письмо (без своего домена — почта владельца аккаунта Resend): " to
docker compose -f docker-compose.prod.yml exec -T -e TO="$to" api python -c '
import os
from backend.app.auth import delivery
print("отправлено через", delivery.send_email(os.environ["TO"], *delivery.code_email("123456", "Проверка почты")))
' && echo "Готово: проверьте ящик $to (и папку «Спам»)." \
  || echo "Письмо не ушло: причина — в строке «Resend не принял…» выше (401 — неверный ключ, 403 — адрес не владельца аккаунта без своего домена)."
