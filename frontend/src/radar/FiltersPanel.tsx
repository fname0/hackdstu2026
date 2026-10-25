import type { Client, Filters } from '../api';
import { num } from '../format';

const KINDS = ['ЮЛ', 'ИП', 'ИП (КФХ)'];
const CLIENTS: { v: Client; label: string }[] = [
  { v: 'all', label: 'Все' }, { v: 'rtk', label: 'Клиенты РТК' }, { v: 'other', label: 'Потенциальные' },
];
const INCOME_PRESETS = [
  { label: 'Любой', min: '', max: '' }, { label: 'от 10 млн', min: '10', max: '' },
  { label: 'от 100 млн', min: '100', max: '' }, { label: 'от 500 млн', min: '500', max: '' },
];

interface Props {
  f: Filters;
  set: (patch: Partial<Filters>) => void;
  reset: () => void;
  industries?: { industry: string; n: number }[];
}

const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v]);

export default function FiltersPanel({ f, set, reset, industries }: Props) {
  return (
    <aside className="filters" aria-label="Фильтры">
      <label className="field">
        <span className="field__label">Поиск</span>
        <input className="rt-input" placeholder="ИНН или название" value={f.q} onChange={e => set({ q: e.target.value })} />
      </label>

      <div className="field">
        <span className="field__label">Клиенты</span>
        <div className="segmented">
          {CLIENTS.map(c => (
            <button key={c.v} className={f.client === c.v ? 'is-active' : ''} onClick={() => set({ client: c.v })}>{c.label}</button>
          ))}
        </div>
        <div className="legend-dots"><i className="dot dot--rtk" />клиент РТК <i className="dot dot--other" />потенциальный</div>
      </div>

      <div className="field">
        <span className="field__label">Вид субъекта</span>
        <div className="chips">
          {KINDS.map(k => (
            <button key={k} className={`chip ${f.kind.includes(k) ? 'is-active' : ''}`} onClick={() => set({ kind: toggle(f.kind, k) })}>{k}</button>
          ))}
        </div>
      </div>

      <div className="field">
        <span className="field__label">Доход за 2025, млн ₽</span>
        <div className="range">
          <input className="rt-input" inputMode="decimal" placeholder="от" value={f.incomeMin} onChange={e => set({ incomeMin: e.target.value })} />
          <span>-</span>
          <input className="rt-input" inputMode="decimal" placeholder="до" value={f.incomeMax} onChange={e => set({ incomeMax: e.target.value })} />
        </div>
        <div className="chips">
          {INCOME_PRESETS.map(p => (
            <button key={p.label} className={`chip ${f.incomeMin === p.min && f.incomeMax === p.max ? 'is-active' : ''}`}
              onClick={() => set({ incomeMin: p.min, incomeMax: p.max })}>{p.label}</button>
          ))}
        </div>
      </div>

      <label className="field">
        <span className="field__label">Рост дохода за год не ниже, %</span>
        <input className="rt-input" inputMode="decimal" placeholder="например, 10" value={f.growthMin} onChange={e => set({ growthMin: e.target.value })} />
      </label>

      <div className="field">
          <>
            <span className="field__label">Компании реестра МСП · отрасль</span>
            <div className="chips chips--scroll">
              {industries?.map(i => (
                <button key={i.industry} className={`chip ${f.industry.includes(i.industry) ? 'is-active' : ''}`}
                  onClick={() => set({ industry: toggle(f.industry, i.industry) })}>
                  {i.industry} <span>{num(i.n)}</span>
                </button>
              ))}
            </div>
          </>
      </div>

      <button className="link-btn" onClick={reset}>Сбросить фильтры</button>
    </aside>
  );
}
