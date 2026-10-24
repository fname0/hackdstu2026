const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

export const num = (v: number | null | undefined) => (v == null ? '—' : nf.format(v));

export function money(v: number | null | undefined) {
  if (v == null) return 'нет данных';
  const a = Math.abs(v);
  if (a >= 1e9) return `${nf.format(v / 1e9)} млрд ₽`;
  if (a >= 1e6) return `${nf.format(v / 1e6)} млн ₽`;
  if (a >= 1e3) return `${nf.format(Math.round(v / 1e3))} тыс. ₽`;
  return `${nf.format(v)} ₽`;
}

export const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '—' : `${v > 0 ? '+' : ''}${v.toLocaleString('ru-RU', { maximumFractionDigits: digits })}%`;

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
}
