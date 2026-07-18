'use strict';
/*
 * Preload — the only bridge between the sandboxed renderer and the main process.
 * Exposes a small, explicit `window.centurio` API over contextBridge.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('centurio', {
  // Read the full library state (apps, categories, settings, running ids).
  getState: () => ipcRenderer.invoke('state:get'),

  // Subscribe to pushed state updates. Returns an unsubscribe function.
  onStateUpdate: (cb) => {
    const handler = (_e, state) => cb(state);
    ipcRenderer.on('state:update', handler);
    return () => ipcRenderer.removeListener('state:update', handler);
  },
  onWindowState: (cb) => {
    const handler = (_e, s) => cb(s);
    ipcRenderer.on('window:state', handler);
    return () => ipcRenderer.removeListener('window:state', handler);
  },

  // Apps
  pickExecutable: () => ipcRenderer.invoke('app:pickExecutable'),
  addApp: (data) => ipcRenderer.invoke('app:add', data),
  updateApp: (id, patch) => ipcRenderer.invoke('app:update', id, patch),
  removeApp: (id) => ipcRenderer.invoke('app:remove', id),
  launchApp: (id) => ipcRenderer.invoke('app:launch', id),
  toggleFavorite: (id) => ipcRenderer.invoke('app:toggleFavorite', id),
  toggleQuick: (id) => ipcRenderer.invoke('app:toggleQuick', id),
  showInFolder: (id) => ipcRenderer.invoke('app:showInFolder', id),

  // Categories
  addCategory: (name, icon) => ipcRenderer.invoke('category:add', name, icon),
  updateCategory: (id, patch) => ipcRenderer.invoke('category:update', id, patch),
  removeCategory: (id) => ipcRenderer.invoke('category:remove', id),

  // Settings
  setSetting: (key, value) => ipcRenderer.invoke('settings:set', key, value),

  // Window controls
  windowMinimize: () => ipcRenderer.send('window:minimize'),
  windowMaximizeToggle: () => ipcRenderer.send('window:maximizeToggle'),
  windowClose: () => ipcRenderer.send('window:close'),
  windowHideToTray: () => ipcRenderer.send('window:hideToTray'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),

  platform: process.platform,
  isElectron: true,
});
