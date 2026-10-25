import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import logo from '../../../assets/brand/rt-logo.svg';
import { ApiError, authApi, type Challenge, type Me } from './api';

export default function LoginPage({ onDone }: { onDone: (me: Me) => void }) {
  const opts = useQuery({ queryKey: ['auth-options'], queryFn: authApi.options, staleTime: 60_000 });
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [fullName, setFullName] = useState('');
  const [repeat, setRepeat] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [code, setCode] = useState('');
  const [ch, setCh] = useState<Challenge | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => { document.title = `${mode === 'login' ? 'Вход' : 'Регистрация'} - Ростелеком`; }, [mode]);
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait(w => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await fn(); } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Сервер недоступен, попробуйте позже');
      // Код устарел или попытки кончились — вернуть на первый шаг
      if (e instanceof ApiError && e.status === 410) { setCh(null); setCode(''); }
    } finally { setBusy(false); }
  };

  const gotChallenge = (c: Challenge) => {
    setCh(c); setCode(''); setWait(c.resend_in);
    setTimeout(() => codeRef.current?.focus(), 0);
  };

  const submitPassword = (e: FormEvent) => {
    e.preventDefault();
    run(async () => gotChallenge(await authApi.login(email, password)));
  };
  const domains = opts.data?.signup_domains ?? [];
  const regProblem = password && password.length < 8 ? 'Пароль - не короче 8 символов'
    : repeat && password !== repeat ? 'Пароли не совпадают' : '';
  const submitRegister = (e: FormEvent) => {
    e.preventDefault();
    if (regProblem) return;
    run(async () => gotChallenge(await authApi.register(email, fullName, password)));
  };
  const switchMode = (m: 'login' | 'register') => { setMode(m); setError(''); setPassword(''); setRepeat(''); };
  const submitCode = (value = code) => {
    if (value.length !== 6 || busy) return;
    run(async () => onDone(await authApi.verify(ch!.challenge, value)));
  };
  const resend = () => run(async () => gotChallenge(await authApi.resend(ch!.challenge)));
  const asGuest = () => run(async () => onDone(await authApi.guest()));

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <img src={logo} alt="Ростелеком" width={140} height={36} />
        <p className="auth-product">Коммерческий блок · Радар, инвестнавигатор, калькулятор сделок</p>

        {!ch && mode === 'register' ? (
          <form onSubmit={submitRegister} className="auth-form" noValidate>
            <h1 className="auth-title">Регистрация</h1>
            <label className="field">
              <span className="field__label">ФИО <em>· попадёт в подпись коммерческих предложений</em></span>
              <input className="rt-input" autoComplete="name" autoFocus required minLength={2} maxLength={120}
                value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Иванова Анна Сергеевна" />
            </label>
            <label className="field">
              <span className="field__label">Рабочая почта{domains.length > 0 && <em> · только {domains.map(d => '@' + d).join(', ')}</em>}</span>
              <input className="rt-input" type="email" autoComplete="email" required
                value={email} onChange={e => setEmail(e.target.value)} placeholder={domains.length ? `name@${domains[0]}` : 'name@rt.ru'} />
            </label>
            <label className="field">
              <span className="field__label">Пароль <em>· от 8 символов, буквы и цифры</em></span>
              <span className="auth-pw">
                <input className="rt-input" type={showPw ? 'text' : 'password'} autoComplete="new-password" required
                  value={password} onChange={e => setPassword(e.target.value)} />
                <button type="button" className="auth-pw__toggle" onClick={() => setShowPw(v => !v)}
                  aria-label={showPw ? 'Скрыть пароль' : 'Показать пароль'}>{showPw ? 'Скрыть' : 'Показать'}</button>
              </span>
            </label>
            <label className="field">
              <span className="field__label">Повторите пароль</span>
              <input className="rt-input" type={showPw ? 'text' : 'password'} autoComplete="new-password" required
                value={repeat} onChange={e => setRepeat(e.target.value)} />
            </label>
            {(error || regProblem) && <p className="auth-error" role="alert">{error || regProblem}</p>}
            <button className="rt-btn rt-btn--primary"
              disabled={busy || fullName.trim().length < 2 || !email || !password || password !== repeat || !!regProblem}>
              {busy ? 'Отправляем…' : 'Зарегистрироваться'}
            </button>
            <p className="auth-note">На почту придёт код из 6 цифр - он подтверждает, что адрес ваш. После этого вы сразу войдёте</p>
            <button type="button" className="link-btn auth-back" onClick={() => switchMode('login')}>← Уже есть учётная запись - войти</button>
          </form>
        ) : !ch ? (
          <>
            <form onSubmit={submitPassword} className="auth-form" noValidate>
              <h1 className="auth-title">Вход</h1>
              <label className="field">
                <span className="field__label">Рабочая почта</span>
                <input className="rt-input" type="email" autoComplete="username" autoFocus required
                  value={email} onChange={e => setEmail(e.target.value)} placeholder="name@rt.ru" />
              </label>
              <label className="field">
                <span className="field__label">Пароль</span>
                <span className="auth-pw">
                  <input className="rt-input" type={showPw ? 'text' : 'password'} autoComplete="current-password" required
                    value={password} onChange={e => setPassword(e.target.value)} />
                  <button type="button" className="auth-pw__toggle" onClick={() => setShowPw(v => !v)}
                    aria-label={showPw ? 'Скрыть пароль' : 'Показать пароль'}>{showPw ? 'Скрыть' : 'Показать'}</button>
                </span>
              </label>
              {error && <p className="auth-error" role="alert">{error}</p>}
              <button className="rt-btn rt-btn--primary" disabled={busy || !email || !password}>
                {busy ? 'Проверяем…' : 'Получить код на почту'}
              </button>
              <p className="auth-note">Вход в два шага: пароль и одноразовый код на рабочую почту</p>
              {opts.data?.signup && (
                <p className="auth-switch">Нет учётной записи?{' '}
                  <button type="button" className="link-btn" onClick={() => switchMode('register')}>Зарегистрироваться</button>
                </p>
              )}
            </form>
            {opts.data?.guest && (
              <div className="auth-guest">
                <span className="auth-or">или</span>
                <button type="button" className="rt-btn rt-btn--ghost" onClick={asGuest} disabled={busy}>Войти гостем</button>
                <span className="auth-note">Без пароля и кода: можно смотреть все модули и выгружать данные, профиль недоступен</span>
              </div>
            )}
          </>
        ) : (
          <form onSubmit={e => { e.preventDefault(); submitCode(); }} className="auth-form" noValidate>
            <h1 className="auth-title">{mode === 'register' ? 'Подтвердите почту' : 'Введите код'}</h1>
            <p className="auth-sent">
              Отправили 6 цифр на почту{' '}<b>{ch.to}</b>. Код действует {Math.round(ch.expires_in / 60)} минут
            </p>
            {ch.dev_console && (
              <p className="auth-dev">Почта на сервере не настроена: это режим разработки, код записан в журнал API
                (<code>docker compose logs api</code>)</p>
            )}
            <input ref={codeRef} className="rt-input auth-code" inputMode="numeric" autoComplete="one-time-code"
              aria-label="Код из 6 цифр" maxLength={6} value={code} placeholder="••••••"
              onChange={e => { const v = e.target.value.replace(/\D/g, '').slice(0, 6); setCode(v); if (v.length === 6) submitCode(v); }} />
            {error && <p className="auth-error" role="alert">{error}</p>}
            <button className="rt-btn rt-btn--primary" disabled={busy || code.length !== 6}>{busy ? 'Проверяем…' : mode === 'register' ? 'Подтвердить и войти' : 'Войти'}</button>
            <div className="auth-links">
              <button type="button" className="link-btn" disabled={busy || wait > 0} onClick={() => resend()}>
                {wait > 0 ? `Отправить снова через ${wait} с` : 'Отправить код снова'}
              </button>
              <button type="button" className="link-btn auth-back" onClick={() => { setCh(null); setError(''); }}>
                {mode === 'register' ? '← Изменить данные' : '← Другая учётная запись'}
              </button>
            </div>
          </form>
        )}
      </div>
      <p className="auth-legal">ДАННЫЕ ДЛЯ ВНУТРЕННЕГО ИСПОЛЬЗОВАНИЯ ПАО «РОСТЕЛЕКОМ». ДЕЙСТВИЯ В СИСТЕМЕ ЗАПИСЫВАЮТСЯ В ЖУРНАЛ</p>
    </div>
  );
}
