import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api, type Filters, type Summary, type ZoneCollection, type ZoneProps } from '../api';
import { money, num, pct, plural } from '../format';
import { FACTOR_LABELS, type Weights } from './potential';

const FACTORS: { key: 'f_income' | 'f_growth' | 'f_gap'; w: keyof Weights }[] = [
  { key: 'f_income', w: 'income' }, { key: 'f_growth', w: 'growth' }, { key: 'f_gap', w: 'gap' },
];

export function Overview({ summary, zones, filtered, onZone, onCompany }: {
  summary?: Summary; zones?: ZoneCollection; filtered: boolean;
  onZone: (oktmo: string) => void; onCompany: (inn: string) => void;
}) {
  const churn = useQuery({ queryKey: ['churn'], queryFn: api.churn });
  if (!summary || !zones) return <div className="panel"><div className="skeleton" style={{ height: 240 }} /></div>;
  const zs = zones.features.map(f => f.properties);
  const spots = zs.filter(z => z.white_spot).sort((a, b) => b.potential - a.potential);
  const companies = zs.reduce((a, z) => a + z.companies, 0);
  const rtk = zs.reduce((a, z) => a + z.rtk_clients, 0);
  const income = zs.reduce((a, z) => a + z.income_sum, 0);
  const newMonth = zs.reduce((a, z) => a + z.new_month, 0);
  return (
    <div className="panel">
      <div className="stats">
        <Stat value={num(companies)} label={`субъектов МСП${filtered ? ' по фильтрам' : ''}`} />
        <Stat value={num(rtk)} label="клиентов РТК" accent />
        <Stat value={filtered ? `+${num(newMonth)}` : `+${num(summary.new_month)} / −${num(summary.left_month)}`}
          label={filtered ? 'новые за месяц' : 'новые / выбывшие за месяц'} />
        <Stat value={money(income)} label="доходы юрлиц за 2025" />
      </div>

      <section className="block">
        <h2>Белые пятна <span className="count">{spots.length}</span></h2>
        <p className="meta">Охват РТК не выше 75% от среднего по выборке, а потенциал района - в верхней трети</p>
        {rtk < 50 && (
          <p className="meta meta--warn">В выборке всего {rtk} клиентов РТК на 55 районов - в большинстве районов их ноль, поэтому недоохват здесь
            малонадёжен. Смотрите прежде всего на доход и рост или уменьшите вес недоохвата</p>
        )}
        {spots.length === 0 && <p className="empty">При текущих весах и фильтрах белых пятен нет</p>}
        <ul className="list">
          {spots.map(z => (
            <li key={z.oktmo}>
              <button className="list__row" onClick={() => onZone(z.oktmo)}>
                <span className="list__main"><strong>{z.municipality}</strong>
                  <span className="sub">охват {Math.round(z.coverage_vs_region * 100)}% от среднего</span></span>
                <span className="score">{num(z.potential)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="block">
        <h2>Отток клиентов</h2>
        {churn.data && (
          <>
            <div className="sub-h">Выбыли за месяц <span className="count">{churn.data.left.length}</span></div>
            <ul className="list list--compact">
              {churn.data.left.map(r => (
                <li key={r.inn}><div className="list__row list__row--static">
                  <span className="list__main">{r.name}<span className="sub">{r.municipality} · {r.churn_type}{r.dd_liquidation_date ? `, ${fmtDate(r.dd_liquidation_date)}` : ''}</span></span>
                </div></li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}

export function ZonePanel({ zone, weights, filters, onClose, onCompany, gov }: {
  zone: ZoneProps; weights: Weights; filters: Filters; onClose: () => void; onCompany: (inn: string) => void;
  /** Блок «Госсектор района», когда слой включён */
  gov?: ReactNode;
}) {
  const sumW = weights.income + weights.growth + weights.gap || 1;
  const [sort, setSort] = useState('lead_score');
  const [page, setPage] = useState(0);
  const f = { ...filters, oktmo: [zone.oktmo] };
  const leads = useQuery({ queryKey: ['leads', f, sort, page], queryFn: () => api.companies(f, sort, page * 50) });

  return (
    <div className="panel">
      <div className="panel__head">
        <button className="link-btn" onClick={onClose}>← Вся область</button>
        <h2 className="zone-title">{zone.municipality}</h2>
        {zone.white_spot && <span className="badge badge--spot">белое пятно</span>}
        {zone.white_spot_reason && <p className="meta">{zone.white_spot_reason}</p>}
      </div>

      <div className="stats stats--3">
        <Stat value={num(zone.potential)} label={`потенциал · ${zone.potential_rank} место из 55`} accent />
        <Stat value={`${zone.rtk_clients} / ${num(zone.companies)}`} label={`клиентов РТК · охват ${zone.rtk_share_pct.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`} />
        <Stat value={`+${zone.new_month}`} label="новых компаний за месяц" />
      </div>

      <section className="block">
        <h3>Из чего сложился потенциал <span className="hint">оценка</span></h3>
        {FACTORS.map(x => {
          const max = Math.round((weights[x.w] / sumW) * 100);
          return (
            <div className="factor" key={x.key}>
              <span>{FACTOR_LABELS[x.w].label}</span>
              <span className="factor__bar"><i style={{ width: `${max ? (zone[x.key] / max) * 100 : 0}%` }} /></span>
              <span className="num">{num(zone[x.key])} / {max}</span>
            </div>
          );
        })}
        <p className="meta">Доход юрлиц за 2025: {money(zone.income_sum)} · изменение к 2024: {zone.income_growth_abs >= 0 ? '+' : ''}{money(zone.income_growth_abs)} ({pct(zone.income_growth_pct)}) · охват {Math.round(zone.coverage_vs_region * 100)}% от среднего</p>
      </section>

      {gov}

      <section className="block">
        <div className="block__head">
          <h3>Компании <span className="count">{leads.data ? num(leads.data.total) : '…'}</span></h3>
          <select className="rt-input rt-input--sm" value={sort} onChange={e => { setSort(e.target.value); setPage(0); }}>
            <option value="lead_score">по потенциалу</option>
            <option value="income">по доходу</option>
            <option value="growth">по росту</option>
          </select>
        </div>
        <div className="export">
          <a className="rt-btn rt-btn--primary rt-btn--sm" href={api.exportCsvUrl(f)}>Выгрузить CSV</a>
          <a className="rt-btn rt-btn--outline rt-btn--sm" href={api.exportCrmUrl(f, 'amocrm')}>amoCRM</a>
          <a className="rt-btn rt-btn--outline rt-btn--sm" href={api.exportCrmUrl(f, 'bitrix24')}>Bitrix24</a>
        </div>
        {leads.isLoading && <div className="skeleton" style={{ height: 300 }} />}
        {leads.data && leads.data.total === 0 && <p className="empty">Нет компаний по выбранным фильтрам</p>}
        <ul className="list">
          {leads.data?.items.map(c => (
            <li key={c.inn}>
              <button className="list__row" onClick={() => onCompany(c.inn)}>
                <span className="list__main">
                  <strong>{c.name_short}</strong>
                  {c.is_rtk_client && <span className="badge badge--rtk">клиент РТК</span>}
                  <span className="sub">{c.kind} · {c.industry} · {c.place}</span>
                  <span className="sub">{c.kind === 'ЮЛ' ? `${money(c.income_2025)} · ${c.income_growth_pct != null ? pct(c.income_growth_pct, 0) : 'рост -'}` : `в реестре ${num(c.msp_years)} лет`}</span>
                </span>
                <span className="score">{num(c.lead_score)}</span>
              </button>
            </li>
          ))}
        </ul>
        {leads.data && leads.data.total > 50 && (
          <div className="pager">
            <button className="link-btn" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← назад</button>
            <span>{page * 50 + 1}-{Math.min((page + 1) * 50, leads.data.total)} из {num(leads.data.total)}</span>
            <button className="link-btn" disabled={(page + 1) * 50 >= leads.data.total} onClick={() => setPage(p => p + 1)}>дальше →</button>
          </div>
        )}
        <p className="meta">Балл - оценка потребности в продуктах РТК (масштаб, рост, отрасль, район). Для ИП и юрлиц считается по разным формулам: у ИП нет открытых данных о доходах</p>
      </section>
    </div>
  );
}

function Stat({ value, label, accent }: { value: string; label: string; accent?: boolean }) {
  return (
    <div className="stat">
      <div className={`stat__value ${accent ? 'stat__value--accent' : ''}`}>{value}</div>
      <div className="stat__label">{label}</div>
    </div>
  );
}

export const fmtDate = (iso?: string | null) => (iso ? iso.split('-').reverse().join('.') : '-');
export { plural };
