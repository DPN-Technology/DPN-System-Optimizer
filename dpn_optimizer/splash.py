"""Animated boot screen: borderless, fades in and out, and runs real startup checks."""
from __future__ import annotations

import math
import random
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from .theme import (AMBER, BG, GREEN, LINE, MONO, MUTED, PANEL2, RED, RED_DIM, RED_HOT,
                    TERMINAL, WHITE, FONT_BOLD)
from .widgets import lerp_color, round_rect

Step = tuple[str, Callable[[], tuple[bool, str]]]


class SplashScreen:
    WIDTH, HEIGHT = 780, 470
    FRAME_MS = 33
    FADE_IN, STEP_FRAMES, HOLD, FADE_OUT = 10, 6, 10, 9
    CELL = 16
    TRAIL = 8
    TITLE = "SYSTEM OPTIMIZER"

    def __init__(self, root: tk.Tk, steps: list[Step], version: str, logo_path: Path,
                 on_done: Callable[[], Any]) -> None:
        self.root = root
        self.steps = steps
        self.version = version
        self.on_done = on_done
        self.results: list[tuple[str, bool, str]] = []
        self.finished = False
        self._frame = 0
        self._skip_at: int | None = None
        self._progress = 0.0
        self._columns = [self._new_column(random.uniform(0, self.HEIGHT / self.CELL))
                         for _ in range(self.WIDTH // 20)]

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.configure(bg=BG)
        x = (root.winfo_screenwidth() - self.WIDTH) // 2
        y = (root.winfo_screenheight() - self.HEIGHT) // 2
        self.win.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self._set_alpha(0.0)
        self.win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.win, width=self.WIDTH, height=self.HEIGHT, bg=BG,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        try:
            self.logo: tk.PhotoImage | None = tk.PhotoImage(file=str(logo_path))
        except tk.TclError:
            self.logo = None
        self.canvas.bind("<Button-1>", lambda _e: self.skip())
        self.win.bind("<Escape>", lambda _e: self.skip())
        self.win.bind("<Return>", lambda _e: self.skip())
        self.win.deiconify()
        self.win.focus_force()
        self.win.after(self.FRAME_MS, self._tick)

    def skip(self) -> None:
        if self._skip_at is None and not self.finished:
            self._skip_at = self._frame

    @staticmethod
    def _new_column(head: float) -> dict[str, Any]:
        return {"head": head, "speed": random.uniform(0.35, 1.0),
                "chars": [random.choice("01") for _ in range(40)]}

    def _set_alpha(self, value: float) -> None:
        try:
            self.win.attributes("-alpha", max(0.0, min(1.0, value)))
        except tk.TclError:
            pass

    @property
    def _work_end(self) -> int:
        return self.FADE_IN + len(self.steps) * self.STEP_FRAMES

    def _tick(self) -> None:
        try:
            self._advance()
        except tk.TclError:
            self.finished = True

    def _advance(self) -> None:
        if self.finished or not self.win.winfo_exists():
            self.finished = True
            return
        frame = self._frame
        out_start = self._skip_at if self._skip_at is not None else self._work_end + self.HOLD
        if frame < self.FADE_IN:
            self._set_alpha((frame + 1) / self.FADE_IN)
        elif frame >= out_start:
            fade = (frame - out_start + 1) / self.FADE_OUT
            self._set_alpha(1.0 - fade)
            if fade >= 1.0:
                self._finish()
                return
        self._run_steps(frame)
        self._draw(frame)
        self._frame += 1
        self.win.after(self.FRAME_MS, self._tick)

    def _finish(self) -> None:
        self.finished = True
        try:
            self.win.destroy()
        finally:
            self.on_done()

    def _run_steps(self, frame: int) -> None:
        index = (frame - self.FADE_IN) // self.STEP_FRAMES
        midpoint = (frame - self.FADE_IN) % self.STEP_FRAMES == self.STEP_FRAMES // 2
        if 0 <= index < len(self.steps) and midpoint and len(self.results) == index:
            label, check = self.steps[index]
            try:
                ok, detail = check()
            except Exception as exc:  # a failed check must never block startup
                ok, detail = False, type(exc).__name__
            self.results.append((label, ok, detail))

    def _draw(self, frame: int) -> None:
        c = self.canvas
        c.delete("all")
        self._draw_rain(frame)
        round_rect(c, 14, 14, self.WIDTH - 14, self.HEIGHT - 14, 14, fill="", outline=LINE, width=1)
        c.create_text(34, 36, text="DPN // TECHNOLOGY", anchor="w", fill=RED,
                      font=(MONO, 10, "bold"))
        c.create_text(self.WIDTH - 34, 36, text=f"SYSTEM OPTIMIZER  v{self.version}", anchor="e",
                      fill=MUTED, font=(MONO, 9))
        self._draw_logo(frame)
        self._draw_terminal(frame)
        self._draw_progress(frame)

    def _draw_rain(self, frame: int) -> None:
        c = self.canvas
        for i, col in enumerate(self._columns):
            col["head"] += col["speed"]
            if col["head"] * self.CELL - self.TRAIL * self.CELL > self.HEIGHT:
                col.update(self._new_column(random.uniform(-10, 0)))
            if random.random() < 0.15:
                col["chars"][random.randrange(len(col["chars"]))] = random.choice("01")
            x = 12 + i * 20
            for k in range(self.TRAIL):
                row = int(col["head"]) - k
                y = row * self.CELL
                if not 0 <= y < self.HEIGHT:
                    continue
                tone = lerp_color("#FF5A4D" if k == 0 else "#A10D08", BG, 0.35 + 0.65 * k / self.TRAIL)
                c.create_text(x, y, text=col["chars"][row % len(col["chars"])], fill=tone,
                              font=(MONO, 10, "bold"))

    def _draw_logo(self, frame: int) -> None:
        c = self.canvas
        cx, cy, half = 210, 210, 118
        pulse = 0.5 + 0.5 * math.sin(frame * 0.18)
        c.create_rectangle(cx - half - 24, cy - half - 24, cx + half + 24, cy + half + 24,
                           fill=BG, outline="")
        for ring in range(3, 0, -1):
            grow = ring * 6
            round_rect(c, cx - half - grow, cy - half - grow, cx + half + grow, cy + half + grow,
                       14 + grow, fill="", width=1,
                       outline=lerp_color(RED, BG, 0.45 + ring * 0.16 - 0.25 * pulse))
        round_rect(c, cx - half, cy - half, cx + half, cy + half, 12, fill=BG,
                   outline=lerp_color(RED_DIM, RED_HOT, pulse), width=2)
        if self.logo is not None:
            c.create_image(cx, cy, image=self.logo)
        wave = (frame * 3) % (2 * (2 * half - 8))
        offset = wave if wave <= 2 * half - 8 else 2 * (2 * half - 8) - wave
        scan_y = cy - half + 4 + offset
        for trail in range(4):
            c.create_line(cx - half + 6, scan_y - trail * 3, cx + half - 6, scan_y - trail * 3,
                          fill=lerp_color(RED_HOT, BG, 0.2 + trail * 0.22))
        arm = 22
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            bx, by = cx + sx * (half + 8), cy + sy * (half + 8)
            c.create_line(bx, by, bx - sx * arm, by, fill=RED_HOT, width=2)
            c.create_line(bx, by, bx, by - sy * arm, fill=RED_HOT, width=2)
        revealed = min(len(self.TITLE), max(0, int((frame - 4) / max(1, self._work_end * 0.55) * len(self.TITLE))))
        title = "".join(ch if i < revealed or ch == " " else random.choice("01#$%@")
                        for i, ch in enumerate(self.TITLE))
        c.create_text(cx, cy + half + 42, text=title, fill=WHITE, font=(FONT_BOLD, 16))
        c.create_text(cx, cy + half + 66, text="LOCAL-FIRST  ·  PREVIEW-FIRST  ·  NO TELEMETRY",
                      fill=MUTED, font=(MONO, 8))

    def _draw_terminal(self, frame: int) -> None:
        c = self.canvas
        left, top, right, bottom = 410, 70, self.WIDTH - 32, 356
        round_rect(c, left, top, right, bottom, 10, fill=TERMINAL, outline=LINE, width=1)
        c.create_rectangle(left + 2, top + 2, right - 2, top + 26, fill=PANEL2, outline="")
        c.create_text(left + 14, top + 14, text="▍BOOT SEQUENCE", anchor="w", fill=RED,
                      font=(MONO, 9, "bold"))
        c.create_text(right - 12, top + 14, text=f"{len(self.results)}/{len(self.steps)}",
                      anchor="e", fill=MUTED, font=(MONO, 9))
        y = top + 40
        for label, ok, detail in self.results:
            tag, tone = ("OK", GREEN) if ok else ("WARN", AMBER)
            c.create_text(left + 14, y, text=f"[{tag:^4}]", anchor="w", fill=tone,
                          font=(MONO, 9, "bold"))
            c.create_text(left + 74, y, text=label, anchor="w", fill=WHITE, font=(MONO, 9))
            c.create_text(left + 74, y + 13, text="↳ " + detail[:40], anchor="w", fill=MUTED,
                          font=(MONO, 8))
            y += 29
        if len(self.results) < len(self.steps) and self._skip_at is None:
            spinner = "|/-\\"[(frame // 2) % 4]
            c.create_text(left + 14, y, text=f"[ {spinner}  ]", anchor="w", fill=RED_HOT,
                          font=(MONO, 9, "bold"))
            cursor = "█" if (frame // 4) % 2 == 0 else " "
            c.create_text(left + 74, y, text=self.steps[len(self.results)][0] + " " + cursor,
                          anchor="w", fill=MUTED, font=(MONO, 9))

    def _draw_progress(self, frame: int) -> None:
        c = self.canvas
        done = len(self.results)
        partial = ((frame - self.FADE_IN) % self.STEP_FRAMES) / self.STEP_FRAMES if done < len(self.steps) else 0
        target = min(1.0, (done + partial * 0.9) / max(1, len(self.steps)))
        if self._skip_at is not None:
            target = 1.0
        self._progress += (target - self._progress) * 0.25
        left, right, y = 34, self.WIDTH - 34, 424
        status = ("SYSTEM READY" if self._progress > 0.985 or self._skip_at is not None
                  else "LOADING  ·  " + self.steps[min(done, len(self.steps) - 1)][0].upper())
        c.create_text(left, y - 18, text=status, anchor="w", fill=MUTED, font=(MONO, 9, "bold"))
        c.create_text(right, y - 18, text=f"{self._progress * 100:3.0f}%", anchor="e",
                      fill=WHITE, font=(MONO, 10, "bold"))
        round_rect(c, left, y - 4, right, y + 4, 4, fill=PANEL2, outline="")
        head = left + (right - left) * self._progress
        if head > left + 6:
            round_rect(c, left, y - 4, head, y + 4, 4, fill=RED, outline="")
            c.create_oval(head - 9, y - 9, head + 9, y + 9, fill=lerp_color(BG, RED, 0.35), outline="")
            c.create_oval(head - 4, y - 4, head + 4, y + 4, fill=RED_HOT, outline="")
        c.create_text(left, y + 24, text="CLICK OR PRESS ESC TO SKIP", anchor="w", fill="#444A54",
                      font=(MONO, 7))
