'use strict';
/*
 * demo-data.js
 * When Centurio runs inside Electron, window.centurio is provided by preload and
 * this file does nothing. When index.html is opened in a plain browser (for design
 * preview / testing), this installs a fully working in-memory mock of the same API,
 * seeded with the sample library from the product design.
 */
(function () {
  if (window.centurio) return; // real bridge present — nothing to do.

  const now = Date.now();
  const min = 60 * 1000;

  const CATEGORIES = [
    { id: 'work', name: 'Работа', icon: 'briefcase', order: 0 },
    { id: 'create', name: 'Творчество', icon: 'wand', order: 1 },
    { id: 'games', name: 'Игры', icon: 'gamepad', order: 2 },
  ];

  const A = (name, sub, categoryId, hue, opts = {}) => ({
    id: 'demo-' + name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
    name, sub, categoryId, hue,
    path: 'C:/Program Files/' + name + '/' + name.replace(/\s+/g, '') + '.exe',
    args: [],
    favorite: !!opts.fav,
    quick: !!opts.quick,
    hotkey: opts.hotkey || null,
    lastLaunched: opts.last || 0,
    launchCount: opts.count || 0,
    addedAt: now,
  });

  const apps = [
    // Work
    A('Notion', 'Документы и базы', 'work', 80, { fav: true, last: now - 2 * 60 * min, count: 12 }),
    A('Slack', 'Командный чат', 'work', 330, { count: 4 }),
    A('Windows Terminal', 'Командная строка', 'work', 250),
    A('Postman', 'API-клиент', 'work', 50),
    A('Chrome', 'Браузер', 'work', 230, { fav: true, count: 40 }),
    A('Zoom', 'Видеозвонки', 'work', 240),
    A('Linear', 'Задачи и спринты', 'work', 275),
    A('1Password', 'Пароли', 'work', 210, { fav: true }),
    // Create
    A('Blender', '3D-моделирование', 'create', 60),
    A('OBS Studio', 'Запись и стримы', 'create', 270),
    A('Photoshop', 'Графика', 'create', 240, { fav: true }),
    A('DaVinci Resolve', 'Видеомонтаж', 'create', 20),
    A('FL Studio', 'Аудиостудия', 'create', 300),
    // Games
    A('Counter-Strike 2', 'Steam', 'games', 150, { fav: true }),
    A('Baldur’s Gate 3', 'Steam', 'games', 35),
    A('Hades II', 'Steam', 'games', 15),
    A('Factorio', 'Steam', 'games', 85, { fav: true }),
    // Quick launch picks
    A('Telegram', 'Мессенджер', 'work', 230, { quick: true, last: now - 60 * min }),
    A('Figma', 'Дизайн', 'create', 20, { quick: true, last: now - 12 * min }),
    A('VS Code', 'Редактор кода', 'work', 250, { quick: true, last: now - 40 * min }),
    A('Spotify', 'Музыка', 'create', 150, { quick: true, last: now - 3 * 60 * min }),
    A('Obsidian', 'Заметки', 'work', 290, { quick: true }),
    A('Steam', 'Игры', 'games', 215, { quick: true }),
  ];

  const settings = {
    autostart: true,
    minimizeToTray: true,
    closeToTray: true,
    accent: '#f5f5f7',
    tileSize: 'large',
    showQuickRow: true,
  };

  const STORAGE_KEY = 'centurio-demo-state';
  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    return { categories: CATEGORIES, apps, settings };
  }
  let state = load();
  const running = new Set(['demo-notion', 'demo-chrome', 'demo-counter-strike-2']);
  const listeners = [];

  function persist() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (_) {} }
  function snapshot() {
    return JSON.parse(JSON.stringify({
      categories: state.categories,
      apps: state.apps,
      settings: state.settings,
      running: Array.from(running),
    }));
  }
  function emit() { const s = snapshot(); listeners.forEach((l) => l(s)); }
  function find(id) { return state.apps.find((a) => a.id === id); }
  function uid() { return 'app-' + Math.random().toString(36).slice(2, 10); }
  function hue(str) { let h = 0; for (const c of String(str).toLowerCase()) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

  window.centurio = {
    isElectron: false,
    platform: 'browser',
    getState: async () => snapshot(),
    onStateUpdate: (cb) => { listeners.push(cb); return () => { const i = listeners.indexOf(cb); if (i >= 0) listeners.splice(i, 1); }; },
    onWindowState: () => () => {},
    pickExecutable: async () => {
      const p = window.prompt('Путь к программе (демо-режим):', 'C:/Program Files/MyApp/MyApp.exe');
      if (!p) return null;
      const base = p.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
      return { path: p, suggestedName: base.replace(/[-_]+/g, ' ') };
    },
    addApp: async (data) => {
      const rec = {
        id: uid(), name: data.name || 'Без названия', path: data.path || '', args: data.args || [],
        sub: data.sub || '', categoryId: data.categoryId || 'work',
        hue: typeof data.hue === 'number' ? data.hue : hue(data.name), favorite: !!data.favorite,
        quick: !!data.quick, hotkey: data.hotkey || null, lastLaunched: 0, launchCount: 0, addedAt: Date.now(),
      };
      state.apps.push(rec); persist(); emit(); return rec;
    },
    updateApp: async (id, patch) => { const a = find(id); if (a) Object.assign(a, patch); persist(); emit(); return a; },
    removeApp: async (id) => { state.apps = state.apps.filter((a) => a.id !== id); running.delete(id); persist(); emit(); return true; },
    launchApp: async (id) => {
      const a = find(id); if (!a) return { ok: false, error: 'not found' };
      a.lastLaunched = Date.now(); a.launchCount = (a.launchCount || 0) + 1;
      running.add(id); persist(); emit();
      return { ok: true, running: true };
    },
    toggleFavorite: async (id) => { const a = find(id); if (a) a.favorite = !a.favorite; persist(); emit(); return true; },
    toggleQuick: async (id) => { const a = find(id); if (a) a.quick = !a.quick; persist(); emit(); return true; },
    showInFolder: async () => ({ ok: true }),
    addCategory: async (name, icon) => { const c = { id: uid(), name, icon: icon || 'folder', order: state.categories.length }; state.categories.push(c); persist(); emit(); return c; },
    updateCategory: async (id, patch) => { const c = state.categories.find((x) => x.id === id); if (c) Object.assign(c, patch); persist(); emit(); return c; },
    removeCategory: async (id) => {
      state.categories = state.categories.filter((c) => c.id !== id);
      const fb = state.categories[0] && state.categories[0].id;
      state.apps.forEach((a) => { if (a.categoryId === id) a.categoryId = fb; });
      persist(); emit(); return true;
    },
    setSetting: async (key, value) => { state.settings[key] = value; persist(); emit(); return state.settings; },
    windowMinimize: () => {}, windowMaximizeToggle: () => {}, windowClose: () => {}, windowHideToTray: () => {},
    isMaximized: async () => false,
    __resetDemo: () => { localStorage.removeItem(STORAGE_KEY); location.reload(); },
  };

  // Mark preview mode so styles center the frame like the design canvas.
  document.addEventListener('DOMContentLoaded', () => document.body.classList.add('preview'));
})();
