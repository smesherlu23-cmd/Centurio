"""The one place the program talks back.

There are no confirmation dialogs left: a destructive action happens, and this
is what offers to undo it for eight seconds. Ordinary messages sit for ~2.6 s
and go. It is a plain control the UI parks in the window, not ft.SnackBar,
because a snack bar can't hold a live countdown or a second line.
"""
from __future__ import annotations

import threading

import flet as ft

from . import colors as C
from . import log
from .format import T

PLAIN_SECONDS = 2.6
UNDO_SECONDS = 8


class ToastHost:
    """A single toast, positioned by the caller, driven by one timer.

    Every method is safe to call from any thread: a rescan worker and the
    process monitor both report through here.
    """

    def __init__(self, page: ft.Page):
        self.page = page
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._token = 0
        self._left = 0
        self._action = None

        self.icon = ft.Icon(ft.Icons.CHECK, size=18, color=C.GREEN)
        self.text = T("", size=13, color=C.TEXT, max_lines=2,
                      overflow=ft.TextOverflow.ELLIPSIS)
        self.detail = T("", size=11.5, color=C.MUTED, max_lines=2, visible=False,
                        overflow=ft.TextOverflow.ELLIPSIS)
        self.body = ft.Column([self.text, self.detail], spacing=3, expand=True, tight=True)
        self.action_label = T("", size=12.5, weight=ft.FontWeight.W_600, color=C.TEXT)
        self.action_btn = ft.Container(
            self.action_label, visible=False, padding=ft.padding.only(0, 0, 0, 2),
            border=ft.border.only(bottom=ft.BorderSide(1, C.TEXT_FAINT)),
            on_click=lambda e: self.fire_action())
        self.countdown = T("", size=10.5, color=C.MUTED_2, font_family="monospace", visible=False)

        # min/max width from the design: a one-word message still reads as a
        # bar, a long path still wraps instead of spanning the window.
        self.card = ft.Container(
            ft.Row([self.icon, self.body, self.action_btn, self.countdown],
                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   tight=True),
            bgcolor=C.TOAST_BG, border=ft.border.all(1, C.TOAST_BORDER),
            border_radius=12, padding=ft.padding.symmetric(13, 16), shadow=ft.BoxShadow(blur_radius=50, spread_radius=0,
                                            offset=ft.Offset(0, 20), color=C.SHADOW_TOAST),
            animate_opacity=ft.Animation(C.ANIM_FAST, ft.AnimationCurve.EASE_OUT),
        )
        # bottom=70 with left/right pinned: the toast is centred over whatever
        # mode is on screen without knowing the window's width.
        self.control = ft.Container(
            ft.Row([ft.Container(self.card, width=None)],
                   alignment=ft.MainAxisAlignment.CENTER),
            left=0, right=0, bottom=70, visible=False,
        )

    # ---- public ----
    def show(self, text: str, icon=ft.Icons.CHECK, icon_color=C.GREEN,
             action=None, action_label: str | None = None, error: bool = False,
             detail: str | None = None):
        """Put a message up. With `action`, it stays 8 s and counts down."""
        with self._lock:
            self._cancel_timer()
            self._token += 1
            token = self._token
            self._action = action
            self._left = UNDO_SECONDS if action else 0

            self.icon.name = ft.Icons.ERROR_OUTLINE if error else icon
            self.icon.color = C.DANGER if error else icon_color
            self.text.value = text
            self.detail.value = detail or ""
            self.detail.visible = bool(detail)
            self.card.bgcolor = C.ERR_BG if error else C.TOAST_BG
            self.card.border = ft.border.all(1, C.ERR_BORDER if error else C.TOAST_BORDER)
            self.action_btn.visible = bool(action)
            self.action_label.value = action_label or "Вернуть"
            self.countdown.visible = bool(action)
            self.countdown.value = str(self._left) if action else ""
            # Flet has no min/max width, so the two the design gives are used
            # as the two sizes a toast comes in.
            self.card.width = (C.TOAST_MIN_W if len(text) <= 48 and not detail
                               else C.TOAST_MAX_W)
            self.control.visible = True
            self._arm(1.0 if action else PLAIN_SECONDS, token)
        self._safe_update()

    def error(self, text: str, action=None, action_label: str | None = None,
              detail: str | None = None):
        self.show(text, error=True, action=action, action_label=action_label, detail=detail)

    def fire_action(self):
        with self._lock:
            action = self._action
            self._action = None
            self._cancel_timer()
            self.control.visible = False
        self._safe_update()
        if action:
            try:
                action()
            except Exception:
                log.exception("undoing from a toast failed")

    def dismiss(self):
        with self._lock:
            self._cancel_timer()
            self._action = None
            self.control.visible = False
        self._safe_update()

    def stop(self):
        """Drop the pending timer — the window is going away."""
        with self._lock:
            self._cancel_timer()
            self._action = None

    # ---- internals ----
    def _arm(self, delay: float, token: int):
        timer = threading.Timer(delay, self._tick, args=(token,))
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _tick(self, token: int):
        with self._lock:
            # A toast that was replaced while its timer was in flight must not
            # count down, or clear, the one that took its place.
            if token != self._token:
                return
            self._timer = None
            if not self._action:
                self.control.visible = False
            else:
                self._left -= 1
                if self._left <= 0:
                    self._action = None
                    self.control.visible = False
                else:
                    self.countdown.value = str(self._left)
                    self._arm(1.0, token)
        self._safe_update()

    def _safe_update(self):
        # Called from timer threads and from Flet handlers alike; a page that
        # has gone away (window closed mid-countdown) must not raise here.
        try:
            if self.control.page:
                self.control.update()
        except Exception:
            log.exception("updating the toast failed")
