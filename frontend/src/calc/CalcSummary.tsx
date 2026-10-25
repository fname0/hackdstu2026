import { useState } from 'react';
import { num, plural } from '../format';
import { calcApi, type Estimate, type EstimateRequest, type ForkKey, type Reference } from './api';
import type { Draft } from './CalcPage';
import { fmtK } from './CalcParams';

const rub = (v: number) => `${num(Math.round(v))} ₽`;
const pct = (v: number) => `${(v * 100).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
const FORK: [ForkKey, string][] = [['min', 'Минимум'], ['opt', 'Оптимум'], ['max', 'Максимум']];

/** Правая панель: ценовая вилка, цена в КП с маржинальностью, разложение формулы, уровни, выгрузки. */
export default function CalcSummary({ d, set, ref_, est, req, loading }: {
  d: Draft; set: (p: Partial<Draft>) => void; ref_: Reference; est?: Estimate; req: EstimateRequest; loading: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!est) return <div className="panel"><div className="skeleton" style={{ height: 420 }} /></div>;
  if (!est.equipment) {
    return <div className="panel"><p className="empty">Добавьте оборудование в спецификацию - здесь появится ценовая вилка</p></div>;
  }

  const price = d.offer === 'custom' && d.offerPrice ? d.offerPrice : est.fork[d.offer === 'custom' ? 'opt' : d.offer].price;
  const markup = (price - est.cost) / est.cost, margin = (price - est.cost) / price;
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setError(null);
    try { await fn(); } catch { setError('Не удалось сформировать файл. Проверьте, что API запущен, и повторите'); } finally { setBusy(null); }
  };

  return (
    <div className={`panel calc-summary ${loading ? 'is-loading' : ''}`}>
      <section className="block">
        <h2>Ценовая вилка <span className="hint">без НДС</span></h2>
        <div className="stats stats--3 fork">
          {FORK.map(([k, label]) => (
            <button key={k} className={`stat fork__item ${d.offer === k ? 'is-active' : ''}`} aria-pressed={d.offer === k}
              onClick={() => set({ offer: k, offerPrice: null })} title={`Взять в КП: наценка ${pct(est.fork[k].markup)}`}>
              <div className={`stat__value ${k === 'opt' ? 'stat__value--hot' : ''}`}>{rub(est.fork[k].price)}</div>
              <div className="stat__label">{label} · +{pct(est.fork[k].markup)}</div>
            </button>
          ))}
        </div>
        <p className="meta">Себестоимость {rub(est.cost)}. Наценка к ней: минимум {pct(ref_.markup.min)}, оптимум {pct(ref_.markup.opt)},
          максимум {pct(ref_.markup.max)}.</p>
      </section>

      <section className="block">
        <h3>Цена в КП</h3>
        <MarginChart est={est} price={price} onPrice={p => set({ offer: 'custom', offerPrice: Math.round(p) })} />
        <div className="offer">
          <div>
            <div className="offer__price">{rub(price * (1 + est.vat))}</div>
            <div className="sub">с НДС {pct(est.vat)} · без НДС {rub(price)}</div>
          </div>
          <label className="offer__input">
            <span className="sub">своя цена без НДС</span>
            <input className="rt-input rt-input--sm num" type="number" min={0} step={1000} value={Math.round(price)}
              onChange={e => set({ offer: 'custom', offerPrice: Math.max(0, Number(e.target.value) || 0) })} />
          </label>
        </div>
        <dl className="facts facts--tight">
          <dt>Прибыль</dt><dd className="num">{rub(price - est.cost)}</dd>
          <dt>Наценка / маржа</dt><dd className="num">{pct(markup)} / {pct(margin)}</dd>
          <dt>Срок</dt><dd>{est.weeks} {plural(est.weeks, 'неделя', 'недели', 'недель')}
            {est.weeks !== est.weeks_std && <span className="sub">стандартно {est.weeks_std}</span>}</dd>
        </dl>
        {price < est.cost && <p className="meta meta--error">Цена ниже себестоимости - сделка в убыток</p>}
        {price >= est.cost && price < est.fork.min.price - 1 && <p className="meta meta--warn">Наценка ниже минимальной ({pct(ref_.markup.min)}) - понадобится согласование</p>}
        {price > est.fork.max.price + 1 && <p className="meta meta--warn">Цена выше верхней границы вилки - растёт риск проиграть конкурентам</p>}
      </section>

      <section className="block">
        <h3>Выгрузить</h3>
        <div className="export">
          <button className="rt-btn rt-btn--primary rt-btn--sm" disabled={!!busy} onClick={() => run('kp', () => calcApi.kp(req))}>
            {busy === 'kp' ? 'Готовим КП…' : 'Скачать КП (DOCX)'}
          </button>
          <button className="rt-btn rt-btn--outline rt-btn--sm" disabled={!!busy} onClick={() => run('csv', () => calcApi.csv(req))}>CSV</button>
          <button className="rt-btn rt-btn--outline rt-btn--sm" disabled={!!busy} onClick={() => run('amo', () => calcApi.crm(req, 'amocrm'))}>amoCRM</button>
          <button className="rt-btn rt-btn--outline rt-btn--sm" disabled={!!busy} onClick={() => run('bx', () => calcApi.crm(req, 'bitrix24'))}>Bitrix24</button>
        </div>
        {error && <p className="meta meta--error">{error}</p>}
      </section>

      <section className="block">
        <h3>Как посчитано</h3>
        <ul className="calc-steps">
          <Step label="Оборудование по прайсу × сложность" value={est.equipment_std} source="прайс организаторов" />
          {est.equipment_custom > 0 && <Step label={`ПО и нестандарт (+${pct(ref_.custom_markup)})`} value={est.equipment_custom} source="наценка за нестандарт" />}
          {est.works.map(w => <Step key={w.code} label={`${w.label}, ${pct(w.pct)}`} value={w.sum} source="доля от стоимости оборудования" />)}
          <Step label="Итого до коэффициентов" value={est.subtotal} strong />
          {est.coefficients.map(c => <Step key={c.kind} label={c.label} k={c.value} source={c.note} />)}
          <Step label="Себестоимость" value={est.cost} strong />
          <Step label={`Наценка ${pct(markup)}`} value={price - est.cost} />
          <Step label="Цена без НДС" value={price} strong />
        </ul>
      </section>

      <section className="block">
        <h3>Тот же состав на другом уровне</h3>
        <ul className="list list--compact">
          {est.levels.map(l => (
            <li key={l.code}>
              <button className={`list__row ${l.code === d.level ? 'is-current' : ''}`} onClick={() => set({ level: l.code })}>
                <span className="list__main">{l.label} <span className="sub">×{fmtK(l.value)} · {ref_.levels.find(x => x.code === l.code)?.note}</span></span>
                <span className="num">{rub(l.opt)}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="meta">Цена по оптимуму, без НДС</p>
      </section>

    </div>
  );
}

function Step({ label, value, k, source, note, strong }: {
  label: string; value?: number; k?: number; source?: string; note?: string; strong?: boolean;
}) {
  return (
    <li className={strong ? 'is-strong' : ''} title={note}>
      <span>{label}{source && <span className="sub">{source}{note ? ` · ${note}` : ''}</span>}</span>
      <span className="num">{k != null ? `×${fmtK(k)}` : rub(value ?? 0)}</span>
    </li>
  );
}

/** Маржинальность от цены: кривая (P − C) / P, зоны «убыток / ниже минимума / вилка / выше вилки», ползунок цены. */
function MarginChart({ est, price, onPrice }: { est: Estimate; price: number; onPrice: (p: number) => void }) {
  const lo = est.cost * 0.9, hi = est.fork.max.price * 1.15;
  const x = (p: number) => ((Math.min(hi, Math.max(lo, p)) - lo) / (hi - lo)) * 100;
  const yMax = 0.35, yMin = -0.12;
  const y = (m: number) => ((yMax - Math.min(yMax, Math.max(yMin, m))) / (yMax - yMin)) * 100;
  const path = Array.from({ length: 41 }, (_, i) => {
    const p = lo + ((hi - lo) * i) / 40;
    return `${i ? 'L' : 'M'}${x(p).toFixed(2)},${y((p - est.cost) / p).toFixed(2)}`;
  }).join(' ');
  const m = (price - est.cost) / price;
  return (
    <div className="mchart">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <rect x={0} y={0} width={x(est.cost)} height={100} className="mchart__loss" />
        <rect x={x(est.fork.min.price)} y={0} width={x(est.fork.max.price) - x(est.fork.min.price)} height={100} className="mchart__fork" />
        <line x1={0} x2={100} y1={y(0)} y2={y(0)} className="mchart__zero" />
        <path d={path} className="mchart__line" vectorEffect="non-scaling-stroke" />
        <line x1={x(price)} x2={x(price)} y1={0} y2={100} className="mchart__price" vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="mchart__dot" style={{ left: `${x(price)}%`, top: `${y(m)}%` }} />
      <span className="mchart__label" style={{ left: `${Math.min(86, Math.max(14, x(price)))}%` }}>маржа {pct(m)}</span>
      <div className="mchart__axis">
        <span style={{ left: `${x(est.cost)}%` }}>себестоимость</span>
        <span style={{ left: `${x(est.fork.opt.price)}%` }}>оптимум</span>
      </div>
      <input type="range" className="mchart__range" min={Math.round(lo)} max={Math.round(hi)} step={Math.max(1, Math.round((hi - lo) / 200))}
        value={Math.round(Math.min(hi, Math.max(lo, price)))} onChange={e => onPrice(Number(e.target.value))}
        aria-label="Цена предложения без НДС" />
    </div>
  );
}
