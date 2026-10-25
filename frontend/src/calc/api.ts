/** Клиент /api/calc — модуль «Калькулятор сделок». Расчёт целиком на сервере (backend/app/services/pricing.py). */

export interface Coef { code: string; label: string; value: number; note: string }
export interface PriceItem { id: string; group: string; group_code: string; name: string; unit: string; price: number; complexity: number }
export interface Option { code: string; label: string; value: number; note?: string; speedup?: number }
export interface ObjectType { code: string; label: string; density: number; systems: string[] }

export interface Reference {
  items: PriceItem[]; regions: Coef[]; levels: Coef[]; stages: Coef[];
  urgency: Option[]; financing: Option[]; object_types: ObjectType[];
  region_default: string; markup: Record<ForkKey, number>; vat: number; custom_markup: number;
  assumptions: string[]; meta: { source: string; built: string } | null;
}

export type ForkKey = 'min' | 'opt' | 'max';
export type Offer = ForkKey | 'custom';

export interface Client { name: string; inn: string; object_name: string; address: string; contact: string; project_id: string }
export interface CustomItem { name: string; price: number; qty: number }

export interface EstimateRequest {
  items: { id: string; qty: number }[];
  custom: CustomItem[];
  region: string; level: string; stages: string[]; urgency: string; financing: string;
  object_type: string; area_m2: number;
  client: Client; offer: Offer; offer_price: number | null;
}

export interface ForkPoint { markup: number; price: number; profit: number; margin: number; price_vat: number }

export interface Estimate {
  lines: (PriceItem & { qty: number; sum: number })[];
  custom: (CustomItem & { sum: number })[];
  points: number;
  equipment_std: number; equipment_custom: number; equipment: number;
  works: { code: string; label: string; pct: number; sum: number }[]; works_total: number; subtotal: number;
  coefficients: { kind: string; label: string; value: number; note: string; source: string }[];
  formula_base: number; cost: number; fork: Record<ForkKey, ForkPoint>; vat: number;
  weeks: number; weeks_std: number;
  levels: { code: string; label: string; value: number; opt: number }[];
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

/** Выгрузки строятся по телу расчёта (POST), поэтому качаем через fetch и сохраняем blob под именем из ответа. */
async function download(path: string, body: unknown) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  const cd = r.headers.get('Content-Disposition') ?? '';
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : path.split('/').pop()!;
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const calcApi = {
  reference: () => get<Reference>('/api/calc/reference'),
  typical: (objectType: string, area: number, systems: string[]) => {
    const p = new URLSearchParams({ object_type: objectType, area_m2: String(area) });
    systems.forEach(s => p.append('systems', s));
    return get<{ id: string; qty: number }[]>(`/api/calc/typical?${p}`);
  },
  estimate: (req: EstimateRequest) => post<Estimate>('/api/calc/estimate', req),
  kp: (req: EstimateRequest) => download('/api/calc/kp', req),
  csv: (req: EstimateRequest) => download('/api/calc/export.csv', req),
  crm: (req: EstimateRequest, format: 'amocrm' | 'bitrix24') => download(`/api/calc/export/crm?format=${format}`, req),
};

/** Отрасль из радара или навигатора → тип объекта калькулятора (по ключевым словам, иначе офис). */
export function objectTypeFor(industry: string | null | undefined): string {
  const s = (industry ?? '').toLowerCase();
  const rules: [string[], string][] = [
    [['здрав', 'медицин'], 'clinic'], [['образов'], 'school'], [['склад', 'логист', 'транспорт', 'опт'], 'warehouse'],
    [['апк', 'сельск'], 'agro'], [['промышл', 'производ', 'тэк', 'энерг', 'добыч'], 'production'],
    [['жиль', 'девелоп', 'жкх'], 'residential'], [['торгов', 'розниц', 'horeca', 'авто', 'бытов', 'общепит'], 'retail'],
  ];
  return rules.find(([keys]) => keys.some(k => s.includes(k)))?.[1] ?? 'office';
}
