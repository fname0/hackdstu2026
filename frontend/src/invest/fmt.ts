import { money, plural } from '../format';

/** Сумма в млн ₽ → «16,8 млрд ₽». */
export const mln = (v: number | null | undefined) => (v == null ? 'нет данных' : money(v * 1e6));

/** Месяцы до ввода → «через 14 мес.» / «введён». Ввод в реестре задан годом, считаем на конец года. */
export function launchIn(months: number | null | undefined, stage: string) {
  if (stage === 'введён') return 'введён';
  if (stage === 'работы завершены') return 'работы завершены';
  if (stage === 'стадия не подтверждена') return 'стадия уточняется';
  if (stage === 'приостановлен') return 'приостановлен';
  if (months == null && (stage === 'реализация' || stage === 'подготовка')) return stage;
  if (months == null) return 'срок не указан';
  if (months <= 0) return 'срок ввода прошёл';
  if (months < 12) return `через ${months} мес`;
  const y = Math.round(months / 12 * 10) / 10;
  return `через ${y.toLocaleString('ru-RU')} ${plural(Math.round(y), 'год', 'года', 'лет')}`;
}

export const inWindow = (months: number | null | undefined, stage: string) =>
  months != null && months >= 6 && months <= 18 && stage !== 'введён' && stage !== 'приостановлен';

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return '-';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
}
