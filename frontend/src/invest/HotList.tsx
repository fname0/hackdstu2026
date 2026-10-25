import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { num, plural } from '../format';
import { investApi, NEED_LABELS, type InvestFilters, type ProjectRow } from './api';
import { inWindow, launchIn, mln } from './fmt';

const SORTS = [
  { v: 'hot', label: 'Горячие' }, { v: 'launch', label: 'Скоро ввод' }, { v: 'sum', label: 'Крупные' }, { v: 'recent', label: 'Новые' },
];
const PAGE = 30;

/** Правая панель: все проекты под фильтрами, по умолчанию — по баллу горячести. */
export default function HotList({ filters, onProject }: { filters: InvestFilters; onProject: (id: string) => void }) {
  const [sort, setSort] = useState('hot');
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [filters, sort]);

  const page = useQuery({
    queryKey: ['invest-projects', filters, sort, offset], queryFn: () => investApi.projects(filters, sort, offset),
    placeholderData: keepPreviousData,
  });
  const data = page.data;

  return (
    <div className="panel">
      <section className="block">
        <h2>Все проекты {data && <span className="count">{num(data.total)}</span>}</h2>
        <div className="segmented" style={{ marginTop: 12 }}>
          {SORTS.map(s => <button key={s.v} className={sort === s.v ? 'is-active' : ''} onClick={() => setSort(s.v)}>{s.label}</button>)}
        </div>

        {!data && <div className="skeleton" style={{ height: 320, marginTop: 12 }} />}
        {data && data.total === 0 && <p className="empty">Нет проектов по фильтрам. Снимите часть фильтров слева</p>}
        <ul className="list">
          {data?.items.map(p => <Row key={p.project_id} p={p} onProject={onProject} />)}
        </ul>
        {data && data.total > PAGE && (
          <div className="pager">
            <button className="link-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Назад</button>
            <span>{num(offset + 1)}-{num(Math.min(offset + PAGE, data.total))} из {num(data.total)}</span>
            <button className="link-btn" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Дальше →</button>
          </div>
        )}
      </section>

      <section className="block">
        <h3>Выгрузить {data ? `${num(data.total)} ${plural(data.total, 'проект', 'проекта', 'проектов')}` : ''}</h3>
        <div className="export">
          <a className="rt-btn rt-btn--primary rt-btn--sm" href={investApi.exportCsvUrl(filters)}>Выгрузить CSV</a>
          <a className="rt-btn rt-btn--outline rt-btn--sm" href={investApi.exportCrmUrl(filters, 'amocrm')}>amoCRM</a>
          <a className="rt-btn rt-btn--outline rt-btn--sm" href={investApi.exportCrmUrl(filters, 'bitrix24')}>Bitrix24</a>
        </div>
        <p className="meta">В CRM проекты уходят сделками: бюджет - потенциал для РТК (оценка), в примечании - потребности,
          что предложить и окно продаж</p>
      </section>
    </div>
  );
}

function Row({ p, onProject }: { p: ProjectRow; onProject: (id: string) => void }) {
  const probable = p.match_method?.includes('вероятное');
  return (
    <li>
      <button className="list__row project-row" onClick={() => onProject(p.project_id)}>
        <span className="list__main">
          <span className="clamp2" title={p.title}>{p.title}</span>
          <span className="sub">{p.customer_name || p.initiator}{p.municipality ? ` · ${p.municipality}` : ''}</span>
          <span className="project-row__meta">
            <span className={inWindow(p.months_to_launch, p.stage) ? 'tag tag--hot' : 'tag'}>{launchIn(p.months_to_launch, p.stage)}</span>
            <span className="num">{mln(p.sum_mln)}</span>
            {p.needs.map(n => <span key={n} className="tag tag--need">{NEED_LABELS[n]}</span>)}
            {p.is_interregional && <span className="tag">межрегиональный</span>}
            {p.sector === 'government' && <span className="tag">госсектор</span>}
            {p.work_type && <span className="tag">{p.work_type}</span>}
            {p.client_status === 'наш клиент' && <span className="tag tag--need">клиент РТК</span>}
            {!p.initiator_inn && !p.customer_inn && <span className="tag" title="контакт - через куратора проекта, обычно администрацию района">ИНН не найден</span>}
            {probable && <span className="tag" title={p.match_method}>ИНН вероятный</span>}
          </span>
        </span>
        <span className="score" title="балл горячести">{num(p.hot_score)}</span>
      </button>
    </li>
  );
}
