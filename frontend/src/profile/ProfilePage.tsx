import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { ApiError, authApi, device, fmtDateTime, initials, type AuthEvent, type Me } from '../auth/api';
import { useUser } from '../auth/AuthGate';

const ROLE: Record<Me['role'], string> = { manager: 'Менеджер', admin: 'Администратор', guest: 'Гость' };
const EVENT: Record<string, [string, string]> = {
  // kind → [успех, неудача]
  password: ['Пароль верный, отправлен код', 'Неверный пароль'],
  code: ['Код принят', 'Неверный код'],
  login: ['Вход выполнен', 'Вход не выполнен'],
  logout: ['Выход', 'Выход'],
  password_change: ['Пароль изменён', 'Неудачная смена пароля'],
  session_end: ['Сеанс завершён', ''],
};
const errText = (e: unknown) => (e instanceof ApiError ? e.message : 'Сервер недоступен, попробуйте позже');

export default function ProfilePage() {
  const user = useUser();
  if (user.role === 'guest') return <GuestProfile />;
  return (
    <div className="profile">
      <div className="profile__inner">
        <div className="profile__head">
          <span className="avatar avatar--lg">{initials(user.full_name)}</span>
          <div>
            <h1 className="profile__title">{user.full_name}</h1>
            <p className="meta">{user.position || 'Должность не указана'} · {ROLE[user.role]} · в системе с {new Date(user.created_at).toLocaleDateString('ru-RU')}</p>
          </div>
        </div>
        <div className="profile__grid">
          <div className="profile__col">
            <PersonalBlock />
            <PasswordBlock />
          </div>
          <div className="profile__col">
            <TwoFactorBlock />
            <SessionsBlock />
            <EventsBlock />
          </div>
        </div>
      </div>
    </div>
  );
}

function GuestProfile() {
  const qc = useQueryClient();
  const login = async () => {
    await authApi.logout().catch(() => undefined);
    qc.setQueryData(['me'], null);
    qc.removeQueries({ predicate: q => q.queryKey[0] !== 'me' });
  };
  return (
    <div className="profile">
      <div className="profile__inner profile__inner--narrow">
        <section className="pblock" id="profile-personal">
          <h1 className="profile__title">Гостевой режим</h1>
          <p className="pguest">Вы смотрите систему без учётной записи: радар, инвестнавигатор и калькулятор работают полностью, выгрузки в CSV, CRM и КП доступны.
            Профиль, двухфакторный вход и журнал есть только у сотрудников - КП из гостевого режима выходит без подписи менеджера</p>
          <button className="rt-btn rt-btn--primary rt-btn--sm" onClick={login}>Войти с учётной записью</button>
          <p className="meta">Гостевой сеанс действует 4 часа</p>
        </section>
      </div>
    </div>
  );
}

function useSetMe() {
  const qc = useQueryClient();
  return (me: Me) => qc.setQueryData(['me'], me);
}

function PersonalBlock() {
  const user = useUser();
  const setMe = useSetMe();
  const [form, setForm] = useState({ full_name: user.full_name, position: user.position, phone: user.phone });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const save = useMutation({
    mutationFn: () => authApi.update(form),
    onSuccess: me => { setMe(me); setMsg({ ok: true, text: 'Сохранено' }); },
    onError: e => setMsg({ ok: false, text: errText(e) }),
  });
  const dirty = form.full_name !== user.full_name || form.position !== user.position || form.phone !== user.phone;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => { setForm({ ...form, [k]: e.target.value }); setMsg(null); };

  return (
    <section className="pblock" id="profile-personal">
      <h2 className="pblock__title">Личные данные</h2>
      <p className="meta">Подставляются в подпись коммерческого предложения (DOCX) из калькулятора сделок</p>
      <form className="pform" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
        <label className="field"><span className="field__label">ФИО</span>
          <input className="rt-input" value={form.full_name} onChange={set('full_name')} required minLength={2} maxLength={120} /></label>
        <label className="field"><span className="field__label">Должность</span>
          <input className="rt-input" value={form.position} onChange={set('position')} maxLength={120} /></label>
        <label className="field"><span className="field__label">Телефон для клиентов</span>
          <input className="rt-input" type="tel" value={form.phone} onChange={set('phone')} maxLength={40} placeholder="+7 ___ ___-__-__" /></label>
        <label className="field"><span className="field__label">Рабочая почта <em>· меняет администратор</em></span>
          <input className="rt-input" value={user.email} disabled /></label>
        <div className="pform__actions">
          <button className="rt-btn rt-btn--primary rt-btn--sm" disabled={!dirty || save.isPending || form.full_name.trim().length < 2}>
            {save.isPending ? 'Сохраняем…' : 'Сохранить'}
          </button>
          {msg && <span className={msg.ok ? 'pmsg pmsg--ok' : 'pmsg pmsg--err'} role="status">{msg.text}</span>}
        </div>
      </form>
    </section>
  );
}

