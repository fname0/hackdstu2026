/** Клиент /api/invest — модуль «Инвестиционный навигатор». */

export type Need = 'it' | 'asutp' | 'security';
export type Client = 'all' | 'rtk' | 'other';

export const NEED_LABELS: Record<Need, string> = { it: 'ИТ', asutp: 'АСУ ТП', security: 'Безопасность' };
export const NEED_FULL: Record<Need, string> = { it: 'ИТ-инфраструктура', asutp: 'АСУ ТП и диспетчеризация', security: 'Безопасность' };

/** «Звонить сейчас» — окно продаж + ИНН найден + не клиент РТК; via_admin — окно продаж без ИНН; any — все проекты. */
export type Contact = 'any' | 'callable' | 'via_admin';

export interface InvestFilters {
  q: string;
  stage: string[];
  industry: string[];
  need: Need[];
  oktmo: string[];
  client: Client;
  sector: 'all' | 'government' | 'private';
  interregional: boolean;
  keyOnly: boolean;
  hasInn: boolean;
  window: boolean;
  active: boolean;
  sumMin: string;
  sumMax: string;
  finishFrom?: number;
  finishTo?: number;
}

export const emptyInvestFilters: InvestFilters = {
  q: '', stage: [], industry: [], need: [], oktmo: [], client: 'all', sector: 'all', interregional: false, keyOnly: false, hasInn: false,
  window: false, active: true, sumMin: '', sumMax: '',
};

export interface ProjectRow {
  project_id: string; title: string; initiator: string; initiator_inn: string | null; client_status: string;
  is_interregional: boolean; is_key: boolean; municipality: string | null; oktmo: string | null;
  stage: string; site_status: string | null; start_year: number | null; finish_year: number | null;
  months_to_launch: number | null; sales_window: string; sum_mln: number | null; jobs: number | null;
  industry: string; needs: Need[]; rtk_potential_mln: number | null; hot_score: number;
  lat: number | null; lon: number | null; location_precision: string; source: string;
  in_organizers_sample: boolean; url: string | null; curator: string | null; match_method: string;
  sector: 'government' | 'private'; beneficiary_inn: string | null; beneficiary_name: string | null;
  work_type: string | null; document_date: string | null;
  customer_name?: string | null; customer_inn?: string | null;
  contract_number?: string | null; contract_status?: string | null;
}

export interface NeedDetail { need: Need; label: string; offer: string; quote: string }

export interface ProjectCardData extends ProjectRow {
  curator: string | null; initiators: string; initiator_matched_name: string | null; match_score: number | null;
  match_method: string; industry_reason: string | null; needs_detail: NeedDetail[]; it_share: number;
  hot_factors: Record<string, number>; duration_years: number | null; address_from_text: string | null;
  organizers_no: string | null; create_date: string | null; modify_date: string | null;
  company: { inn: string; name_short: string; is_rtk_client: boolean; lead_score: number; industry: string } | null;
  initiator_other_projects: ProjectRow[];
  provenance: Record<string, string>;
  program_executor?: string | null;
  source_detail?: { program: string; coverage: string; sum_conflict: boolean; location_note: string;
    stage_event?: { date: string; title: string; url: string; publisher: string } } | null;
  contract_signed?: string | null; contract_finish?: string | null; contract_amount_rub?: number | null;
  contractor_name?: string | null; contractor_inn?: string | null;
  stage_basis?: string | null; stage_evidence_url?: string | null; stage_checked_at?: string | null;
  customer_institution_available?: boolean;
  contract_work_address?: string | null;
}

export interface InvestSummary {
  projects: number; active: number; active_sum_mln: number; active_potential_mln: number;
  in_window: number; in_window_sum_mln: number; interregional_active: number; interregional: number;
  rtk_clients: number; with_inn: number; organizers_sample: number; active_initiators: number;
  by_need: { key: Need; n: number; potential_mln: number; label: string }[];
  list_requested_at: string | null; built_at: string | null; sources: string;
}

export interface InvestStats {
  projects: number; sum_mln: number | null; in_window: number; in_window_sum_mln: number | null;
  interregional: number; potential_mln: number | null; rtk_clients: number; with_inn: number;
  callable: number; via_admin: number; government: number;
}

export interface Facet { key: string; label?: string; n: number; active: number }
export interface Facets { stage: Facet[]; status: Facet[]; industry: Facet[]; municipality: Facet[]; sector: Facet[] }

export interface ProjectPoint {
  project_id: string; lat: number; lon: number; stage: string; sum_mln: number | null; hot_score: number;
  industry: string; title: string; initiator: string; location_precision: string; months_to_launch?: number | null;
}

export type GanttSort = 'hot' | 'launch' | 'start' | 'sum';

export interface GanttRow {
  project_id: string; title: string; initiator: string; municipality: string | null;
  start_year: number | null; finish_year: number; stage: string; months_to_launch: number | null;
  sum_mln: number | null; hot_score: number; is_interregional: boolean; client_status: string;
}

export interface Timeline {
  years: { year: number; n: number; sum_mln: number | null; in_window: number }[];
  gantt: GanttRow[];
  gantt_total: number;
}

export function toInvestParams(f: InvestFilters, extra: Record<string, string | number | undefined> = {}) {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set('q', f.q.trim());
  f.stage.forEach(v => p.append('stage', v));
  f.industry.forEach(v => p.append('industry', v));
  f.need.forEach(v => p.append('need', v));
  f.oktmo.forEach(v => p.append('oktmo', v));
  if (f.client !== 'all') p.set('client', f.client);
  if (f.sector !== 'all') p.set('sector', f.sector);
  if (f.interregional) p.set('interregional', 'true');
  if (f.keyOnly) p.set('key_only', 'true');
  if (f.hasInn) p.set('has_inn', 'true');
  if (f.window) p.set('window', 'true');
  p.set('active', String(f.active));
  if (f.sumMin) p.set('sum_min', f.sumMin);
  if (f.sumMax) p.set('sum_max', f.sumMax);
  if (f.finishFrom != null) p.set('finish_from', String(f.finishFrom));
  if (f.finishTo != null) p.set('finish_to', String(f.finishTo));
  Object.entries(extra).forEach(([k, v]) => v !== undefined && v !== '' && p.set(k, String(v)));
  return p;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export const investApi = {
  summary: () => get<InvestSummary>('/api/invest/summary'),
  facets: () => get<Facets>('/api/invest/facets'),
  stats: (f: InvestFilters) => get<InvestStats>(`/api/invest/stats?${toInvestParams(f)}`),
  projects: (f: InvestFilters, sort: string, offset: number, contact: Contact = 'any') =>
    get<{ total: number; sum_mln: number | null; items: ProjectRow[] }>(`/api/invest/projects?${toInvestParams(f, { sort, limit: 30, offset, contact })}`),
  points: (f: InvestFilters) => get<ProjectPoint[]>(`/api/invest/points?${toInvestParams(f)}`),
  timeline: (f: InvestFilters, sort: GanttSort) =>
    get<Timeline>(`/api/invest/timeline?${toInvestParams(f, { gantt_limit: 60, gantt_sort: sort })}`),
  project: (id: string) => get<ProjectCardData>(`/api/invest/projects/${encodeURIComponent(id)}`),
  exportCsvUrl: (f: InvestFilters, contact: Contact = 'any') => `/api/invest/export.csv?${toInvestParams(f, { contact })}`,
  exportCrmUrl: (f: InvestFilters, format: 'amocrm' | 'bitrix24', contact: Contact = 'any') =>
    `/api/invest/export/crm?${toInvestParams(f, { format, contact })}`,
};
