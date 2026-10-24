export type Client = 'all' | 'rtk' | 'other';

export interface Filters {
  client: Client;
  kind: string[];
  industry: string[];
  oktmo: string[];
  incomeMin: string;
  incomeMax: string;
  growthMin: string;
  includeNoIncome: boolean;
  q: string;
}

export const emptyFilters: Filters = {
  client: 'all', kind: [], industry: [], oktmo: [], incomeMin: '', incomeMax: '', growthMin: '',
  includeNoIncome: true, q: '',
};

export interface Summary {
  companies: number; ul: number; ip: number; kfh: number; rtk_clients: number; rtk_share_pct: number;
  new_month: number; left_month: number; with_income: number; with_point: number; income_sum: number;
  white_spots: number; zones: number; msp_release: string; msp_prev_release: string;
  clients_status: { msp_status: string; churn_type: string | null; n: number }[];
}

export interface ZoneProps {
  oktmo: string; municipality: string; short: string; kind: string;
  companies: number; ul: number; rtk_clients: number; rtk_share_pct: number; coverage_vs_region: number;
  expected_clients: number; income_sum: number; income_growth_abs: number; income_growth_pct: number | null;
  new_month: number; left_month: number;
  potential: number; potential_rank: number; f_income: number; f_growth: number; f_gap: number;
  low_coverage: boolean; white_spot: boolean; white_spot_reason: string | null;
}

export interface ZoneFeature { type: 'Feature'; geometry: GeoJSON.Geometry; properties: ZoneProps }
export interface ZoneCollection { type: 'FeatureCollection'; features: ZoneFeature[] }

export interface BaseZoneCollection { type: 'FeatureCollection'; features: { type: 'Feature'; geometry: GeoJSON.Geometry; properties: Record<string, any> }[] }

export interface ZoneStat {
  oktmo: string; companies: number; ul: number; rtk_clients: number;
  income_sum: number; income_cur: number; income_prev: number; new_month: number;
}

export interface CompanyRow {
  inn: string; name_short: string; kind: string; category: string; industry: string; okved_main: string | null;
  municipality: string | null; place: string | null; is_rtk_client: boolean;
  income_2025: number | null; income_growth_pct: number | null; staff_2025: number | null; msp_years: number | null;
  lead_score: number; products: string; dd_status: string | null; reloc_signals: string | null;
  location_precision: string | null; flag_zero_income: boolean; flag_check_category: boolean;
  rtk_in_same_building: boolean | null; geo_lat: number | null; geo_lon: number | null;
}

export interface Point { inn: string; name_short: string; kind: string; industry: string; is_rtk_client: boolean;
  lead_score: number; income_2025: number | null; lat: number; lon: number; geo_precision: string }

export interface ChurnRow { inn: string; name: string; kind: string; municipality: string | null;
  churn_type: string | null; churn_risk: string | null; dd_status: string | null; dd_liquidation_date: string | null }

export function toParams(f: Filters, extra: Record<string, string | number | undefined> = {}) {
  const p = new URLSearchParams();
  p.set('client', f.client);
  f.kind.forEach(v => p.append('kind', v));
  f.industry.forEach(v => p.append('industry', v));
  f.oktmo.forEach(v => p.append('oktmo', v));
  if (f.incomeMin) p.set('income_min', f.incomeMin);
  if (f.incomeMax) p.set('income_max', f.incomeMax);
  if (f.growthMin) p.set('growth_min', f.growthMin);
  p.set('include_no_income', String(f.includeNoIncome));
  if (f.q.trim()) p.set('q', f.q.trim());
  Object.entries(extra).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)));
  return p;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export const api = {
  summary: () => get<Summary>('/api/radar/summary'),
  zones: () => get<BaseZoneCollection>('/api/radar/zones'),
  industries: () => get<{ industry: string; n: number; rtk: number }[]>('/api/radar/industries'),
  churn: () => get<{ left: ChurnRow[]; risk: ChurnRow[] }>('/api/radar/churn'),

  zoneMetrics: (f: Filters) => {
    const p = toParams({ ...f, client: 'all', oktmo: [], q: '' });
    p.delete('client');
    return get<ZoneStat[]>(`/api/radar/zones/metrics?${p}`);
  },
  companies: (f: Filters, sort: string, offset: number) =>
    get<{ total: number; items: CompanyRow[] }>(`/api/radar/companies?${toParams(f, { sort, limit: 50, offset })}`),
  points: (f: Filters) => get<Point[]>(`/api/radar/points?${toParams(f, { limit: 5000 })}`),
  company: (inn: string) => get<Record<string, any>>(`/api/radar/companies/${inn}`),
  exportCsvUrl: (f: Filters) => `/api/radar/export.csv?${toParams(f)}`,
  exportCrmUrl: (f: Filters, format: 'amocrm' | 'bitrix24') => `/api/radar/export/crm?${toParams(f, { format })}`,
};
