import { num } from '../format';
import type { GanttRow, GanttSort, Timeline as TimelineData } from './api';
import { inWindow, launchIn, mln } from './fmt';

const SORTS: { v: GanttSort; label: string }[] = [
  { v: 'hot', label: 'Горячие' }, { v: 'launch', label: 'Скоро ввод' }, { v: 'start', label: 'По старту' }, { v: 'sum', label: 'Крупные' },
];
// Шкала не дальше чем на 8 лет вперёд: единичные проекты с вводом в 2041 и 2055 сжали бы всё остальное в полоску
const AHEAD = 8;

/** Диаграмма Ганта инвестсобытий: полоса «начало → ввод» по каждому проекту под фильтром.
 *  Колонка следующего года подсвечена — это окно продаж; клик по году на шкале — фильтр по году ввода. */
export default function Timeline({ data, sort, onSort, selected, onProject, height, from, to, onRange }: {
  data?: TimelineData; sort: GanttSort; onSort: (s: GanttSort) => void; height: number;
  selected: string | null; onProject: (id: string) => void;
  from?: number; to?: number; onRange: (from?: number, to?: number) => void;
}) {
  const now = new Date();
  const year = now.getFullYear();
  const t = year + now.getMonth() / 12; // «сегодня» внутри года

  const rows = data?.gantt ?? [];
  const lo = Math.max(year - AHEAD, Math.min(year - 1, ...rows.map(r => r.start_year ?? r.finish_year)));
  const hi = Math.min(year + AHEAD, Math.max(year + 2, ...rows.map(r => r.finish_year)));
  const years = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  const span = hi + 1 - lo;
  const x = (v: number) => `${((Math.max(lo, Math.min(hi + 1, v)) - lo) / span) * 100}%`;
  const w = (a: number, b: number) => `${((Math.min(hi + 1, b) - Math.max(lo, a)) / span) * 100}%`;
  const pickYear = (y: number) => (from === y && to === y ? onRange(undefined, undefined) : onRange(y, y));

  return (
    <div className="gantt-box">
      <div className="timeline__head">
        {/* Цвета — те же, что у точек на карте, их легенда над Гантом; отдельную здесь не повторяем */}
        <h3 title="Сроки в реестре указаны годами: полоса от начала года старта до конца года ввода">Таймлайн инвестсобытий</h3>
        <div className="segmented segmented--inline">
          {SORTS.map(s => <button key={s.v} className={sort === s.v ? 'is-active' : ''} onClick={() => onSort(s.v)}>{s.label}</button>)}
        </div>
        <span className="meta">
          {data ? `${num(rows.length)} из ${num(data.gantt_total)}` : ''}
          {from != null && <> · ввод в {from} · <button className="link-btn" onClick={() => onRange(undefined, undefined)}>все годы</button></>}
        </span>
      </div>

      {!data && <div className="skeleton" style={{ height }} />}
      {data && rows.length === 0 && <p className="empty">Нет проектов со сроком ввода по фильтрам</p>}
      {data && rows.length > 0 && (
        <div className="gantt-chart" style={{ height }} role="table" aria-label="Проекты: начало и ввод в эксплуатацию">
          <div className="gantt-row gantt-row--axis" role="row">
            <div className="gantt-row__label" role="columnheader">Проект</div>
            <div className="gantt-row__track" role="columnheader">
              <span className="gantt-window" style={{ left: x(year + 1), width: w(year + 1, year + 2) }} />
              {years.map(y => (
                <button key={y} className={`gantt-year ${y === year ? 'is-now' : ''} ${from === y && to === y ? 'is-active' : ''} ${(y - year) % 2 ? 'is-odd' : ''}`}
                  style={{ left: x(y), width: w(y, y + 1) }} onClick={() => pickYear(y)}
                  title={`Показать проекты с вводом в ${y}`}>
                  {/* на телефоне — «26» и через год, иначе 15 подписей слипаются */}
                  <span className="y-full">{y}</span><span className="y-short">{String(y).slice(2)}</span>
                  {y === hi && rows.some(r => r.finish_year > hi) ? '+' : ''}
                </button>
              ))}
            </div>
          </div>
          <div className="gantt-body">
            <span className="gantt-window gantt-window--body" style={{ left: `calc(var(--gantt-label) + (100% - var(--gantt-label)) * ${(year + 1 - lo) / span})`, width: `calc((100% - var(--gantt-label)) * ${1 / span})` }} />
            <span className="gantt-today" style={{ left: `calc(var(--gantt-label) + (100% - var(--gantt-label)) * ${(t - lo) / span})` }} title="сегодня" />
            {rows.map(r => <Row key={r.project_id} r={r} x={x} w={w} hi={hi} selected={r.project_id === selected} onProject={onProject} />)}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ r, x, w, hi, selected, onProject }: {
  r: GanttRow; x: (v: number) => string; w: (a: number, b: number) => string; hi: number;
  selected: boolean; onProject: (id: string) => void;
}) {
  const start = r.start_year ?? r.finish_year;
  const cls = inWindow(r.months_to_launch, r.stage) ? 'is-hot'
    : r.stage === 'подготовка' ? 'is-prep' : ['введён', 'приостановлен', 'работы завершены', 'стадия не подтверждена'].includes(r.stage) ? 'is-done' : '';
  const late = r.finish_year > hi;
  return (
    <button className={`gantt-row ${selected ? 'is-selected' : ''}`} role="row" onClick={() => onProject(r.project_id)}
      title={`${r.title}\n${r.initiator} · ${start}-${r.finish_year} · ${mln(r.sum_mln)} · ${launchIn(r.months_to_launch, r.stage)}`}>
      <span className="gantt-row__label" role="cell">
        <span className="gantt-row__name">{r.initiator}</span>
        <span className="gantt-row__title">{r.title}</span>
      </span>
      <span className="gantt-row__track" role="cell">
        <span className={`gantt-bar ${cls}`} style={{ left: x(start), width: w(start, r.finish_year + 1) }}>
          <span className="gantt-bar__sum">{mln(r.sum_mln)}</span>
        </span>
        {!late && <span className={`gantt-mark ${cls}`} style={{ left: x(r.finish_year + 1) }} />}
        {late && <span className="gantt-late" style={{ left: x(hi + 1) }}>→ {r.finish_year}</span>}
      </span>
    </button>
  );
}
