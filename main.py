from __future__ import annotations

import os

import flet as ft

from app.main import ASSETS_DIR, main

if __name__ == "__main__":
    web = os.environ.get("CENTURIO_WEB") == "1"
    port = int(os.environ.get("CENTURIO_PORT", "0") or 0)
    if web:
        ft.app(target=main, view=None, port=port or 8550, assets_dir=str(ASSETS_DIR))
    else:
        ft.app(target=main, assets_dir=str(ASSETS_DIR))
