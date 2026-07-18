'use strict';
/*
 * Launcher — starts external applications and tracks which of them are running.
 *
 * Executables (.exe / native binaries / .app bundles) are spawned detached so we
 * can watch their lifetime and surface a "running" indicator. Documents, folders
 * and shortcuts are opened via the OS shell (no lifetime tracking).
 */
const { spawn } = require('child_process');
const { shell } = require('electron');
const path = require('path');
const fs = require('fs');

class Launcher {
  constructor() {
    // appId -> { pid, child }
    this._running = new Map();
    this._onChange = null;
  }

  onChange(cb) { this._onChange = cb; }

  _emit() {
    if (this._onChange) this._onChange(this.runningIds());
  }

  runningIds() {
    return Array.from(this._running.keys());
  }

  isRunning(appId) {
    return this._running.has(appId);
  }

  _isExecutable(p) {
    const ext = path.extname(p).toLowerCase();
    if (process.platform === 'win32') return ext === '.exe' || ext === '.bat' || ext === '.cmd' || ext === '.com';
    if (process.platform === 'darwin') return ext === '.app' || ext === '';
    return ext === '' || ext === '.sh' || ext === '.appimage' || ext === '.run';
  }

  /**
   * Launch an app record. Returns { ok, running, error }.
   */
  async launch(app) {
    if (!app || !app.path) return { ok: false, error: 'Не указан путь к приложению' };

    // Verify the target still exists to give a friendly error instead of a crash.
    if (!fs.existsSync(app.path)) {
      return { ok: false, error: 'Файл не найден: ' + app.path };
    }

    // macOS .app bundles are opened with `open` for correct behaviour.
    if (process.platform === 'darwin' && path.extname(app.path).toLowerCase() === '.app') {
      const child = spawn('open', ['-a', app.path, ...(app.args || [])], { detached: true, stdio: 'ignore' });
      return this._track(app.id, child, /*trackable*/ false);
    }

    if (this._isExecutable(app.path)) {
      try {
        const child = spawn(app.path, app.args || [], {
          detached: true,
          stdio: 'ignore',
          cwd: path.dirname(app.path),
        });
        return this._track(app.id, child, /*trackable*/ true);
      } catch (err) {
        // Fall back to the shell opener if direct spawn is refused.
        const res = await shell.openPath(app.path);
        if (res) return { ok: false, error: res };
        return { ok: true, running: false };
      }
    }

    // Non-executable: hand off to the OS (documents, folders, links).
    const res = await shell.openPath(app.path);
    if (res) return { ok: false, error: res };
    return { ok: true, running: false };
  }

  _track(appId, child, trackable) {
    if (!child || typeof child.pid !== 'number') {
      return { ok: false, error: 'Не удалось запустить процесс' };
    }
    child.on('error', () => {
      this._running.delete(appId);
      this._emit();
    });
    if (trackable) {
      this._running.set(appId, { pid: child.pid, child });
      child.on('exit', () => {
        this._running.delete(appId);
        this._emit();
      });
      // Let the parent exit independently of the child.
      child.unref();
      this._emit();
      return { ok: true, running: true };
    }
    child.unref();
    return { ok: true, running: false };
  }

  showInFolder(app) {
    if (!app || !app.path) return { ok: false, error: 'Не указан путь' };
    if (!fs.existsSync(app.path)) return { ok: false, error: 'Файл не найден' };
    shell.showItemInFolder(app.path);
    return { ok: true };
  }
}

module.exports = { Launcher };
