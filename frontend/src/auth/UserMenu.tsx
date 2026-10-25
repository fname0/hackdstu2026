import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { authApi, initials } from './api';
import { useUser } from './AuthGate';

export default function UserMenu() {
  const user = useUser();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
  }, [open]);

  const logout = async () => {
    await authApi.logout().catch(() => undefined);
    // Данные модулей чужому сеансу не оставляем; запрос me не удаляем — на нём держится AuthGate
    qc.setQueryData(['me'], null);
    qc.removeQueries({ predicate: q => q.queryKey[0] !== 'me' });
  };

  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar avatar--btn" onClick={() => setOpen(v => !v)} aria-haspopup="menu" aria-expanded={open}
        title={user.full_name}>{initials(user.full_name)}</button>
      {open && (
        <div className="user-menu__pop" role="menu">
          <div className="user-menu__who">
            <b>{user.full_name}</b>
            <span className="sub">{user.role === 'guest' ? 'Гостевой режим · без профиля' : user.email}</span>
          </div>
          {user.role === 'guest' ? (
            <button role="menuitem" onClick={logout}>Войти с учётной записью</button>
          ) : (
            <>
              <a role="menuitem" href="#profile" onClick={() => setOpen(false)}>Профиль и безопасность</a>
              <button role="menuitem" onClick={logout}>Выйти</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
