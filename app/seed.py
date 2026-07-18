"""Demo library used for preview/screenshots (CENTURIO_SEED=1).

Mirrors the sample data from the product design so the UI can be reviewed
without manually adding apps. Paths are placeholders and won't launch.
"""
from __future__ import annotations

import time

from .store import Store

_MIN = 60 * 1000


def seed_demo(store: Store) -> None:
    now = int(time.time() * 1000)

    # Ensure the three design categories exist with stable ids.
    store.data["categories"] = [
        {"id": "work", "name": "Работа", "icon": "work", "order": 0},
        {"id": "create", "name": "Творчество", "icon": "brush", "order": 1},
        {"id": "games", "name": "Игры", "icon": "sports_esports", "order": 2},
    ]

    def add(name, sub, cid, hue, fav=False, quick=False, last=0):
        rec = store.add_app({"name": name, "sub": sub, "category_id": cid, "hue": hue,
                             "favorite": fav, "quick": quick,
                             "path": f"C:/Program Files/{name}/{name.replace(' ', '')}.exe"})
        if last:
            rec["last_launched"] = last
            rec["launch_count"] = 5

    add("Notion", "Документы и базы", "work", 80, fav=True, last=now - 2 * 60 * _MIN)
    add("Slack", "Командный чат", "work", 330)
    add("Windows Terminal", "Командная строка", "work", 250)
    add("Postman", "API-клиент", "work", 50)
    add("Chrome", "Браузер", "work", 230, fav=True)
    add("Zoom", "Видеозвонки", "work", 240)
    add("Linear", "Задачи и спринты", "work", 275)
    add("1Password", "Пароли", "work", 210, fav=True)

    add("Blender", "3D-моделирование", "create", 60)
    add("OBS Studio", "Запись и стримы", "create", 270)
    add("Photoshop", "Графика", "create", 240, fav=True)
    add("DaVinci Resolve", "Видеомонтаж", "create", 20)
    add("FL Studio", "Аудиостудия", "create", 300)

    add("Counter-Strike 2", "Steam", "games", 150, fav=True)
    add("Baldur's Gate 3", "Steam", "games", 35)
    add("Hades II", "Steam", "games", 15)
    add("Factorio", "Steam", "games", 85, fav=True)

    add("Telegram", "Мессенджер", "work", 230, quick=True, last=now - 60 * _MIN)
    add("Figma", "Дизайн", "create", 20, quick=True, last=now - 12 * _MIN)
    add("VS Code", "Редактор кода", "work", 250, quick=True, last=now - 40 * _MIN)
    add("Spotify", "Музыка", "create", 150, quick=True, last=now - 3 * 60 * _MIN)
    add("Obsidian", "Заметки", "work", 290, quick=True)
    add("Steam", "Игры", "games", 215, quick=True)

    store._persist()
