from __future__ import annotations

import threading
from pathlib import Path

from . import log


class TrayController:
    """The tray icon, and the mini-launcher behind it.

    The menu is built on every open from `menu_provider`, so the five pinned
    programs it offers are the ones currently pinned — clicking one launches it
    without the window ever appearing.
    """

    def __init__(self, icon_path: Path | str, on_show=None, on_quit=None,
                 on_open_library=None, menu_provider=None):
        self.icon_path = str(icon_path)
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_open_library = on_open_library
        self.menu_provider = menu_provider
        self._icon = None
        self._thread = None
        self.available = False

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image
        except Exception:
            self.available = False
            return False

        try:
            image = Image.open(self.icon_path)
        except Exception:
            self.available = False
            return False

        self._icon = pystray.Icon("centurio", image, "Centurio — быстрый запуск приложений",
                                  menu=pystray.Menu(self._menu_items))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.available = True
        return True

    def _menu_items(self):
        """Yielded lazily: pystray re-reads this every time the menu opens."""
        import pystray
        yield pystray.MenuItem("Открыть Centurio", self._show, default=True)
        pinned, summary = self._provided()
        if pinned:
            yield pystray.Menu.SEPARATOR
            for label, action in pinned:
                yield pystray.MenuItem(label, self._wrap(action))
        yield pystray.Menu.SEPARATOR
        if summary:
            yield pystray.MenuItem(summary, None, enabled=False)
        yield pystray.MenuItem("Открыть библиотеку", self._open_library)
        yield pystray.MenuItem("Выход", self._quit)

    def _provided(self):
        if not self.menu_provider:
            return [], ""
        try:
            items, summary = self.menu_provider()
            return list(items)[:5], summary
        except Exception:
            log.exception("building the tray menu failed")
            return [], ""

    def _wrap(self, action):
        def run(*_):
            try:
                action()
            except Exception:
                log.exception("a tray menu action failed")
        return run

    def refresh(self):
        """Ask pystray to redraw the menu after the library changed."""
        if not self._icon:
            return
        try:
            self._icon.update_menu()
        except Exception:
            log.exception("refreshing the tray menu failed")

    def _run(self):
        try:
            self._icon.run()
        except Exception:
            self.available = False

    def _show(self, *_):
        if self.on_show:
            self._wrap(self.on_show)()

    def _open_library(self, *_):
        if self.on_open_library:
            self._wrap(self.on_open_library)()

    def _quit(self, *_):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
        if self.on_quit:
            self.on_quit()

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
