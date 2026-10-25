import { useQuery } from '@tanstack/react-query';
import { load } from '@2gis/mapgl';
import { CompositeLayer, Deck } from '@deck.gl/core';
import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { Deck2gisLayer, initDeck } from '@2gis/deck2gis-layer';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ProjectPoint } from './api';
import { inWindow, launchIn, mln } from './fmt';

type RGB = [number, number, number];
// Цвет — стадия в фиолетовой шкале бренда; оранжевый только у проектов в окне продаж (правило 70/30)
const HOT: RGB = [255, 79, 18];
const STAGE_COLOR: Record<string, RGB> = {
  'подготовка': [119, 0, 255], 'реализация': [148, 102, 255], 'ввод в этом году': [116, 159, 214],
};
const DONE: RGB = [134, 139, 149];
const PURPLE: RGB = [119, 0, 255];

export const pointColor = (p: ProjectPoint): RGB =>
  inWindow(p.months_to_launch, p.stage) ? HOT : STAGE_COLOR[p.stage] ?? DONE;

// Площадь круга пропорциональна сумме: 5 px у самых мелких, ~26 px у проектов на сотни миллиардов
const radius = (sum: number | null) => Math.max(5, Math.min(26, 3 + Math.sqrt(Math.max(0, sum ?? 0)) / 9));

const NO_DEPTH = { depthCompare: 'always', depthWriteEnabled: false } as const;

/** Контуры районов + точки проектов одним слоем: порядок отрисовки фиксирован (как в радаре). */
class InvestLayer extends CompositeLayer<any> {
  static layerName = 'InvestLayer';
  renderLayers() {
    const { zones, points, selected, onHover } = this.props;
    // Мелкие сверху, чтобы крупный проект не закрывал соседей в одном селе
    const sorted = [...points].sort((a: ProjectPoint, b: ProjectPoint) => (b.sum_mln ?? 0) - (a.sum_mln ?? 0));
    return [
      zones && new GeoJsonLayer({
        id: `${this.props.id}-zones`, data: zones, filled: true, stroked: true, pickable: false,
        getFillColor: [243, 236, 248, 60], getLineColor: [119, 0, 255, 70], getLineWidth: 1, lineWidthUnits: 'pixels',
        parameters: NO_DEPTH,
      }),
      new ScatterplotLayer({
        id: `${this.props.id}-points`, data: sorted, pickable: true, stroked: true,
        getPosition: (d: ProjectPoint) => [d.lon, d.lat], radiusUnits: 'pixels',
        getRadius: (d: ProjectPoint) => radius(d.sum_mln) + (d.project_id === selected ? 3 : 0),
        getFillColor: (d: ProjectPoint) => [...pointColor(d), 215],
        getLineColor: (d: ProjectPoint) => (d.project_id === selected ? PURPLE : [255, 255, 255]),
        getLineWidth: (d: ProjectPoint) => (d.project_id === selected ? 3 : 1.5), lineWidthUnits: 'pixels',
        updateTriggers: { getRadius: [selected], getLineColor: [selected], getLineWidth: [selected] },
        onHover, parameters: NO_DEPTH,
      }),
    ].filter(Boolean);
  }
}

export default function InvestMap({ points, selected, onSelect, focus }: {
  points?: ProjectPoint[]; selected: string | null; onSelect: (id: string) => void;
  focus?: { id: string; lat: number; lon: number; approx: boolean };
}) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const deckRef = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; p: ProjectPoint } | null>(null);
  const zones = useQuery({ queryKey: ['zones'], queryFn: api.zones });
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    let map: any;
    let cancelled = false;
    load().then(mapgl => {
      if (cancelled || !el.current) return;
      const key = import.meta.env.VITE_DGIS_KEY as string;
      if (!key) { setError('Нет ключа карты 2ГИС (DGIS_API_KEY в .env)'); return; }
      map = new mapgl.Map(el.current, { center: [40.6, 47.6], zoom: 6.6, key, zoomControl: 'topRight' });
      mapRef.current = map;
      deckRef.current = initDeck(map, Deck, { antialiasing: 'msaa' });
      map.on('styleload', () => setReady(true));
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(el.current);
      map.on('destroy' as any, () => ro.disconnect());
      // Клик ловим на карте: 2ГИС перехватывает click, onClick слоя deck.gl ненадёжен (см. RadarMap)
      map.on('click', (e: any) => {
        try {
          const picks = deckRef.current?.pickMultipleObjects({ x: e.point[0], y: e.point[1], radius: 8, depth: 5 }) ?? [];
          const hit = picks.find((p: any) => p.object?.project_id);
          if (hit) onSelectRef.current(hit.object.project_id);
        } catch { /* picking недоступен */ }
      });
    }).catch(err => setError(String(err)));
    return () => { cancelled = true; map?.destroy(); };
  }, []);

  useEffect(() => {
    const map = mapRef.current, deck = deckRef.current;
    if (!ready || !map || !deck) return;
    try { map.removeLayer('invest'); } catch { /* слоя ещё нет */ }
    map.addLayer(new Deck2gisLayer({
      id: 'invest', deck, type: InvestLayer, data: [],
      zones: zones.data, points: points ?? [], selected,
      onHover: (info: any) => setHover(info.object ? { x: info.x, y: info.y, p: info.object } : null),
    }));
  }, [ready, zones.data, points, selected]);

  // Выбрали проект (в списке, на Ганте, на карте) — подлетаем: проект в центре, масштаб не мельче улиц.
  // Если точка — центр муниципалитета, ближе района не приближаем: точного места всё равно нет.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const target = focus.approx ? 10 : 13;
    map.setCenter([focus.lon, focus.lat], { duration: 900, easing: 'easeInOutCubic' });
    if (map.getZoom() < target) map.setZoom(target, { duration: 900, easing: 'easeInOutCubic' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focus?.id]);

  return (
    <div className="map-wrap" onMouseLeave={() => setHover(null)}>
      <div ref={el} className="map" />
      {error && <div className="map-error">{error}</div>}
      {hover && (
        <div className="map-tip map-tip--wide" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          <strong>{hover.p.title.length > 80 ? `${hover.p.title.slice(0, 80)}…` : hover.p.title}</strong>
          <span>{hover.p.initiator} · {mln(hover.p.sum_mln)} · {launchIn(hover.p.months_to_launch, hover.p.stage)}</span>
        </div>
      )}
    </div>
  );
}
