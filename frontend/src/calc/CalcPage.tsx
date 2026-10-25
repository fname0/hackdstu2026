import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { investApi } from '../invest/api';
import { calcApi, objectTypeFor, type Client, type CustomItem, type EstimateRequest, type Offer } from './api';
import CalcParams from './CalcParams';
import CalcSummary from './CalcSummary';
import SpecTable from './SpecTable';

export interface Draft {
  objectType: string; area: number; systems: string[];
  level: string; region: string; urgency: string; financing: string; stages: string[];
  qty: Record<string, number>; custom: CustomItem[];
  client: Client; offer: Offer; offerPrice: number | null;
  /** откуда пришли: из карточки инвестпроекта или компании радара — для ссылки «назад» */
  from: { kind: 'project' | 'company'; id: string; title: string } | null;
}

const emptyClient: Client = { name: '', inn: '', object_name: '', address: '', contact: '', project_id: '' };
const DRAFT_KEY = 'calc.draft.v1';
const ALL_GROUPS = ['el', 'ht', 'ws', 'wo', 'vn', 'kd', 'gs'];

function readDraft(): Partial<Draft> {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}'); } catch { return {}; }
}

/** Параметры в hash: #calc?project=<id> или #calc?inn=<ИНН> — переход из навигатора и радара. */
function hashParams() {
  const h = window.location.hash;
  return new URLSearchParams(h.includes('?') ? h.slice(h.indexOf('?') + 1) : '');
}

