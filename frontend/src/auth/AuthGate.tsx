import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { authApi, type Me } from './api';
import LoginPage from './LoginPage';
import './auth.css';

// Любой запрос модулей с ответом 401 (сеанс истёк или завершён с другого устройства) возвращает на экран входа
const UNAUTHORIZED = 'rt:unauthorized';
let patched = false;
function watchUnauthorized() {
  if (patched) return;
  patched = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const r = await orig(input, init);
    const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
    if (r.status === 401 && url.includes('/api/') && !url.includes('/api/auth/')) window.dispatchEvent(new Event(UNAUTHORIZED));
    return r;
  };
}

const UserContext = createContext<Me | null>(null);
/** Текущий пользователь; внутри AuthGate всегда есть. */
export const useUser = () => useContext(UserContext)!;

export default function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: authApi.me, staleTime: Infinity, retry: 1 });

  useEffect(() => {
    watchUnauthorized();
    const on = () => qc.setQueryData(['me'], null);
    window.addEventListener(UNAUTHORIZED, on);
    return () => window.removeEventListener(UNAUTHORIZED, on);
  }, [qc]);

  if (me.isPending) return <div className="auth-boot" aria-busy="true" />;
  if (me.isError) {
    return (
      <div className="auth-screen"><div className="auth-card">
        <p className="auth-error" role="alert">Сервер недоступен. Проверьте, что API запущен, и обновите страницу</p>
        <button className="rt-btn rt-btn--outline" onClick={() => me.refetch()}>Повторить</button>
      </div></div>
    );
  }
  if (!me.data) return <LoginPage onDone={user => { qc.removeQueries({ predicate: q => q.queryKey[0] !== 'me' }); qc.setQueryData(['me'], user); }} />;
  return <UserContext.Provider value={me.data}>{children}</UserContext.Provider>;
}
