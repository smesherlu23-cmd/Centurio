'use strict';
/*
 * Tray — the system-tray icon that keeps Centurio "always at hand".
 * Left click toggles the window; the context menu offers Show / Quit.
 */
const { Tray, Menu, nativeImage } = require('electron');
const path = require('path');

function createTray({ onToggle, onShow, onQuit, getVisible }) {
  const iconPath = path.join(__dirname, '..', '..', 'assets', process.platform === 'win32' ? 'tray.png' : 'tray.png');
  let image = nativeImage.createFromPath(iconPath);
  // Tray icons look best small; resize defensively.
  if (!image.isEmpty()) {
    image = image.resize({ width: 18, height: 18 });
  }
  const tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image);
  tray.setToolTip('Centurio — быстрый запуск приложений');

  const buildMenu = () => Menu.buildFromTemplate([
    { label: getVisible && getVisible() ? 'Скрыть окно' : 'Открыть Centurio', click: () => onShow && onShow() },
    { type: 'separator' },
    { label: 'Выход', click: () => onQuit && onQuit() },
  ]);

  tray.setContextMenu(buildMenu());

  // Single click toggles visibility (Windows/Linux). On macOS a click opens the menu.
  tray.on('click', () => onToggle && onToggle());
  tray.on('double-click', () => onShow && onShow());

  return {
    tray,
    refresh() { tray.setContextMenu(buildMenu()); },
    destroy() { tray.destroy(); },
  };
}

module.exports = { createTray };
