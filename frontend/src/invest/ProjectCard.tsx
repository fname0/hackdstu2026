import { useQuery } from '@tanstack/react-query';
import { num } from '../format';
import { investApi, NEED_LABELS, type ProjectCardData } from './api';
import { fmtDateTime, inWindow, launchIn, mln } from './fmt';
import GovCard from '../radar/GovCard';
import { useState } from 'react';

const FACTOR_MAX: Record<string, number> = { 'окно продаж': 50, 'потенциал': 30, 'ключевой проект': 10, 'не наш клиент': 10, 'плановое финансирование': 20, 'контракт на исполнении': 20 };

export default function ProjectCard({ id, onClose, onProject, onCompany }: {
  id: string; onClose: () => void; onProject: (id: string) => void; onCompany: (inn: string) => void;
}) {
  const q = useQuery({ queryKey: ['invest-project', id], queryFn: () => investApi.project(id) });
  const p = q.data;
  return (
    <div className="panel project-card">
      <button className="link-btn" onClick={onClose}>← К списку проектов</button>
      {q.isLoading && <div className="skeleton" style={{ height: 420 }} />}
      {q.isError && <p className="empty">Проект не найден. Вернитесь к списку</p>}
      {p && <Body p={p} onProject={onProject} onCompany={onCompany} />}
    </div>
  );
}

