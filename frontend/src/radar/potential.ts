/**
 * Потенциал района в браузере: те же формулы, что в backend/etl/scoring.py, но веса задаёт пользователь,
 * а сырые метрики приходят под текущие фильтры (отрасль, вид субъекта, доход) — /api/radar/zones/metrics.
 *
 *   доход     = суммарный доход юрлиц района за 2025 → место среди районов (0…1)
 *   рост      = изменение суммарного дохода 2025 к 2024 по одним и тем же юрлицам, % → место среди районов
 *   недоохват = 1 − охват района / средний охват (0 клиентов → 1, средний и выше → 0)
 *   потенциал = Σ вес_i × фактор_i, веса нормируются к 100
 */
import type { BaseZoneCollection, ZoneCollection, ZoneFeature, ZoneProps, ZoneStat } from '../api';

export interface Weights { income: number; growth: number; gap: number }
export const DEFAULT_WEIGHTS: Weights = { income: 40, growth: 30, gap: 30 };
export const FACTOR_LABELS: Record<keyof Weights, { label: string; hint: string }> = {
  income: { label: 'Доход', hint: 'суммарный доход юрлиц района за 2025 год' },
  growth: { label: 'Рост доходов', hint: 'изменение суммарного дохода юрлиц 2025 к 2024 (одни и те же компании)' },
  gap: { label: 'Недоохват РТК', hint: 'насколько охват РТК в районе ниже среднего по выборке' },
};
const LOW_COVERAGE = 0.75;

/** Перцентиль 0…1 среди районов; пустые значения — в самом низу. */
function pctRank(values: (number | null)[]) {
  const sorted = values.filter((v): v is number => v != null).sort((a, b) => a - b);
  const n = sorted.length;
  return values.map(v => {
    if (v == null || n === 0) return 0;
    let lo = 0, hi = n;
    while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < v) lo = m + 1; else hi = m; }
    let up = lo; while (up < n && sorted[up] === v) up++;
    return n === 1 ? 1 : ((lo + up - 1) / 2) / (n - 1); // среднее место для одинаковых значений
  });
}

export function computeZones(base: BaseZoneCollection, stats: ZoneStat[], w: Weights): ZoneCollection {
  const byOktmo = new Map(stats.map(s => [s.oktmo, s]));
  const rows = base.features.map(f => {
    const s = byOktmo.get(f.properties.oktmo);
    const companies = s?.companies ?? 0, rtk = s?.rtk_clients ?? 0;
    const growthAbs = s ? s.income_cur - s.income_prev : 0;
    return {
      f, companies, rtk, ul: s?.ul ?? 0, income: s?.income_sum ?? 0, newMonth: s?.new_month ?? 0,
      growthAbs, growthPct: s && s.income_prev > 0 ? (growthAbs / s.income_prev) * 100 : null,
    };
  });

  const totalCompanies = rows.reduce((a, r) => a + r.companies, 0);
  const totalRtk = rows.reduce((a, r) => a + r.rtk, 0);
  const avgShare = totalCompanies ? totalRtk / totalCompanies : 0;
  const rIncome = pctRank(rows.map(r => (r.companies ? r.income : null)));
  const rGrowth = pctRank(rows.map(r => r.growthPct));
  const sumW = w.income + w.growth + w.gap || 1;

  const derived = rows.map((r, i) => {
    const share = r.companies ? r.rtk / r.companies : 0;
    const cov = avgShare > 0 ? share / avgShare : 1;
    const gap = r.companies ? Math.min(1, Math.max(0, 1 - cov)) : 0;
    const f_income = (w.income / sumW) * 100 * rIncome[i];
    const f_growth = (w.growth / sumW) * 100 * rGrowth[i];
    const f_gap = (w.gap / sumW) * 100 * gap;
    return { r, share, cov, f_income, f_growth, f_gap, potential: r.companies ? f_income + f_growth + f_gap : 0 };
  });

  const pots = derived.filter(d => d.r.companies).map(d => d.potential).sort((a, b) => a - b);
  const q66 = pots.length ? pots[Math.floor((pots.length - 1) * (2 / 3))] : Infinity;
  const ranked = [...derived].sort((a, b) => b.potential - a.potential);

  const features: ZoneFeature[] = derived.map(d => {
    const p = d.r.f.properties;
    const lowCoverage = d.r.companies > 0 && (d.cov <= LOW_COVERAGE || d.r.rtk === 0);
    const whiteSpot = lowCoverage && d.potential >= q66;
    const expected = d.r.companies * avgShare;
    const props: ZoneProps = {
      oktmo: p.oktmo, municipality: p.municipality, short: p.short, kind: p.kind,
      companies: d.r.companies, ul: d.r.ul, rtk_clients: d.r.rtk,
      rtk_share_pct: d.share * 100, coverage_vs_region: d.cov, expected_clients: expected,
      income_sum: d.r.income, income_growth_abs: d.r.growthAbs, income_growth_pct: d.r.growthPct,
      new_month: d.r.newMonth, left_month: p.left_month,
      potential: round1(d.potential), potential_rank: ranked.indexOf(d) + 1,
      f_income: round1(d.f_income), f_growth: round1(d.f_growth), f_gap: round1(d.f_gap),
      low_coverage: lowCoverage, white_spot: whiteSpot,
      white_spot_reason: whiteSpot
        ? `клиентов РТК ${d.r.rtk} при ожидаемых ${expected.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} (охват ${Math.round(d.cov * 100)}% от среднего по выборке)`
        : null,
    };
    return { type: 'Feature', geometry: d.r.f.geometry, properties: props };
  });
  return { type: 'FeatureCollection', features };
}

const round1 = (v: number) => Math.round(v * 10) / 10;
