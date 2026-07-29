from __future__ import annotations

import threading
from pathlib import Path


class TrayController:
    def __init__(self, icon_path: Path | str, on_show=None, on_quit=None):
        self.icon_path = str(icon_path)
        self.on_show = on_show
        self.on_quit = on_quit
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

        menu = pystray.Menu(
            pystray.MenuItem("Открыть Centurio", self._show, default=True),
            pystray.MenuItem("Выход", self._quit),
        )
        self._icon = pystray.Icon("centurio", image, "Centurio — быстрый запуск приложений", menu)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.available = True
        return True

    def _run(self):
        try:
            self._icon.run()
        except Exception:
            self.available = False

    def _show(self, *_):
        if self.on_show:
            self.on_show()

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
