#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/rt
DB_PORT="${DB_PUBLIC_PORT:-15432}"

echo "== 1. Пакеты и Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl ufw fail2ban >/dev/null
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
systemctl enable --now docker >/dev/null

echo "== 2. Файрвол: SSH, сайт (80/443), база для start.bat ($DB_PORT)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow "$DB_PORT"/tcp >/dev/null
ufw --force enable >/dev/null

echo "== 3. Защита SSH: fail2ban; вход по паролю выключается только по запросу (DISABLE_SSH_PASSWORD=1) и если есть ключ"
systemctl enable --now fail2ban >/dev/null
if [ "${DISABLE_SSH_PASSWORD:-0}" = "1" ] && [ -s /root/.ssh/authorized_keys ]; then
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  [ -d /etc/ssh/sshd_config.d ] && echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/99-rt-no-password.conf
  systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
fi

echo "== 4. Секреты (.env создаётся один раз со случайными паролями)"
cd "$APP_DIR"
if [ ! -f .env ]; then
  umask 077
  cat > .env <<ENV
POSTGRES_DB=rt
POSTGRES_USER=rt
POSTGRES_PASSWORD=$(openssl rand -hex 24)
RT_READER_PASSWORD=$(openssl rand -hex 24)
DB_PUBLIC_PORT=$DB_PORT
DGIS_API_KEY=${DGIS_API_KEY:-}
ENV
fi
chmod 600 .env

echo "== 5. Сборка и запуск"
docker compose -f docker-compose.prod.yml up -d --build

echo "== 6. Данные"
if [ -f /opt/rt/radar.dump ]; then
  docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --role="$POSTGRES_USER"' < /opt/rt/radar.dump || true
  docker compose -f docker-compose.prod.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO rt_reader;"'
elif [ -d data/seed/radar ]; then
  docker compose -f docker-compose.prod.yml run --rm api python -m backend.load.load_radar
fi

echo "== Готово"
docker compose -f docker-compose.prod.yml ps
