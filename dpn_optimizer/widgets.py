"""Reusable modern Tk widgets for the DPN interface (standard library only)."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from typing import Any, Callable

from .theme import (AMBER, BG, FONT, FONT_BOLD, GREEN, LINE, MONO, MUTED, PANEL, PANEL2,
                    PANEL3, RED, RED_DIM, RED_HOT, SIDE, WHITE)


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def lerp_color(a: str, b: str, t: float) -> str:
    """Blend hex color `a` toward `b` by fraction `t` (clamped to 0..1)."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t),
                              round(ba + (bb - ba) * t))


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               r: float, **kwargs: Any) -> int:
    points = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
              x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
              x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r,
              x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def filter_commands(labels: list[str], query: str) -> list[int]:
    """Indices of labels matching every query word; prefix matches rank first."""
    words = query.casefold().split()
    scored = []
    for index, label in enumerate(labels):
        folded = label.casefold()
        if all(word in folded for word in words):
            starts = bool(words) and folded.startswith(words[0])
            scored.append((0 if starts else 1, index))
    return [index for _, index in sorted(scored)]


class GlowButton(tk.Canvas):
    """Rounded button with animated hover glow and press feedback."""

    def __init__(self, parent: tk.Widget, text: str, command: Callable[[], Any],
                 primary: bool = False, padx: int = 20, height: int = 38) -> None:
        self._face = tkfont.Font(family=FONT_BOLD, size=10)
        self._pad = padx
        super().__init__(parent, width=self._face.measure(text) + padx * 2, height=height,
                         bg=parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self._label = text
        self._command = command
        self._primary = primary
        self._enabled = True
        self._hover = 0.0
        self._hover_goal = 0.0
        self._pressed = False
        self._anim: str | None = None
        self.bind("<Enter>", lambda _e: self._aim(1.0))
        self.bind("<Leave>", lambda _e: self._release_aim())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Destroy>", self._cancel_anim, add="+")
        self._draw()

    def configure(self, cnf: Any = None, **kw: Any) -> Any:  # type: ignore[override]
        if cnf is None and not kw:
            return super().configure()
        if cnf:
            kw = {**cnf, **kw}
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            kw["cursor"] = "hand2" if self._enabled else "arrow"
        if "text" in kw:
            self._label = kw.pop("text")
            kw["width"] = self._face.measure(self._label) + self._pad * 2
        result = super().configure(**kw) if kw else None
        self._draw()
        return result

    config = configure

    def invoke(self) -> None:
        if self._enabled:
            self._command()

    def _aim(self, goal: float) -> None:
        self._hover_goal = goal if self._enabled else 0.0
        if self._anim is None:
            self._anim = self.after(16, self._step)

    def _release_aim(self) -> None:
        self._pressed = False
        self._aim(0.0)

    def _step(self) -> None:
        self._anim = None
        self._hover += (self._hover_goal - self._hover) * 0.4
        if abs(self._hover_goal - self._hover) < 0.03:
            self._hover = self._hover_goal
        self._draw()
        if self._hover != self._hover_goal:
            self._anim = self.after(16, self._step)

    def _cancel_anim(self, _event: Any = None) -> None:
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None

    def _press(self, _event: tk.Event) -> None:
        if self._enabled:
            self._pressed = True
            self._draw()

    def _release(self, event: tk.Event) -> None:
        was_pressed, self._pressed = self._pressed, False
        self._draw()
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if was_pressed and inside and self._enabled:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        parent_bg = self.master.cget("bg") if self.master else BG
        glow = self._hover
        if self._primary:
            base, hot = RED, RED_HOT
            face = lerp_color(base, hot, glow)
            if self._pressed:
                face = lerp_color(face, "#000000", 0.25)
            ring = lerp_color(parent_bg, RED_HOT, 0.45 * glow)
            text = WHITE
        else:
            face = lerp_color(PANEL2, PANEL3, glow)
            if self._pressed:
                face = lerp_color(face, "#000000", 0.25)
            ring = lerp_color(LINE, RED, 0.9 * glow)
            text = WHITE
        if not self._enabled:
            face, ring, text = lerp_color(face, parent_bg, 0.55), parent_bg, MUTED
        round_rect(self, 1, 1, w - 1, h - 1, 9, fill=ring, outline="")
        round_rect(self, 2.5, 2.5, w - 2.5, h - 2.5, 8, fill=face, outline="")
        self.create_text(w / 2, h / 2, text=self._label, fill=text, font=self._face)


class Toggle(tk.Canvas):
    """Animated pill switch bound to a tk.IntVar/BooleanVar."""

    def __init__(self, parent: tk.Widget, variable: tk.Variable,
                 command: Callable[[], Any] | None = None) -> None:
        super().__init__(parent, width=44, height=24, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2")
        self._variable = variable
        self._toggle_command = command
        self._pos = 1.0 if variable.get() else 0.0
        self._anim: str | None = None
        self._trace = variable.trace_add("write", lambda *_: self._aim())
        self.bind("<Button-1>", lambda _e: self.flip())
        self.bind("<Destroy>", self._cleanup, add="+")
        self._draw()

    def flip(self) -> None:
        self._variable.set(0 if self._variable.get() else 1)
        if self._toggle_command:
            self._toggle_command()

    def _cleanup(self, _event: Any = None) -> None:
        try:
            self._variable.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass

    def _aim(self) -> None:
        if self._anim is None:
            self._anim = self.after(16, self._step)

    def _step(self) -> None:
        self._anim = None
        goal = 1.0 if self._variable.get() else 0.0
        self._pos += (goal - self._pos) * 0.45
        if abs(goal - self._pos) < 0.04:
            self._pos = goal
        self._draw()
        if self._pos != goal:
            self._anim = self.after(16, self._step)

    def _draw(self) -> None:
        self.delete("all")
        track = lerp_color("#2A2A31", RED, self._pos)
        round_rect(self, 1, 3, 43, 21, 9, fill=lerp_color(LINE, RED_HOT, 0.8 * self._pos), outline="")
        round_rect(self, 2, 4, 42, 20, 8, fill=track, outline="")
        x = 12 + 20 * self._pos
        self.create_oval(x - 7, 12 - 7, x + 7, 12 + 7, fill=WHITE, outline="")


class GradientBar(tk.Canvas):
    """Thin horizontal red-to-black accent line."""

    def __init__(self, parent: tk.Widget, height: int = 3, start: str = RED_HOT,
                 end: str = BG) -> None:
        super().__init__(parent, height=height, bg=end, highlightthickness=0, bd=0)
        self._start, self._end = start, end
        self.bind("<Configure>", self._draw)

    def _draw(self, event: tk.Event) -> None:
        self.delete("all")
        width, height = max(event.width, 1), int(self["height"])
        for x in range(0, width, 4):
            self.create_rectangle(x, 0, x + 4, height, outline="",
                                  fill=lerp_color(self._start, self._end, x / width))


class NavItem(tk.Frame):
    """Sidebar entry with an active indicator bar, icon, label and shortcut hint."""

    def __init__(self, parent: tk.Widget, icon: str, text: str, hint: str,
                 command: Callable[[], Any]) -> None:
        super().__init__(parent, bg=SIDE, cursor="hand2")
        self._active = False
        self._command = command
        self._bar = tk.Frame(self, width=3, bg=SIDE)
        self._bar.pack(side="left", fill="y")
        self._icon = tk.Label(self, text=icon, bg=SIDE, fg=MUTED, font=(FONT, 12), width=2)
        self._icon.pack(side="left", padx=(12, 2), pady=9)
        self._name = tk.Label(self, text=text, bg=SIDE, fg=WHITE, font=(FONT, 11), anchor="w")
        self._name.pack(side="left", fill="x", expand=True)
        self._hint = tk.Label(self, text=hint, bg=SIDE, fg="#4A4F58", font=(MONO, 8))
        self._hint.pack(side="right", padx=(0, 10))
        for widget in (self, self._bar, self._icon, self._name, self._hint):
            widget.bind("<Enter>", lambda _e: self._paint(hover=True))
            widget.bind("<Leave>", lambda _e: self._paint(hover=False))
            widget.bind("<Button-1>", lambda _e: self._command())

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint(hover=False)

    def _paint(self, hover: bool) -> None:
        if self._active:
            bg, bar, fg, icon = PANEL2, RED, WHITE, RED
        elif hover:
            bg, bar, fg, icon = PANEL, RED_DIM, WHITE, RED_HOT
        else:
            bg, bar, fg, icon = SIDE, SIDE, "#C9D0DA", MUTED
        self.configure(bg=bg)
        self._bar.configure(bg=bar)
        self._icon.configure(bg=bg, fg=icon)
        self._name.configure(bg=bg, fg=fg, font=(FONT_BOLD if self._active else FONT, 11))
        self._hint.configure(bg=bg)


class ArcGauge(tk.Canvas):
    """Animated 270-degree arc gauge with a rolling sparkline and caption."""

    SWEEP = 270
    HISTORY = 24

    def __init__(self, parent: tk.Widget, title: str, height: int = 150,
                 animate: Callable[[], bool] = lambda: True) -> None:
        super().__init__(parent, height=height, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.title = title
        self.subtitle = "Waiting for data…"
        self.history: list[float] = []
        self.target = 0.0
        self.shown = 0.0
        self.available = False
        self._animate_enabled = animate
        self._anim: str | None = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Destroy>", self._cancel, add="+")

    def update_value(self, value: float | None, subtitle: str) -> None:
        self.subtitle = subtitle
        self.available = value is not None
        if value is not None:
            self.target = max(0.0, min(100.0, float(value)))
            self.history.append(self.target)
            del self.history[:-self.HISTORY]
        if self._animate_enabled():
            if self._anim is None:
                self._anim = self.after(16, self._step)
        else:
            self.shown = self.target
            self.redraw()

    def _cancel(self, _event: Any = None) -> None:
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None

    def _step(self) -> None:
        self._anim = None
        self.shown += (self.target - self.shown) * 0.22
        if abs(self.target - self.shown) < 0.15:
            self.shown = self.target
        self.redraw()
        if self.shown != self.target:
            self._anim = self.after(16, self._step)

    @staticmethod
    def color_for(value: float) -> str:
        return lerp_color(RED, "#FF8A5C", (value - 55) / 45)

    def redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 260)
        height = max(self.winfo_height(), 150)
        cx, cy, radius = 76, height / 2 + 2, min(58, height / 2 - 14)
        frac = self.shown / 100
        color = self.color_for(self.shown)
        ticks = 30
        for i in range(ticks + 1):
            angle = math.radians(225 - self.SWEEP * i / ticks)
            lit = self.available and i / ticks <= frac
            inner, outer = radius + 8, radius + (13 if i % 5 == 0 else 11)
            self.create_line(cx + inner * math.cos(angle), cy - inner * math.sin(angle),
                             cx + outer * math.cos(angle), cy - outer * math.sin(angle),
                             fill=color if lit else "#26262B", width=1)
        box = (cx - radius, cy - radius, cx + radius, cy + radius)
        self.create_arc(*box, start=225, extent=-self.SWEEP, style="arc", outline=PANEL2, width=10)
        if self.available and frac > 0:
            self.create_arc(*box, start=225, extent=-self.SWEEP * frac, style="arc",
                            outline=lerp_color(color, BG, 0.55), width=14)
            self.create_arc(*box, start=225, extent=-self.SWEEP * frac, style="arc",
                            outline=color, width=8)
        self.create_text(cx, cy - 2, text=f"{self.shown:.0f}%" if self.available else "N/A",
                         fill=WHITE, font=(FONT_BOLD, 19))
        self.create_text(cx, cy + 20, text="LOAD", fill=MUTED, font=(MONO, 8, "bold"))
        left = 164
        self.create_text(left, 24, text=self.title, anchor="w", fill=RED, font=(MONO, 9, "bold"))
        self.create_text(left, 46, text=self.subtitle, anchor="nw", fill=MUTED,
                         font=(FONT, 9), width=max(width - left - 10, 60))
        top, bottom = height - 54, height - 18
        right = max(width - 12, left + 40)
        self.create_line(left, bottom, right, bottom, fill=LINE)
        self.create_text(right, top - 8, text="LAST 2 MIN", anchor="e", fill="#555B66",
                         font=(MONO, 7))
        if len(self.history) > 1:
            points = []
            for i, sample in enumerate(self.history):
                points.extend((left + (right - left) * i / (len(self.history) - 1),
                               bottom - sample / 100 * (bottom - top)))
            area = [left, bottom, *points, points[-2], bottom]
            self.create_polygon(area, fill=lerp_color(BG, RED, 0.18), outline="")
            self.create_line(*points, fill=RED, width=2, smooth=True)
            self.create_oval(points[-2] - 3, points[-1] - 3, points[-2] + 3, points[-1] + 3,
                             fill=RED_HOT, outline="")


class ToastHost:
    """Stacked, auto-dismissing notifications anchored to the window's bottom-right."""

    COLORS = {"info": MUTED, "success": GREEN, "warn": AMBER, "error": RED_HOT}
    MAX = 4

    def __init__(self, root: tk.Misc, animate: Callable[[], bool] = lambda: True,
                 bottom_margin: int = 44) -> None:
        self.root = root
        self.animate = animate
        self.bottom = bottom_margin
        self.toasts: list[tk.Frame] = []

    def show(self, message: str, kind: str = "info", ms: int = 4500) -> None:
        accent = self.COLORS.get(kind, MUTED)
        toast = tk.Frame(self.root, bg=PANEL2, highlightthickness=1,
                         highlightbackground=lerp_color(LINE, accent, 0.5))
        tk.Frame(toast, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(toast, text=message, bg=PANEL2, fg=WHITE, font=(FONT, 10), justify="left",
                 wraplength=300, padx=12, pady=10).pack(side="left")
        self.toasts.append(toast)
        while len(self.toasts) > self.MAX:
            self._remove(self.toasts[0])
        self._layout(entering=toast)
        self.root.after(ms, lambda: self._remove(toast))

    def _layout(self, entering: tk.Frame | None = None) -> None:
        self.root.update_idletasks()
        y = self.bottom
        for toast in reversed(self.toasts):
            toast.place(relx=1.0, rely=1.0, anchor="se", x=-22, y=-y)
            toast.lift()
            y += toast.winfo_reqheight() + 8
        if entering is not None and self.animate():
            self._slide(entering, 260)

    def _slide(self, toast: tk.Frame, offset: int) -> None:
        try:
            if not toast.winfo_exists():
                return
            toast.place_configure(x=-22 + offset)
            if offset > 0:
                toast.after(16, self._slide_next, toast, int(offset * 0.62))
        except tk.TclError:
            return

    def _slide_next(self, toast: tk.Frame, offset: int) -> None:
        if toast not in self.toasts:
            return
        self._slide(toast, 0 if offset < 3 else offset)

    def _remove(self, toast: tk.Frame) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
            try:
                toast.destroy()
            except tk.TclError:
                return
            self._layout()


class CommandPalette:
    """Ctrl+K quick-launch overlay: filter by typing, Enter to run, Esc to close."""

    def __init__(self, root: tk.Misc,
                 commands: Callable[[], list[tuple[str, str, Callable[[], Any]]]]) -> None:
        self.root = root
        self._commands = commands
        self._visible: list[tuple[str, str, Callable[[], Any]]] = []
        self.frame = tk.Frame(root, bg=PANEL, highlightthickness=1, highlightbackground=RED_DIM)
        tk.Frame(self.frame, bg=RED, height=2).pack(fill="x")
        tk.Label(self.frame, text="COMMAND PALETTE", bg=PANEL, fg=RED, font=(MONO, 9, "bold"),
                 anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        self.query = tk.StringVar()
        self.entry = tk.Entry(self.frame, textvariable=self.query, bg=PANEL2, fg=WHITE,
                              insertbackground=RED_HOT, bd=0, relief="flat", font=(FONT, 13))
        self.entry.pack(fill="x", padx=14, ipady=8)
        self.listbox = tk.Listbox(self.frame, height=9, bg=PANEL, fg=WHITE, bd=0,
                                  highlightthickness=0, selectbackground=RED,
                                  selectforeground=WHITE, activestyle="none", font=(FONT, 11))
        self.listbox.pack(fill="both", expand=True, padx=14, pady=(8, 4))
        tk.Label(self.frame, text="↑↓ navigate   ·   Enter run   ·   Esc close", bg=PANEL,
                 fg="#555B66", font=(MONO, 8)).pack(anchor="w", padx=14, pady=(0, 10))
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Up>", lambda _e: self._move(-1) or "break")
        self.entry.bind("<Down>", lambda _e: self._move(1) or "break")
        self.entry.bind("<Return>", lambda _e: self.run_selected())
        self.entry.bind("<Escape>", lambda _e: self.close())
        self.listbox.bind("<ButtonRelease-1>", lambda _e: self.run_selected())

    @property
    def is_open(self) -> bool:
        return bool(self.frame.winfo_ismapped())

    def open(self) -> None:
        self.query.set("")
        self._refill()
        self.frame.place(relx=0.5, y=84, anchor="n", width=560)
        self.frame.lift()
        self.entry.focus_set()

    def close(self) -> None:
        self.frame.place_forget()
        self.root.focus_set()

    def toggle(self) -> None:
        self.close() if self.is_open else self.open()

    def _refill(self) -> None:
        commands = self._commands()
        order = filter_commands([c[0] for c in commands], self.query.get())
        self._visible = [commands[i] for i in order]
        self.listbox.delete(0, "end")
        for label, hint, _ in self._visible:
            self.listbox.insert("end", f"  {label}" + (f"      [{hint}]" if hint else ""))
        if self._visible:
            self.listbox.selection_set(0)

    def _on_key(self, event: tk.Event) -> None:
        if event.keysym not in ("Up", "Down", "Return", "Escape"):
            self._refill()

    def _move(self, step: int) -> None:
        if not self._visible:
            return
        current = (self.listbox.curselection() or (0,))[0]
        target = max(0, min(len(self._visible) - 1, current + step))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(target)
        self.listbox.see(target)

    def run_selected(self) -> None:
        selected = self.listbox.curselection()
        if not selected:
            return
        action = self._visible[selected[0]][2]
        self.close()
        action()
