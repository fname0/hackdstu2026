(() => {
  const { companies, projects, places } = window.RT_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const fmt = n => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 });
  const rub = n => fmt(Math.round(n)) + ' ₽';
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const plural = (n, one, few, many) => {
    const m10 = n % 10, m100 = n % 100;
    return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
  };
  const THIS_YEAR = 2026;

  /* ---------- Навигация ---------- */
  const views = ['radar', 'invest', 'calc'];
  function route() {
    const v = views.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'radar';
    views.forEach(id => { $('#view-' + id).hidden = id !== v; });
    document.querySelectorAll('.tabs .rt-tab').forEach(a => a.classList.toggle('rt-tab--active', a.dataset.view === v));
    window.scrollTo(0, 0);
    if (v === 'radar' && map) setTimeout(() => { map.invalidateSize(); }, 0);
  }
  window.addEventListener('hashchange', route);
  history.scrollRestoration = 'manual';

  /* ---------- Состояние Радара ---------- */
  const state = {
    client: 'all',      // 'all' | 'our' | 'their'
    revMin: null,
    revMax: null,
    place: '',
    useBbox: true,
    ind: new Set(),
    type: 'all',
    onlyReloc: false,   // задача со *
    onlyClosed: false,  // закрытые/исключённые из МСП
    onlyNew: false,
    subtab: 'zones',    // 'zones' | 'companies'
  };

  let map, layer, isFitting = false;

  /* ---------- Инициализация контролов фильтрации ---------- */
  const industries = Object.entries(companies.reduce((a, c) => (a[c.ind] = (a[c.ind] || 0) + 1, a), {}))
    .sort((a, b) => (a[0] === 'Прочее') - (b[0] === 'Прочее') || b[1] - a[1]);

  $('#f-industry').innerHTML = industries.map(([name, n]) =>
    `<button class="chip" data-ind="${esc(name)}">${esc(name)} <span>${n}</span></button>`).join('');

  const sortedPlaces = Object.entries(companies.reduce((a, c) => (a[c.place] = (a[c.place] || 0) + 1, a), {}))
    .sort((a, b) => b[1] - a[1]);
  $('#f-place').innerHTML = `<option value="">Вся Ростовская область (${fmt(companies.length)})</option>` +
    sortedPlaces.map(([p, n]) => `<option value="${esc(p)}">${esc(p)} (${n})</option>`).join('');

  $('#f-client').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.client = b.dataset.v;
    $('#f-client').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x === b));
    renderRadar();
  });

  function syncRevInputs() {
    const minVal = $('#f-rev-min').value.trim();
    const maxVal = $('#f-rev-max').value.trim();
    state.revMin = minVal !== '' ? Math.max(0, Number(minVal)) : null;
    state.revMax = maxVal !== '' ? Math.max(0, Number(maxVal)) : null;
    renderRadar();
  }
  $('#f-rev-min').addEventListener('input', syncRevInputs);
  $('#f-rev-max').addEventListener('input', syncRevInputs);

  $('#f-rev-presets').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    $('#f-rev-min').value = b.dataset.min;
    $('#f-rev-max').value = b.dataset.max;
    $('#f-rev-presets').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x === b));
    syncRevInputs();
  });

  $('#f-place').addEventListener('change', e => {
    state.place = e.target.value;
    if (state.place && places[state.place] && map) {
      isFitting = true;
      map.setView(places[state.place], 11);
      setTimeout(() => { isFitting = false; renderRadar(); }, 50);
    } else if (!state.place && map) {
      fitRegion();
    } else {
      renderRadar();
    }
  });

  $('#f-bbox').addEventListener('change', e => {
    state.useBbox = e.target.checked;
    renderRadar();
  });

  $('#f-industry').addEventListener('click', e => {
    const b = e.target.closest('.chip'); if (!b) return;
    state.ind.has(b.dataset.ind) ? state.ind.delete(b.dataset.ind) : state.ind.add(b.dataset.ind);
    b.classList.toggle('is-active');
    renderRadar();
  });

  $('#f-type').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.type = b.dataset.v;
    $('#f-type').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x === b));
    renderRadar();
  });

  $('#f-reloc').addEventListener('change', e => { state.onlyReloc = e.target.checked; renderRadar(); });
  $('#f-closed').addEventListener('change', e => {
    state.onlyClosed = e.target.checked;
    if (state.onlyClosed && state.client === 'their') {
      state.client = 'all';
      $('#f-client').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x.dataset.v === 'all'));
    }
    renderRadar();
  });
  $('#f-new').addEventListener('change', e => { state.onlyNew = e.target.checked; renderRadar(); });

  $('#radar-subtabs').addEventListener('click', e => {
    const b = e.target.closest('[data-subtab]'); if (!b) return;
    state.subtab = b.dataset.subtab;
    $('#radar-subtabs').querySelectorAll('.rt-tab').forEach(x => x.classList.toggle('rt-tab--active', x === b));
    renderRadar();
  });

  function reset() {
    state.client = 'all';
    state.revMin = null;
    state.revMax = null;
    state.place = '';
    state.useBbox = true;
    state.ind.clear();
    state.type = 'all';
    state.onlyReloc = false;
    state.onlyClosed = false;
    state.onlyNew = false;

    $('#f-rev-min').value = '';
    $('#f-rev-max').value = '';
    $('#f-place').value = '';
    $('#f-bbox').checked = true;
    $('#f-reloc').checked = false;
    $('#f-closed').checked = false;
    $('#f-new').checked = false;

    document.querySelectorAll('#f-industry .chip, #f-rev-presets .chip').forEach(c => c.classList.remove('is-active'));
    $('#f-client').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x.dataset.v === 'all'));
    $('#f-type').querySelectorAll('button').forEach(x => x.classList.toggle('is-active', x.dataset.v === 'all'));
    fitRegion();
  }
  $('#f-reset').addEventListener('click', reset);
  document.querySelector('[data-reset]').addEventListener('click', reset);
  $('#map-fit').addEventListener('click', () => {
    state.place = '';
    $('#f-place').value = '';
    fitRegion();
  });

  /* ---------- Выборка компаний ---------- */
  function isZoomedIn() {
    return map && map.getZoom() >= 9;
  }

  function filtered() {
    const bounds = (state.useBbox && map && isZoomedIn()) ? map.getBounds() : null;
    return companies.filter(c => {
      if (state.client === 'our' && !c.our) return false;
      if (state.client === 'their' && c.our) return false;
      if (state.revMin !== null && c.rev < state.revMin) return false;
      if (state.revMax !== null && c.rev > state.revMax) return false;
      if (state.place && c.place !== state.place) return false;
      if (state.ind.size && !state.ind.has(c.ind)) return false;
      if (state.type !== 'all' && c.type !== state.type) return false;
      if (state.onlyReloc && !c.relocType) return false;
      if (state.onlyClosed && !c.closed) return false;
      if (state.onlyNew && !c.isNew) return false;
      if (bounds && !bounds.contains([c.lat, c.lon])) return false;
      return true;
    });
  }

  function zones(list) {
    const z = {};
    for (const c of list) {
      const e = z[c.place] ??= {
        place: c.place, n: 0, our: 0, their: 0, closed: 0,
        ul: 0, isNew: 0, reloc: 0, rev: 0, ind: {},
      };
      e.n++;
      if (c.our) e.our++; else e.their++;
      if (c.closed) e.closed++;
      if (c.type === 'ЮЛ') e.ul++;
      if (c.isNew) e.isNew++;
      if (c.relocType) e.reloc++;
      e.rev += c.rev || 0;
      e.ind[c.ind] = (e.ind[c.ind] || 0) + 1;
    }
    return Object.values(z).map(e => {
      const ranked = Object.entries(e.ind).sort((a, b) => b[1] - a[1]);
      const [top, topN] = ranked.find(([k]) => k !== 'Прочее') || ranked[0];
      return { ...e, top, topShare: topN / e.n };
    }).sort((a, b) => b.n - a.n);
  }

  /* ---------- Карта ---------- */
  function initMap() {
    map = L.map('map', { zoomControl: true, scrollWheelZoom: true, attributionControl: true }).setView([47.7, 40.8], 7);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap', maxZoom: 18,
    }).addTo(map);
    layer = L.layerGroup().addTo(map);

    map.on('moveend zoomend', () => {
      if (isFitting) return;
      if (state.useBbox) renderRadar();
    });

    fitRegion();
  }

  function fitRegion() {
    if (!map) return;
    isFitting = true;
    map.fitBounds(L.latLngBounds(Object.values(places)), { padding: [16, 16] });
    setTimeout(() => { isFitting = false; renderRadar(); }, 60);
  }

  function renderRadar() {
    const list = filtered();
    const zs = zones(list);
    const max = Math.max(1, ...zs.map(z => z.n));

    const ourCount = list.filter(c => c.our).length;
    const theirCount = list.length - ourCount;
    const closedCount = list.filter(c => c.closed).length;
    const relocCount = list.filter(c => c.relocType).length;
    const totalRev = list.reduce((s, c) => s + (c.rev || 0), 0);

    $('#radar-meta').textContent =
      `Ростовская область · ${fmt(list.length)} из ${fmt(companies.length)} субъектов МСП (759 в базе РТК + реестр МСП ФНС)`;

    $('#radar-stats').innerHTML = [
      [fmt(ourCount), `Наши клиенты РТК (из них ${fmt(closedCount)} исключены из МСП)`, 'stat__value--our'],
      [fmt(theirCount), 'Потенциальные («не наши» из ФНС)', 'stat__value--their'],
      [fmt(totalRev / 1000) + ' млрд ₽', 'Суммарная годовая выручка выборки', ''],
      [fmt(relocCount), 'Бизнес не по месту регистрации (*)', ''],
    ].map(([v, l, cls]) =>
      `<div class="stat"><div class="stat__value ${cls}">${v}</div><div class="stat__label">${l}</div></div>`
    ).join('');

    $('#comp-tab-count').textContent = fmt(list.length);
    $('#zones-count').textContent = state.subtab === 'zones'
      ? (zs.length ? `${zs.length} ${plural(zs.length, 'территория', 'территории', 'территорий')}` : '')
      : `Показаны топ-${Math.min(100, list.length)} по выручке`;

    const zoomed = isZoomedIn();
    $('#map-fit').hidden = !zoomed && !state.place;
    $('#map-bbox-status').textContent = zoomed && state.useBbox
      ? `В видимой области карты: ${fmt(list.length)} комп. (зум ${map.getZoom()})`
      : 'Обзор региона · приблизьте карту для выбора точек (как ПВЗ)';

    /* Отрисовка карты */
    layer.clearLayers();
    const showIndividualPoints = (map && map.getZoom() >= 10) || list.length <= 180 || state.onlyReloc || state.onlyClosed;

    if (showIndividualPoints) {
      // При приближении (или узком фильтре) рисуем конкретные точки компаний (как ПВЗ на карте)
      for (const c of list.slice(0, 600)) {
        const color = c.closed ? '#868B95' : (c.our ? '#7700FF' : '#FF4F12');
        // Если включён фильтр «*» и регистрация внутри области — проводим пунктирную дугу от места регистрации
        if ((state.onlyReloc || list.length <= 80) && c.relocType === 'intra' && places[c.regPlace]) {
          L.polyline([places[c.regPlace], [c.lat, c.lon]], {
            color: '#7700FF', weight: 1.5, dashArray: '4 4', opacity: 0.55,
          }).addTo(layer);
        }
        L.circleMarker([c.lat, c.lon], {
          radius: c.type === 'ЮЛ' ? 6.5 : 4.5,
          color: '#fff',
          weight: 1.5,
          fillColor: color,
          fillOpacity: 0.9,
        }).bindTooltip(
          `<b>${esc(c.name)}</b><br>` +
          `ИНН ${esc(c.inn)} · ${c.our ? '<span style="color:#7700FF">Наш клиент РТК</span>' : '<span style="color:#FF4F12">Потенциал (не наш)</span>'}` +
          (c.closed ? ' · <b>Исключён из МСП</b>' : '') +
          `<br>${esc(c.ind)} · выручка <b>${fmt(c.rev)} млн ₽</b>` +
          (c.relocType ? `<br>★ Рег.: ${esc(c.regPlace)} → Факт: ${esc(c.place)} (${esc(c.relocSource)})` : '')
        ).addTo(layer);
      }
    } else {
      // На уровне области рисуем агрегированные зоны с наглядным разделением Наши (#7700FF) vs Не наши (#FF4F12)
      for (const z of [...zs].reverse()) {
        const ll = places[z.place]; if (!ll) continue;
        const rTotal = 6 + Math.sqrt(z.n / max) * 28;
        const ourRatio = z.n ? z.our / z.n : 0;

        if (state.client === 'our') {
          L.circleMarker(ll, {
            radius: rTotal, color: '#fff', weight: 1.5, fillColor: '#7700FF', fillOpacity: 0.85,
          }).bindTooltip(zoneTooltip(z)).on('click', () => zoomToPlace(z.place)).addTo(layer);
        } else if (state.client === 'their') {
          L.circleMarker(ll, {
            radius: rTotal, color: '#fff', weight: 1.5, fillColor: '#FF4F12', fillOpacity: 0.85,
          }).bindTooltip(zoneTooltip(z)).on('click', () => zoomToPlace(z.place)).addTo(layer);
        } else {
          // Режим «Все»: внешний круг — весь рынок/потенциал (оранжевый #FF4F12), внутреннее ядро — доля наших клиентов РТК (фиолетовый #7700FF)
          L.circleMarker(ll, {
            radius: rTotal, color: '#fff', weight: 1.5, fillColor: '#FF4F12', fillOpacity: 0.78,
          }).bindTooltip(zoneTooltip(z)).on('click', () => zoomToPlace(z.place)).addTo(layer);

          if (z.our > 0) {
            const rOur = Math.max(3.5, rTotal * Math.sqrt(ourRatio));
            L.circleMarker(ll, {
              radius: rOur, color: '#fff', weight: 1, fillColor: '#7700FF', fillOpacity: 0.95, interactive: false,
            }).addTo(layer);
          }
        }
      }
    }

    /* Отрисовка таблиц (Зоны / Компании) */
    const hasData = list.length > 0;
    $('#zones-empty').hidden = hasData;
    $('#wrap-zones').hidden = !hasData || state.subtab !== 'zones';
    $('#wrap-companies').hidden = !hasData || state.subtab !== 'companies';

    if (state.subtab === 'zones') {
      $('#zones tbody').innerHTML = zs.slice(0, 20).map(z => {
        const ourPct = Math.round((z.our / z.n) * 100);
        const theirPct = 100 - ourPct;
        return `<tr class="is-clickable" data-place="${esc(z.place)}" title="Нажмите, чтобы приблизить ${esc(z.place)} на карте">
          <td><strong>${esc(z.place)}</strong>${z.closed ? `<span class="badge badge--closed" title="Закрылись / исключены из МСП">${z.closed} закр.</span>` : ''}</td>
          <td class="num">${fmt(z.n)}</td>
          <td class="split-cell">
            <div class="split-nums">
              <span class="split-nums__our">${fmt(z.our)} наш. (${ourPct}%)</span>
              <span class="split-nums__their">${fmt(z.their)} не наш.</span>
            </div>
            <div class="split-bar">
              <i class="split-bar__our" style="width:${ourPct}%"></i>
              <i class="split-bar__their" style="width:${theirPct}%"></i>
            </div>
          </td>
          <td class="num">${fmt(z.rev)}</td>
          <td class="num">${z.reloc ? `<span class="badge badge--reloc">${fmt(z.reloc)}</span>` : '—'}</td>
          <td>${esc(z.top)}<span class="share" title="${Math.round(z.topShare * 100)}% субъектов зоны"><i style="width:${Math.round(z.topShare * 100)}%"></i></span></td>
        </tr>`;
      }).join('');
    } else {
      const topCompanies = [...list].sort((a, b) => b.rev - a.rev).slice(0, 100);
      $('#companies-table tbody').innerHTML = topCompanies.map(c => `<tr>
        <td>
          <strong>${esc(c.name)}</strong>
          <span class="sub">ИНН ${esc(c.inn)} · ${esc(c.type)} · ${esc(c.cat)}</span>
        </td>
        <td>
          ${c.our
            ? `<span class="badge badge--our">Наш клиент РТК</span>`
            : `<span class="badge badge--their">Не наш (ФНС)</span>`}
          ${c.closed ? `<span class="badge badge--closed">Исключён из МСП</span>` : ''}
        </td>
        <td>
          ${esc(c.place)}
          ${c.relocType
            ? `<span class="sub"><span class="badge badge--reloc">★ Рег.: ${esc(c.regPlace)}</span> · ${esc(c.relocSource)}</span>`
            : `<span class="sub">Совпадает с регистрацией ИФНС</span>`}
        </td>
        <td>${esc(c.ind)}<span class="sub clamp" title="${esc(c.okved)}">${esc(c.okved)}</span></td>
        <td class="num">
          <strong>${fmt(c.rev)}</strong>
          <span class="sub">${c.closed ? 'закрыт' : (c.growth >= 0 ? `+${c.growth}% к пр. году` : `${c.growth}% к пр. году`)}</span>
        </td>
      </tr>`).join('');
    }
  }

  function zoneTooltip(z) {
    const ourPct = Math.round((z.our / z.n) * 100);
    return `<b>${esc(z.place)}</b><br>` +
      `Всего: <b>${fmt(z.n)}</b> · Выручка: <b>${fmt(z.rev)} млн ₽</b><br>` +
      `<span style="color:#7700FF">● Наши (РТК): ${fmt(z.our)} (${ourPct}%)</span><br>` +
      `<span style="color:#FF4F12">● Не наши (потенциал): ${fmt(z.their)} (${100 - ourPct}%)</span>` +
      (z.reloc ? `<br>★ Не по месту рег. (*): ${fmt(z.reloc)}` : '');
  }

  function zoomToPlace(placeName) {
    if (!places[placeName] || !map) return;
    state.place = placeName;
    $('#f-place').value = placeName;
    isFitting = true;
    map.setView(places[placeName], 11);
    setTimeout(() => { isFitting = false; renderRadar(); }, 60);
  }

  $('#zones').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-place]');
    if (tr) zoomToPlace(tr.dataset.place);
  });

  /* ---------- Инвестнавигатор ---------- */
  function stage(p) {
    if (!p.start || p.start > THIS_YEAR) return 'Проектирование';
    if (p.finish && p.finish < THIS_YEAR) return 'Запуск';
    return 'Стройка';
  }
  function renderInvest() {
    const total = projects.reduce((s, p) => s + p.sum, 0);
    const jobs = projects.reduce((s, p) => s + (Number(p.jobs) || 0), 0);
    const finishingSoon = projects.filter(p => p.finish === THIS_YEAR || p.finish === THIS_YEAR + 1).length;
    $('#invest-meta').textContent = `${projects.length} проектов · реестр инвестпроектов Ростовской области`;
    $('#invest-stats').innerHTML = [
      [fmt(total / 1000) + ' млрд ₽', 'Совокупный объём инвестиций'],
      [fmt(projects.length), 'Проектов в реестре'],
      [fmt(finishingSoon), `Ввод в ${THIS_YEAR}–${THIS_YEAR + 1} гг.`],
      [fmt(jobs), 'Новых рабочих мест'],
    ].map(([v, l]) => `<div class="stat"><div class="stat__value">${v}</div><div class="stat__label">${l}</div></div>`).join('');

    const MIN = 2020, MAX = 2034, span = MAX - MIN;
    const pos = y => ((Math.min(Math.max(y, MIN), MAX) - MIN) / span) * 100;
    $('#projects tbody').innerHTML = [...projects].sort((a, b) => b.sum - a.sum).map(p => `<tr>
      <td class="project"><span class="clamp" title="${esc(p.title)}">${esc(p.title)}</span>${p.key ? '<span class="badge">ключевой</span>' : ''}<span class="sub">${esc(p.initiator)}</span></td>
      <td>${esc(p.mo)}<span class="sub">${stage(p)}</span></td>
      <td><span>${p.start ?? '—'}–${p.finish ?? '—'}</span>
        <div class="timeline" title="Оранжевая метка — ${THIS_YEAR} г."><i style="left:${pos(p.start || MIN)}%;width:${Math.max(2, pos(p.finish || MAX) - pos(p.start || MIN))}%"></i><b style="left:${pos(THIS_YEAR)}%"></b></div></td>
      <td class="num">${fmt(p.sum)}</td>
      <td class="num">${p.jobs ?? '—'}</td>
    </tr>`).join('');
  }

  /* ---------- Калькулятор (справочник МОД3_Таб4) ---------- */
  const PRICE = [
    ['el_01', 'Смарт-счётчик (3-фазный)', 'Электроснабжение', 8500, 1.2],
    ['el_02', 'Датчик качества электроэнергии', 'Электроснабжение', 12000, 1.2],
    ['el_03', 'Модуль контроля АВР', 'Электроснабжение', 5500, 1.2],
    ['ht_01', 'Тепловычислитель (узел учёта)', 'Отопление', 22000, 1.4],
    ['ht_02', 'Датчик температуры (погружной)', 'Отопление', 1800, 1.4],
    ['ht_03', 'Привод регулирующего клапана', 'Отопление', 9500, 1.4],
    ['ws_01', 'Ультразвуковой расходомер', 'Водоснабжение', 14000, 1.1],
    ['ws_02', 'Датчик давления (аналоговый)', 'Водоснабжение', 4200, 1.1],
    ['ws_03', 'Датчик протечки воды', 'Водоснабжение', 1200, 1.1],
    ['wo_01', 'Датчик уровня (поплавковый)', 'Водоотведение', 2500, 1.3],
    ['wo_02', 'Датчик перегрева насоса', 'Водоотведение', 3800, 1.3],
    ['wo_03', 'Блок управления КНС', 'Водоотведение', 18500, 1.3],
    ['vn_01', 'Контроллер ПВУ', 'Вентиляция', 28000, 1.6],
    ['vn_02', 'Датчик CO₂', 'Вентиляция', 7500, 1.6],
    ['vn_03', 'Датчик перепада давления (фильтр)', 'Вентиляция', 3100, 1.6],
    ['kd_01', 'Контроллер VRF-системы', 'Кондиционирование', 35000, 1.5],
    ['kd_02', 'Датчик температуры/влажности', 'Кондиционирование', 2800, 1.5],
    ['kd_03', 'ИК-излучатель (управление сплитом)', 'Кондиционирование', 4500, 1.5],
    ['gs_01', 'Газоанализатор (метановый)', 'Газоснабжение', 11000, 2],
    ['gs_02', 'Электромагнитный отсечной клапан', 'Газоснабжение', 6800, 2],
  ];
  function renderCalc() {
    $('#price tbody').innerHTML = PRICE.map(([id, name, grp, price, k]) => `<tr>
      <td>${esc(name)}<span class="sub">${id} · сложность ×${String(k).replace('.', ',')}</span></td>
      <td>${grp}</td>
      <td class="num">${fmt(price)}</td>
      <td class="num"><input class="qty" type="number" min="0" step="1" value="0" data-id="${id}" aria-label="Количество: ${esc(name)}"></td>
    </tr>`).join('');
    const recalc = () => {
      let equip = 0;
      document.querySelectorAll('.qty').forEach(i => {
        const row = PRICE.find(p => p[0] === i.dataset.id);
        equip += Math.max(0, +i.value || 0) * row[3] * row[4];
      });
      const works = equip * 0.30;
      const total = (equip + works) * 1.1 * +$('#c-level').value;
      $('#s-equip').textContent = rub(equip);
      $('#s-works').textContent = rub(works);
      $('#s-total').textContent = rub(total);
      $('.summary__cta').disabled = !equip;
      $('.hint').hidden = !!equip;
    };
    $('#price').addEventListener('input', recalc);
    $('#c-level').addEventListener('change', recalc);
  }

  /* ---------- Экспорт CSV ---------- */
  function csv(rows) {
    const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    return '\uFEFF' + rows.map(r => r.map(q).join(';')).join('\r\n');
  }
  function download(name, text) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-export]'); if (!b) return;
    if (b.dataset.export === 'radar') {
      download('radar.csv', csv([
        ['ИНН', 'Наименование', 'Статус РТК', 'Активен в МСП', 'Тип', 'Категория', 'ОКВЭД', 'Отрасль', 'Факт. локация', 'Место регистрации (*)', 'Источник локации (*)', 'Выручка, млн руб.', 'Рост, %'],
        ...filtered().map(c => [
          c.inn, c.name, c.our ? 'Наш клиент' : 'Потенциал (не наш)', c.closed ? 'Исключён/Закрыт' : 'Действующий',
          c.type, c.cat, c.okved, c.ind, c.place, c.regPlace || c.place, c.relocSource || 'ФНС', c.rev, c.growth
        ])
      ]));
    } else {
      download('invest.csv', csv([['Проект', 'Инициатор', 'Территория', 'Начало', 'Ввод', 'Объём, млн ₽', 'Рабочих мест', 'Ключевой'],
        ...projects.map(p => [p.title, p.initiator, p.mo, p.start, p.finish, p.sum, p.jobs, p.key ? 'Да' : 'Нет'])]));
    }
  });

  initMap();
  renderRadar();
  renderInvest();
  renderCalc();
  route();
})();
