import { DEFAULT_WEIGHTS, FACTOR_LABELS, type Weights } from './potential';

const KEYS = Object.keys(FACTOR_LABELS) as (keyof Weights)[];

export default function WeightsPanel({ w, set }: { w: Weights; set: (w: Weights) => void }) {
  const sum = KEYS.reduce((a, k) => a + w[k], 0) || 1;
  const isDefault = KEYS.every(k => w[k] === DEFAULT_WEIGHTS[k]);
  return (
    <section className="weights" aria-label="Что важнее для потенциала">
      <div className="weights__head">
        <h3>Что важнее для потенциала</h3>
        {!isDefault && <button className="link-btn" onClick={() => set(DEFAULT_WEIGHTS)}>по умолчанию</button>}
      </div>
      {KEYS.map(k => (
        <label key={k} className="weight" title={FACTOR_LABELS[k].hint}>
          <span className="weight__label">{FACTOR_LABELS[k].label}</span>
          <input type="range" min={0} max={100} step={5} value={w[k]}
            onChange={e => set({ ...w, [k]: Number(e.target.value) })}
            aria-label={`Вес: ${FACTOR_LABELS[k].label}`} />
          <span className="weight__value num">{Math.round((w[k] / sum) * 100)}%</span>
        </label>
      ))}
      <p className="meta">Доли нормируются к 100%. Потенциал = Σ доля × место района по фактору.</p>
    </section>
  );
}
