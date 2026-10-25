#!/bin/sh
# Роль только для чтения — под ней start.bat (вариант 2) читает базу VPS по сети.
# Права на будущие таблицы выдаются заранее: загрузчик пересоздаёт таблицы от имени владельца базы.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE rt_reader LOGIN PASSWORD '${RT_READER_PASSWORD}';
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO rt_reader;
GRANT USAGE ON SCHEMA public TO rt_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rt_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public GRANT SELECT ON TABLES TO rt_reader;
SQL
