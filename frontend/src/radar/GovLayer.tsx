import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, type GovSummary } from '../api';
import { money, num } from '../format';
import { fmtDay } from './GovCard';

const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v]);

/** Панель фильтров: «Госсектор» — включает учреждения на карте; под ним сегменты (как отрасли у частного сектора). */
export function GovFilter({ summary, on, setOn, segments, setSegments }: {
  summary?: GovSummary; on: boolean; setOn: (v: boolean) => void; segments: string[]; setSegments: (s: string[]) => void;
}) {
  const ready = summary?.available;
  return (
    <div className="field">
      <label className="check check--section">
        <input type="checkbox" checked={ready ? on : false} disabled={!ready} onChange={e => setOn(e.target.checked)} />
        <span>Госсектор {ready && <span className="count">{num(summary.with_point)}</span>}</span>
      </label>
      {!ready && <p className="meta">Данные загружаются: выгрузка bus.gov.ru ещё идёт</p>}
      {ready && on && (
        <>
          <span className="field__label">Учреждения с bus.gov.ru · клиент РТК - есть действующий контракт на связь (ЕИС)</span>
          <div className="chips">
            {summary.by_segment?.map(s => (
              <button key={s.key} className={`chip ${segments.includes(s.key) ? 'is-active' : ''}`}
                onClick={() => setSegments(toggle(segments, s.key))}>
                {s.key} <span>{num(s.n)}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Панель района: учреждения госсектора в выбранном районе. */
export function GovZoneBlock({ oktmo, segments, onSelect }: {
  oktmo: string; segments: string[]; onSelect: (inn: string) => void;
}) {
  const q = useQuery({ queryKey: ['gov-zone', oktmo, segments], queryFn: () => api.govZone(oktmo, segments),
    placeholderData: keepPreviousData });
  const d = q.data;
  if (!d) return <section className="block"><div className="skeleton" style={{ height: 120 }} /></section>;
  return (
    <section className="block">
      <div className="block__head">
        <h3>Госсектор района <span className="count">{num(d.total)}</span></h3>
        <a className="link-btn" href={api.govExportCsvUrl(segments, oktmo)}>CSV</a>
      </div>
      <div className="chips">{d.by_segment.map(s => <span key={s.key} className="chip chip--static">{s.key} <span>{num(s.n)}</span></span>)}</div>
      {d.telecom && d.telecom.contracts > 0 && (
        <p className="meta">Связь по контрактам ЕИС: у Ростелекома {num(d.telecom.rtk)} из {num(d.telecom.contracts)} действующих
          {d.telecom.sales_window > 0 && <>, у конкурентов скоро кончаются <strong>{num(d.telecom.sales_window)}</strong></>}</p>
      )}
      {d.total === 0 && <p className="empty">В районе нет учреждений по выбранным сегментам</p>}
      <ul className="list list--compact">
        {d.items.map(r => (
          <li key={r.inn}>
            <button className="list__row" onClick={() => onSelect(r.inn)}>
              <span className="list__main"><strong>{r.name_short || r.name}</strong>
                <span className="sub">{r.segment} · {r.inst_type}</span></span>
            </button>
          </li>
        ))}
      </ul>
      {d.total > d.items.length && <p className="meta">Показаны первые {d.items.length}, все - в CSV</p>}
    </section>
  );
}

/** Обзор области: «кому звонить» в госсекторе — контракты на связь у конкурентов, которые скоро кончаются. */
export function GovExpiring({ summary, onSelect }: { summary?: GovSummary; onSelect: (inn: string) => void }) {
  const q = useQuery({ queryKey: ['gov-expiring'], queryFn: () => api.govExpiring(6) });
  const c = summary?.contracts;
  const d = q.data;
  return (
    <section className="block">
      <h2>Госсектор: звонить сейчас {d && <span className="count">{num(d.total)}</span>}</h2>
      <p className="meta">Контракты учреждений на связь не с Ростелекомом, которые кончаются в ближайшие 6 месяцев
        {d ? ` - всего на ${money(d.sum)}` : ''}. К новой закупке нужно успеть с предложением</p>
      {c && <p className="meta">Доля Ростелекома в контрактах на связь (ЕИС, 44-ФЗ, с 2024): {num(c.rtk_share_by_count_pct)}% по числу,
        {' '}{num(c.rtk_share_by_sum_pct)}% по сумме · поставщик известен у {num(c.with_supplier)} из {num(c.contracts)}</p>}
      {!d && <div className="skeleton" style={{ height: 160 }} />}
      <ul className="list list--compact">
        {d?.items.map(k => (
          <li key={k.reestr_number}>
            <button className="list__row" disabled={!k.has_card} onClick={() => k.has_card && onSelect(k.customer_inn)}
              title={k.has_card ? 'Открыть карточку учреждения' : 'Учреждения нет в выгрузке bus.gov.ru'}>
              <span className="list__main"><strong>{k.customer}</strong>
                <span className="sub">{k.service} · {k.operator === 'другой' ? k.supplier : k.operator} · {money(k.price)}</span>
                <span className="sub">до {fmtDay(k.finish_date)}{k.municipality ? ` · ${k.municipality}` : ''}</span></span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
