export interface Me {
  id: number; email: string; full_name: string; position: string; phone: string; role: 'manager' | 'admin' | 'guest';
  created_at: string; password_changed_at: string; session_id: number | null;
  /** smtp — письма уходят; console — режим разработки, код в журнале API; null — почта не настроена */
  email_delivery: 'smtp' | 'console' | null;
  /** первый вход сотрудника или гость — предложить подсказки */
  first_login: boolean;
}

export interface Challenge {
  challenge: string; to: string; dev_console: boolean; expires_in: number; resend_in: number;
}

export interface Session { id: number; ip: string | null; user_agent: string | null;
  created_at: string; last_seen_at: string; expires_at: string; current: boolean }

export interface AuthEvent { kind: string; ok: boolean; detail: string | null; ip: string | null; user_agent: string | null; at: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api/auth${path}`, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data?.detail;
    throw new ApiError(r.status, typeof d === 'string' ? d : r.status === 422 ? 'Проверьте заполнение полей' : 'Сервер недоступен, попробуйте позже');
  }
  return data as T;
}

export const authApi = {
  /** null — не вошли */
  me: () => call<Me | null>('GET', '/me'),
  options: () => call<{ guest: boolean; signup: boolean; signup_domains: string[] }>('GET', '/options'),
  register: (email: string, full_name: string, password: string) => call<Challenge>('POST', '/register', { email, full_name, password }),
  login: (email: string, password: string) => call<Challenge>('POST', '/login', { email, password }),
  guest: () => call<Me>('POST', '/guest'),
  resend: (challenge: string) => call<Challenge>('POST', '/resend', { challenge }),
  verify: (challenge: string, code: string) => call<Me>('POST', '/verify', { challenge, code }),
  logout: () => call<{ ok: boolean }>('POST', '/logout'),
  update: (patch: Partial<Pick<Me, 'full_name' | 'position' | 'phone'>>) => call<Me>('PATCH', '/me', patch),
  password: (current: string, next: string) => call<{ ok: boolean }>('POST', '/password', { current, new: next }),
  sessions: () => call<Session[]>('GET', '/sessions'),
  endSession: (id: number) => call<{ ok: boolean }>('DELETE', `/sessions/${id}`),
  endOthers: () => call<{ ended: number }>('POST', '/sessions/end-others'),
  events: () => call<AuthEvent[]>('GET', '/events'),
};

/** «Chrome · Windows» из User-Agent — для списка сеансов и журнала. */
export function device(ua: string | null): string {
  if (!ua) return 'Неизвестное устройство';
  const browser = /Edg\//.test(ua) ? 'Edge' : /YaBrowser/.test(ua) ? 'Яндекс Браузер' : /OPR\//.test(ua) ? 'Opera'
    : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari'
    : /curl|python/i.test(ua) ? 'Скрипт' : 'Браузер';
  const os = /iPhone|iPad/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows'
    : /Mac OS X/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return os ? `${browser} · ${os}` : browser;
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]!.toUpperCase()).join('') || '-';

export const fmtDateTime = (s: string) =>
  new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