export default function CalcPage() {
  const ref = useQuery({ queryKey: ['calc-reference'], queryFn: calcApi.reference, staleTime: Infinity });
  const [d, setD] = useState<Draft | null>(null);
  const set = (patch: Partial<Draft>) => setD(cur => (cur ? { ...cur, ...patch } : cur));

  // Черновик: из localStorage (удобство, не данные) поверх значений по умолчанию из справочника
  useEffect(() => {
    if (!ref.data || d) return;
    const r = ref.data, saved = readDraft();
    const type = r.object_types.find(t => t.code === saved.objectType) ?? r.object_types[0];
    setD({
      objectType: type.code, area: 2000, systems: type.systems, level: 'basic', region: r.region_default,
      urgency: 'standard', financing: 'prepay', stages: r.stages.map(s => s.code), qty: {}, custom: [],
      offer: 'opt', offerPrice: null, from: null, ...saved, client: { ...emptyClient, ...saved.client },
    });
  }, [ref.data, d]);
  useEffect(() => {
    if (d) try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch { /* хранилище недоступно - не страшно */ }
  }, [d]);

  // Переход «Рассчитать КП» из карточки проекта или компании: подставляем клиента и тип объекта
  const hp = hashParams();
  const projectId = hp.get('project'), inn = hp.get('inn');
  const project = useQuery({ queryKey: ['invest-project', projectId], queryFn: () => investApi.project(projectId!), enabled: !!projectId });
  const company = useQuery({ queryKey: ['company', inn], queryFn: () => api.company(inn!), enabled: !!inn && !projectId });
  useEffect(() => {
    if (!d || !ref.data) return;
    const p = project.data, c = company.data;
    if (p && d.from?.id !== p.project_id) {
      const type = objectTypeFor(p.industry);
      set({ objectType: type, systems: ref.data.object_types.find(t => t.code === type)!.systems, qty: {},
        from: { kind: 'project', id: p.project_id, title: p.title },
        client: { ...emptyClient, name: p.customer_name || p.company?.name_short || p.initiator, inn: p.customer_inn || p.initiator_inn || '',
          object_name: p.title.slice(0, 160), address: p.contract_work_address || p.municipality || '', project_id: p.project_id } });
    } else if (c && !p && d.from?.id !== c.inn) {
      const type = objectTypeFor(c.industry);
      set({ objectType: type, systems: ref.data.object_types.find(t => t.code === type)!.systems, qty: {},
        from: { kind: 'company', id: c.inn, title: c.dd_name || c.name_short },
        client: { ...emptyClient, name: c.dd_name || c.name_short, inn: c.inn, address: c.legal_address || c.place || '' } });
    }
  }, [project.data, company.data, d, ref.data]);

  // Типовая комплектация по всем системам сразу: при включении системы берём из неё нормы своей группы.
  // Смена типа объекта или площади заполняет спецификацию заново; включение и выключение системы
  // добавляет или убирает только её компоненты, ручные правки остальных строк сохраняются.
  const typical = useQuery({
    queryKey: ['calc-typical', d?.objectType, d?.area],
    queryFn: () => calcApi.typical(d!.objectType, d!.area, ALL_GROUPS), enabled: !!d && d.area > 0,
  });
  const groupOf = (id: string) => ref.data?.items.find(i => i.id === id)?.group_code;
  const typicalFor = (systems: string[]) =>
    Object.fromEntries((typical.data ?? []).filter(t => systems.includes(groupOf(t.id) ?? '')).map(t => [t.id, t.qty]));
  const [typicalKey, setTypicalKey] = useState('');
  useEffect(() => {
    if (!typical.data || !d) return;
    const key = JSON.stringify([d.objectType, d.area]);
    const empty = !Object.keys(d.qty).length;
    const fill = typicalFor(d.systems);
    if (key === typicalKey && (!empty || !Object.keys(fill).length)) return;
    const first = !typicalKey;
    setTypicalKey(key);
    // Первый расчёт после загрузки черновика ручные количества не трогает
    if (first && !empty) return;
    set({ qty: fill });
  }, [typical.data, d?.qty]);

  const toggleSystem = (code: string) => {
    if (!d || !ref.data) return;
    if (d.systems.includes(code)) {
      const qty = Object.fromEntries(Object.entries(d.qty).filter(([id]) => groupOf(id) !== code));
      set({ systems: d.systems.filter(s => s !== code), qty });
    } else {
      set({ systems: [...d.systems, code], qty: { ...d.qty, ...typicalFor([code]) } });
    }
  };

  const req: EstimateRequest | null = useMemo(() => d && ({
    items: Object.entries(d.qty).filter(([, q]) => q > 0).map(([id, qty]) => ({ id, qty })),
    custom: d.custom.filter(c => c.name.trim() && c.price > 0 && c.qty > 0),
    region: d.region, level: d.level, stages: d.stages, urgency: d.urgency, financing: d.financing,
    object_type: d.objectType, area_m2: d.area, client: d.client, offer: d.offer, offer_price: d.offerPrice,
  }), [d]);
  const [debounced, setDebounced] = useState(req);
  useEffect(() => { const t = setTimeout(() => setDebounced(req), 200); return () => clearTimeout(t); }, [req]);
  const calcBody = debounced && { ...debounced, client: emptyClient, offer: 'opt' as Offer, offer_price: null };
  const est = useQuery({ queryKey: ['calc-estimate', calcBody], queryFn: () => calcApi.estimate(calcBody!),
    enabled: !!calcBody, placeholderData: keepPreviousData });

  if (ref.isError) return <p className="empty">Справочники калькулятора не загружены. Запустите backend.load.load_calc.</p>;
  if (!ref.data || !d || !req) return <div className="calc"><div className="skeleton" style={{ height: 480, margin: 20 }} /></div>;

  const resetSpec = () => set({ qty: typicalFor(d.systems) });

  return (
    <div className="calc">
      <CalcParams d={d} set={set} ref_={ref.data} onToggleSystem={toggleSystem} />
      <section className="calc__main">
        <SpecTable d={d} set={set} ref_={ref.data} est={est.data} onReset={resetSpec} />
      </section>
      <section className="calc__side">
        <CalcSummary d={d} set={set} ref_={ref.data} est={est.data} req={req} loading={est.isFetching} />
      </section>
    </div>
  );
}
