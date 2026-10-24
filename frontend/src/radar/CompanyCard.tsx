import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { money, num, pct } from '../format';
import { fmtDate } from './SidePanel';

const PART_LABELS: Record<string, string> = {
  s_scale: 'Масштаб (доход)', s_staff: 'Численность', s_growth: 'Рост дохода', s_industry: 'Отраслевой спрос',
  s_zone: 'Потенциал района', s_age: 'Стаж в реестре', s_licenses: 'Лицензии', s_kfh: 'Фермерское хозяйство', s_new: 'Новый бизнес',
};

export default function CompanyCard({ inn, onClose }: { inn: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['company', inn], queryFn: () => api.company(inn) });
  const c = q.data;
  return (
    <div className="drawer" role="dialog" aria-label="Карточка компании">
      <div className="drawer__head">
        <button className="link-btn" onClick={onClose}>✕ Закрыть</button>
      </div>
      {q.isLoading && <div className="skeleton" style={{ height: 400 }} />}
      {q.isError && <p className="empty">Компания не найдена в реестре МСП региона.</p>}
      {c && (
        <div className="drawer__body">
          <h2>{c.dd_name || c.name_short}</h2>
          <div className="badges">
            {c.is_rtk_client ? <span className="badge badge--rtk">клиент РТК</span> : <span className="badge badge--other">потенциальный клиент</span>}
            <span className="badge">{c.kind} · {c.category}</span>
            {c.dd_status && <span className={`badge ${c.dd_status === 'действует' ? '' : 'badge--warn'}`}>ЕГРЮЛ: {c.dd_status}</span>}
            {c.client_status?.churn_type && <span className="badge badge--warn">{c.client_status.churn_type}</span>}
            {c.flag_zero_income && <span className="badge badge--warn">нулевая отчётность</span>}
            {c.flag_check_category && <span className="badge badge--warn">доход не соответствует категории — проверить</span>}
          </div>

          <dl className="facts">
            <dt>ИНН</dt><dd>{c.inn}{c.kpp ? ` · КПП ${c.kpp}` : ''}</dd>
            <dt>ОКВЭД</dt><dd>{c.okved_main} {c.okved_main_name}</dd>
            <dt>Отрасль</dt><dd>{c.industry}</dd>
            <dt>Где</dt><dd>{c.legal_address || c.place}<span className="sub">{c.municipality} · точность: {c.location_precision}</span></dd>
            <dt>В реестре МСП</dt><dd>с {c.msp_since}{c.msp_since === '01.08.2016' ? ' (дата запуска реестра — бизнес не моложе)' : ''}</dd>
            {c.kind === 'ЮЛ' ? (<>
              <dt>Доход 2025</dt><dd>{money(c.income_2025)}<span className="sub">2024: {money(c.income_2024)} · рост {pct(c.income_growth_pct, 0)}</span></dd>
              <dt>Численность</dt><dd>{num(c.staff_2025)}</dd>
              <dt>Налоговый режим</dt><dd>{c.tax_regime ?? 'общий или нет сведений'}</dd>
            </>) : (<>
              <dt>Доход</dt><dd>не публикуется для ИП</dd>
            </>)}
            {c.branch_count > 0 && <><dt>Филиалы</dt><dd>{c.branch_count}{c.branches?.map((b: any) => <span key={b.kpp} className="sub">{b.address}</span>)}</dd></>}
            {c.reloc_signals && <><dt>Регистрация ≠ место работы</dt><dd>{c.reloc_signals}</dd></>}
            {c.rtk_in_same_building && <><dt>Подключение</dt><dd>в здании уже есть клиент РТК <span className="hint">оценка</span></dd></>}
          </dl>

          <section className="block">
            <h3>Что предложить <span className="hint">рекомендация</span></h3>
            <div className="chips">{(c.products || '').split('; ').map((p: string) => <span key={p} className="chip chip--static">{p}</span>)}</div>
            <p className="meta">{c.products_reason}</p>
          </section>

          <section className="block">
            <h3>Балл {num(c.lead_score)} из 100 <span className="hint">оценка</span></h3>
            {Object.entries(c.score_parts as Record<string, number>).map(([k, v]) => (
              <div className="factor" key={k}><span>{PART_LABELS[k] ?? k}</span><span className="factor__bar"><i style={{ width: `${Math.min(100, (v / 45) * 100)}%` }} /></span><span className="num">{num(v)}</span></div>
            ))}
          </section>

          <section className="block">
            <h3>Источники</h3>
            <ul className="sources">
              {Object.entries(c.provenance as Record<string, string>).map(([k, v]) => <li key={k}><strong>{k}</strong> — {v}</li>)}
              {c.dd_liquidation_date && <li>Дата ликвидации по ЕГРЮЛ: {fmtDate(c.dd_liquidation_date)}</li>}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
