import { useEffect, useRef, useState } from 'react';
import { load } from '@2gis/mapgl';
import { CompositeLayer, Deck } from '@deck.gl/core';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { Deck2gisLayer, initDeck } from '@2gis/deck2gis-layer';
import type { GovPoint, Point, ZoneCollection, ZoneProps } from '../api';

export type ZoneMetric = 'potential' | 'rtk_share_pct' | 'companies' | 'income_growth_pct';

export const METRICS: Record<ZoneMetric, { label: string; hint: string }> = {
  potential: { label: 'Потенциал', hint: 'оценка 0-100: доход, рост доходов, недоохват РТК - веса задаются справа' },
  rtk_share_pct: { label: 'Охват РТК', hint: 'доля клиентов РТК среди субъектов МСП района' },
  companies: { label: 'Плотность бизнеса', hint: 'число субъектов МСП' },
  income_growth_pct: { label: 'Рост доходов', hint: 'изменение суммарного дохода юрлиц 2025 к 2024' },
};

// Шкала бренда: Lavander → светло-фиолетовый → Purple (оранжевый оставлен для акцентов, правило 70/30)
const RAMP: [number, number, number][] = [[243, 236, 248], [232, 210, 237], [196, 170, 255], [148, 102, 255], [119, 0, 255]];
const ORANGE: [number, number, number] = [255, 79, 18];
const PURPLE: [number, number, number] = [119, 0, 255];
// Госсектор красится как компании (клиент РТК — фиолетовый, нет — оранжевый); отличается тёмной обводкой
const GOV_LINE: [number, number, number] = [16, 24, 40];

function colorFor(t: number): [number, number, number] {
  const x = Math.max(0, Math.min(0.9999, t)) * (RAMP.length - 1);
  const i = Math.floor(x), f = x - i;
  return RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * f)) as [number, number, number];
}

/** Перцентиль значения внутри 55 районов — чтобы Ростов не «выжигал» шкалу. */
function rankScale(zones: ZoneCollection, metric: ZoneMetric) {
  // пустые значения (например, нет роста дохода) — в самом низу шкалы
  const vals = zones.features.map(f => (f.properties[metric] as number | null) ?? -Infinity).sort((a, b) => a - b);
  return (raw: number | null) => {
    const v = raw ?? -Infinity;
    let lo = 0, hi = vals.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (vals[m] < v) lo = m + 1; else hi = m; }
    return lo / Math.max(1, vals.length - 1);
  };
}

// Районы и точки лежат на одной высоте: с проверкой глубины точки, нарисованные позже, отбрасывались и «тонули» под заливкой
const NO_DEPTH = { depthCompare: 'always', depthWriteEnabled: false } as const;

/** Районы (GeoJSON) + точки компаний в одном слое с фиксированным порядком отрисовки. */
class RadarLayer extends CompositeLayer<any> {
  static layerName = 'RadarLayer';
  renderLayers() {
    const { zones, points, gov, metric, selected, alpha, onZoneHover, onPointHover, onPointClick, onGovHover } = this.props;
    const scale = rankScale(zones, metric);
    return [
      new GeoJsonLayer({
        id: `${this.props.id}-zones`, data: zones, filled: true, stroked: true, pickable: true,
        getFillColor: (f: any) => [...colorFor(scale(f.properties[metric])), f.properties.oktmo === selected ? Math.min(230, alpha + 60) : alpha],
        getLineColor: (f: any) => f.properties.oktmo === selected ? PURPLE : f.properties.white_spot ? ORANGE : [255, 255, 255],
        getLineWidth: (f: any) => (f.properties.oktmo === selected ? 3 : f.properties.white_spot ? 2.5 : 1),
        lineWidthUnits: 'pixels',
        updateTriggers: { getFillColor: [metric, selected, alpha], getLineColor: [selected], getLineWidth: [selected] },
        onHover: onZoneHover,
        parameters: NO_DEPTH,
      }),
      // Учреждения — под точками компаний: компании кликабельнее, учреждения различимы по цвету и обводке
      gov?.length && new ScatterplotLayer({
        id: `${this.props.id}-gov`, data: gov, pickable: true, stroked: true,
        getPosition: (d: GovPoint) => [d.lon, d.lat], radiusUnits: 'pixels', getRadius: 5,
        getFillColor: (d: GovPoint) => (d.is_rtk_client ? [...PURPLE, 240] : [...ORANGE, 230]),
        getLineColor: GOV_LINE, lineWidthMinPixels: 1.5,
        onHover: onGovHover, parameters: NO_DEPTH,
      }),
      new ScatterplotLayer({
        id: `${this.props.id}-points`, data: points, pickable: true, stroked: true,
        getPosition: (d: Point) => [d.lon, d.lat], radiusUnits: 'pixels',
        getRadius: (d: Point) => (d.kind === 'ЮЛ' ? 6 : 5),
        getFillColor: (d: Point) => (d.is_rtk_client ? [...PURPLE, 240] : [...ORANGE, 230]),
        getLineColor: [255, 255, 255], lineWidthMinPixels: 1.5,
        onHover: onPointHover, onClick: onPointClick,
        parameters: NO_DEPTH,
      }),
    ].filter(Boolean);
  }
}

