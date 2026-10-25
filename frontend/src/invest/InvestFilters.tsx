import { num } from '../format';
import { NEED_FULL, type Client, type Facets, type InvestFilters, type Need } from './api';

const CLIENTS: { v: Client; label: string }[] = [
  { v: 'all', label: 'Все' }, { v: 'other', label: 'Не наши' }, { v: 'rtk', label: 'Клиенты РТК' },
];
const SUM_PRESETS = [
  { label: 'Любая', min: '', max: '' }, { label: 'от 100 млн', min: '100', max: '' },
  { label: 'от 1 млрд', min: '1000', max: '' }, { label: 'до 50 млн', min: '', max: '50' },
];
// Стадии в порядке жизненного цикла проекта; введённые и приостановленные — только при снятой галочке «активные»
const STAGE_ORDER = ['подготовка', 'реализация', 'ввод в этом году', 'стадия не подтверждена', 'введён', 'работы завершены', 'приостановлен', 'сроки не указаны'];

const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v]);

interface Props {
  f: InvestFilters;
  set: (patch: Partial<InvestFilters>) => void;
  reset: () => void;
  facets?: Facets;
}

export default function InvestFiltersPanel({ f, set, reset, facets }: Props) {
  const stages = [...(facets?.stage ?? [])]
    .filter(s => !f.active || s.active > 0)
    .sort((a, b) => STAGE_ORDER.indexOf(a.key) - STAGE_ORDER.indexOf(b.key));
  const count = (x: { n: number; active: number }) => (f.active ? x.active : x.n);

  return (
    <aside className="filters" aria-label="Фильтры проектов">
      <label className="field">
        <span className="field__label">Поиск</span>
        <input className="rt-input" placeholder="Проект, инициатор или ИНН" value={f.q} onChange={e => set({ q: e.target.value })} />
      </label>

      <div className="field invest-sector">
        <span className="field__label">Сектор</span>
        <div className="segmented">
          {([{ value: 'all', label: 'Все' }, { value: 'government', label: 'Госсектор' },
             { value: 'private', label: 'Бизнес' }] as const).map(s => (
            <button key={s.value} className={f.sector === s.value ? 'is-active' : ''}
              onClick={() => set({ sector: s.value })}>{s.label}</button>
          ))}
        </div>
        {f.sector === 'government' && <p className="meta">Объекты госучреждений и госпрограмм, включая капремонт и реконструкцию</p>}
      </div>

      <div className="field">
        <span className="field__label">Потребность РТК</span>
        <div className="chips">
          {(Object.keys(NEED_FULL) as Need[]).map(n => (
            <button key={n} className={`chip ${f.need.includes(n) ? 'is-active' : ''}`} onClick={() => set({ need: toggle(f.need, n) })}>{NEED_FULL[n]}</button>
          ))}
        </div>
      </div>

      <div className="field">
        <span className="field__label">Стадия</span>
        <div className="chips">
          {stages.map(s => (
            <button key={s.key} className={`chip ${f.stage.includes(s.key) ? 'is-active' : ''}`} onClick={() => set({ stage: toggle(f.stage, s.key) })}>
              {s.key} <span>{num(count(s))}</span>
            </button>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={f.window} onChange={e => set({ window: e.target.checked })} />
          Только окно продаж: ввод в следующем году
        </label>
        <label className="check">
          <input type="checkbox" checked={f.active} onChange={e => set({ active: e.target.checked, stage: [] })} />
          Скрыть завершённые и архивные проекты
        </label>
      </div>

      <div className="field">
        <span className="field__label">Инициатор</span>
        <div className="segmented">
          {CLIENTS.map(c => (
            <button key={c.v} className={f.client === c.v ? 'is-active' : ''} onClick={() => set({ client: c.v })}>{c.label}</button>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={f.interregional} onChange={e => set({ interregional: e.target.checked })} />
          Межрегиональные игроки (ИНН другого региона)
        </label>
        <label className="check">
          <input type="checkbox" checked={f.keyOnly} onChange={e => set({ keyOnly: e.target.checked })} />
          Ключевые («100 губернаторских»)
        </label>
        <label className="check">
          <input type="checkbox" checked={f.hasInn} onChange={e => set({ hasInn: e.target.checked })} />
          ИНН инициатора или заказчика найден
        </label>
      </div>

      <div className="field">
        <span className="field__label">Сумма проекта, млн ₽</span>
        <div className="range">
          <input className="rt-input" inputMode="decimal" placeholder="от" value={f.sumMin} onChange={e => set({ sumMin: e.target.value })} />
          <span>-</span>
          <input className="rt-input" inputMode="decimal" placeholder="до" value={f.sumMax} onChange={e => set({ sumMax: e.target.value })} />
        </div>
        <div className="chips">
          {SUM_PRESETS.map(p => (
            <button key={p.label} className={`chip ${f.sumMin === p.min && f.sumMax === p.max ? 'is-active' : ''}`}
              onClick={() => set({ sumMin: p.min, sumMax: p.max })}>{p.label}</button>
          ))}
        </div>
      </div>

      <div className="field">
        <span className="field__label">Отрасль</span>
        <div className="chips chips--scroll">
          {facets?.industry.filter(i => count(i) > 0).map(i => (
            <button key={i.key} className={`chip ${f.industry.includes(i.key) ? 'is-active' : ''}`}
              onClick={() => set({ industry: toggle(f.industry, i.key) })}>
              {i.key} <span>{num(count(i))}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <span className="field__label">Муниципалитет</span>
        <div className="chips chips--scroll">
          {facets?.municipality.filter(m => count(m) > 0).map(m => (
            <button key={m.key} className={`chip ${f.oktmo.includes(m.key) ? 'is-active' : ''}`}
              onClick={() => set({ oktmo: toggle(f.oktmo, m.key) })}>
              {m.label} <span>{num(count(m))}</span>
            </button>
          ))}
        </div>
      </div>

      <button className="link-btn" onClick={reset}>Сбросить фильтры</button>
    </aside>
  );
}
