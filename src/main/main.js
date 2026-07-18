'use strict';
/*
 * Centurio — main process.
 * Frameless window with a custom title bar, system-tray integration,
 * autostart, global quick-launch hotkeys, and IPC for the renderer.
 */
const {
  app, BrowserWindow, ipcMain, Tray, dialog, globalShortcut, shell, nativeImage,
} = require('electron');
const path = require('path');

const { Store } = require('./store');
const { Launcher } = require('./launcher');
const { createTray } = require('./tray');

// Single-instance lock: a second launch focuses the existing window.
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

let mainWindow = null;
let trayHandle = null;
let store = null;
const launcher = new Launcher();

const WIN_WIDTH = 1400;
const WIN_HEIGHT = 880;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: WIN_WIDTH,
    height: WIN_HEIGHT,
    minWidth: 940,
    minHeight: 620,
    frame: false,
    show: false,
    backgroundColor: '#0b0b0d',
    title: 'Centurio',
    icon: path.join(__dirname, '..', '..', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Close button behaviour: hide to tray unless we're really quitting.
  mainWindow.on('close', (e) => {
    if (!app.isQuiting && store.getState().settings.closeToTray) {
      e.preventDefault();
      mainWindow.hide();
      if (trayHandle) trayHandle.refresh();
    }
  });

  mainWindow.on('minimize', (e) => {
    if (store.getState().settings.minimizeToTray) {
      e.preventDefault();
      mainWindow.hide();
      if (trayHandle) trayHandle.refresh();
    }
  });

  mainWindow.on('maximize', () => sendWindowState());
  mainWindow.on('unmaximize', () => sendWindowState());
  mainWindow.on('show', () => { if (trayHandle) trayHandle.refresh(); });
  mainWindow.on('hide', () => { if (trayHandle) trayHandle.refresh(); });
}

function sendWindowState() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('window:state', { maximized: mainWindow.isMaximized() });
  }
}

function showWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function toggleWindow() {
  if (!mainWindow) return;
  if (mainWindow.isVisible() && !mainWindow.isMinimized()) {
    mainWindow.hide();
  } else {
    showWindow();
  }
}

// --- Broadcast full state to the renderer (with live running ids merged in) ---
function pushState() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const state = store.getState();
  state.running = launcher.runningIds();
  mainWindow.webContents.send('state:update', state);
}

// --- Global quick-launch hotkeys ---
function registerHotkeys() {
  globalShortcut.unregisterAll();
  const state = store.getState();
  // Explicit per-app hotkeys first.
  for (const app of state.apps) {
    if (app.hotkey) {
      try {
        globalShortcut.register(app.hotkey, () => launchById(app.id));
      } catch (_) { /* ignore invalid accelerators */ }
    }
  }
  // Auto-assign Ctrl+1..9 to quick apps that have no explicit hotkey.
  const quick = state.apps.filter((a) => a.quick && !a.hotkey).slice(0, 9);
  quick.forEach((a, i) => {
    const accel = `CommandOrControl+${i + 1}`;
    try {
      globalShortcut.register(accel, () => launchById(a.id));
    } catch (_) { /* ignore */ }
  });
}

async function launchById(id) {
  const appRecord = store.getApp(id);
  if (!appRecord) return { ok: false, error: 'Приложение не найдено' };
  const res = await launcher.launch(appRecord);
  if (res.ok) {
    store.markLaunched(id);
  }
  pushState();
  return res;
}

function applyAutostart(enabled) {
  try {
    app.setLoginItemSettings({
      openAtLogin: !!enabled,
      openAsHidden: true,
      args: ['--hidden'],
    });
  } catch (_) { /* not supported on some platforms */ }
}

