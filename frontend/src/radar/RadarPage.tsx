import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { api, emptyFilters, type Filters } from '../api';
import CompanyCard from './CompanyCard';
import FiltersPanel from './FiltersPanel';
import { computeZones, DEFAULT_WEIGHTS, type Weights } from './potential';
import RadarMap, { METRICS, type ZoneMetric } from './RadarMap';
import { Overview, ZonePanel } from './SidePanel';
import WeightsPanel from './WeightsPanel';

export default function RadarPage() {
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const deferred = useDeferredValue(filters);
  const [debounced, setDebounced] = useState(filters);
  useEffect(() => { const t = setTimeout(() => setDebounced(deferred), 350); return () => clearTimeout(t); }, [deferred]);

  const [weights, setWeights] = useState<Weights>(DEFAULT_WEIGHTS);
  const [metric, setMetric] = useState<ZoneMetric>('potential');
  const [zoneId, setZoneId] = useState<string | null>(null);
  const [company, setCompany] = useState<string | null>(null);

  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary });
  const baseZones = useQuery({ queryKey: ['zones'], queryFn: api.zones });
  const industries = useQuery({ queryKey: ['industries'], queryFn: api.industries });
  const points = useQuery({ queryKey: ['points', debounced], queryFn: () => api.points(debounced) });

  const stats = useQuery({ queryKey: ['zone-metrics', debounced], queryFn: () => api.zoneMetrics(debounced),
    placeholderData: keepPreviousData });

  const zones = useMemo(
    () => (baseZones.data && stats.data ? computeZones(baseZones.data, stats.data, weights) : undefined),
    [baseZones.data, stats.data, weights]);
  const zone = zones?.features.find(f => f.properties.oktmo === zoneId)?.properties ?? null;

  const set = (patch: Partial<Filters>) => setFilters(f => ({ ...f, ...patch }));
  const onCompany = useCallback((inn: string) => setCompany(inn), []);
  const onSelectZone = useCallback((z: { oktmo: string } | null) => setZoneId(z?.oktmo ?? null), []);
  const filtered = debounced.industry.length > 0 || debounced.kind.length > 0 || !!debounced.incomeMin
    || !!debounced.incomeMax || !!debounced.growthMin;

  const pointsNote = useMemo(() => {
    const n = points.data?.length ?? 0;
    const rtk = points.data?.filter(p => p.is_rtk_client).length ?? 0;
    return `Точки — юрлица с найденным адресом (ЕГРЮЛ → координаты дома): ${n.toLocaleString('ru-RU')}, из них клиентов РТК ${rtk.toLocaleString('ru-RU')}. `
      + 'Остальные компании без точки: адрес ИП не публикуется, юрлица геокодируются постепенно (лимит DaData). Они учтены в цвете района и в списках.';
  }, [points.data]);

  return (
    <div className="radar">
      <FiltersPanel f={filters} set={set} reset={() => setFilters(emptyFilters)} industries={industries.data} />

      <section className="radar__map">
        <div className="map-toolbar">
          <div className="segmented segmented--map">
            {(Object.keys(METRICS) as ZoneMetric[]).map(m => (
              <button key={m} className={metric === m ? 'is-active' : ''} title={METRICS[m].hint} onClick={() => setMetric(m)}>{METRICS[m].label}</button>
            ))}
          </div>
          {filtered && <div className="map-filter-note">Районы пересчитаны под выбранные фильтры{stats.isFetching ? '…' : ''}</div>}
        </div>
        <RadarMap zones={zones} points={points.data} metric={metric} selected={zoneId}
          onSelectZone={onSelectZone} onSelectCompany={onCompany} />
        <div className="map-legend">
          <span>{METRICS[metric].label}: меньше</span><i className="legend-bar" /><span>больше</span>
          <span className="legend-spot">белое пятно</span>
          <span><i className="dot dot--rtk" /> клиент РТК <i className="dot dot--other" /> потенциальный</span>
          <span className="legend-note">{pointsNote}</span>
        </div>
      </section>

      <section className="radar__side">
        <WeightsPanel w={weights} set={setWeights} />
        {zone
          ? <ZonePanel zone={zone} weights={weights} filters={debounced} onClose={() => setZoneId(null)} onCompany={onCompany} />
          : <Overview summary={summary.data} zones={zones} filtered={filtered} onZone={setZoneId} onCompany={onCompany} />}
      </section>

      {company && <CompanyCard inn={company} onClose={() => setCompany(null)} />}
    </div>
  );
}
