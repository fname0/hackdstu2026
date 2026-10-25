import { num, plural } from '../format';
import type { Estimate, Reference } from './api';
import type { Draft } from './CalcPage';
import { fmtK } from './CalcParams';

const rub = (v: number) => `${num(Math.round(v))} ₽`;

/** Спецификация: прайс МОД3_Таб4 по выбранным системам, количество заполнено типовой комплектацией и правится. */
export default function SpecTable({ d, set, ref_, est, onReset }: {
  d: Draft; set: (p: Partial<Draft>) => void; ref_: Reference; est?: Estimate; onReset: () => void;
}) {
  const groups = [...new Set(ref_.items.map(i => i.group_code))]
    .filter(g => d.systems.includes(g) || ref_.items.some(i => i.group_code === g && (d.qty[i.id] ?? 0) > 0));
  const setQty = (id: string, v: number) => set({ qty: { ...d.qty, [id]: Math.max(0, Math.min(100000, Math.round(v) || 0)) } });
  const setCustom = (i: number, patch: Partial<Draft['custom'][number]>) =>
    set({ custom: d.custom.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const otype = ref_.object_types.find(t => t.code === d.objectType);

  return (
    <div className="panel">
      <div className="block__head">
        <div>
          <h2 className="calc__title">Спецификация</h2>
          <p className="meta">{otype?.label}, {num(d.area)} м² · типовая комплектация, поправьте количество под объект</p>
        </div>
        <button className="rt-btn rt-btn--ghost rt-btn--sm" onClick={onReset}>Вернуть типовую</button>
      </div>

      {groups.length === 0 && <p className="empty">Выберите хотя бы одну инженерную систему слева</p>}
      <div className="spec">
        <div className="spec__row spec__row--head">
          <span>Компонент</span><span className="num">Цена</span><span className="num">Кол-во</span><span className="num">Сумма</span>
        </div>
        {groups.map(g => {
          const items = ref_.items.filter(i => i.group_code === g);
          const sum = items.reduce((s, i) => s + i.price * (d.qty[i.id] ?? 0) * i.complexity, 0);
          return (
            <div key={g} className="spec__group">
              <div className="spec__group-head">
                <span>{items[0].group}</span>
                <span className="sub">сложность ×{fmtK(items[0].complexity)}</span>
                <span className="num">{rub(sum)}</span>
              </div>
              {items.map(i => {
                const q = d.qty[i.id] ?? 0;
                return (
                  <div key={i.id} className={`spec__row ${q ? '' : 'is-zero'}`}>
                    <span className="spec__name">{i.name}</span>
                    <span className="num spec__price">{rub(i.price)}</span>
                    <span className="spec__qty">
                      <button aria-label={`Меньше: ${i.name}`} onClick={() => setQty(i.id, q - 1)} disabled={!q}>−</button>
                      <input type="number" min={0} value={q} aria-label={`Количество: ${i.name}`}
                        onChange={e => setQty(i.id, Number(e.target.value))} />
                      <button aria-label={`Больше: ${i.name}`} onClick={() => setQty(i.id, q + 1)}>+</button>
                    </span>
                    <span className="num">{q ? rub(i.price * q * i.complexity) : '-'}</span>
                  </div>
                );
              })}
            </div>
          );
        })}

        <div className="spec__group">
          <div className="spec__group-head">
            <span>ПО и нестандартное оборудование</span>
            <span className="sub">наценка {Math.round(ref_.custom_markup * 100)}%</span>
            <span className="num">{rub(est?.equipment_custom ?? 0)}</span>
          </div>
          {d.custom.map((c, i) => (
            <div key={i} className="spec__row spec__row--custom">
              <input className="rt-input rt-input--sm" placeholder="Название: ПО SCADA, лицензия, шлюз…" value={c.name}
                onChange={e => setCustom(i, { name: e.target.value })} aria-label="Название позиции" />
              <input className="rt-input rt-input--sm num" type="number" min={0} placeholder="Цена, ₽" value={c.price || ''}
                onChange={e => setCustom(i, { price: Math.max(0, Number(e.target.value) || 0) })} aria-label="Цена за единицу" />
              <input className="rt-input rt-input--sm num" type="number" min={0} value={c.qty || ''}
                onChange={e => setCustom(i, { qty: Math.max(0, Math.round(Number(e.target.value)) || 0) })} aria-label="Количество" />
              <span className="spec__custom-sum">
                <span className="num">{c.price && c.qty ? rub(c.price * c.qty * (1 + ref_.custom_markup)) : '-'}</span>
                <button className="link-btn" onClick={() => set({ custom: d.custom.filter((_, j) => j !== i) })} aria-label="Удалить позицию">✕</button>
              </span>
            </div>
          ))}
          <AddPosition d={d} set={set} ref_={ref_} />
        </div>

        <div className="spec__total">
          <span>Оборудование и ПО <span className="sub">{num(est?.points ?? 0)} {plural(est?.points ?? 0, 'точка', 'точки', 'точек')} учёта и управления</span></span>
          <span className="num">{rub(est?.equipment ?? 0)}</span>
        </div>
      </div>
      <p className="meta">Цены и коэффициенты сложности - прайс организаторов кейса, без НДС</p>
    </div>
  );
}

/** «Добавить позицию»: готовый компонент из прайса (которого ещё нет в спецификации) или своя позиция — ПО, нестандарт. */
function AddPosition({ d, set, ref_ }: { d: Draft; set: (p: Partial<Draft>) => void; ref_: Reference }) {
  const free = ref_.items.filter(i => !(d.qty[i.id] > 0));
  const groups = [...new Set(free.map(i => i.group))];
  const onPick = (v: string) => {
    if (v === 'custom') set({ custom: [...d.custom, { name: '', price: 0, qty: 1 }] });
    else if (v) set({ qty: { ...d.qty, [v]: 1 } });
  };
  return (
    <div className="spec__add">
      <select className="rt-input rt-input--sm" value="" onChange={e => onPick(e.target.value)} aria-label="Добавить позицию">
        <option value="">+ Добавить позицию…</option>
        <option value="custom">Своя позиция: ПО, нестандартное оборудование</option>
        {groups.map(g => (
          <optgroup key={g} label={g}>
            {free.filter(i => i.group === g).map(i => <option key={i.id} value={i.id}>{i.name} - {num(i.price)} ₽</option>)}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
