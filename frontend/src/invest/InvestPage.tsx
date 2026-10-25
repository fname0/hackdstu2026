import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { num } from '../format';
import CompanyCard from '../radar/CompanyCard';
import { emptyInvestFilters, investApi, type GanttSort, type InvestFilters } from './api';
import { mln } from './fmt';
import HotList from './HotList';
import InvestFiltersPanel from './InvestFilters';
import InvestMap from './InvestMap';
import ProjectCard from './ProjectCard';
import Timeline from './Timeline';

export default function InvestPage() {
  const [filters, setFilters] = useState<InvestFilters>(emptyInvestFilters);
  const [debounced, setDebounced] = useState(filters);
  useEffect(() => { const t = setTimeout(() => setDebounced(filters), 300); return () => clearTimeout(t); }, [filters]);

  const [projectId, setProjectId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false); // только на узком экране: на десктопе панель видна всегда
  const [company, setCompany] = useState<string | null>(null);

  const [ganttH, setGanttH] = useState(readGanttHeight);
  useEffect(() => { try { localStorage.setItem(GANTT_KEY, String(ganttH)); } catch { /* хранилище недоступно - не страшно */ } }, [ganttH]);
  const facets = useQuery({ queryKey: ['invest-facets'], queryFn: investApi.facets });
  // Плитки сверху считаются по тем же фильтрам, что карта, Гант и список
  const stats = useQuery({ queryKey: ['invest-stats', debounced], queryFn: () => investApi.stats(debounced),
    placeholderData: keepPreviousData });
  const points = useQuery({ queryKey: ['invest-points', debounced], queryFn: () => investApi.points(debounced),
    placeholderData: keepPreviousData });
  const [ganttSort, setGanttSort] = useState<GanttSort>('hot');
  const timeline = useQuery({ queryKey: ['invest-timeline', debounced, ganttSort], queryFn: () => investApi.timeline(debounced, ganttSort),
    placeholderData: keepPreviousData });

  // Та же карточка, что открыта справа (общий кэш запроса): из неё берём координаты, чтобы подлететь картой к проекту
  const card = useQuery({ queryKey: ['invest-project', projectId], queryFn: () => investApi.project(projectId!),
    enabled: !!projectId });

  const set = (patch: Partial<InvestFilters>) => setFilters(f => ({ ...f, ...patch }));
  const onProject = useCallback((id: string) => setProjectId(id), []);
  const st = stats.data;
  const filtered = JSON.stringify(debounced) !== JSON.stringify(emptyInvestFilters);

  return (
    <div className={`invest ${filtersOpen ? 'is-filters-open' : ''}`}>
      <button className="filters-toggle rt-btn rt-btn--ghost rt-btn--sm" onClick={() => setFiltersOpen(o => !o)} aria-expanded={filtersOpen}>
        {filtersOpen ? 'Скрыть фильтры' : `Фильтры${filtered ? ' · заданы' : ''}`}
      </button>
      <InvestFiltersPanel f={filters} set={set} reset={() => setFilters(emptyInvestFilters)} facets={facets.data} />

      <section className="invest__main">
        <div className="kpis" aria-label="Сводка">
          <Kpi value={num(st?.projects)} label={filtered ? 'проектов по фильтрам' : 'проектов в работе и планах'} />
          <Kpi value={num(st?.in_window)} label="в окне продаж" accent
            active={filters.window} onClick={() => set({ window: !filters.window })} />
          <Kpi value={num(st?.interregional)} label="межрегиональных игроков"
            active={filters.interregional} onClick={() => set({ interregional: !filters.interregional })} />
          <Kpi value={mln(st?.potential_mln)} label="потенциал для РТК" />
          <Kpi value={num(st?.rtk_clients)} label="инициаторов - клиентов РТК"
            active={filters.client === 'rtk'} onClick={() => set({ client: filters.client === 'rtk' ? 'all' : 'rtk' })} />
        </div>

        <div className="invest__map">
          <InvestMap points={points.data} selected={projectId} onSelect={onProject}
            focus={card.data && card.data.lat != null && card.data.lon != null
              ? { id: card.data.project_id, lat: card.data.lat, lon: card.data.lon, approx: card.data.location_precision !== 'точный адрес' && card.data.location_precision !== 'точка с портала' }
              : undefined} />
          <div className="map-legend map-legend--compact" title="Размер точки - сумма проекта">
            <span><i className="dot dot--hot" /> ввод в след. году</span>
            <span><i className="dot dot--prep" /> подготовка</span>
            <span><i className="dot dot--build" /> реализация</span>
            <span><i className="dot dot--launch" /> ввод в этом году</span>
            <span><i className="dot dot--done" /> завершён</span>
          </div>
        </div>

        <Splitter height={ganttH} onChange={setGanttH} />

        <Timeline data={timeline.data} sort={ganttSort} onSort={setGanttSort} selected={projectId} onProject={onProject}
          height={ganttH} from={filters.finishFrom} to={filters.finishTo} onRange={(a, b) => set({ finishFrom: a, finishTo: b })} />
      </section>

      <section className="invest__side">
        {projectId
          ? <ProjectCard id={projectId} onClose={() => setProjectId(null)} onProject={onProject} onCompany={setCompany} />
          : <HotList filters={debounced} onProject={onProject} />}
      </section>

      {company && <CompanyCard inn={company} onClose={() => setCompany(null)} />}
    </div>
  );
}

