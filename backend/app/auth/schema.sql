-- Схема входа: пользователи, одноразовые коды на почту (2FA), сеансы, журнал.
-- Идемпотентна: выполняется при старте API (backend/app/auth/core.py: ensure_schema).
-- Данные радара под ролью rt_reader только читаются, а в схему auth ей можно писать — иначе start.bat не сможет войти.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id                  serial PRIMARY KEY,
    email               text NOT NULL UNIQUE,              -- в нижнем регистре
    full_name           text NOT NULL,
    position            text NOT NULL DEFAULT '',
    phone               text NOT NULL DEFAULT '',
    role                text NOT NULL DEFAULT 'manager',  -- manager / admin / guest (ограничение ниже)
    password_hash       text NOT NULL,                     -- scrypt, см. core.hash_password
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    password_changed_at timestamptz NOT NULL DEFAULT now()
);

-- Второй шаг входа: код из 6 цифр, хранится только HMAC, живёт 5 минут, 5 попыток
CREATE TABLE IF NOT EXISTS auth.challenges (
    id         uuid PRIMARY KEY,
    user_id    int NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    channel    text NOT NULL DEFAULT 'email',
    code_hash  text NOT NULL,
    attempts   int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);
CREATE INDEX IF NOT EXISTS challenges_user ON auth.challenges (user_id, created_at);

-- Сеанс: в cookie случайный токен, в базе только его sha256
CREATE TABLE IF NOT EXISTS auth.sessions (
    id           bigserial PRIMARY KEY,
    token_hash   text NOT NULL UNIQUE,
    user_id      int NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    channel      text NOT NULL,                            -- email — вход с кодом, guest — гость
    ip           text,
    user_agent   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz
);

-- Журнал: входы (удачные и нет), отправка кодов, смена пароля, гостевые входы
CREATE TABLE IF NOT EXISTS auth.events (
    id         bigserial PRIMARY KEY,
    user_id    int REFERENCES auth.users ON DELETE CASCADE,
    email      text,
    kind       text NOT NULL,
    ok         boolean NOT NULL DEFAULT true,
    detail     text,
    ip         text,
    user_agent text,
    at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_user ON auth.events (user_id, at DESC);
CREATE INDEX IF NOT EXISTS events_email ON auth.events (email, at DESC);

-- Саморегистрация: запись создаётся с pending = true и становится рабочей после кода с почты
ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS pending boolean NOT NULL DEFAULT false;

-- guest — общий демо-пользователь для входа без пароля (жюри, показ); пароля нет, профиль только для чтения
ALTER TABLE auth.users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE auth.users ADD CONSTRAINT users_role_check CHECK (role IN ('manager', 'admin', 'guest'));
INSERT INTO auth.users (email, full_name, position, role, password_hash)
VALUES ('guest', 'Гость', 'Демо-доступ', 'guest', '!') ON CONFLICT (email) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rt_reader') THEN
        GRANT USAGE ON SCHEMA auth TO rt_reader;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA auth TO rt_reader;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth TO rt_reader;
    END IF;
END $$;