function Body({ p, onProject, onCompany }: { p: ProjectCardData; onProject: (id: string) => void; onCompany: (inn: string) => void }) {
  const hot = inWindow(p.months_to_launch, p.stage);
  const [institutionInn, setInstitutionInn] = useState<string | null>(null);
  const gov = p.source === 'Госпрограммы РО';
  return (<>
    <div className="panel__head">
      <div className="badges">
        <span className={`badge ${hot ? 'badge--other' : ''}`}>{p.stage}</span>
        {p.sector === 'government' && <span className="badge badge--rtk">госсектор</span>}
        {p.client_status === 'наш клиент'
          ? <span className="badge badge--rtk">инициатор - клиент РТК</span>
          : p.initiator_inn && <span className="badge">не клиент РТК</span>}
        {p.is_interregional && <span className="badge">межрегиональный игрок</span>}
        {p.is_key && <span className="badge">ключевой проект</span>}
      </div>
      <h2 className="project-card__title">{p.title}</h2>
      <p className="meta">{p.customer_name || p.beneficiary_name || p.initiator}{p.municipality ? ` · ${p.municipality}` : ''}</p>
    </div>

    <div className="stats stats--3">
      <div className="stat"><div className="stat__value">{mln(p.sum_mln)}</div><div className="stat__label">{gov ? 'сметная стоимость' : 'сумма проекта'}</div></div>
      <div className="stat"><div className={`stat__value ${hot ? 'stat__value--hot' : ''}`}>{gov ? p.finish_year ?? '-' : launchIn(p.months_to_launch, p.stage)}</div><div className="stat__label">{gov ? 'год завершения по плану' : `ввод${p.finish_year ? ` в ${p.finish_year}` : ''}`}</div></div>
      <div className="stat"><div className="stat__value stat__value--accent">{num(p.hot_score)}</div><div className="stat__label">балл из 100</div></div>
    </div>

    <Gantt start={p.start_year} finish={p.finish_year} />
    <p className="meta">{p.sales_window}</p>
    {gov && <section className="block">
      <h3>Объект госпрограммы</h3>
      <p className="meta">{p.stage_basis || 'Плановый срок и финансирование не подтверждают фактическую стадию работ'}</p>
      {p.source_detail?.stage_event && <p className="meta"><a href={p.source_detail.stage_event.url} target="_blank" rel="noreferrer">Сообщение об открытии после ремонта</a></p>}
      {p.source_detail?.coverage && <p className="meta">{p.source_detail.coverage}</p>}
      <dl className="facts">
        <dt>Программа</dt><dd>{p.source_detail?.program}</dd>
        <dt>Вид работ</dt><dd>{p.work_type || '-'}</dd>
        <dt>Документ</dt><dd>{fmtDateTime(p.document_date)}</dd>
        <dt>Заказчик</dt><dd>{p.customer_name || 'Не подтверждён'}
          {p.customer_inn && <span className="sub">ИНН {p.customer_inn} - из контракта ЕИС</span>}</dd>
        <dt>Получатель</dt><dd>{p.beneficiary_name || 'Учреждение уточняется'}
          {p.beneficiary_inn && <span className="sub">ИНН {p.beneficiary_inn} - получатель, не подтверждённый заказчик</span>}</dd>
        <dt>Локация</dt><dd>{p.location_precision}</dd>
      </dl>
      {p.source_detail?.sum_conflict && <p className="meta">В документе несколько строк объекта с разными сметами - сумма требует проверки</p>}
      {p.customer_institution_available && p.customer_inn && <button className="rt-btn rt-btn--outline rt-btn--sm" onClick={() => setInstitutionInn(p.customer_inn!)}>Карточка заказчика</button>}
      {p.beneficiary_inn && p.beneficiary_inn !== (p.customer_institution_available ? p.customer_inn : null) && <button className="rt-btn rt-btn--outline rt-btn--sm" onClick={() => setInstitutionInn(p.beneficiary_inn!)}>Карточка учреждения</button>}
    </section>}

    {gov && p.contract_number && <section className="block">
      <h3>Контракт ЕИС</h3>
      <dl className="facts">
        <dt>Номер</dt><dd>{p.contract_number}</dd>
        <dt>Статус</dt><dd>{p.contract_status}</dd>
        <dt>Заключён</dt><dd>{fmtDateTime(p.contract_signed)}</dd>
        <dt>Срок контракта</dt><dd>{fmtDateTime(p.contract_finish)}</dd>
        {p.contract_work_address && <><dt>Место работ</dt><dd>{p.contract_work_address}</dd></>}
        <dt>Цена контракта</dt><dd>{mln(p.contract_amount_rub == null ? null : p.contract_amount_rub / 1e6)}<span className="sub">Отдельно от сметы всего проекта</span></dd>
        <dt>Подрядчик</dt><dd>{p.contractor_name || 'Уточняется'}{p.contractor_inn && <span className="sub">ИНН {p.contractor_inn}</span>}</dd>
        <dt>Проверено</dt><dd>{fmtDateTime(p.stage_checked_at)}</dd>
      </dl>
      {p.stage_evidence_url && <a className="rt-btn rt-btn--ghost rt-btn--sm" href={p.stage_evidence_url} target="_blank" rel="noreferrer">Открыть контракт в ЕИС</a>}
    </section>}

    <section className="block">
      <h3>Что предложить</h3>
      {p.needs_detail.length === 0 && <p className="meta">В названии проекта нет признаков потребностей - уточните у инициатора</p>}
      <ul className="needs">
        {p.needs_detail.map(n => (
          <li key={n.need} className="need">
            <span className="tag tag--need">{NEED_LABELS[n.need]}</span>
            <span><strong>{n.offer}</strong></span>
          </li>
        ))}
      </ul>
    </section>

    <div className="actions">
      <a className="rt-btn rt-btn--primary" href={`#calc?project=${encodeURIComponent(p.project_id)}`}>Рассчитать КП</a>
      {p.company && <button className="rt-btn rt-btn--outline" onClick={() => onCompany(p.company!.inn)}>Компания в радаре</button>}
      {p.url && <a className="rt-btn rt-btn--ghost" href={p.url} target="_blank" rel="noreferrer">Открыть источник</a>}
    </div>

    <section className="block">
      <h3>Почему балл {num(p.hot_score)} <span className="hint">оценка</span></h3>
      {Object.entries(p.hot_factors).map(([k, v]) => (
        <div className="factor" key={k}>
          <span>{k}</span>
          <span className="factor__bar"><i style={{ width: `${(v / (FACTOR_MAX[k] ?? 50)) * 100}%` }} /></span>
          <span className="num">{num(v)} из {FACTOR_MAX[k] ?? '-'}</span>
        </div>
      ))}
    </section>

    <section className="block">
      <h3>Проект</h3>
      <dl className="facts">
        <dt>Инициатор</dt>
        <dd>{p.initiators || p.initiator}
          <span className="sub">{p.initiator_inn ? `ИНН ${p.initiator_inn}` : 'ИНН не найден'}</span></dd>
        <dt>Отрасль</dt><dd>{p.industry}</dd>
        <dt>Сроки</dt><dd>{p.start_year ?? '-'} → {p.finish_year ?? '-'}</dd>
        {p.site_status && <><dt>Статус на портале</dt><dd>{p.site_status}</dd></>}
        <dt>Рабочих мест</dt><dd>{num(p.jobs)}</dd>
        <dt>Куратор</dt><dd>{p.curator || '-'}</dd>
        <dt>Где</dt><dd>{p.municipality ?? '-'}</dd>
        <dt>Источник</dt><dd>{p.source}{p.modify_date && <span className="sub">запись обновлена {fmtDateTime(p.modify_date)}</span>}
          {p.organizers_no && <span className="sub">строка {p.organizers_no} в файле организаторов</span>}</dd>
      </dl>
    </section>

    {p.initiator_other_projects.length > 0 && (
      <section className="block">
        <h3>Другие проекты {p.customer_inn ? 'заказчика' : 'инициатора'} <span className="count">{p.initiator_other_projects.length}</span></h3>
        <ul className="list list--compact">
          {p.initiator_other_projects.map(o => (
            <li key={o.project_id}>
              <button className="list__row" onClick={() => onProject(o.project_id)}>
                <span className="list__main"><span className="clamp2">{o.title}</span>
                  <span className="sub">{o.stage} · {mln(o.sum_mln)}</span></span>
                <span className="score">{num(o.hot_score)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    )}
    {institutionInn && <GovCard inn={institutionInn} onClose={() => setInstitutionInn(null)} />}
  </>);
}

/** Мини-Гант: полоса «начало → ввод», отметка «сегодня» и окно продаж (6–18 мес. до ввода). */
function Gantt({ start, finish }: { start: number | null; finish: number | null }) {
  if (!finish) return null;
  const now = new Date();
  const t = now.getFullYear() + now.getMonth() / 12;
  const s = start ?? finish;
  const end = finish + 1; // ввод - конец года
  const lo = Math.min(s, Math.floor(t)) - 0.25, hi = Math.max(end, t) + 0.25;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const w = (a: number, b: number) => `${((b - a) / (hi - lo)) * 100}%`;
  return (
    <div className="gantt" aria-label={`Начало ${s}, ввод ${finish}`}>
      {/* «сегодня» — над полосой, годы — под ней: при близких датах подписи не наезжают друг на друга */}
      <div className="gantt__scale gantt__scale--top"><span style={{ left: x(t) }} className="gantt__now-label">сегодня</span></div>
      <div className="gantt__track">
        <span className="gantt__bar" style={{ left: x(s), width: w(s, end) }} />
        <span className="gantt__window" style={{ left: x(end - 1.5), width: w(end - 1.5, end - 0.5) }} title="окно продаж: год перед вводом" />
        <span className="gantt__now" style={{ left: x(t) }} />
      </div>
      <div className="gantt__scale">
        <span style={{ left: x(s) }}>{s}</span>
        <span style={{ left: x(end) }}>ввод {finish}</span>
      </div>
    </div>
  );
}
