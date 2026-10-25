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

/** Район для карты и панелей: метрики пересчитаны под фильтры, потенциал — по весам пользователя (radar/potential.ts). */
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
/** Границы и базовые поля района из базы (/api/radar/zones) — основа для пересчёта. */
export interface BaseZoneCollection { type: 'FeatureCollection'; features: { type: 'Feature'; geometry: GeoJSON.Geometry; properties: Record<string, any> }[] }

/** Сырые метрики района под фильтры — /api/radar/zones/metrics. */
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

/** Госсектор: учреждения с bus.gov.ru (слой радара). */
export interface GovSummary {
  available: boolean; institutions?: number; liquidating?: number; with_point?: number;
  by_segment?: { key: string; n: number }[]; by_level?: { key: string; n: number }[];
  complete?: boolean; built_at?: string; source?: string;
  contracts?: { contracts: number; with_supplier: number; customers: number; rtk_share_by_count_pct: number; rtk_share_by_sum_pct: number;
    sales_window: number; sales_window_sum_rub: number; by_operator: Record<string, number> } | null;
}
/** Контракт госсектора на связь (ЕИС, 44-ФЗ). */
export interface GovContract {
  reestr_number: string; customer_inn: string; customer: string; subject: string; service: string; price: number | null;
  signed_date?: string | null; finish_date: string | null; is_active?: boolean; months_left: number | null;
  supplier: string | null; supplier_inn?: string | null; operator: string | null; is_rtk?: boolean; supplier_known?: boolean;
  sales_window?: boolean; segment?: string | null; municipality?: string | null; has_card?: boolean;
}
export interface GovPoint { inn: string; name_short: string; segment: string; level: string; lat: number; lon: number;
  /** есть действующий контракт на связь с Ростелекомом (ЕИС) */
  is_rtk_client: boolean }
export interface GovRow {
  inn: string; name_short: string | null; name: string; segment: string; level: string; inst_type: string;
  municipality: string | null; oktmo: string | null; place: string | null; address: string; lat: number | null; lon: number | null;
  phone: string | null; www: string | null; chief: string | null; chief_position: string | null; founder: string | null;
  offer: string; is_liquidating: boolean;
}

function segParams(segment: string[]) {
  const p = new URLSearchParams();
  segment.forEach(s => p.append('segment', s));
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
  // клиентский фильтр, поиск, район и область карты на метрики районов не влияют — охват считается по всем компаниям
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
  govSummary: () => get<GovSummary>('/api/gov/summary'),
  govPoints: (segment: string[]) => get<GovPoint[]>(`/api/gov/points?${segParams(segment)}`),
  govZone: (oktmo: string, segment: string[]) =>
    get<{ by_segment: { key: string; n: number }[]; total: number; items: GovRow[];
      telecom: { contracts: number; rtk: number; sales_window: number } | null }>(`/api/gov/zone/${oktmo}?${segParams(segment)}`),
  govExpiring: (months = 6) => get<{ total: number; sum: number; items: GovContract[] }>(`/api/gov/expiring?months=${months}&limit=30`),
  govInstitution: (inn: string) => get<GovRow & Record<string, any> & { contracts: GovContract[] }>(`/api/gov/institutions/${inn}`),
  govExportCsvUrl: (segment: string[], oktmo?: string) => {
    const p = segParams(segment);
    if (oktmo) p.append('oktmo', oktmo);
    return `/api/gov/export.csv?${p}`;
  },
};