// --- IPC handlers ---
function registerIpc() {
  ipcMain.handle('state:get', () => {
    const state = store.getState();
    state.running = launcher.runningIds();
    return state;
  });

  ipcMain.handle('app:pickExecutable', async () => {
    const filters = process.platform === 'win32'
      ? [{ name: 'Программы', extensions: ['exe', 'bat', 'cmd', 'lnk'] }, { name: 'Все файлы', extensions: ['*'] }]
      : [{ name: 'Все файлы', extensions: ['*'] }];
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Выберите приложение',
      properties: ['openFile'],
      filters,
    });
    if (result.canceled || !result.filePaths.length) return null;
    const filePath = result.filePaths[0];
    const base = path.basename(filePath, path.extname(filePath));
    const suggestedName = base.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    return { path: filePath, suggestedName };
  });

  ipcMain.handle('app:add', (_e, data) => {
    const record = store.addApp(data);
    registerHotkeys();
    pushState();
    return record;
  });

  ipcMain.handle('app:update', (_e, id, patch) => {
    const record = store.updateApp(id, patch);
    registerHotkeys();
    pushState();
    return record;
  });

  ipcMain.handle('app:remove', (_e, id) => {
    const ok = store.removeApp(id);
    registerHotkeys();
    pushState();
    return ok;
  });

  ipcMain.handle('app:launch', (_e, id) => launchById(id));

  ipcMain.handle('app:toggleFavorite', (_e, id) => {
    const a = store.getApp(id);
    if (a) store.updateApp(id, { favorite: !a.favorite });
    pushState();
    return true;
  });

  ipcMain.handle('app:toggleQuick', (_e, id) => {
    const a = store.getApp(id);
    if (a) store.updateApp(id, { quick: !a.quick });
    registerHotkeys();
    pushState();
    return true;
  });

  ipcMain.handle('app:showInFolder', (_e, id) => {
    const a = store.getApp(id);
    return a ? launcher.showInFolder(a) : { ok: false };
  });

  ipcMain.handle('category:add', (_e, name, icon) => {
    const cat = store.addCategory(name, icon);
    pushState();
    return cat;
  });

  ipcMain.handle('category:update', (_e, id, patch) => {
    const cat = store.updateCategory(id, patch);
    pushState();
    return cat;
  });

  ipcMain.handle('category:remove', (_e, id) => {
    const ok = store.removeCategory(id);
    pushState();
    return ok;
  });

  ipcMain.handle('settings:set', (_e, key, value) => {
    const settings = store.setSetting(key, value);
    if (key === 'autostart') applyAutostart(value);
    pushState();
    return settings;
  });

  // Window controls (custom title bar).
  ipcMain.on('window:minimize', () => mainWindow && mainWindow.minimize());
  ipcMain.on('window:maximizeToggle', () => {
    if (!mainWindow) return;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  });
  ipcMain.on('window:close', () => mainWindow && mainWindow.close());
  ipcMain.on('window:hideToTray', () => {
    if (mainWindow) mainWindow.hide();
    if (trayHandle) trayHandle.refresh();
  });
  ipcMain.handle('window:isMaximized', () => mainWindow ? mainWindow.isMaximized() : false);
}

app.whenReady().then(() => {
  store = new Store(path.join(app.getPath('userData'), 'centurio-data.json'));

  launcher.onChange(() => pushState());

  registerIpc();
  createWindow();

  trayHandle = createTray({
    onToggle: toggleWindow,
    onShow: showWindow,
    onQuit: () => { app.isQuiting = true; app.quit(); },
    getVisible: () => mainWindow && mainWindow.isVisible() && !mainWindow.isMinimized(),
  });

  // Apply persisted settings on boot.
  applyAutostart(store.getState().settings.autostart);
  registerHotkeys();

  // If launched at login with --hidden, stay in the tray.
  if (process.argv.includes('--hidden')) {
    if (mainWindow) mainWindow.once('ready-to-show', () => mainWindow.hide());
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else showWindow();
  });
});

app.on('second-instance', () => {
  showWindow();
});

// When the last window closes: stay alive in the tray only if "close to tray"
// is on; otherwise this was a real close, so quit.
app.on('window-all-closed', () => {
  const keepInTray = store && store.getState().settings.closeToTray;
  if (!keepInTray) {
    app.isQuiting = true;
    app.quit();
  }
});

app.on('before-quit', () => {
  app.isQuiting = true;
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});