function pointInRing(x: number, y: number, ring: number[][]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function zoneAt(zones: ZoneCollection, lon: number, lat: number): ZoneProps | null {
  for (const f of zones.features) {
    const g = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon;
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
    if (polys.some(p => pointInRing(lon, lat, p[0]) && !p.slice(1).some(h => pointInRing(lon, lat, h)))) return f.properties;
  }
  return null;
}

interface Props {
  zones?: ZoneCollection;
  points?: Point[];
  metric: ZoneMetric;
  selected: string | null;
  onSelectZone: (z: ZoneProps | null) => void;
  onSelectCompany: (inn: string) => void;
  onBounds?: (bbox: string | null) => void;
  /** Слой «Госсектор»: точки учреждений и выбор учреждения кликом */
  gov?: GovPoint[];
  onSelectGov?: (inn: string) => void;
}

export default function RadarMap({ zones, points, metric, selected, onSelectZone, onSelectCompany, gov, onSelectGov }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const deckRef = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [zoom, setZoom] = useState(6.5);
  const zonesRef = useRef(zones);
  zonesRef.current = zones;
  const onSelectCompanyRef = useRef(onSelectCompany);
  onSelectCompanyRef.current = onSelectCompany;
  const onSelectGovRef = useRef(onSelectGov);
  onSelectGovRef.current = onSelectGov;

  useEffect(() => {
    let map: any;
    let cancelled = false;
    load().then(mapgl => {
      if (cancelled || !el.current) return;
      const key = import.meta.env.VITE_DGIS_KEY as string;
      if (!key) { setError('Нет ключа карты 2ГИС (DGIS_API_KEY в .env)'); return; }
      map = new mapgl.Map(el.current, { center: [40.6, 47.8], zoom: 6.6, key, zoomControl: 'topRight' });
      mapRef.current = map;
      deckRef.current = initDeck(map, Deck, { antialiasing: 'msaa' });
      map.on('styleload', () => setReady(true));
      map.on('zoomend', () => setZoom(Math.round(map.getZoom() * 2) / 2));
      // Контейнер карты меняет размер после первой отрисовки (grid, адаптив) — сообщаем об этом карте
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(el.current);
      map.on('destroy' as any, () => ro.disconnect());
      // Клик обрабатываем сами: карта 2ГИС перехватывает click, поэтому onClick слоя deck.gl ненадёжен.
      // Сначала ищем точку компании под курсором (радиус 8 px), иначе выбираем район.
      map.on('click', (e: any) => {
        try {
          // Все объекты под курсором; у составного слоя info.layer — родитель, поэтому узнаём точку по полю inn
          const picks = deckRef.current?.pickMultipleObjects({ x: e.point[0], y: e.point[1], radius: 10, depth: 5 }) ?? [];
          // Компания и учреждение различаются полем segment (оно есть только у учреждений)
          const company = picks.find((p: any) => p.object?.inn && !p.object.segment);
          if (company) { onSelectCompanyRef.current(company.object.inn); return; }
          const inst = picks.find((p: any) => p.object?.inn && p.object.segment);
          if (inst && onSelectGovRef.current) { onSelectGovRef.current(inst.object.inn); return; }
        } catch { /* picking недоступен - выбираем район по координатам */ }
        const z = zonesRef.current && zoneAt(zonesRef.current, e.lngLat[0], e.lngLat[1]);
        onSelectZone(z ?? null);
      });
    }).catch(err => setError(String(err)));
    return () => { cancelled = true; map?.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Районы и точки рисуются ОДНИМ составным слоем: порядок внутри CompositeLayer гарантирован (районы снизу, точки сверху).
  // Два отдельных слоя 2ГИС/deck.gl после пересборки иногда менялись местами — районы перекрывали точки и клики.
  useEffect(() => {
    const map = mapRef.current, deck = deckRef.current;
    if (!ready || !map || !deck || !zones) return;
    try { map.removeLayer('radar'); } catch { /* слоя ещё нет */ }

    // При приближении заливка районов бледнеет, чтобы были видны улицы и точки
    // Заливка не исчезает при приближении: становится полупрозрачной, но район остаётся различим (границы — всегда)
    const alpha = zoom < 8 ? 170 : zoom < 10 ? 135 : 110;
    map.addLayer(new Deck2gisLayer({
      id: 'radar', deck, type: RadarLayer, data: [],
      zones, points: points ?? [], gov: gov ?? [], metric, selected, alpha,
      onZoneHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y,
        text: `${info.object.properties.short} · ${METRICS[metric].label}: ${fmtMetric(metric, info.object.properties[metric])}` } : null),
      onPointHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y,
        text: `${info.object.name_short} · ${info.object.is_rtk_client ? 'клиент РТК' : 'потенциальный'}` } : null),
      onPointClick: (info: any) => { if (info.object) onSelectCompany(info.object.inn); return true; },
      onGovHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y,
        text: `${info.object.name_short} · госсектор, ${info.object.segment} · ${info.object.is_rtk_client ? 'клиент РТК' : 'потенциальный'}` } : null),
    }));
  }, [ready, zones, points, gov, metric, selected, zoom, onSelectCompany]);

  return (
    // Курсор ушёл с карты — подсказку убираем (deck.gl сам не присылает «пустой» hover при выходе)
    <div className="map-wrap" onMouseLeave={() => setHover(null)}>
      <div ref={el} className="map" />
      {error && <div className="map-error">{error}</div>}
      {hover && <div className="map-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>{hover.text}</div>}
    </div>
  );
}

export function fmtMetric(metric: ZoneMetric, v: number) {
  if (v == null) return '-';
  if (metric === 'rtk_share_pct') return `${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`;
  if (metric === 'income_growth_pct') return `${v > 0 ? '+' : ''}${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`;
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
}
