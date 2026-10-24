import { useEffect, useRef, useState } from 'react';
import { load } from '@2gis/mapgl';
import { CompositeLayer, Deck } from '@deck.gl/core';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { Deck2gisLayer, initDeck } from '@2gis/deck2gis-layer';
import type { Point, ZoneCollection, ZoneProps } from '../api';

export type ZoneMetric = 'potential' | 'rtk_share_pct' | 'companies' | 'income_growth_pct';

export const METRICS: Record<ZoneMetric, { label: string; hint: string }> = {
  potential: { label: 'Потенциал', hint: 'оценка 0–100: доход, рост доходов, недоохват РТК — веса задаются справа' },
  rtk_share_pct: { label: 'Охват РТК', hint: 'доля клиентов РТК среди субъектов МСП района' },
  companies: { label: 'Плотность бизнеса', hint: 'число субъектов МСП' },
  income_growth_pct: { label: 'Рост доходов', hint: 'изменение суммарного дохода юрлиц 2025 к 2024' },
};

const RAMP: [number, number, number][] = [[243, 236, 248], [232, 210, 237], [196, 170, 255], [148, 102, 255], [119, 0, 255]];
const ORANGE: [number, number, number] = [255, 79, 18];
const PURPLE: [number, number, number] = [119, 0, 255];

function colorFor(t: number): [number, number, number] {
  const x = Math.max(0, Math.min(0.9999, t)) * (RAMP.length - 1);
  const i = Math.floor(x), f = x - i;
  return RAMP[i].map((c, k) => Math.round(c + (RAMP[i + 1][k] - c) * f)) as [number, number, number];
}

function rankScale(zones: ZoneCollection, metric: ZoneMetric) {

  const vals = zones.features.map(f => (f.properties[metric] as number | null) ?? -Infinity).sort((a, b) => a - b);
  return (raw: number | null) => {
    const v = raw ?? -Infinity;
    let lo = 0, hi = vals.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (vals[m] < v) lo = m + 1; else hi = m; }
    return lo / Math.max(1, vals.length - 1);
  };
}

const NO_DEPTH = { depthCompare: 'always', depthWriteEnabled: false } as const;

class RadarLayer extends CompositeLayer<any> {
  static layerName = 'RadarLayer';
  renderLayers() {
    const { zones, points, metric, selected, alpha, onZoneHover, onPointHover, onPointClick } = this.props;
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
      new ScatterplotLayer({
        id: `${this.props.id}-points`, data: points, pickable: true, stroked: true,
        getPosition: (d: Point) => [d.lon, d.lat], radiusUnits: 'pixels',
        getRadius: (d: Point) => (d.kind === 'ЮЛ' ? 6 : 5),
        getFillColor: (d: Point) => (d.is_rtk_client ? [...PURPLE, 240] : [...ORANGE, 230]),
        getLineColor: [255, 255, 255], lineWidthMinPixels: 1.5,
        onHover: onPointHover, onClick: onPointClick,
        parameters: NO_DEPTH,
      }),
    ];
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
}

export default function RadarMap({ zones, points, metric, selected, onSelectZone, onSelectCompany }: Props) {
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

      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(el.current);
      map.on('destroy' as any, () => ro.disconnect());

      map.on('click', (e: any) => {
        try {

          const picks = deckRef.current?.pickMultipleObjects({ x: e.point[0], y: e.point[1], radius: 10, depth: 5 }) ?? [];
          const company = picks.find((p: any) => p.object?.inn);
          if (company) { onSelectCompanyRef.current(company.object.inn); return; }
        } catch {                                                          }
        const z = zonesRef.current && zoneAt(zonesRef.current, e.lngLat[0], e.lngLat[1]);
        onSelectZone(z ?? null);
      });
    }).catch(err => setError(String(err)));
    return () => { cancelled = true; map?.destroy(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current, deck = deckRef.current;
    if (!ready || !map || !deck || !zones) return;
    try { map.removeLayer('radar'); } catch {                    }

    const alpha = zoom < 8 ? 170 : zoom < 10 ? 135 : 110;
    map.addLayer(new Deck2gisLayer({
      id: 'radar', deck, type: RadarLayer, data: [],
      zones, points: points ?? [], metric, selected, alpha,
      onZoneHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y,
        text: `${info.object.properties.short} · ${METRICS[metric].label}: ${fmtMetric(metric, info.object.properties[metric])}` } : null),
      onPointHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y,
        text: `${info.object.name_short} · ${info.object.is_rtk_client ? 'клиент РТК' : 'потенциальный'}` } : null),
      onPointClick: (info: any) => { if (info.object) onSelectCompany(info.object.inn); return true; },
    }));
  }, [ready, zones, points, metric, selected, zoom, onSelectCompany]);

  return (

    <div className="map-wrap" onMouseLeave={() => setHover(null)}>
      <div ref={el} className="map" />
      {error && <div className="map-error">{error}</div>}
      {hover && <div className="map-tip" style={{ left: hover.x + 12, top: hover.y + 12 }}>{hover.text}</div>}
    </div>
  );
}

export function fmtMetric(metric: ZoneMetric, v: number) {
  if (v == null) return '—';
  if (metric === 'rtk_share_pct') return `${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`;
  if (metric === 'income_growth_pct') return `${v > 0 ? '+' : ''}${v.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`;
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 1 });
}
