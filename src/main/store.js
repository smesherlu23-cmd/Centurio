'use strict';
/*
 * Store — JSON persistence for Centurio's library (apps, categories, settings).
 * Data lives in <userData>/centurio-data.json. Writes are atomic (temp + rename).
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DEFAULT_CATEGORIES = [
  { id: 'work', name: 'Работа', icon: 'briefcase', order: 0 },
  { id: 'create', name: 'Творчество', icon: 'wand', order: 1 },
  { id: 'games', name: 'Игры', icon: 'gamepad', order: 2 },
  { id: 'dev', name: 'Разработка', icon: 'code', order: 3 },
];

const DEFAULT_SETTINGS = {
  autostart: false,
  minimizeToTray: true,
  closeToTray: true,
  accent: '#f5f5f7',
  tileSize: 'large',   // 'large' | 'compact'
  showQuickRow: true,
};

class Store {
  constructor(filePath) {
    this.filePath = filePath;
    this.data = this._load();
  }

  _defaults() {
    return {
      version: 1,
      categories: DEFAULT_CATEGORIES.map((c) => ({ ...c })),
      apps: [],
      settings: { ...DEFAULT_SETTINGS },
    };
  }

  _load() {
    try {
      const raw = fs.readFileSync(this.filePath, 'utf8');
      const parsed = JSON.parse(raw);
      // Merge with defaults so new fields are always present.
      return {
        version: parsed.version || 1,
        categories: Array.isArray(parsed.categories) && parsed.categories.length
          ? parsed.categories
          : this._defaults().categories,
        apps: Array.isArray(parsed.apps) ? parsed.apps : [],
        settings: { ...DEFAULT_SETTINGS, ...(parsed.settings || {}) },
      };
    } catch (err) {
      return this._defaults();
    }
  }

  _persist() {
    const dir = path.dirname(this.filePath);
    fs.mkdirSync(dir, { recursive: true });
    const tmp = `${this.filePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.data, null, 2), 'utf8');
    fs.renameSync(tmp, this.filePath);
  }

  getState() {
    // Return a deep copy so callers can't mutate internal state directly.
    return JSON.parse(JSON.stringify(this.data));
  }

  // --- Apps ---
  addApp(app) {
    const now = Date.now();
    const record = {
      id: crypto.randomUUID(),
      name: app.name || 'Без названия',
      path: app.path || '',
      args: Array.isArray(app.args) ? app.args : [],
      sub: app.sub || '',
      categoryId: app.categoryId || (this.data.categories[0] && this.data.categories[0].id) || 'work',
      hue: typeof app.hue === 'number' ? app.hue : hueFromString(app.name || app.path || ''),
      favorite: !!app.favorite,
      quick: !!app.quick,
      hotkey: app.hotkey || null,
      lastLaunched: 0,
      launchCount: 0,
      addedAt: now,
    };
    this.data.apps.push(record);
    this._persist();
    return record;
  }

  updateApp(id, patch) {
    const app = this.data.apps.find((a) => a.id === id);
    if (!app) return null;
    const allowed = ['name', 'path', 'args', 'sub', 'categoryId', 'hue', 'favorite', 'quick', 'hotkey'];
    for (const key of allowed) {
      if (key in patch) app[key] = patch[key];
    }
    this._persist();
    return app;
  }

  removeApp(id) {
    const before = this.data.apps.length;
    this.data.apps = this.data.apps.filter((a) => a.id !== id);
    const changed = this.data.apps.length !== before;
    if (changed) this._persist();
    return changed;
  }

  markLaunched(id) {
    const app = this.data.apps.find((a) => a.id === id);
    if (!app) return null;
    app.lastLaunched = Date.now();
    app.launchCount = (app.launchCount || 0) + 1;
    this._persist();
    return app;
  }

  getApp(id) {
    return this.data.apps.find((a) => a.id === id) || null;
  }

  // --- Categories ---
  addCategory(name, icon) {
    const id = crypto.randomUUID();
    const order = this.data.categories.length;
    const cat = { id, name: name || 'Категория', icon: icon || 'folder', order };
    this.data.categories.push(cat);
    this._persist();
    return cat;
  }

  updateCategory(id, patch) {
    const cat = this.data.categories.find((c) => c.id === id);
    if (!cat) return null;
    if ('name' in patch) cat.name = patch.name;
    if ('icon' in patch) cat.icon = patch.icon;
    if ('order' in patch) cat.order = patch.order;
    this._persist();
    return cat;
  }

  removeCategory(id) {
    const before = this.data.categories.length;
    this.data.categories = this.data.categories.filter((c) => c.id !== id);
    // Move orphaned apps to the first remaining category.
    const fallback = this.data.categories[0] && this.data.categories[0].id;
    for (const app of this.data.apps) {
      if (app.categoryId === id) app.categoryId = fallback || null;
    }
    const changed = this.data.categories.length !== before;
    if (changed) this._persist();
    return changed;
  }

  // --- Settings ---
  setSetting(key, value) {
    if (!(key in DEFAULT_SETTINGS)) return this.data.settings;
    this.data.settings[key] = value;
    this._persist();
    return this.data.settings;
  }
}

// Deterministic hue (0..359) from a string — mirrors the design's colour-by-name look.
function hueFromString(str) {
  const hash = crypto.createHash('md5').update(String(str).toLowerCase()).digest();
  return ((hash[0] << 8) | hash[1]) % 360;
}

module.exports = { Store, DEFAULT_CATEGORIES, DEFAULT_SETTINGS, hueFromString };
