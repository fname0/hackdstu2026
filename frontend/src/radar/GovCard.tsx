import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { money } from '../format';

export const fmtDay = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '-');

/** Карточка учреждения госсектора (bus.gov.ru) — по образцу карточки компании. */
export default function GovCard({ inn, onClose }: { inn: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['gov-institution', inn], queryFn: () => api.govInstitution(inn) });
  const c = q.data;
  return (
    <div className="drawer" role="dialog" aria-label="Карточка учреждения">
      <div className="drawer__head">
        <button className="link-btn" onClick={onClose}>✕ Закрыть</button>
      </div>
      {q.isLoading && <div className="skeleton" style={{ height: 400 }} />}
      {q.isError && <p className="empty">Учреждение не найдено</p>}
      {c && (
        <div className="drawer__body">
          <h2>{c.name_short || c.name}</h2>
          <div className="badges">
            <span className="badge badge--gov">госсектор · {c.segment}</span>
            <span className="badge">{c.level}</span>
            {c.is_liquidating && <span className="badge badge--warn">в ликвидации</span>}
          </div>

          <dl className="facts">
            <dt>Полное название</dt><dd>{c.name}</dd>
            <dt>ИНН</dt><dd>{c.inn}{c.kpp ? ` · КПП ${c.kpp}` : ''}</dd>
            <dt>Тип</dt><dd>{c.inst_type}<span className="sub">{c.okopf}</span></dd>
            <dt>ОКВЭД</dt><dd>{c.okved_main} {c.okved_main_name}</dd>
            <dt>Где</dt><dd>{c.address}<span className="sub">{c.municipality}</span></dd>
            {c.chief && <><dt>Руководитель</dt><dd>{c.chief}<span className="sub">{c.chief_position?.toLowerCase()}</span></dd></>}
            {/* в ГИС ГМУ телефоны бывают списком через «;» или «,» — каждый отдельной ссылкой */}
            {c.phone && <><dt>Телефон</dt><dd>{c.phone.split(/[;,]/).map((t: string) => t.trim()).filter(Boolean).map((t: string, i: number) => (
              <span key={t}>{i > 0 && ', '}<a href={`tel:${t.replace(/[^\d+]/g, '')}`}>{t}</a></span>))}</dd></>}
            {c.www && <><dt>Сайт</dt><dd><a href={c.www.startsWith('http') ? c.www : `http://${c.www}`} target="_blank" rel="noreferrer">{c.www}</a></dd></>}
            {c.founder && <><dt>Учредитель</dt><dd>{c.founder}<span className="sub">через учредителя согласуются закупки и бюджет</span></dd></>}
          </dl>

          <section className="block">
            <h3>Что предложить <span className="hint">рекомендация</span></h3>
            <div className="chips">{c.offer.split(', ').map((p: string) => <span key={p} className="chip chip--static">{p}</span>)}</div>
            <p className="meta">Закупки учреждений идут по 44-ФЗ и 223-ФЗ: сроки и бюджет согласуются с учредителем</p>
          </section>

          <section className="block">
            <h3>Контракты на связь <span className="count">{c.contracts.length}</span></h3>
            {c.contracts.length === 0 && <p className="meta">В выгрузке ЕИС (44-ФЗ, с 2024 года) контрактов на связь нет</p>}
            <ul className="list list--compact">
              {c.contracts.map(k => (
                <li key={k.reestr_number} className="list__row list__row--static">
                  <span className="list__main">
                    <strong>{k.service}</strong>
                    {k.is_rtk ? <span className="badge badge--rtk">Ростелеком</span>
                      : k.supplier_known ? <span className="badge badge--other">{k.operator === 'другой' ? 'конкурент' : k.operator}</span>
                      : <span className="badge">поставщик не загружен</span>}
                    {k.sales_window && <span className="badge badge--spot">кончается скоро</span>}
                    <span className="sub">{k.supplier ?? '-'}</span>
                    <span className="sub">{money(k.price)} · {k.is_active ? 'до' : 'закончился'} {fmtDay(k.finish_date)}</span>
                  </span>
                  <a className="link-btn" href={`https://zakupki.gov.ru/epz/contract/contractCard/common-info.html?reestrNumber=${k.reestr_number}`}
                    target="_blank" rel="noreferrer">ЕИС</a>
                </li>
              ))}
            </ul>
          </section>

          <section className="block">
            <h3>Источник</h3>
            <p className="meta">{c.source}. Запись обновлена {c.change_date ? new Date(c.change_date).toLocaleDateString('ru-RU') : '-'}.
              Сегмент и «что предложить» - оценка команды по ОКВЭД и типу учреждения</p>
          </section>
        </div>
      )}
    </div>
  );
}
