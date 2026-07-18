'use strict';
/*
 * Centurio — renderer. Builds the whole UI from the library state and wires up
 * every interaction (launch, categorise, favourite, search, settings, tray).
 * Works both inside Electron (window.centurio from preload) and in a plain
 * browser (window.centurio from demo-data.js).
 */
(function () {
  const bridge = window.centurio;
  const appRoot = document.getElementById('app');
  const modalRoot = document.getElementById('modal-root');
  const toastRoot = document.getElementById('toast-root');

  // ---- Colour helpers: clean, saturated per-app tints (no haze, no glare) ----
  const cover = (h) => `linear-gradient(145deg, oklch(0.64 0.19 ${h}), oklch(0.46 0.19 ${h}))`;
  const chip = (h) => `linear-gradient(145deg, oklch(0.68 0.19 ${h}), oklch(0.52 0.19 ${h}))`;
  const glyphFg = () => `#ffffff`;

  // ---- Icons ----
  const ICONS = {
    grid: '<svg viewBox="0 0 20 20" fill="currentColor"><rect x="2" y="2" width="6.4" height="6.4" rx="1.7"/><rect x="11.6" y="2" width="6.4" height="6.4" rx="1.7"/><rect x="2" y="11.6" width="6.4" height="6.4" rx="1.7"/><rect x="11.6" y="11.6" width="6.4" height="6.4" rx="1.7"/></svg>',
    briefcase: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2.5" y="5.5" width="15" height="11" rx="2.2"/><path d="M7 5.5V4.3c0-.9.6-1.5 1.5-1.5h3c.9 0 1.5.6 1.5 1.5v1.2"/><path d="M2.5 10.5h15"/></svg>',
    wand: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10 2.5c-4.4 0-7.5 3.1-7.5 6.9 0 3 2.2 4.6 4.4 4.6 1 0 1.6.7 1.6 1.6 0 1.1.9 1.9 2 1.9 3.6 0 6.5-3 6.5-7.1 0-5-4.3-9-7-9.9Z"/><circle cx="6.6" cy="9" r="1"/><circle cx="9.4" cy="6.2" r="1"/><circle cx="13" cy="7.4" r="1"/></svg>',
    gamepad: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6.5 6.5h7a4 4 0 0 1 3.9 3.1l.7 3.2c.3 1.4-.8 2.7-2.2 2.7-.7 0-1.3-.3-1.7-.9l-.9-1.2a2 2 0 0 0-1.6-.8H8.1a2 2 0 0 0-1.6.8l-.9 1.2c-.4.6-1 .9-1.7.9-1.4 0-2.5-1.3-2.2-2.7l.7-3.2A4 4 0 0 1 6.5 6.5Z"/><path d="M5.6 9.3v2.2M4.5 10.4h2.2" stroke-linecap="round"/><circle cx="13.3" cy="9.9" r=".9" fill="currentColor" stroke="none"/><circle cx="15" cy="11.6" r=".9" fill="currentColor" stroke="none"/></svg>',
    code: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 6 3.5 10l4 4M12.5 6l4 4-4 4"/></svg>',
    folder: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 6C2.5 5 3.3 4.2 4.3 4.2h3.4l1.7 2.1h6.3c1 0 1.8.8 1.8 1.8v6.3c0 1-.8 1.8-1.8 1.8H4.3c-1 0-1.8-.8-1.8-1.8Z"/></svg>',
    star: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M9 2.2l1.9 4 4.3.5-3.2 2.9.9 4.3L9 11.9l-3.8 2 .9-4.3L2.9 6.7l4.3-.5Z"/></svg>',
    clock: '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="9" cy="9" r="6.6"/><path d="M9 5.2V9l2.6 1.6" stroke-linecap="round"/></svg>',
    search: '<svg viewBox="0 0 14 14" fill="none"><circle cx="6.2" cy="6.2" r="4.4" stroke="currentColor" stroke-width="1.3"/><path d="M9.6 9.6 12.4 12.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    play: '<svg viewBox="0 0 12 12" fill="currentColor"><path d="M3 1.5 10 6 3 10.5Z"/></svg>',
    playSmall: '<svg viewBox="0 0 10 10" fill="currentColor"><path d="M2.2 1.2 8.6 5 2.2 8.8Z"/></svg>',
    trayDown: '<svg viewBox="0 0 14 14" fill="none"><path d="M7 2v6M4.5 5.5 7 8l2.5-2.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><rect x="2" y="10.5" width="10" height="1.4" rx="0.7" fill="currentColor"/></svg>',
    minimize: '<svg viewBox="0 0 12 12"><rect x="1" y="5.4" width="10" height="1.2" rx="0.6" fill="currentColor"/></svg>',
    maximize: '<svg viewBox="0 0 12 12" fill="none"><rect x="1.6" y="1.6" width="8.8" height="8.8" rx="1.5" stroke="currentColor" stroke-width="1.2"/></svg>',
    close: '<svg viewBox="0 0 12 12"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    chevron: '<svg viewBox="0 0 10 10" fill="none"><path d="M2 3.5 5 6.5 8 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    gridSmall: '<svg viewBox="0 0 14 14" fill="currentColor"><rect x="1" y="1" width="5.2" height="5.2" rx="1.2"/><rect x="7.8" y="1" width="5.2" height="5.2" rx="1.2"/><rect x="1" y="7.8" width="5.2" height="5.2" rx="1.2"/><rect x="7.8" y="7.8" width="5.2" height="5.2" rx="1.2"/></svg>',
    listView: '<svg viewBox="0 0 14 14" fill="currentColor"><rect x="1" y="2" width="12" height="1.6" rx="0.8"/><rect x="1" y="6.2" width="12" height="1.6" rx="0.8"/><rect x="1" y="10.4" width="12" height="1.6" rx="0.8"/></svg>',
    plus: '<svg viewBox="0 0 14 14"><path d="M7 2v10M2 7h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    settings: '<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="2.6" stroke="currentColor" stroke-width="1.5"/><path d="M10 1.8v1.8M10 16.4v1.8M2.2 10H4M16 10h1.8M4.3 4.3l1.3 1.3M14.4 14.4l1.3 1.3M15.7 4.3l-1.3 1.3M5.6 14.4l-1.3 1.3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    folderOpen: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M2 4.5C2 3.7 2.7 3 3.5 3h2.7l1.3 1.6h4.9c.8 0 1.5.7 1.5 1.5v.4H4.6c-.7 0-1.3.4-1.5 1L2 12Z"/><path d="M2 12l1.1-4.5c.2-.6.8-1 1.5-1H15l-1.4 4.5c-.2.6-.8 1-1.5 1H2Z"/></svg>',
    trash: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10M6.5 4.5V3.5c0-.6.4-1 1-1h1c.6 0 1 .4 1 1v1M5 4.5l.6 8c0 .6.5 1 1 1h2.8c.5 0 1-.4 1-1l.6-8"/></svg>',
    pencil: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><path d="M10.5 3.2l2.3 2.3M3 11.5l7.8-7.8 2.3 2.3L5.3 13.8 2.5 14.5Z"/></svg>',
    bolt: '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8.8 1.5 3.5 9h3.4l-.7 5.5L12.5 6.5H8.9Z"/></svg>',
  };
  const CATEGORY_ICON_NAMES = ['briefcase', 'wand', 'gamepad', 'code', 'folder'];

  function icon(name, size, cls) {
    const span = document.createElement('span');
    span.className = 'ic' + (cls ? ' ' + cls : '');
    span.style.width = (size || 16) + 'px';
    span.style.height = (size || 16) + 'px';
    span.innerHTML = ICONS[name] || '';
    return span;
  }

  // ---- DOM helper ----
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'style') node.setAttribute('style', v);
        else if (k === 'html') node.innerHTML = v;
        else if (k === 'dataset') Object.assign(node.dataset, v);
        else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
        else node.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === 'object' ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  // ---- State ----
  let state = { categories: [], apps: [], settings: {}, running: [] };
  const view = { filter: 'all', query: '', sort: 'alpha', mode: 'grid' };

  function runningSet() { return new Set(state.running || []); }
  function catById(id) { return state.categories.find((c) => c.id === id); }

  // ---- Formatting ----
  function timeAgo(ts) {
    if (!ts) return '';
    const diff = Date.now() - ts;
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'только что';
    if (m < 60) return m + ' ' + plural(m, 'минуту', 'минуты', 'минут') + ' назад';
    const h = Math.floor(m / 60);
    if (h < 24) return h + ' ' + plural(h, 'час', 'часа', 'часов') + ' назад';
    const d = Math.floor(h / 24);
    return d + ' ' + plural(d, 'день', 'дня', 'дней') + ' назад';
  }
  function plural(n, one, few, many) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  }
  function plu(n) { return plural(n, 'приложение', 'приложения', 'приложений'); }

  // ---- Toast ----
  function toast(msg, isErr) {
    const t = el('div', { class: 'toast' + (isErr ? ' err' : '') }, el('span', { class: 'td' }), msg);
    toastRoot.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; setTimeout(() => t.remove(), 320); }, 2600);
  }

  // ---- Actions ----
  async function launch(id) {
    const res = await bridge.launchApp(id);
    if (res && !res.ok) toast(res.error || 'Не удалось запустить', true);
    else {
      const a = state.apps.find((x) => x.id === id);
      if (a) toast('Запуск: ' + a.name);
    }
  }
  async function toggleFav(id, ev) { if (ev) ev.stopPropagation(); await bridge.toggleFavorite(id); }
  async function showInFolder(id) { const r = await bridge.showInFolder(id); if (r && !r.ok) toast(r.error || 'Не найдено', true); }

  // ================= RENDER =================
  function render() {
    // Preserve content scroll + search focus/caret across full rebuilds.
    const prevContent = appRoot.querySelector('.content');
    const scroll = prevContent ? prevContent.scrollTop : 0;
    const active = document.activeElement;
    const searchFocused = active && active.id === 'search-input';
    const caret = searchFocused ? active.selectionStart : null;

    document.documentElement.style.setProperty('--accent', state.settings.accent || '#f5f5f7');
    document.documentElement.style.setProperty('--tile-min', state.settings.tileSize === 'compact' ? '152px' : '198px');

    appRoot.setAttribute('aria-busy', 'false');
    appRoot.innerHTML = '';
    appRoot.append(buildTitlebar(), buildBody());

    const c = appRoot.querySelector('.content');
    if (c) c.scrollTop = scroll;
    if (searchFocused) {
      const s = document.getElementById('search-input');
      if (s) { s.focus(); if (caret != null) { try { s.setSelectionRange(caret, caret); } catch (_) {} } }
    }
  }

  function buildTitlebar() {
    return el('div', { class: 'titlebar' },
      el('div', { class: 'tb-left' },
        el('span', { class: 'tb-brand' }, 'Centurio'),
        el('span', { class: 'tb-sep' }),
        el('span', { class: 'tb-tag' }, 'быстрый запуск приложений'),
      ),
      el('div', { class: 'tb-right' },
        el('button', { class: 'tb-btn', title: 'Свернуть в трей', onclick: () => bridge.windowHideToTray() }, icon('trayDown', 14)),
        el('span', { class: 'tb-divider' }),
        el('button', { class: 'tb-btn', title: 'Свернуть', onclick: () => bridge.windowMinimize() }, icon('minimize', 12)),
        el('button', { class: 'tb-btn', title: 'Развернуть', onclick: () => bridge.windowMaximizeToggle() }, icon('maximize', 12)),
        el('button', { class: 'tb-btn tb-close', title: 'Закрыть', onclick: () => bridge.windowClose() }, icon('close', 12)),
      ),
    );
  }

  function buildBody() {
    return el('div', { class: 'frame-body' }, buildRail(), buildSidebar(), buildMain());
  }

  // ---- Rail ----
  function buildRail() {
    const cats = [...state.categories].sort((a, b) => (a.order || 0) - (b.order || 0));
    const railItem = (name, active, onclick, title) => el('div', { class: 'rail-item-wrap' },
      active ? el('span', { class: 'active-bar' }) : null,
      el('div', { class: 'rail-item' + (active ? ' active' : ''), title, onclick }, name),
    );

    return el('div', { class: 'rail' },
      el('div', { class: 'rail-logo' }, 'C'),
      el('div', { class: 'rail-hr' }),
      railItem(icon('grid', 19), view.filter === 'all', () => setFilter('all'), 'Все приложения'),
      ...cats.map((cat) => railItem(
        icon(CATEGORY_ICON_NAMES.includes(cat.icon) ? cat.icon : 'folder', 19),
        view.filter === 'category:' + cat.id,
        () => setFilter('category:' + cat.id),
        cat.name,
      )),
      el('div', { class: 'rail-spacer' }),
      el('div', { class: 'rail-add', title: 'Добавить категорию', onclick: openCategoryModal }, icon('plus', 16)),
      el('div', { class: 'rail-item', title: 'Настройки', style: 'margin-bottom:10px', onclick: openSettingsModal }, icon('settings', 18)),
      el('div', { class: 'rail-avatar', title: 'Аккаунт' }, 'АК'),
    );
  }

  // ---- Sidebar ----
  function currentTitle() {
    if (view.query) return 'Поиск';
    if (view.filter === 'all') return 'Все приложения';
    if (view.filter === 'favorites') return 'Избранное';
    if (view.filter === 'recent') return 'Недавние';
    if (view.filter === 'running') return 'Запущено';
    if (view.filter.startsWith('category:')) {
      const c = catById(view.filter.slice(9));
      return c ? c.name : 'Категория';
    }
    return 'Все приложения';
  }

  function buildSidebar() {
    const apps = state.apps;
    const running = runningSet();
    const favCount = apps.filter((a) => a.favorite).length;
    const recentCount = apps.filter((a) => a.lastLaunched > 0).length;

    const showItem = (iconNode, label, count, filter, countColor) => el('div', {
      class: 'sb-item' + (view.filter === filter ? ' active' : ''),
      onclick: () => setFilter(filter),
    }, el('span', { class: 'sb-ico' }, iconNode), el('span', { class: 'sb-name' }, label),
      el('span', { class: 'sb-count', style: countColor ? 'color:' + countColor : '' }, String(count)));

    const recents = [...apps].filter((a) => a.lastLaunched > 0)
      .sort((a, b) => b.lastLaunched - a.lastLaunched).slice(0, 4);

    return el('div', { class: 'sidebar' },
      el('div', { class: 'sb-title' }, currentTitle()),
      el('div', { class: 'sb-sub' }, `${apps.length} ${plu(apps.length)} · ${state.categories.length} ${plural(state.categories.length, 'категория', 'категории', 'категорий')}`),
      el('div', { class: 'sb-hr' }),
      el('div', { class: 'sb-label' }, 'Показать'),
      showItem(icon('grid', 16), 'Все приложения', apps.length, 'all'),
      showItem(icon('star', 16), 'Избранное', favCount, 'favorites'),
      showItem(icon('clock', 16), 'Недавние', recentCount, 'recent'),
      showItem(el('span', { class: 'sb-dot' }), 'Запущено', running.size, 'running', '#4ade80'),

      recents.length ? el('div', { class: 'sb-hr' }) : null,
      recents.length ? el('div', { class: 'sb-label' }, 'Недавние') : null,
      ...recents.map((a) => el('div', { class: 'sb-recent', onclick: () => launch(a.id) },
        el('div', { class: 'mini', style: `background:${chip(a.hue)}; color:${glyphFg(a.hue)}` }, initials(a.name)),
        el('div', { class: 'meta' },
          el('div', { class: 'rname' }, a.name),
          el('div', { class: 'rtime' }, timeAgo(a.lastLaunched)),
        ),
      )),

      buildSidebarFooter(),
    );
  }

  function buildSidebarFooter() {
    const s = state.settings;
    const toggleRow = (label, key) => el('div', { class: 'sb-toggle-row', onclick: () => bridge.setSetting(key, !s[key]) },
      el('span', { class: 'lbl' }, label),
      el('span', { class: 'switch' + (s[key] ? ' on' : '') }, el('span', { class: 'knob' })),
    );
    return el('div', { class: 'sb-footer' },
      toggleRow('Автозапуск с Windows', 'autostart'),
      toggleRow('Сворачивать в трей', 'minimizeToTray'),
      el('div', { class: 'sb-version' },
        el('span', {}, 'Centurio'),
        el('span', {}, 'v1.2.0'),
      ),
    );
  }

  // ---- Main ----
  function buildMain() {
    return el('div', { class: 'main' }, buildToolbar(), buildContent(), buildStatusbar());
  }

  function buildToolbar() {
    const sortLabels = { alpha: 'По алфавиту', recent: 'Недавние', added: 'Недавно добавленные' };
    return el('div', { class: 'toolbar' },
      el('label', { class: 'search' },
        icon('search', 14),
        el('input', {
          id: 'search-input', type: 'text', placeholder: 'Поиск приложений…', value: view.query, autocomplete: 'off',
          oninput: (e) => { view.query = e.target.value; render(); },
        }),
        el('span', { class: 'kbd' }, 'Ctrl+K'),
      ),
      el('div', { class: 'toolbar-spacer' }),
      el('button', { class: 'tb-select', title: 'Сортировка', onclick: cycleSort },
        sortLabels[view.sort], icon('chevron', 9)),
      el('div', { class: 'viewtoggle' },
        el('span', { class: view.mode === 'grid' ? 'active' : '', title: 'Сетка', onclick: () => { view.mode = 'grid'; render(); } }, icon('gridSmall', 13)),
        el('span', { class: view.mode === 'list' ? 'active' : '', title: 'Список', onclick: () => { view.mode = 'list'; render(); } }, icon('listView', 13)),
      ),
      el('button', { class: 'btn-primary', onclick: () => openAppModal() }, icon('plus', 13), 'Добавить приложение'),
    );
  }

  function cycleSort() {
    const order = ['alpha', 'recent', 'added'];
    view.sort = order[(order.indexOf(view.sort) + 1) % order.length];
    render();
  }

  function sortApps(apps) {
    const copy = [...apps];
    if (view.sort === 'alpha') copy.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    else if (view.sort === 'recent') copy.sort((a, b) => (b.lastLaunched || 0) - (a.lastLaunched || 0));
    else if (view.sort === 'added') copy.sort((a, b) => (b.addedAt || 0) - (a.addedAt || 0));
    return copy;
  }

  function matchesQuery(a) {
    const q = view.query.trim().toLowerCase();
    if (!q) return true;
    return a.name.toLowerCase().includes(q) || (a.sub || '').toLowerCase().includes(q);
  }

  // Build list of sections [{ id, name, meta, apps, editable }]
  function computeSections() {
    const running = runningSet();
    let apps = state.apps.filter(matchesQuery);

    if (view.query.trim()) {
      apps = sortApps(apps);
      return [{ id: 'search', name: 'Результаты поиска', apps }];
    }
    if (view.filter === 'favorites') {
      return [{ id: 'fav', name: 'Избранное', apps: sortApps(apps.filter((a) => a.favorite)) }];
    }
    if (view.filter === 'recent') {
      const list = apps.filter((a) => a.lastLaunched > 0).sort((a, b) => b.lastLaunched - a.lastLaunched);
      return [{ id: 'recent', name: 'Недавние', apps: list }];
    }
    if (view.filter === 'running') {
      return [{ id: 'running', name: 'Запущено', apps: sortApps(apps.filter((a) => running.has(a.id))) }];
    }
    if (view.filter.startsWith('category:')) {
      const cid = view.filter.slice(9);
      const c = catById(cid);
      return [{ id: cid, name: c ? c.name : 'Категория', apps: sortApps(apps.filter((a) => a.categoryId === cid)), editable: !!c, categoryId: cid }];
    }
    // all: one section per category, in order, only non-empty (plus keep order)
    const cats = [...state.categories].sort((a, b) => (a.order || 0) - (b.order || 0));
    const sections = cats.map((c) => ({
      id: c.id, name: c.name, categoryId: c.id, editable: true,
      apps: sortApps(apps.filter((a) => a.categoryId === c.id)),
    }));
    // apps with an unknown/missing category
    const known = new Set(cats.map((c) => c.id));
    const orphan = sortApps(apps.filter((a) => !known.has(a.categoryId)));
    if (orphan.length) sections.push({ id: 'other', name: 'Без категории', apps: orphan });
    return sections.filter((s) => s.apps.length > 0);
  }

  function buildContent() {
    const content = el('div', { class: 'content' });
    const running = runningSet();
    const isAll = view.filter === 'all' && !view.query.trim();

    // Empty library
    if (state.apps.length === 0) {
      content.append(emptyState(
        'Библиотека пуста',
        'Добавьте первое приложение — выберите его исполняемый файл, и Centurio закрепит его для быстрого запуска.',
        'Добавить приложение', () => openAppModal(),
      ));
      return content;
    }

    // Hero: last launched app (only on the default view)
    if (isAll) {
      const heroApp = [...state.apps].filter((a) => a.lastLaunched > 0).sort((a, b) => b.lastLaunched - a.lastLaunched)[0];
      if (heroApp) content.append(buildHero(heroApp, running.has(heroApp.id)));
    }

    // Quick launch row
    if (isAll && state.settings.showQuickRow) {
      const quick = state.apps.filter((a) => a.quick);
      if (quick.length) content.append(buildQuickRow(quick));
    }

    const sections = computeSections();
    if (sections.length === 0 || sections.every((s) => s.apps.length === 0)) {
      content.append(emptyState('Ничего не найдено', view.query ? 'Попробуйте изменить запрос.' : 'В этом разделе пока нет приложений.', null, null));
      return content;
    }

    for (const sec of sections) {
      if (!sec.apps.length) continue;
      content.append(buildSectionHead(sec));
      content.append(view.mode === 'list' ? buildList(sec.apps, running) : buildGrid(sec.apps, running));
    }
    return content;
  }

  function buildHero(a, isRunning) {
    return el('div', { class: 'hero' },
      el('span', { class: 'ghost' }, initials(a.name)),
      el('div', { class: 'inner' },
        el('div', { class: 'eyebrow' }, el('span', { class: 'dot' }), el('span', {}, isRunning ? 'ПРОДОЛЖИТЬ · ОТКРЫТО СЕЙЧАС' : 'ПРОДОЛЖИТЬ · НЕДАВНО ОТКРЫТО')),
        el('h2', {}, a.name),
        el('div', { class: 'desc' }, a.sub || 'Быстрый доступ к последнему запущенному приложению.'),
        el('div', { class: 'actions' },
          el('button', { class: 'btn-open', onclick: () => launch(a.id) }, icon('play', 12), 'Открыть'),
          el('button', { class: 'btn-ghost', onclick: () => showInFolder(a.id) }, 'Показать в папке'),
          a.lastLaunched ? el('span', { class: 'meta' }, 'запущено ' + timeAgo(a.lastLaunched)) : null,
        ),
      ),
    );
  }

  function buildQuickRow(quick) {
    const frag = el('div', {});
    frag.append(el('div', { class: 'section-head' },
      el('span', { class: 'title' }, 'Быстрый запуск'),
      el('span', { class: 'meta' }, 'закреплено · глобальные горячие клавиши'),
    ));
    const row = el('div', { class: 'quickrow' });
    quick.forEach((q, i) => {
      const key = q.hotkey || ('Ctrl+' + (i + 1));
      row.append(el('div', { class: 'quick-card', onclick: () => launch(q.id), oncontextmenu: (e) => { e.preventDefault(); openAppModal(q); } },
        el('div', { class: 'key' }, key),
        el('div', { class: 'qi', style: `background:${chip(q.hue)}; color:${glyphFg(q.hue)}` }, initials(q.name)),
        el('div', { class: 'qn' }, q.name),
        el('div', { class: 'qs' }, q.sub || ''),
      ));
    });
    frag.append(row);
    return frag;
  }

  function buildSectionHead(sec) {
    return el('div', { class: 'section-head' },
      el('span', { class: 'sq' }),
      el('span', { class: 'title' }, sec.name),
      el('span', { class: 'meta' }, `${sec.apps.length} ${plu(sec.apps.length)}`),
      el('span', { class: 'grow' }),
      sec.editable ? el('span', { class: 'edit', onclick: () => openCategoryModal(sec.categoryId) }, 'Изменить') : null,
    );
  }

  function buildGrid(apps, running) {
    const grid = el('div', { class: 'grid' });
    for (const a of apps) grid.append(buildTile(a, running.has(a.id)));
    return grid;
  }

  function buildTile(a, isRunning) {
    const star = el('span', { class: 'star' + (a.favorite ? ' on' : ''), title: a.favorite ? 'В избранном' : 'В избранное', onclick: (e) => toggleFav(a.id, e) });
    const starSvg = icon('star', 13);
    if (a.favorite) starSvg.querySelector('svg').setAttribute('fill', '#f5c518');
    star.append(starSvg);

    return el('div', { class: 'tile', onclick: () => launch(a.id), oncontextmenu: (e) => { e.preventDefault(); openAppModal(a); } },
      el('div', { class: 'cover', style: `background:${cover(a.hue)}` },
        el('span', { class: 'glyph', style: `color:${glyphFg(a.hue)}` }, initials(a.name)),
        isRunning ? el('span', { class: 'run-badge' }, el('span', { class: 'd' }), 'Запущено') : null,
        star,
        el('span', { class: 'play' }, el('span', { class: 'pbtn' }, icon('play', 18))),
      ),
      el('div', { class: 'foot' },
        el('div', { class: 'info' },
          el('div', { class: 'tn' }, a.name),
          el('div', { class: 'ts' }, a.sub || pathTail(a.path)),
        ),
        el('div', { class: 'go', title: 'Запустить', onclick: (e) => { e.stopPropagation(); launch(a.id); } }, icon('playSmall', 10)),
      ),
    );
  }

  function buildList(apps, running) {
    const list = el('div', { class: 'list' });
    for (const a of apps) {
      const isRunning = running.has(a.id);
      list.append(el('div', { class: 'row', onclick: () => launch(a.id), oncontextmenu: (e) => { e.preventDefault(); openAppModal(a); } },
        el('div', { class: 'ri', style: `background:${chip(a.hue)}; color:${glyphFg(a.hue)}` }, initials(a.name)),
        el('div', { class: 'rmeta' },
          el('div', { class: 'rn' }, a.name),
          el('div', { class: 'rs' }, a.sub || pathTail(a.path)),
        ),
        isRunning ? el('div', { class: 'rrun' }, el('span', { class: 'd' }), 'Запущено') : null,
        el('div', { class: 'ract', title: a.favorite ? 'В избранном' : 'В избранное', style: a.favorite ? 'color:#f5c518' : '', onclick: (e) => toggleFav(a.id, e) }, starFor(a.favorite)),
        el('div', { class: 'ract', title: 'Изменить', onclick: (e) => { e.stopPropagation(); openAppModal(a); } }, icon('pencil', 14)),
      ));
    }
    return list;
  }

  function starFor(on) {
    const s = icon('star', 14);
    if (on) s.querySelector('svg').setAttribute('fill', '#f5c518');
    return s;
  }

  function buildStatusbar() {
    const running = runningSet();
    return el('div', { class: 'statusbar' },
      el('span', { class: 'live' }, el('span', { class: 'd' }), 'Centurio работает в фоне — значок в трее'),
      running.size ? el('span', { class: 'mono' }, `${running.size} ${plural(running.size, 'запущено', 'запущено', 'запущено')}`) : null,
      el('span', { class: 'grow' }),
      el('span', { class: 'mono' }, `${state.apps.length} ${plu(state.apps.length)} · ${state.categories.length} ${plural(state.categories.length, 'категория', 'категории', 'категорий')}`),
    );
  }

  function emptyState(title, text, btnLabel, onclick) {
    return el('div', { class: 'empty' },
      el('div', { class: 'ei' }, icon('grid', 26)),
      el('h3', {}, title),
      el('p', {}, text),
      btnLabel ? el('button', { class: 'btn-primary', style: 'margin:0 auto', onclick }, icon('plus', 13), btnLabel) : null,
    );
  }

  // ---- Small utils ----
  function initials(name) {
    const n = (name || '?').trim();
    return n ? n[0].toUpperCase() : '?';
  }
  function pathTail(p) {
    if (!p) return '';
    const parts = p.split(/[\\/]/);
    return parts[parts.length - 1] || p;
  }

  // ---- Filter switching ----
  function setFilter(f) { view.filter = f; view.query = ''; render(); }

  // ================= MODALS =================
  function openModal(node, opts) {
    closeModal();
    const backdrop = el('div', { class: 'modal-backdrop', onclick: (e) => { if (e.target === backdrop) closeModal(); } }, node);
    modalRoot.appendChild(backdrop);
    const focusEl = node.querySelector('input, select, button');
    if (focusEl && !(opts && opts.noFocus)) setTimeout(() => focusEl.focus(), 30);
  }
  function closeModal() { modalRoot.innerHTML = ''; }

  // ---- Add / edit app ----
  function openAppModal(existing) {
    const isEdit = !!existing;
    const draft = existing ? { ...existing } : {
      name: '', path: '', sub: '', categoryId: (state.categories[0] && state.categories[0].id) || 'work',
      hue: Math.floor(Math.random() * 360), favorite: false, quick: false,
    };

    const preview = el('div', { class: 'hue-preview', style: `background:${chip(draft.hue)}; color:${glyphFg(draft.hue)}` }, initials(draft.name));
    function refreshPreview() {
      preview.style.background = chip(draft.hue);
      preview.style.color = glyphFg(draft.hue);
      preview.textContent = initials(draft.name);
    }

    const nameInput = el('input', { type: 'text', value: draft.name, placeholder: 'Например, Visual Studio Code', oninput: (e) => { draft.name = e.target.value; refreshPreview(); } });
    const pathInput = el('input', { type: 'text', value: draft.path, placeholder: 'Путь к .exe', oninput: (e) => { draft.path = e.target.value; } });
    const subInput = el('input', { type: 'text', value: draft.sub, placeholder: 'Короткое описание (необязательно)', oninput: (e) => { draft.sub = e.target.value; } });

    const catSelect = el('select', { onchange: (e) => { draft.categoryId = e.target.value; } },
      ...state.categories.map((c) => el('option', { value: c.id, selected: c.id === draft.categoryId || null }, c.name)));

    const hueSlider = el('input', { type: 'range', class: 'hue-slider', min: '0', max: '359', value: String(draft.hue), oninput: (e) => { draft.hue = parseInt(e.target.value, 10); refreshPreview(); } });

    const favSwitch = el('span', { class: 'switch' + (draft.favorite ? ' on' : '') }, el('span', { class: 'knob' }));
    const quickSwitch = el('span', { class: 'switch' + (draft.quick ? ' on' : '') }, el('span', { class: 'knob' }));

    async function browse() {
      const picked = await bridge.pickExecutable();
      if (!picked) return;
      draft.path = picked.path;
      pathInput.value = picked.path;
      if (!draft.name && picked.suggestedName) {
        draft.name = picked.suggestedName;
        nameInput.value = picked.suggestedName;
        refreshPreview();
      }
    }

    async function save() {
      if (!draft.name.trim()) { toast('Укажите название', true); nameInput.focus(); return; }
      if (!draft.path.trim()) { toast('Выберите файл приложения', true); return; }
      if (isEdit) await bridge.updateApp(existing.id, { name: draft.name, path: draft.path, sub: draft.sub, categoryId: draft.categoryId, hue: draft.hue, favorite: draft.favorite, quick: draft.quick });
      else await bridge.addApp(draft);
      closeModal();
      toast(isEdit ? 'Сохранено' : 'Приложение добавлено');
    }

    async function remove() {
      await bridge.removeApp(existing.id);
      closeModal();
      toast('Удалено');
    }

    const modal = el('div', { class: 'modal' },
      el('h3', {}, isEdit ? 'Изменить приложение' : 'Добавить приложение'),
      el('div', { class: 'm-sub' }, 'Закрепите программу для быстрого запуска из Centurio.'),

      el('div', { class: 'field' }, el('label', {}, 'Файл приложения'),
        el('div', { class: 'with-btn' }, pathInput, el('button', { class: 'btn-outline', onclick: browse }, icon('folderOpen', 14), 'Обзор'))),
      el('div', { class: 'field' }, el('label', {}, 'Название'), nameInput),
      el('div', { class: 'field' }, el('label', {}, 'Описание'), subInput),
      el('div', { class: 'field' }, el('label', {}, 'Категория'), catSelect),
      el('div', { class: 'field' }, el('label', {}, 'Цвет плитки'),
        el('div', { class: 'hue-row' }, preview, hueSlider)),

      el('div', { class: 'checkbox-row', onclick: () => { draft.favorite = !draft.favorite; favSwitch.classList.toggle('on', draft.favorite); } },
        el('div', {}, el('div', { class: 'cl' }, 'В избранное'), el('div', { class: 'ch' }, 'Показывать в разделе «Избранное»')), favSwitch),
      el('div', { class: 'checkbox-row', onclick: () => { draft.quick = !draft.quick; quickSwitch.classList.toggle('on', draft.quick); } },
        el('div', {}, el('div', { class: 'cl' }, 'Быстрый запуск'), el('div', { class: 'ch' }, 'Закрепить сверху и назначить горячую клавишу')), quickSwitch),

      el('div', { class: 'modal-actions' },
        isEdit ? el('button', { class: 'btn-danger-ghost', onclick: remove }, 'Удалить') : null,
        el('span', { class: 'grow' }),
        el('button', { class: 'btn-outline', onclick: closeModal }, 'Отмена'),
        el('button', { class: 'btn-primary', onclick: save }, isEdit ? 'Сохранить' : 'Добавить'),
      ),
    );
    openModal(modal);
  }

  // ---- Category management ----
  function openCategoryModal(focusId) {
    const nameInput = el('input', { type: 'text', placeholder: 'Название категории', onkeydown: (e) => { if (e.key === 'Enter') addCat(); } });
    async function addCat() {
      const name = nameInput.value.trim();
      if (!name) return;
      const iconName = CATEGORY_ICON_NAMES[state.categories.length % CATEGORY_ICON_NAMES.length];
      await bridge.addCategory(name, iconName);
      nameInput.value = '';
      rebuild();
      nameInput.focus();
    }
    async function removeCat(id) {
      await bridge.removeCategory(id);
      rebuild();
    }
    async function renameCat(id, value) {
      await bridge.updateCategory(id, { name: value });
    }

    const listWrap = el('div', { class: 'cat-list' });
    function rebuild() {
      listWrap.innerHTML = '';
      const cats = [...state.categories].sort((a, b) => (a.order || 0) - (b.order || 0));
      for (const c of cats) {
        const count = state.apps.filter((a) => a.categoryId === c.id).length;
        listWrap.append(el('div', { class: 'cat-item' },
          icon(CATEGORY_ICON_NAMES.includes(c.icon) ? c.icon : 'folder', 16),
          el('input', { class: 'cn', type: 'text', value: c.name, style: 'background:transparent;border:none;color:var(--text);outline:none;font-size:13px', onchange: (e) => renameCat(c.id, e.target.value.trim() || c.name) }),
          el('span', { class: 'cc' }, `${count}`),
          el('span', { class: 'cx', title: 'Удалить категорию', onclick: () => removeCat(c.id) }, icon('trash', 15)),
        ));
      }
    }
    rebuild();

    const modal = el('div', { class: 'modal wide' },
      el('h3', {}, 'Категории'),
      el('div', { class: 'm-sub' }, 'Группируйте приложения по смыслу — «Работа», «Игры», «Разработка».'),
      listWrap,
      el('div', { class: 'field' }, el('label', {}, 'Новая категория'),
        el('div', { class: 'with-btn' }, nameInput, el('button', { class: 'btn-outline', onclick: addCat }, icon('plus', 13), 'Добавить'))),
      el('div', { class: 'modal-actions' },
        el('span', { class: 'grow' }),
        el('button', { class: 'btn-primary', onclick: closeModal }, 'Готово'),
      ),
    );
    openModal(modal, { noFocus: true });
    setTimeout(() => nameInput.focus(), 30);
  }

  // ---- Settings ----
  function openSettingsModal() {
    const s = state.settings;
    const accents = ['#f5f5f7', '#4f7dff', '#3ecfaf', '#f0a020'];

    const swatchRow = el('div', { class: 'accent-swatches' },
      ...accents.map((c) => el('div', {
        class: 'swatch' + (s.accent === c ? ' active' : ''), style: `background:${c}`,
        onclick: async (e) => {
          await bridge.setSetting('accent', c);
          swatchRow.querySelectorAll('.swatch').forEach((n) => n.classList.remove('active'));
          e.target.classList.add('active');
        },
      })));

    const tileSelect = el('select', { onchange: (e) => bridge.setSetting('tileSize', e.target.value) },
      el('option', { value: 'large', selected: s.tileSize !== 'compact' || null }, 'Крупные'),
      el('option', { value: 'compact', selected: s.tileSize === 'compact' || null }, 'Компактные'),
    );

    const settingSwitch = (label, hint, key) => {
      const sw = el('span', { class: 'switch' + (s[key] ? ' on' : '') }, el('span', { class: 'knob' }));
      return el('div', { class: 'checkbox-row', onclick: async () => { const nv = !s[key]; s[key] = nv; sw.classList.toggle('on', nv); await bridge.setSetting(key, nv); } },
        el('div', {}, el('div', { class: 'cl' }, label), el('div', { class: 'ch' }, hint)), sw);
    };

    const modal = el('div', { class: 'modal' },
      el('h3', {}, 'Настройки'),
      el('div', { class: 'm-sub' }, 'Centurio — ваш пульт управления приложениями.'),

      el('div', { class: 'field' }, el('label', {}, 'Акцентный цвет'), swatchRow),
      el('div', { class: 'field', style: 'margin-top:16px' }, el('label', {}, 'Размер плиток'), tileSelect),

      settingSwitch('Показывать «Быстрый запуск»', 'Ряд закреплённых приложений сверху', 'showQuickRow'),
      settingSwitch('Автозапуск с Windows', 'Запускать Centurio при входе в систему', 'autostart'),
      settingSwitch('Сворачивать в трей', 'Кнопка «свернуть» прячет окно в трей', 'minimizeToTray'),
      settingSwitch('Закрывать в трей', 'Крестик не закрывает приложение, а прячет его', 'closeToTray'),

      el('div', { class: 'field', style: 'margin-top:16px' },
        el('button', { class: 'btn-outline', style: 'width:100%; justify-content:center', onclick: () => openCategoryModal() }, icon('folder', 15), 'Управление категориями')),

      el('div', { class: 'modal-actions' },
        el('span', { class: 'grow' }),
        el('button', { class: 'btn-primary', onclick: closeModal }, 'Готово'),
      ),
    );
    openModal(modal, { noFocus: true });
  }

  // ================= INIT =================
  function applyState(next) {
    state = next || state;
    if (!state.settings) state.settings = {};
    if (!state.running) state.running = [];
    render();
  }

  // Global keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const s = document.getElementById('search-input');
      if (s) { s.focus(); s.select(); }
    } else if (e.key === 'Escape') {
      if (modalRoot.children.length) { closeModal(); return; }
      if (view.query) { view.query = ''; render(); }
    }
  });

  async function init() {
    try {
      const s = await bridge.getState();
      applyState(s);
    } catch (err) {
      console.error('Не удалось загрузить состояние', err);
    }
    if (bridge.onStateUpdate) bridge.onStateUpdate((s) => applyState(s));
  }

  if (!bridge) {
    appRoot.innerHTML = '<div style="padding:40px;color:#888">Centurio: мост недоступен.</div>';
  } else {
    init();
  }
})();