function PasswordBlock() {
  const user = useUser();
  const qc = useQueryClient();
  const [f, setF] = useState({ current: '', next: '', repeat: '' });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const local = f.next && f.next.length < 8 ? 'Не короче 8 символов'
    : f.repeat && f.next !== f.repeat ? 'Пароли не совпадают' : '';
  const save = useMutation({
    mutationFn: () => authApi.password(f.current, f.next),
    onSuccess: () => {
      setF({ current: '', next: '', repeat: '' });
      setMsg({ ok: true, text: 'Пароль изменён. На других устройствах нужно войти заново' });
      qc.invalidateQueries({ queryKey: ['auth'] });
    },
    onError: e => setMsg({ ok: false, text: errText(e) }),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (!local) save.mutate(); };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => { setF({ ...f, [k]: e.target.value }); setMsg(null); };

  return (
    <section className="pblock" id="profile-password">
      <h2 className="pblock__title">Пароль</h2>
      <form className="pform" onSubmit={submit}>
        <input type="text" autoComplete="username" value={user.email} readOnly hidden />
        <label className="field"><span className="field__label">Текущий пароль</span>
          <input className="rt-input" type="password" autoComplete="current-password" value={f.current} onChange={set('current')} /></label>
        <label className="field"><span className="field__label">Новый пароль <em>· от 8 символов, буквы и цифры</em></span>
          <input className="rt-input" type="password" autoComplete="new-password" value={f.next} onChange={set('next')} /></label>
        <label className="field"><span className="field__label">Повторите новый пароль</span>
          <input className="rt-input" type="password" autoComplete="new-password" value={f.repeat} onChange={set('repeat')} /></label>
        <div className="pform__actions">
          <button className="rt-btn rt-btn--outline rt-btn--sm" disabled={!f.current || !f.next || f.next !== f.repeat || !!local || save.isPending}>
            Сменить пароль
          </button>
          {(local || msg) && <span className={msg?.ok && !local ? 'pmsg pmsg--ok' : 'pmsg pmsg--err'} role="status">{local || msg!.text}</span>}
        </div>
      </form>
      <p className="meta">Последняя смена: {fmtDateTime(user.password_changed_at)}</p>
    </section>
  );
}

function TwoFactorBlock() {
  const user = useUser();
  const note = user.email_delivery === 'smtp' ? 'Письма с кодом уходят на рабочую почту'
    : user.email_delivery === 'console' ? 'Сервер в режиме разработки: код пишется в журнал API'
    : 'Почта на сервере не настроена - обратитесь к администратору';
  return (
    <section className="pblock" id="profile-2fa">
      <div className="pblock__head">
        <h2 className="pblock__title">Двухфакторный вход</h2>
        <span className="badge badge--ok">Включён</span>
      </div>
      <p className="meta">После пароля на почту приходит одноразовый код из 6 цифр: он действует 5 минут, на ввод - 5 попыток</p>
      <div className="channels">
        <div className="channel is-active">
          <span className="channel__icon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></svg>
          </span>
          <span className="channel__body">
            <b>{user.email}</b>
            <span className="sub">{note}</span>
          </span>
        </div>
      </div>
    </section>
  );
}

function SessionsBlock() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['auth', 'sessions'], queryFn: authApi.sessions, staleTime: 0 });
  const refresh = () => qc.invalidateQueries({ queryKey: ['auth'] });
  const end = useMutation({ mutationFn: authApi.endSession, onSuccess: refresh });
  const endOthers = useMutation({ mutationFn: authApi.endOthers, onSuccess: refresh });
  const others = (q.data ?? []).filter(s => !s.current).length;

  return (
    <section className="pblock" id="profile-sessions">
      <div className="pblock__head">
        <h2 className="pblock__title">Активные сеансы</h2>
        {others > 0 && <button className="link-btn" onClick={() => endOthers.mutate()} disabled={endOthers.isPending}>Завершить остальные ({others})</button>}
      </div>
      {q.isPending ? <div className="skeleton" style={{ height: 96 }} />
        : q.isError ? <p className="pmsg pmsg--err">{errText(q.error)}</p>
        : (
          <ul className="plist">
            {q.data.map(s => (
              <li key={s.id} className="plist__row">
                <span>
                  <b>{device(s.user_agent)}</b>{s.current && <span className="badge">Это устройство</span>}
                  <span className="sub">IP {s.ip ?? '-'} · вход {fmtDateTime(s.created_at)} · активность {fmtDateTime(s.last_seen_at)}</span>
                </span>
                {!s.current && <button className="link-btn" onClick={() => end.mutate(s.id)} disabled={end.isPending}>Завершить</button>}
              </li>
            ))}
          </ul>
        )}
      <p className="meta">Сеанс действует 12 часов, потом нужно войти снова</p>
    </section>
  );
}

function EventsBlock() {
  const q = useQuery({ queryKey: ['auth', 'events'], queryFn: authApi.events, staleTime: 0 });
  const label = (e: AuthEvent) => EVENT[e.kind]?.[e.ok ? 0 : 1] || e.kind;
  return (
    <section className="pblock" id="profile-events">
      <h2 className="pblock__title">Журнал входов</h2>
      {q.isPending ? <div className="skeleton" style={{ height: 120 }} />
        : q.isError ? <p className="pmsg pmsg--err">{errText(q.error)}</p>
        : !q.data.length ? <p className="empty">Записей пока нет</p>
        : (
          <ul className="plist plist--dense">
            {q.data.map((e, i) => (
              <li key={i} className={`plist__row ${e.ok ? '' : 'is-fail'}`}>
                <span>
                  <span className={`evt-dot ${e.ok ? '' : 'evt-dot--fail'}`} aria-hidden="true" />
                  {label(e)}
                  <span className="sub">{device(e.user_agent)}{e.ip ? ` · IP ${e.ip}` : ''}</span>
                </span>
                <span className="sub num">{fmtDateTime(e.at)}</span>
              </li>
            ))}
          </ul>
        )}
      <p className="meta">Неудачные попытки отмечены красным. Если вход был не ваш - смените пароль и завершите остальные сеансы</p>
    </section>
  );
}
