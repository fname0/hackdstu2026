import type { Reference } from './api';
import type { Draft } from './CalcPage';

const GROUPS: [string, string][] = [
  ['el', 'Электроснабжение'], ['ht', 'Отопление'], ['ws', 'Водоснабжение'], ['wo', 'Водоотведение'],
  ['vn', 'Вентиляция'], ['kd', 'Кондиционирование'], ['gs', 'Газоснабжение'],
];

/** Левая панель: объект, решение, условия сделки и клиент. Всё, кроме клиента, влияет на цену. */
export default function CalcParams({ d, set, ref_, onToggleSystem }: {
  d: Draft; set: (p: Partial<Draft>) => void; ref_: Reference; onToggleSystem: (code: string) => void;
}) {
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter(x => x !== v) : [...list, v]);
  const onType = (code: string) => set({ objectType: code, systems: ref_.object_types.find(t => t.code === code)!.systems });

  return (
    <aside className="filters calc__params" aria-label="Параметры расчёта">
      {d.from && (
        <div className="calc-from">
          <span className="sub">{d.from.kind === 'project' ? 'Из инвестпроекта' : 'Из радара'}</span>
          <span className="clamp2" title={d.from.title}>{d.from.title}</span>
          <a className="link-btn" href={d.from.kind === 'project' ? '#invest' : '#radar'}>← Вернуться</a>
        </div>
      )}

      <div className="field">
        <span className="field__label">Тип объекта</span>
        <select className="rt-input" value={d.objectType} onChange={e => onType(e.target.value)}>
          {ref_.object_types.map(t => <option key={t.code} value={t.code}>{t.label}</option>)}
        </select>
      </div>
      <label className="field">
        <span className="field__label">Площадь, м²</span>
        <input className="rt-input" type="number" min={50} step={100} value={d.area || ''}
          onChange={e => set({ area: Math.max(0, Number(e.target.value) || 0) })} />
      </label>
      <div className="field">
        <span className="field__label">Инженерные системы <em>- включите, и их компоненты появятся в спецификации</em></span>
        <div className="chips">
          {GROUPS.map(([code, label]) => (
            <button key={code} className={`chip ${d.systems.includes(code) ? 'is-active' : ''}`} aria-pressed={d.systems.includes(code)}
              onClick={() => onToggleSystem(code)}>{label}</button>
          ))}
        </div>
      </div>

      <div className="field">
        <span className="field__label">Уровень решения</span>
        <div className="segmented">
          {ref_.levels.map(l => (
            <button key={l.code} className={d.level === l.code ? 'is-active' : ''} title={l.note}
              onClick={() => set({ level: l.code })}>{l.label}</button>
          ))}
        </div>
        <span className="meta">{ref_.levels.find(l => l.code === d.level)?.note}</span>
      </div>

      <div className="field">
        <span className="field__label">Виды работ <em>- % от стоимости оборудования</em></span>
        {ref_.stages.map(s => (
          <label key={s.code} className="check">
            <input type="checkbox" checked={d.stages.includes(s.code)} onChange={() => set({ stages: toggle(d.stages, s.code) })} />
            <span>{s.label} - {Math.round(s.value * 100)}%<span className="sub">{s.note}</span></span>
          </label>
        ))}
      </div>

      <div className="field">
        <span className="field__label">Срок</span>
        <select className="rt-input" value={d.urgency} onChange={e => set({ urgency: e.target.value })}>
          {ref_.urgency.map(u => <option key={u.code} value={u.code}>{u.label} · ×{fmtK(u.value)}</option>)}
        </select>
      </div>
      <div className="field">
        <span className="field__label">Схема оплаты</span>
        <select className="rt-input" value={d.financing} onChange={e => set({ financing: e.target.value })}>
          {ref_.financing.map(f => <option key={f.code} value={f.code}>{f.label} · ×{fmtK(f.value)}</option>)}
        </select>
      </div>
      <div className="field">
        <span className="field__label">Регион работ</span>
        <select className="rt-input" value={d.region} onChange={e => set({ region: e.target.value })}>
          {ref_.regions.map(r => <option key={r.code} value={r.code}>{r.label} · ×{fmtK(r.value)}</option>)}
        </select>
      </div>

      <div className="field calc-client">
        <span className="field__label">Клиент - для КП и CRM, на цену не влияет</span>
        <input className="rt-input" placeholder="Название компании" value={d.client.name}
          onChange={e => set({ client: { ...d.client, name: e.target.value } })} />
        <input className="rt-input" placeholder="ИНН" inputMode="numeric" value={d.client.inn}
          onChange={e => set({ client: { ...d.client, inn: e.target.value.replace(/\D/g, '').slice(0, 12) } })} />
        <input className="rt-input" placeholder="Объект (например, БЦ «Гранд»)" value={d.client.object_name}
          onChange={e => set({ client: { ...d.client, object_name: e.target.value } })} />
        <input className="rt-input" placeholder="Адрес объекта" value={d.client.address}
          onChange={e => set({ client: { ...d.client, address: e.target.value } })} />
        <input className="rt-input" placeholder="Контактное лицо" value={d.client.contact}
          onChange={e => set({ client: { ...d.client, contact: e.target.value } })} />
      </div>
    </aside>
  );
}

export const fmtK = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