// Высота списка проектов на Ганте: тянется разделителем, запоминается в браузере (только удобство, не данные)
// v2: высота по умолчанию стала меньше — старое сохранённое значение (280) не подхватываем
const GANTT_KEY = 'invest.ganttHeight.v2';
// По умолчанию видны шкала годов и две строки проектов (33 + 2 × 39 + рамки и полоса прокрутки 12); остальное — прокруткой или разделителем
const GANTT_MIN = 90, GANTT_DEFAULT = 124;
const MAP_MIN = 180; // карту целиком не схлопываем

function readGanttHeight() {
  try {
    const v = Number(localStorage.getItem(GANTT_KEY));
    return v >= GANTT_MIN ? v : GANTT_DEFAULT;
  } catch { return GANTT_DEFAULT; }
}

/** Граница между картой и таймлайном: тянем вверх — таймлайн выше, карта ниже. Стрелки ↑/↓ — по 40 px. */
function Splitter({ height, onChange }: { height: number; onChange: (h: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  // Максимум: всё, что выше разделителя, кроме минимальной карты и плиток
  const clamp = (h: number) => {
    const main = ref.current?.closest('.invest__main') as HTMLElement | null;
    const map = main?.querySelector('.invest__map') as HTMLElement | null;
    const room = map ? map.getBoundingClientRect().height - MAP_MIN + height : 600;
    return Math.round(Math.max(GANTT_MIN, Math.min(room, h)));
  };
  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const y0 = e.clientY, h0 = height;
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    document.body.classList.add('is-resizing');
    const move = (ev: PointerEvent) => onChange(clamp(h0 + (y0 - ev.clientY)));
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      document.body.classList.remove('is-resizing');
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowUp') { e.preventDefault(); onChange(clamp(height + 40)); }
    if (e.key === 'ArrowDown') { e.preventDefault(); onChange(clamp(height - 40)); }
  };
  return (
    <div ref={ref} className="splitter" role="separator" aria-orientation="horizontal" aria-label="Размер таймлайна"
      aria-valuenow={height} tabIndex={0} title="Потяните, чтобы изменить высоту таймлайна"
      onPointerDown={onPointerDown} onKeyDown={onKey} onDoubleClick={() => onChange(clamp(GANTT_DEFAULT))}>
      <span className="splitter__grip" />
    </div>
  );
}

function Kpi({ value, label, sub, accent, active, onClick }: {
  value: string; label: string; sub?: string; accent?: boolean; active?: boolean; onClick?: () => void;
}) {
  const body = (<>
    <span className={`kpi__value ${accent ? 'kpi__value--accent' : ''}`}>{value}</span>
    <span className="kpi__label">{label}</span>
    {sub && <span className="kpi__sub">{sub}</span>}
  </>);
  return onClick
    ? <button className={`kpi kpi--button ${active ? 'is-active' : ''}`} onClick={onClick} aria-pressed={active}
        title={active ? 'Снять фильтр' : 'Показать только эти проекты'}>{body}</button>
    : <div className="kpi">{body}</div>;
}
