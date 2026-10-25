"""Dark DPN-themed, responsive Windows desktop interface (standard Tkinter)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import random
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import __version__
from .cleaner import CATEGORIES, DEFAULT_CATEGORIES, human_bytes, list_reports, reports_path, run_cleanup
from .diagnostics import (
    list_process_details,
    performance_advice,
    performance_health_score,
    performance_snapshot,
    ProcessActionError,
    terminate_user_process,
)
from .diskmap import scan_disk_usage, scan_file_insights
from .preferences import AppearancePreferences, load_preferences, save_preferences
from .startup import list_startup_items
from . import scheduler, health

BG = "#07080B"
SIDE = "#0A0B10"
PANEL = "#101218"
PANEL2 = "#171A22"
LINE = "#292D37"
RED = "#E50918"
WHITE = "#F5F6F8"
MUTED = "#9299A6"
GREEN = "#43D6A1"
HOVER = "#20242E"
RED_HOVER = "#FF3041"
ASSETS = Path(__file__).resolve().parent / "assets"


class DPNWindow:
    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.root = tk.Tk()
        self.root.title(f"DPN SYSTEM OPTIMIZER // v{__version__}")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1280, max(960, screen_width - 80))
        height = min(820, max(700, screen_height - 140))
        self.root.geometry(
            f"{width}x{height}+{max(0, (screen_width - width) // 2)}"
            f"+{max(0, (screen_height - 140 - height) // 2)}"
        )
        self.root.minsize(min(980, width), min(700, height))
        self.root.configure(bg=BG)
        self.preference_error: str | None = None
        try:
            self.appearance = load_preferences()
        except (OSError, ValueError, TypeError) as exc:
            self.appearance = AppearancePreferences()
            self.preference_error = f"Appearance preferences could not be loaded: {exc}"
        self._rain_job: str | None = None
        self.appearance_dialog: tk.Toplevel | None = None
        self._images: list[tk.PhotoImage] = []
        self._set_window_icon()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self._poll_job = None
        self.cancel_flag = threading.Event()
        self.insight_busy = False
        self.insight_cancel = threading.Event()
        self.process_refresh_busy = False
        self.process_action_busy = False
        self.process_rows: dict[str, dict[str, Any]] = {}
        self.page = "Dashboard"
        self.buttons: dict[str, tk.Button] = {}
        self.nav_icons: dict[str, tk.Label] = {}
        self.nav_marks: dict[str, tk.Frame] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.metrics: dict[str, tk.Label] = {}
        self.metric_history: dict[str, list[float]] = {
            name: [] for name in ("CPU UTILIZATION", "PHYSICAL MEMORY", "SYSTEM DRIVE")
        }
        self.sparklines: dict[str, tk.Canvas] = {}
        self.choice = {key: tk.IntVar(value=int(key in DEFAULT_CATEGORIES)) for key in CATEGORIES}
        self.age = tk.StringVar(value="48")
        self.schedule_time = tk.StringVar(value="09:00")
        self._configure_style()
        self._layout()
        if self.appearance.show_intro and not self.appearance.reduced_motion:
            self._show_boot_splash()
        if self.preference_error:
            self.root.after(2800, lambda: messagebox.showwarning(
                "Appearance preferences", self.preference_error, parent=self.root
            ))
        self._event_job = self.root.after(250, self._consume_events)
        self._poll_job = self.root.after(300, self._poll_performance)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        sty = ttk.Style(self.root)
        sty.theme_use("clam")
        sty.configure("DPN.Treeview", background=PANEL, foreground=WHITE,
                      fieldbackground=PANEL, borderwidth=0, rowheight=29,
                      relief="flat", font=("Segoe UI", 9))
        sty.configure("DPN.Treeview.Heading", background=PANEL2, foreground=WHITE,
                      relief="flat", borderwidth=0, font=("Segoe UI Semibold", 8))
        sty.map("DPN.Treeview", background=[("selected", "#77303A")],
                foreground=[("selected", WHITE)])
        sty.map("DPN.Treeview.Heading", background=[("active", "#2A3543")])
        sty.layout("DPN.Treeview", [
            ("Treeview.treearea", {"sticky": "nswe"})
        ])
        sty.configure("DPN.Horizontal.TProgressbar", background=RED, troughcolor=PANEL2,
                      bordercolor=PANEL, lightcolor=RED, darkcolor=RED)
        sty.configure("DPN.TNotebook", background=BG, borderwidth=0, tabmargins=0)
        sty.configure("DPN.TNotebook.Tab", background=PANEL, foreground=MUTED,
                      padding=(14, 9), borderwidth=0,
                      font=("Segoe UI Semibold", 8))
        sty.map("DPN.TNotebook.Tab",
                background=[("selected", PANEL2), ("active", HOVER)],
                foreground=[("selected", RED), ("active", WHITE)])
        sty.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=WHITE,
                      arrowcolor=RED, bordercolor=LINE, lightcolor=PANEL2, darkcolor=PANEL2)
        sty.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
                foreground=[("readonly", WHITE)], background=[("readonly", PANEL2)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", WHITE)
        self.root.option_add("*TCombobox*Listbox.selectBackground", RED)

    def _load_logo(self, filename: str) -> tk.PhotoImage | None:
        try:
            image = tk.PhotoImage(file=str(ASSETS / filename))
        except tk.TclError:
            return None
        self._images.append(image)
        return image

    def _set_window_icon(self) -> None:
        icon = self._load_logo("dpn_logo_icon.png")
        if icon is not None:
            self.root.iconphoto(True, icon)

    def _text(self, parent: tk.Widget, value: str, size: int = 10,
              color: str = WHITE, bold: bool = False, **kwargs: Any) -> tk.Label:
        return tk.Label(parent, text=value, bg=parent.cget("bg"), fg=color,
                        font=("Segoe UI Semibold" if bold else "Segoe UI", size),
                        anchor="w", justify="left", **kwargs)

    def _button(self, parent: tk.Widget, title: str, action: Callable,
                primary: bool = False, **kwargs: Any) -> tk.Button:
        normal_bg = RED if primary else PANEL2
        hover_bg = RED_HOVER if primary else HOVER
        button = tk.Button(parent, text=title, command=action,
                           bg=normal_bg, fg=WHITE,
                           activebackground=hover_bg, activeforeground=WHITE,
                           relief="flat", bd=0, highlightthickness=0,
                           font=("Segoe UI Semibold", 10), cursor="hand2",
                           padx=15, pady=11, **kwargs)

        def on_enter(event: tk.Event) -> None:
            if button.cget("state") == "normal":
                event.widget.configure(bg=hover_bg)

        def on_leave(event: tk.Event) -> None:
            if button.cget("state") == "normal":
                event.widget.configure(bg=normal_bg)

        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
        return button

    def _panel(self, parent: tk.Widget, padx: int = 17, pady: int = 15) -> tk.Frame:
        f = tk.Frame(parent, bg=PANEL, padx=padx, pady=pady, highlightthickness=1,
                     highlightbackground=LINE)
        tk.Frame(f, bg=RED, height=2).pack(fill="x", pady=(0, 11))
        return f

    def _page_title(self, parent: tk.Widget, heading: str, desc: str) -> None:
        self._text(parent, "DPN  /  MODULE", 8, RED, True).pack(anchor="w", pady=(0, 5))
        self._text(parent, heading, 22, WHITE, True).pack(anchor="w", pady=(0, 4))
        self._text(parent, desc, 9, MUTED).pack(anchor="w", pady=(0, 16))

    def _layout(self) -> None:
        self.sidebar = tk.Frame(self.root, bg=SIDE, width=238)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self.sidebar, bg=RED, height=5).pack(fill="x")
        title = tk.Frame(self.sidebar, bg=SIDE, padx=19, pady=16)
        title.pack(fill="x")
        logo = self._load_logo("dpn_logo_sidebar.png")
        if logo is not None:
            tk.Label(title, image=logo, bg=SIDE, bd=0).pack(anchor="center")
        else:
            self._text(title, "DPN // TECHNOLOGY", 10, RED, True).pack(anchor="center")
        self._text(title, "SYSTEM OPTIMIZER", 12, WHITE, True).pack(anchor="center", pady=(7, 0))
        self._text(title, "CONTROL CENTER  /  v2.0", 8, MUTED, True).pack(anchor="center", pady=(3, 0))
        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x", padx=18, pady=(0, 13))
        nav = tk.Frame(self.sidebar, bg=SIDE)
        nav.pack(fill="x", padx=9)
        tabs = ("Dashboard", "Processes", "Cleaner", "Disk Map", "File Finder", "Startup",
                "Automation", "Windows Health", "Reports")
        for index, tab in enumerate(tabs, start=1):
            row = tk.Frame(nav, bg=SIDE, height=38)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)
            mark = tk.Frame(row, bg=SIDE, width=3)
            mark.pack(side="left", fill="y")
            icon = tk.Label(row, text=f"{index:02}", width=3, bg=SIDE, fg=MUTED,
                            font=("Consolas", 9, "bold"))
            icon.pack(side="left", padx=(8, 5))
            btn = tk.Button(row, text=tab, anchor="w", fg=WHITE,
                            bg=SIDE, relief="flat", bd=0, highlightthickness=0,
                            activebackground=HOVER, activeforeground=WHITE, padx=5,
                            cursor="hand2", font=("Segoe UI Semibold", 10),
                            command=lambda tab=tab: self.show(tab))
            btn.pack(side="left", fill="both", expand=True, padx=(0, 7))
            icon.bind("<Button-1>", lambda event, tab=tab: self._nav_icon_click(event, tab))
            icon.configure(cursor="hand2")
            btn.bind("<Enter>", lambda event, row=row, tab=tab: self._nav_hover(event, row, tab, True))
            btn.bind("<Leave>", lambda event, row=row, tab=tab: self._nav_hover(event, row, tab, False))
            icon.bind("<Enter>", lambda event, row=row, tab=tab: self._nav_hover(event, row, tab, True))
            icon.bind("<Leave>", lambda event, row=row, tab=tab: self._nav_hover(event, row, tab, False))
            self.buttons[tab] = btn
            self.nav_icons[tab] = icon
            self.nav_marks[tab] = mark
        safety = tk.Frame(self.sidebar, bg=PANEL, padx=13, pady=12,
                          highlightthickness=1, highlightbackground=LINE)
        safety.pack(side="bottom", fill="x", padx=12, pady=13)
        row = tk.Frame(safety, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="●", bg=PANEL, fg=GREEN, font=("Segoe UI", 10)).pack(side="left")
        self._text(row, "LOCAL MODE ACTIVE", 8, GREEN, True).pack(side="left", padx=(7, 0))
        self._text(safety, "Preview first  ·  No telemetry\nNo registry cleanup", 8, MUTED).pack(
            anchor="w", pady=(7, 0))
        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(self.main, bg=BG, padx=30, pady=13)
        header.pack(fill="x")
        heading = tk.Frame(header, bg=BG)
        heading.pack(side="left", fill="y")
        self._text(heading, "DPN TECHNOLOGY  /  SYSTEMS", 8, RED, True).pack(anchor="w")
        self.header_route = self._text(heading, "CONTROL ROOM  /  DASHBOARD", 10, WHITE, True)
        self.header_route.pack(anchor="w", pady=(4, 0))
        status_box = tk.Frame(header, bg=PANEL, padx=11, pady=7,
                              highlightthickness=1, highlightbackground=LINE)
        status_box.pack(side="right")
        self.status = tk.Label(status_box, text="●  READY", bg=PANEL, fg=GREEN,
                               font=("Segoe UI Semibold", 9))
        self.status.pack()
        self._button(header, "Appearance", self._appearance_settings).pack(
            side="right", padx=(0, 10)
        )
        tk.Frame(self.main, height=1, bg=LINE).pack(fill="x")
        self._binary_rain(self.main)
        container = tk.Frame(self.main, bg=BG)
        container.pack(fill="both", expand=True, padx=30, pady=20)
        for tab in self.buttons:
            page = tk.Frame(container, bg=BG)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[tab] = page
        self._dashboard(self.pages["Dashboard"])
        self._process_explorer(self.pages["Processes"])
        self._cleaner(self.pages["Cleaner"])
        self._disk_map(self.pages["Disk Map"])
        self._file_finder(self.pages["File Finder"])
        self._startup(self.pages["Startup"])
        self._automation(self.pages["Automation"])
        self._health(self.pages["Windows Health"])
        self._reports(self.pages["Reports"])
        self.show("Dashboard")

    def _show_boot_splash(self) -> None:
        self.boot_splash = tk.Frame(self.root, bg=BG)
        self.boot_splash.place(x=0, y=0, relwidth=1, relheight=1)
        self.boot_splash.lift()

        self.boot_backdrop = tk.Canvas(self.boot_splash, bg=BG, highlightthickness=0)
        self.boot_backdrop.pack(fill="both", expand=True)
        self.boot_backdrop.bind("<Configure>", self._draw_boot_backdrop)

        self.boot_card = tk.Frame(
            self.boot_splash, bg=PANEL, padx=30, pady=24,
            highlightthickness=1, highlightbackground=LINE
        )
        self.boot_card.place(relx=0.5, rely=0.5, width=870, height=486, anchor="center")

        top = tk.Frame(self.boot_card, bg=PANEL)
        top.pack(fill="x")
        self._text(top, "DPN  /  SYSTEM INITIALIZATION", 9, RED, True).pack(side="left")
        self._text(top, "LOCAL SESSION    •    NO TELEMETRY", 8, MUTED, True).pack(side="right")
        tk.Frame(self.boot_card, bg=LINE, height=1).pack(fill="x", pady=(15, 20))

        main = tk.Frame(self.boot_card, bg=PANEL)
        main.pack(fill="both", expand=True)
        logo_frame = tk.Frame(main, bg="#0B0D12", width=238, height=265,
                              highlightthickness=1, highlightbackground=LINE)
        logo_frame.pack(side="left", fill="y", padx=(0, 27))
        logo_frame.pack_propagate(False)
        splash_logo = self._load_logo("dpn_logo_boot.png")
        if splash_logo is not None:
            tk.Label(logo_frame, image=splash_logo, bg="#0B0D12", bd=0).pack(expand=True)
        else:
            self._text(logo_frame, "DPN // TECHNOLOGY", 10, RED, True).pack(expand=True)
        self._text(logo_frame, "BINARY SYSTEMS  /  LOCAL", 8, MUTED, True).pack(pady=(0, 14))

        info = tk.Frame(main, bg=PANEL)
        info.pack(side="left", fill="both", expand=True)
        self._text(info, "WINDOWS PERFORMANCE SUITE", 8, MUTED, True).pack(anchor="w")
        self.boot_title = self._text(info, "SYSTEM OPTIMIZER", 26, WHITE, True)
        self.boot_title.pack(anchor="w", pady=(6, 0))
        self.boot_binary = self._text(info, "", 9, RED, True)
        self.boot_binary.configure(font=("Consolas", 9, "bold"))
        self.boot_binary.pack(anchor="w", pady=(7, 0))
        self._text(info, "Local-first diagnostics. Conservative maintenance.", 9, MUTED).pack(
            anchor="w", pady=(5, 13))

        self.boot_steps: list[tuple[tk.Label, tk.Label]] = []
        for index, (name, detail) in enumerate((
            ("DPN INTERFACE", "NAVIGATION  /  LOCAL WORKSPACE"),
            ("LIVE DIAGNOSTICS", "CPU  /  MEMORY  /  STORAGE"),
            ("SAFETY CONTROLS", "PREVIEW FIRST  /  EXPLICIT ACTIONS"),
        ), start=1):
            step = tk.Frame(info, bg=PANEL2, padx=10, pady=8)
            step.pack(fill="x", pady=3)
            mark = tk.Label(step, text=f"{index:02}", bg=PANEL2, fg=RED,
                            font=("Consolas", 9, "bold"), width=3)
            mark.pack(side="left")
            labels = tk.Frame(step, bg=PANEL2)
            labels.pack(side="left", padx=(6, 0))
            self._text(labels, name, 8, WHITE, True).pack(anchor="w")
            self._text(labels, detail, 7, MUTED, True).pack(anchor="w", pady=(2, 0))
            state = self._text(step, "READY", 7, MUTED, True)
            state.pack(side="right")
            self.boot_steps.append((mark, state))

        footer = tk.Frame(self.boot_card, bg=PANEL)
        footer.pack(fill="x", pady=(19, 0))
        self.boot_status = self._text(footer, "PREPARING LOCAL COMMAND CENTER", 8, MUTED, True)
        self.boot_status.pack(side="left")
        self.boot_percent = self._text(footer, "00%", 9, RED, True)
        self.boot_percent.pack(side="right")
        self.boot_progress = tk.Canvas(
            self.boot_card, height=5, bg=PANEL2, highlightthickness=0
        )
        self.boot_progress.pack(fill="x", pady=(9, 0))
        self.boot_bar = self.boot_progress.create_rectangle(0, 0, 0, 5, fill=RED, width=0)
        self._text(self.boot_card, "DPN TECHNOLOGY   /   WINDOWS DESKTOP   /   LOCAL-FIRST",
                   7, MUTED, True).pack(anchor="center", pady=(15, 0))

        self._boot_splash_dismissing = False
        self._boot_started = time.monotonic()
        self._boot_splash_tick()
        self.root.after(2500, self._dismiss_boot_splash)

    def _draw_boot_backdrop(self, event: tk.Event) -> None:
        canvas = self.boot_backdrop
        canvas.delete("all")
        width, height = max(event.width, 1), max(event.height, 1)
        center_x, center_y = width / 2, height / 2
        for scale, color in ((1.0, "#13151B"), (0.82, "#101217"), (0.64, "#0D0F14")):
            radius_x, radius_y = width * 0.46 * scale, height * 0.58 * scale
            canvas.create_oval(center_x - radius_x, center_y - radius_y,
                               center_x + radius_x, center_y + radius_y,
                               outline=color, width=1)
        canvas.create_text(28, 25, anchor="w", fill="#414652",
                           font=("Consolas", 8, "bold"), text="DPN // BOOT CONSOLE")
        canvas.create_text(width - 28, height - 23, anchor="e", fill="#414652",
                           font=("Consolas", 8, "bold"), text="LOCAL SYSTEM  /  01")
        self.boot_scanline = canvas.create_line(
            0, 0, width, 0, fill="#29141A", width=1
        )
        columns = max(1, int(width // 52))
        for column in range(columns):
            x = 18 + column * 52
            for row in range(max(1, int(height // 37))):
                if random.random() < 0.34:
                    y = 53 + row * 37
                    canvas.create_text(
                        x, y, text=random.choice("01"),
                        fill=random.choice(("#252832", "#29191F", "#36141C")),
                        font=("Consolas", 8)
                    )

    def _boot_splash_tick(self) -> None:
        if (self._boot_splash_dismissing or not self.root.winfo_exists()
                or not self.boot_splash.winfo_exists()):
            return
        duration = 2.5
        progress = min((time.monotonic() - self._boot_started) / duration, 1.0)
        resolved = min(len("SYSTEM OPTIMIZER"), int(progress * 19))
        scramble = "".join(
            char if index < resolved or char == " " else random.choice("01ABCDEF")
            for index, char in enumerate("SYSTEM OPTIMIZER")
        )
        self.boot_title.configure(text=scramble)
        self.boot_binary.configure(
            text="  ".join("".join(random.choice("01") for _ in range(4)) for _ in range(6))
        )
        width = self.boot_progress.winfo_width()
        self.boot_progress.coords(self.boot_bar, 0, 0, width * progress, 5)
        self.boot_percent.configure(text=f"{int(progress * 100):02}%")
        backdrop_height = max(self.boot_backdrop.winfo_height(), 1)
        scan_y = (time.monotonic() - self._boot_started) * 95 % backdrop_height
        if hasattr(self, "boot_scanline"):
            self.boot_backdrop.coords(
                self.boot_scanline, 0, scan_y, self.boot_backdrop.winfo_width(), scan_y
            )
        active_steps = min(
            int(progress * len(self.boot_steps)) + (1 if progress > 0 else 0),
            len(self.boot_steps),
        )
        for index, (mark, state) in enumerate(self.boot_steps):
            if index < active_steps:
                mark.configure(fg=RED)
                state.configure(text="ONLINE", fg=GREEN)
            else:
                mark.configure(fg=MUTED)
                state.configure(text="STANDBY", fg=MUTED)
        if progress < 1:
            self.root.after(70, self._boot_splash_tick)

    def _dismiss_boot_splash(self) -> None:
        if not self.boot_splash.winfo_exists():
            return
        self._boot_splash_dismissing = True
        self.boot_title.configure(text="SYSTEM OPTIMIZER")
        self.boot_status.configure(text="READY // LOCAL-FIRST")
        self.boot_percent.configure(text="100%")
        self.boot_progress.coords(self.boot_bar, 0, 0, self.boot_progress.winfo_width(), 5)
        for mark, state in self.boot_steps:
            mark.configure(fg=RED)
            state.configure(text="ONLINE", fg=GREEN)
        self.root.after(150, self.boot_splash.destroy)

    def _binary_rain(self, parent: tk.Widget) -> None:
        self.rain = tk.Canvas(parent, height=56, bg=BG, highlightthickness=0)
        self.rain.pack(fill="x")
        self.rain_cols: list[list[Any]] = []
        self.rain_fade = ("#2A0605", "#5C0A07", "#A10D08", RED)
        self.rain.bind("<Configure>", self._rain_resize)

    def _rain_resize(self, event: tk.Event) -> None:
        spacing = {"Low": 28, "Standard": 14, "High": 10}[self.appearance.intensity]
        count = max(1, event.width // spacing)
        while len(self.rain_cols) < count:
            self.rain_cols.append([random.randint(-4, 3), random.randint(0, 3)])
        del self.rain_cols[count:]
        self._restart_rain()

    def _restart_rain(self) -> None:
        if self._rain_job is not None:
            self.root.after_cancel(self._rain_job)
            self._rain_job = None
        self.rain.delete("all")
        if self.appearance.binary_rain and not self.appearance.reduced_motion:
            self._rain_tick()
        else:
            self.rain.create_text(
                18, 28, text="DPN // LOCAL-FIRST SYSTEMS", fill=MUTED,
                anchor="w", font=("Consolas", 10, "bold")
            )

    def _rain_tick(self) -> None:
        self._rain_job = None
        if self.root.winfo_exists():
            self.rain.delete("all")
            spacing = {"Low": 28, "Standard": 14, "High": 10}[self.appearance.intensity]
            for i, col in enumerate(self.rain_cols):
                col[0] += 1
                if col[0] > 6:
                    col[0] = random.randint(-6, 0)
                for t in range(4):
                    row = col[0] - (3 - t)
                    if 0 <= row < 4:
                        self.rain.create_text(i * spacing + 7, row * 14 + 7, text=random.choice("01"),
                                              fill=self.rain_fade[t], font=("Consolas", 10, "bold"))
            self.rain.create_text(self.rain.winfo_width() - 12, 28, text="DPN // 1011 0100",
                                  fill=WHITE, anchor="e", font=("Consolas", 11, "bold"))
            interval = {"Low": 260, "Standard": 140, "High": 90}[self.appearance.intensity]
            self._rain_job = self.root.after(interval, self._rain_tick)

    def _appearance_settings(self) -> None:
        if self.appearance_dialog is not None and self.appearance_dialog.winfo_exists():
            self.appearance_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self.appearance_dialog = dialog
        dialog.title("DPN // Appearance")
        dialog.configure(bg=BG, padx=24, pady=22)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        self._text(dialog, "APPEARANCE & MOTION", 16, WHITE, True).pack(anchor="w")
        self._text(
            dialog, "Personalize DPN without changing monitoring or cleanup behavior.",
            9, MUTED
        ).pack(anchor="w", pady=(7, 18))
        rain = tk.BooleanVar(value=self.appearance.binary_rain)
        reduced = tk.BooleanVar(value=self.appearance.reduced_motion)
        intro = tk.BooleanVar(value=self.appearance.show_intro)
        intensity = tk.StringVar(value=self.appearance.intensity)
        for label, variable in (
            ("Animate the binary-rain banner", rain),
            ("Reduced motion (static banner and no boot intro)", reduced),
            ("Show boot intro on launch", intro),
        ):
            tk.Checkbutton(
                dialog, text=label, variable=variable, bg=BG, fg=WHITE,
                activebackground=BG, activeforeground=WHITE, selectcolor=PANEL2,
                font=("Segoe UI", 10), anchor="w"
            ).pack(anchor="w", pady=5)
        row = tk.Frame(dialog, bg=BG)
        row.pack(fill="x", pady=(14, 0))
        self._text(row, "BINARY INTENSITY", 9, MUTED, True).pack(side="left")
        ttk.Combobox(
            row, textvariable=intensity, values=("Low", "Standard", "High"),
            state="readonly", width=14
        ).pack(side="right")
        self._text(
            dialog, "Low draws fewer digits at a slower rate. Reduced motion overrides\n"
                    "both animation switches. Changes apply immediately after saving.",
            9, MUTED
        ).pack(anchor="w", pady=(14, 0))
        feedback = self._text(dialog, "", 9, RED, wraplength=450)
        feedback.pack(anchor="w", fill="x", pady=(10, 0))

        def save() -> None:
            candidate = AppearancePreferences(
                binary_rain=rain.get(), reduced_motion=reduced.get(),
                show_intro=intro.get(), intensity=intensity.get()
            )
            try:
                save_preferences(candidate)
            except (OSError, ValueError) as exc:
                feedback.configure(text=f"Not saved: {exc}")
                return
            self.appearance = candidate
            spacing = {"Low": 28, "Standard": 14, "High": 10}[candidate.intensity]
            count = max(1, self.rain.winfo_width() // spacing)
            self.rain_cols = [[random.randint(-4, 3), 0] for _ in range(count)]
            self._restart_rain()
            dialog.destroy()

        actions = tk.Frame(dialog, bg=BG)
        actions.pack(fill="x", pady=(6, 0))
        self._button(actions, "Save Appearance", save, primary=True).pack(side="right")
        self._button(actions, "Cancel", dialog.destroy).pack(side="right", padx=8)

    def show(self, name: str) -> None:
        self.page = name
        self.header_route.configure(text=f"CONTROL ROOM  /  {name.upper()}")
        self.pages[name].lift()
        for key, b in self.buttons.items():
            b.configure(bg=PANEL2 if key == name else SIDE,
                        fg=WHITE if key == name else MUTED)
            self.nav_icons[key].configure(
                bg=PANEL2 if key == name else SIDE,
                fg=RED if key == name else MUTED)
            self.nav_marks[key].configure(bg=RED if key == name else SIDE)
        if name == "Startup":
            self._load_startup()
        elif name == "Processes":
            self._refresh_processes()
        elif name == "Reports":
            self._load_reports()
        elif name == "Automation":
            self._load_scheduler()

    def _nav_icon_click(self, event: tk.Event, tab: str) -> None:
        event.widget.focus_set()
        self.show(tab)

    def _nav_hover(self, event: tk.Event, row: tk.Frame, tab: str, entering: bool) -> None:
        if self.page != tab:
            color = HOVER if entering else SIDE
            row.configure(bg=color)
            event.widget.configure(bg=color)

    def _make_tree(self, parent: tk.Widget, columns: tuple[str, ...], widths: tuple[int, ...],
                   height: int = 10) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height,
                            style="DPN.Treeview")
        for col, w in zip(columns, widths):
            tree.heading(col, text=col.upper())
            tree.column(col, width=w, minwidth=70, anchor="w", stretch=True)
        tree.pack(fill="both", expand=True, pady=(10, 0))
        return tree

    def _dashboard(self, page: tk.Frame) -> None:
        self._page_title(page, "Live System Diagnostics",
                         "Current resource usage — no tweaks or background services installed.")
        tiles = tk.Frame(page, bg=BG)
        tiles.pack(fill="x")
        for n, name in enumerate(("CPU UTILIZATION", "PHYSICAL MEMORY", "SYSTEM DRIVE")):
            panel = self._panel(tiles, 15, 12)
            panel.grid(row=0, column=n, sticky="nsew", padx=(0, 10) if n < 2 else 0)
            tiles.columnconfigure(n, weight=1)
            self._text(panel, name, 9, MUTED, True).pack(anchor="w")
            label = self._text(panel, "—", 27, WHITE, True)
            label.pack(anchor="w", pady=(9, 3))
            self.metrics[name] = label
            subtitle = self._text(panel, "Monitoring", 9, MUTED)
            subtitle.pack(anchor="w")
            self.metrics[name + " subtitle"] = subtitle
            sparkline = tk.Canvas(panel, height=25, bg=PANEL, highlightthickness=0)
            sparkline.pack(fill="x", pady=(7, 0))
            self.sparklines[name] = sparkline
        notes = self._panel(page, 13, 10)
        notes.pack(fill="x", pady=(14, 14))
        intelligence = tk.Frame(notes, bg=PANEL)
        intelligence.pack(fill="x")
        self.health_gauge = tk.Canvas(
            intelligence, width=82, height=82, bg=PANEL, highlightthickness=0
        )
        self.health_gauge.pack(side="left", padx=(0, 14))
        self.advice_panel = tk.Frame(intelligence, bg=PANEL)
        self.advice_panel.pack(side="left", fill="x", expand=True)
        self._text(self.advice_panel, "SYSTEM INTELLIGENCE // SNAPSHOT SCORE",
                   10, RED, True).pack(anchor="w")
        self.advice = self._text(self.advice_panel, "Checking resource health…", 10, WHITE,
                                 wraplength=685)
        self.advice.pack(anchor="w", pady=(7, 0), fill="x")
        self._draw_health_gauge(None)
        processes = self._panel(page, 12, 10)
        processes.pack(fill="both", expand=True)
        row = tk.Frame(processes, bg=PANEL)
        row.pack(fill="x")
        self._text(row, "TOP MEMORY CONSUMERS", 10, WHITE, True).pack(side="left")
        self._button(row, "Process Explorer", lambda: self.show("Processes")).pack(
            side="right", padx=(8, 0)
        )
        self._button(row, "Refresh", self._poll_performance).pack(side="right")
        self.processes = self._make_tree(processes, ("Process", "PID", "RAM used"),
                                         (320, 90, 140), height=9)
        self._text(page, "Metrics are samples, not proof of sustained performance problems. psutil enables CPU and process monitoring.",
                   9, MUTED).pack(anchor="w", pady=(10, 0))

    def _process_explorer(self, page: tk.Frame) -> None:
        self._page_title(
            page, "Process Explorer",
            "Inspect local CPU and memory use. Ending a process is manual, confirmed, and limited to verified user apps.",
        )
        controls = self._panel(page, 13, 10)
        controls.pack(fill="x")
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x")
        self._text(row, "FILTER", 8, MUTED, True).pack(side="left")
        self.process_filter = tk.StringVar()
        search = tk.Entry(
            row, textvariable=self.process_filter, bg=PANEL2, fg=WHITE,
            insertbackground=WHITE, bd=0, relief="flat", font=("Segoe UI", 10), width=30
        )
        search.pack(side="left", padx=(9, 14), ipady=7)
        self.process_filter.trace_add("write", lambda *_: self._render_process_rows())
        self.process_refresh_button = self._button(
            row, "Refresh Snapshot", self._refresh_processes, primary=True
        )
        self.process_refresh_button.pack(side="left")
        self.end_process_button = self._button(
            row, "End Selected Process", self._end_selected_process
        )
        self.end_process_button.pack(side="left", padx=(8, 0))
        self.end_process_button.configure(state="disabled")
        self.process_status = self._text(controls, "Optional psutil required for detailed process data.", 8, MUTED)
        self.process_status.pack(anchor="w", pady=(8, 0))

        overview = self._panel(page, 12, 10)
        overview.pack(fill="both", expand=True, pady=(12, 0))
        self._text(overview, "LIVE PROCESS SNAPSHOT  /  SORTED BY CPU THEN RAM",
                   8, RED, True).pack(anchor="w")
        self.process_explorer_table = self._make_tree(
            overview,
            ("Process", "PID", "CPU %", "RAM", "RAM %", "User", "State"),
            (205, 75, 75, 100, 75, 145, 95),
            height=12,
        )
        self.process_explorer_table.bind("<<TreeviewSelect>>", self._select_process)
        self.process_explorer_table.tag_configure("protected", foreground=MUTED)

        details = self._panel(page, 12, 9)
        details.pack(fill="x", pady=(12, 0))
        self._text(details, "SELECTED PROCESS DETAILS", 8, RED, True).pack(anchor="w")
        self.process_detail = tk.Text(
            details, height=3, bg=PANEL2, fg=MUTED, bd=0,
            font=("Consolas", 8), wrap="word", state="disabled"
        )
        self.process_detail.pack(fill="x", pady=(8, 0))

    def _refresh_processes(self) -> None:
        if self.process_refresh_busy or self.process_action_busy:
            return
        self.process_refresh_busy = True
        self.process_refresh_button.configure(state="disabled")
        self.process_status.configure(text="Collecting a local process snapshot…", fg=RED)

        def worker() -> None:
            try:
                self.events.put(("process_snapshot", list_process_details()))
            except (RuntimeError, OSError) as exc:
                self.events.put(("process_snapshot_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _render_process_rows(self) -> None:
        if not hasattr(self, "process_explorer_table"):
            return
        query = self.process_filter.get().strip().casefold()
        tree = self.process_explorer_table
        self.end_process_button.configure(state="disabled")
        tree.delete(*tree.get_children())
        for item in self.process_rows.values():
            searchable = f"{item['name']} {item['pid']} {item['username']} {item['exe']}".casefold()
            if query and query not in searchable:
                continue
            pid = str(item["pid"])
            tree.insert(
                "", "end", iid=pid,
                values=(item["name"], pid, f"{item['cpu_percent']:.1f}",
                        human_bytes(item["ram_bytes"]), f"{item['memory_percent']:.1f}",
                        item["username"], item["status"]),
                tags=() if item["can_end"] else ("protected",),
            )

    def _select_process(self, _event: Any) -> None:
        selection = self.process_explorer_table.selection()
        item = self.process_rows.get(selection[0]) if selection else None
        self.end_process_button.configure(
            state="normal" if item and item["can_end"] and not self.process_action_busy else "disabled"
        )
        self.process_detail.configure(state="normal")
        self.process_detail.delete("1.0", "end")
        if item:
            eligibility = "Verified current-user app; ending it may lose unsaved work." if item["can_end"] \
                else "Protected or unverifiable process; the end action is disabled."
            self.process_detail.insert(
                "end", f"{item['name']}  |  PID {item['pid']}  |  {item['username']}\n"
                       f"CPU {item['cpu_percent']:.1f}%  |  RAM {human_bytes(item['ram_bytes'])} "
                       f"({item['memory_percent']:.1f}%)  |  {item['status']}\n"
                       f"Image: {item['exe'] or 'Unavailable'}\n{eligibility}"
            )
        else:
            self.process_detail.insert("end", "Select a process to inspect its details.")
        self.process_detail.configure(state="disabled")

    def _end_selected_process(self) -> None:
        selection = self.process_explorer_table.selection()
        item = self.process_rows.get(selection[0]) if selection else None
        if not item or not item["can_end"] or self.process_action_busy:
            return
        if not messagebox.askyesno(
            "End selected process?",
            f"End {item['name']} (PID {item['pid']}) now?\n\n"
            "Windows process termination is immediate. Unsaved work may be lost. "
            "Only this verified current-user process will be targeted.",
            icon="warning",
        ):
            return

        self.process_action_busy = True
        self.end_process_button.configure(state="disabled")
        self.process_status.configure(text=f"Ending {item['name']} (PID {item['pid']})…", fg=RED)

        def worker() -> None:
            try:
                terminate_user_process(
                    item["pid"], item["name"], item["create_time"], item["username"]
                )
                self.events.put(("process_ended", item["name"]))
            except (ProcessActionError, OSError) as exc:
                self.events.put(("process_action_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _file_finder(self, page: tk.Frame) -> None:
        self._page_title(
            page, "Duplicate & Large File Finder",
            "Find exact duplicate content and review the biggest files. Scan only; this tool never deletes.",
        )
        controls = self._panel(page, 14, 11)
        controls.pack(fill="x")
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x")
        self._text(row, "SCAN LOCATION", 8, MUTED, True).pack(side="left")
        self.insight_location = tk.StringVar(value="User profile")
        ttk.Combobox(
            row, textvariable=self.insight_location, state="readonly", width=23,
            values=list(self.disk_locations),
        ).pack(side="left", padx=(9, 18))
        self._text(row, "MIN SIZE", 8, MUTED, True).pack(side="left")
        self.insight_min_mb = tk.StringVar(value="1")
        tk.Entry(row, width=5, textvariable=self.insight_min_mb, bg=PANEL2, fg=WHITE,
                 insertbackground=WHITE, bd=0, relief="flat",
                 font=("Consolas", 10)).pack(side="left", padx=(9, 5))
        self._text(row, "MB", 8, MUTED, True).pack(side="left")
        self.insight_scan_button = self._button(
            row, "Analyze Files", self._start_file_insight_scan, primary=True
        )
        self.insight_scan_button.pack(side="left", padx=(16, 0))
        self.insight_stop_button = self._button(row, "Stop Scan", self.insight_cancel.set)
        self.insight_stop_button.pack(side="left", padx=(7, 0))
        self.insight_stop_button.configure(state="disabled")
        self.insight_status = self._text(controls, "Ready for a local scan.", 8, MUTED)
        self.insight_status.pack(anchor="w", fill="x", pady=(8, 0))

        self.insight_summary = self._text(
            page, "SHA-256 exact-match detection  ·  reparse points skipped  ·  bounded scan",
            8, MUTED, True
        )
        self.insight_summary.pack(anchor="w", pady=(10, 8))

        notebook = ttk.Notebook(page, style="DPN.TNotebook")
        notebook.pack(fill="both", expand=True)
        duplicate_tab = tk.Frame(notebook, bg=BG, padx=3, pady=9)
        large_tab = tk.Frame(notebook, bg=BG, padx=3, pady=9)
        notebook.add(duplicate_tab, text="  DUPLICATE GROUPS  ")
        notebook.add(large_tab, text="  LARGEST FILES  ")

        dup_panel = self._panel(duplicate_tab, 12, 10)
        dup_panel.pack(fill="both", expand=True)
        self._text(dup_panel, "EXACT CONTENT MATCHES", 9, RED, True).pack(anchor="w")
        self.duplicate_table = self._make_tree(
            dup_panel, ("Potentially reclaimable", "Copies", "File size", "Sample path"),
            (155, 70, 110, 510), height=12
        )
        duplicate_vertical = ttk.Scrollbar(
            dup_panel, orient="vertical", command=self.duplicate_table.yview
        )
        duplicate_vertical.pack(side="right", fill="y")
        duplicate_scroll = ttk.Scrollbar(
            dup_panel, orient="horizontal", command=self.duplicate_table.xview
        )
        duplicate_scroll.pack(fill="x", pady=(5, 0))
        self.duplicate_table.configure(
            xscrollcommand=duplicate_scroll.set, yscrollcommand=duplicate_vertical.set
        )
        self.duplicate_table.bind("<<TreeviewSelect>>", self._select_duplicate_group)
        self.duplicate_detail = tk.Text(
            dup_panel, height=5, bg=PANEL2, fg=MUTED, bd=0,
            font=("Consolas", 8), wrap="word", state="disabled"
        )
        self.duplicate_detail.pack(fill="x", pady=(10, 0))
        self.duplicate_results: list[dict[str, Any]] = []

        large_panel = self._panel(large_tab, 12, 10)
        large_panel.pack(fill="both", expand=True)
        header = tk.Frame(large_panel, bg=PANEL)
        header.pack(fill="x")
        self._text(header, "LARGEST FILES IN SELECTED LOCATION", 9, RED, True).pack(side="left")
        self._button(header, "Open Selected Folder", self._open_insight_file_folder).pack(side="right")
        self.large_file_table = self._make_tree(
            large_panel, ("Size", "Path"), (110, 700), height=16
        )
        large_vertical = ttk.Scrollbar(
            large_panel, orient="vertical", command=self.large_file_table.yview
        )
        large_vertical.pack(side="right", fill="y")
        large_scroll = ttk.Scrollbar(
            large_panel, orient="horizontal", command=self.large_file_table.xview
        )
        large_scroll.pack(fill="x", pady=(5, 0))
        self.large_file_table.configure(
            xscrollcommand=large_scroll.set, yscrollcommand=large_vertical.set
        )
        self.large_file_paths: dict[str, str] = {}

    def _start_file_insight_scan(self) -> None:
        if self.insight_busy:
            return
        root = self.disk_locations[self.insight_location.get()]
        if not root.is_dir():
            messagebox.showwarning("Location unavailable", f"{root} was not found.")
            return
        try:
            min_size = int(self.insight_min_mb.get()) * 1024 * 1024
            if not 1 <= int(self.insight_min_mb.get()) <= 1024:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid minimum size", "Enter a whole number from 1 to 1024 MB.")
            return

        self.insight_busy = True
        self.insight_cancel.clear()
        self.insight_scan_button.configure(state="disabled")
        self.insight_stop_button.configure(state="normal")
        self.insight_status.configure(text="Indexing files…", fg=RED)
        self.insight_summary.configure(text="Indexing candidate files. Content is hashed only for same-size matches.")

        def worker() -> None:
            try:
                result = scan_file_insights(
                    root, min_size=min_size, cancelled=self.insight_cancel.is_set,
                    progress=lambda count, phase: self.events.put(
                        ("insight_progress", (count, phase))
                    ),
                )
                self.events.put(("insight_done", result))
            except Exception as exc:
                self.events.put(("insight_error", f"File analysis failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_file_insight_result(self, result: dict[str, Any]) -> None:
        self.duplicate_results = result["duplicates"]
        self.duplicate_table.delete(*self.duplicate_table.get_children())
        for index, group in enumerate(self.duplicate_results):
            self.duplicate_table.insert(
                "", "end", iid=str(index),
                values=(human_bytes(group["reclaimable_bytes"]), len(group["paths"]),
                        human_bytes(group["bytes_each"]), group["paths"][0]),
            )
        self.duplicate_detail.configure(state="normal")
        self.duplicate_detail.delete("1.0", "end")
        self.duplicate_detail.insert(
            "end", "Select a duplicate group to inspect every matching path. "
                   "No files are modified."
        )
        self.duplicate_detail.configure(state="disabled")

        self.large_file_table.delete(*self.large_file_table.get_children())
        self.large_file_paths = {}
        for item in result["largest_files"]:
            row = self.large_file_table.insert(
                "", "end", values=(human_bytes(item["bytes"]), item["path"])
            )
            self.large_file_paths[row] = item["path"]

        partial = " · PARTIAL SCAN" if result["truncated"] else ""
        self.insight_status.configure(
            text=f"{result['files_seen']:,} files · {result['errors']} unreadable{partial}",
            fg=RED if result["truncated"] else MUTED,
        )
        self.insight_summary.configure(
            text=(f"{result['duplicate_groups']} exact-match groups  ·  "
                  f"{human_bytes(result['reclaimable_bytes'])} potentially reclaimable  ·  "
                  f"{result['files_hashed']:,} files hashed  ·  estimates only; review before action")
        )
        self.insight_busy = False
        self.insight_scan_button.configure(state="normal")
        self.insight_stop_button.configure(state="disabled")

    def _select_duplicate_group(self, _event: Any) -> None:
        selected = self.duplicate_table.selection()
        if not selected:
            return
        try:
            group = self.duplicate_results[int(selected[0])]
        except (IndexError, ValueError):
            return
        self.duplicate_detail.configure(state="normal")
        self.duplicate_detail.delete("1.0", "end")
        self.duplicate_detail.insert(
            "end", f"SHA-256: {group['sha256']}\n"
                   f"Potentially reclaimable: {human_bytes(group['reclaimable_bytes'])}\n"
                   + "\n".join(group["paths"])
        )
        self.duplicate_detail.configure(state="disabled")

    def _open_insight_file_folder(self) -> None:
        selected = self.large_file_table.selection()
        if not selected or os.name != "nt":
            return
        path = Path(self.large_file_paths.get(selected[0], ""))
        if path.parent.is_dir():
            os.startfile(path.parent)  # type: ignore[attr-defined]  # opens the folder only

    def _cleaner(self, page: tk.Frame) -> None:
        self._page_title(page, "Selective Storage Cleanup",
                         "Choose locations, preview eligible files, then authorize deletion.")
        top = self._panel(page)
        top.pack(fill="x")
        self._text(top, "CLEANUP TARGETS", 10, RED, True).pack(anchor="w", pady=(0, 10))
        for key, label in CATEGORIES.items():
            cb = tk.Checkbutton(top, text=label, variable=self.choice[key],
                                bg=PANEL, fg=WHITE, activebackground=PANEL,
                                activeforeground=WHITE, selectcolor=PANEL2,
                                font=("Segoe UI", 10), anchor="w", cursor="hand2")
            cb.pack(anchor="w", pady=2)
        row = tk.Frame(top, bg=PANEL)
        row.pack(fill="x", pady=(15, 0))
        self._text(row, "MINIMUM FILE AGE (HOURS)", 9, MUTED, True).pack(side="left")
        tk.Entry(row, width=7, textvariable=self.age, bg=PANEL2, fg=WHITE,
                 insertbackground=WHITE, bd=1, relief="flat",
                 font=("Consolas", 12)).pack(side="left", padx=12)
        self.preview_button = self._button(row, "Scan / Preview", lambda: self._start_cleanup(False))
        self.preview_button.pack(side="right")
        self.clean_button = self._button(row, "Apply Cleanup", lambda: self._start_cleanup(True), primary=True)
        self.clean_button.pack(side="right", padx=(0, 8))
        results = self._panel(page)
        results.pack(fill="both", expand=True, pady=(14, 0))
        self._text(results, "OPERATION REPORT", 10, WHITE, True).pack(anchor="w")
        self.progress = ttk.Progressbar(results, mode="indeterminate", style="DPN.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(12, 10))
        self.log = tk.Text(results, bg="#0B111B", fg="#DDE8F0", insertbackground=WHITE,
                           bd=0, relief="flat", height=11, font=("Consolas", 9),
                           wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self._log("Ready. Default: User temp only, files at least 48 hours old. Nothing is deleted by a preview.\n")

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + ("" if message.endswith("\n") else "\n"))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start_cleanup(self, apply: bool) -> None:
        if self.busy:
            messagebox.showinfo("Already running", "Another operation is running.")
            return
        selected = [key for key, state in self.choice.items() if state.get()]
        if not selected:
            messagebox.showwarning("Choose locations", "Choose at least one cleanup category.")
            return
        try:
            age = float(self.age.get())
            if not 1 <= age <= 8760:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid age", "Enter an age from 1 to 8760 hours.")
            return
        if apply:
            question = ("This will permanently DELETE eligible old files in:\n\n" +
                        "\n".join(" • " + CATEGORIES[x] for x in selected) +
                        f"\n\nMinimum file age: {age:g} hours. Continue?")
            if not messagebox.askyesno("Confirm cleanup", question, icon="warning"):
                return
        self.busy = True
        self.cancel_flag.clear()
        self.status.configure(text="●  RUNNING", fg=RED)
        self.preview_button.configure(state="disabled")
        self.clean_button.configure(state="disabled")
        self.progress.start(15)
        self._log("\n" + ("CLEANING" if apply else "PREVIEW") + " — " + ", ".join(selected))

        def worker() -> None:
            try:
                report = run_cleanup(selected, age_hours=age, apply=apply,
                                     notify=lambda msg: self.events.put(("log", msg)),
                                     cancelled=self.cancel_flag.is_set)
                self.events.put(("cleanup_done", report))
            except Exception as exc:
                self.events.put(("error", f"Cleanup failed: {type(exc).__name__}: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _end_busy(self) -> None:
        self.busy = False
        self.status.configure(text="●  READY", fg=GREEN)
        self.progress.stop()
        self.preview_button.configure(state="normal")
        self.clean_button.configure(state="normal")

    def _disk_map(self, page: tk.Frame) -> None:
        self._page_title(page, "Disk Space Map",
                         "Read-only scan showing which folders and files use the most space. Nothing is deleted or modified.")
        self.disk_busy = False
        self.disk_cancel = threading.Event()
        self.disk_locations = {
            "User profile": Path.home(),
            "Downloads": Path.home() / "Downloads",
            "Documents": Path.home() / "Documents",
            "System drive (slow, 45s cap)": Path(os.environ.get("SystemDrive", "C:") + "\\"),
        }
        self.disk_choice = tk.StringVar(value="User profile")
        controls = tk.Frame(page, bg=BG)
        controls.pack(fill="x")
        self._text(controls, "LOCATION", 9, MUTED, True).pack(side="left")
        picker = ttk.Combobox(controls, textvariable=self.disk_choice, state="readonly", width=30,
                              values=list(self.disk_locations))
        picker.pack(side="left", padx=12)
        self.disk_scan_button = self._button(controls, "Scan Space Usage", self._start_disk_scan, primary=True)
        self.disk_scan_button.pack(side="left")
        self.disk_stop_button = self._button(controls, "Stop", self.disk_cancel.set)
        self.disk_stop_button.pack(side="left", padx=8)
        self.disk_status = self._text(controls, "Not scanned yet.", 9, MUTED)
        self.disk_status.pack(side="right")

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=1, uniform="disk")
        body.columnconfigure(1, weight=1, uniform="disk")
        body.rowconfigure(0, weight=1)
        left = self._panel(body, 12, 10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._text(left, "LARGEST FOLDERS", 10, RED, True).pack(anchor="w")
        self.disk_bars = tk.Canvas(left, bg=PANEL, highlightthickness=0)
        self.disk_bars.pack(fill="both", expand=True, pady=(10, 0))
        self.disk_bars.bind("<Configure>", self._draw_disk_bars)
        self.disk_folders: list[dict[str, Any]] = []
        right = self._panel(body, 12, 10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        header = tk.Frame(right, bg=PANEL)
        header.pack(fill="x")
        self._text(header, "LARGEST FILES", 10, RED, True).pack(side="left")
        self._button(header, "Open Folder", self._open_selected_file_folder).pack(side="right")
        self.disk_files = self._make_tree(right, ("Size", "Path"), (90, 330), height=12)
        self.disk_file_paths: dict[str, str] = {}

    def _start_disk_scan(self) -> None:
        if self.disk_busy:
            return
        root = self.disk_locations[self.disk_choice.get()]
        if not root.is_dir():
            messagebox.showwarning("Location unavailable", f"{root} was not found.")
            return
        self.disk_busy = True
        self.disk_cancel.clear()
        self.disk_scan_button.configure(state="disabled")
        self.disk_status.configure(text="Scanning…", fg=RED)

        def worker() -> None:
            try:
                result = scan_disk_usage(
                    root, cancelled=self.disk_cancel.is_set,
                    progress=lambda n: self.events.put(("disk_progress", n)))
                self.events.put(("disk_done", result))
            except Exception as exc:
                self.events.put(("disk_error", f"Disk scan failed: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_disk_scan(self) -> None:
        self.disk_busy = False
        self.disk_scan_button.configure(state="normal")

    def _show_disk_result(self, result: dict[str, Any]) -> None:
        self.disk_folders = result["folders"][:12]
        self._draw_disk_bars()
        self.disk_files.delete(*self.disk_files.get_children())
        self.disk_file_paths = {}
        for item in result["largest_files"]:
            row = self.disk_files.insert("", "end", values=(human_bytes(item["bytes"]), item["path"]))
            self.disk_file_paths[row] = item["path"]
        note = " · partial (stopped early)" if result["truncated"] else ""
        self.disk_status.configure(
            text=(f"{human_bytes(result['total_bytes'])} in {result['files_seen']:,} files · "
                  f"{result['errors']} unreadable{note}"), fg=MUTED)
        self._finish_disk_scan()

    def _draw_disk_bars(self, event: tk.Event | None = None) -> None:
        canvas = self.disk_bars
        canvas.delete("all")
        width = max(event.width if event is not None else canvas.winfo_width(), 200)
        if not self.disk_folders:
            canvas.create_text(10, 12, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                               text="Run a scan to map folder sizes.")
            return
        biggest = max(f["bytes"] for f in self.disk_folders) or 1
        bar_left, bar_right = 150, width - 90
        for i, folder in enumerate(self.disk_folders):
            y = 6 + i * 30
            canvas.create_text(0, y + 10, anchor="w", fill=WHITE, font=("Segoe UI", 9),
                               text=folder["name"][:22])
            canvas.create_rectangle(bar_left, y + 3, bar_right, y + 17, fill=PANEL2, outline="")
            fill_to = bar_left + (bar_right - bar_left) * folder["bytes"] / biggest
            canvas.create_rectangle(bar_left, y + 3, fill_to, y + 17, fill=RED, outline="")
            canvas.create_text(width, y + 10, anchor="e", fill=MUTED, font=("Consolas", 9),
                               text=f"{human_bytes(folder['bytes'])} {folder['percent']:.0f}%")

    def _open_selected_file_folder(self) -> None:
        selected = self.disk_files.selection()
        if not selected or os.name != "nt":
            return
        path = Path(self.disk_file_paths.get(selected[0], ""))
        if path.parent.is_dir():
            os.startfile(path.parent)  # type: ignore[attr-defined]  # opens the folder only

    def _startup(self, page: tk.Frame) -> None:
        self._page_title(page, "Windows Startup Inventory",
                         "Read-only inventory. Estimates use app names; publisher signatures are not verified.")
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x")
        self._text(row, "Review entries before changing them in Windows Settings.",
                   10, MUTED).pack(side="left")
        self._button(row, "Refresh Inventory", self._load_startup).pack(side="right")
        panel = self._panel(page)
        panel.pack(fill="both", expand=True, pady=(16, 0))
        self.startup_table = self._make_tree(
            panel, ("Source", "Application", "Impact (estimate)", "Publisher", "Command (read-only)"),
            (120, 135, 115, 150, 360), height=16
        )
        startup_scroll = ttk.Scrollbar(panel, orient="horizontal", command=self.startup_table.xview)
        startup_scroll.pack(fill="x", pady=(6, 0))
        self.startup_table.configure(xscrollcommand=startup_scroll.set)
        self.startup_table.tag_configure("potentially_high", foreground=RED)
        self.startup_count = self._text(panel, "Not scanned yet.", 9, MUTED)
        self.startup_count.pack(anchor="w", pady=(12, 0))

    def _load_startup(self) -> None:
        self.startup_table.delete(*self.startup_table.get_children())
        try:
            items = sorted(
                list_startup_items(),
                key=lambda item: (
                    item.get("impact") != "Potentially high",
                    item["source"], item["name"].casefold()
                ),
            )
            for item in items:
                impact = item.get("impact", "Unrated")
                self.startup_table.insert(
                    "", "end",
                    values=(item["source"], item["name"], impact,
                            item.get("publisher", "Unknown (not verified)"), item["command"]),
                    tags=("potentially_high",) if impact == "Potentially high" else (),
                )
            high_count = sum(item.get("impact") == "Potentially high" for item in items)
            self.startup_count.configure(
                text=(f"{len(items)} entries · {high_count} potentially high-impact "
                      "estimate(s) · publishers not verified. Read-only.")
            )
        except Exception as exc:
            self.startup_count.configure(text=f"Startup scan unavailable: {type(exc).__name__}")

    def _automation(self, page: tk.Frame) -> None:
        self._page_title(page, "Automatic Maintenance",
                         "Create a Windows Task Scheduler job only when you choose Enable.")
        panel = self._panel(page)
        panel.pack(fill="x")
        self._text(panel, "DAILY SAFE CLEANUP", 11, RED, True).pack(anchor="w")
        self._text(panel, "Task deletes only user temp files 48+ hours old. Runs with limited privileges.",
                   10, WHITE, wraplength=660).pack(anchor="w", pady=(9, 17))
        row = tk.Frame(panel, bg=PANEL)
        row.pack(anchor="w", fill="x")
        self._text(row, "LOCAL START TIME", 9, MUTED, True).pack(side="left")
        tk.Entry(row, width=7, textvariable=self.schedule_time, bg=PANEL2, fg=WHITE,
                 insertbackground=WHITE, bd=0, font=("Consolas", 12)).pack(side="left", padx=14)
        self._button(row, "Enable Daily Clean", self._enable_schedule, primary=True).pack(side="left", padx=5)
        self._button(row, "Disable", self._disable_schedule).pack(side="left", padx=5)
        self._button(row, "Refresh", self._load_scheduler).pack(side="left", padx=5)
        details = self._panel(page)
        details.pack(fill="both", expand=True, pady=(15, 0))
        self._text(details, "SCHEDULER STATUS", 10, WHITE, True).pack(anchor="w")
        self.schedule_status = tk.Text(details, bg="#0B111B", fg=WHITE, bd=0,
                                      font=("Consolas", 9), height=11, wrap="word")
        self.schedule_status.pack(fill="both", expand=True, pady=(12, 0))
        self.schedule_status.insert("end", "Not checked yet")
        self.schedule_status.configure(state="disabled")
        self._text(page, "Keep this folder in a permanent location. If the script is moved, re-enable the scheduled task.",
                   9, MUTED).pack(anchor="w", pady=(12, 0))

    def _set_schedule_text(self, value: str) -> None:
        self.schedule_status.configure(state="normal")
        self.schedule_status.delete("1.0", "end")
        self.schedule_status.insert("end", value)
        self.schedule_status.configure(state="disabled")

    def _load_scheduler(self) -> None:
        try:
            present, desc = scheduler.task_status()
            self._set_schedule_text(("ENABLED\n" if present else "DISABLED\n") + desc)
        except Exception as exc:
            self._set_schedule_text(f"Task Scheduler unavailable: {exc}")

    def _enable_schedule(self) -> None:
        if not messagebox.askyesno("Enable automatic cleaning?",
            "Create a daily Windows task that permanently deletes only 48+ hour-old user-temp files?\n\n"
            "No Windows-temp, browser, crash-dump, or shader cleanup will be scheduled."):
            return
        try:
            message = scheduler.install_daily(self.script_path, self.schedule_time.get())
            messagebox.showinfo("Task created", message or "Daily task created")
            self._load_scheduler()
        except Exception as exc:
            messagebox.showerror("Task not created", str(exc))

    def _disable_schedule(self) -> None:
        if not messagebox.askyesno("Remove scheduled task?", "Disable DPN automatic cleanup?"):
            return
        try:
            scheduler.remove_daily()
            self._load_scheduler()
        except Exception as exc:
            messagebox.showerror("Could not remove", str(exc))

    def _health(self, page: tk.Frame) -> None:
        self._page_title(page, "Windows Integrity Diagnostics",
                         "Official built-in read-only Windows checks. These can run for several minutes.")
        panel = self._panel(page)
        panel.pack(fill="x")
        self._text(panel, "VERIFICATION ONLY — NO AUTOMATIC REPAIR", 10, GREEN, True).pack(anchor="w")
        self._text(panel, "SFC checks protected system files; DISM checks the Windows component store. "
                   "DISM can require administrator rights.", 10, WHITE, wraplength=690).pack(anchor="w", pady=(8, 15))
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill="x")
        self._button(row, "Run SFC Verify", lambda: self._run_health("sfc-verify"), primary=True).pack(side="left")
        self._button(row, "Run DISM Scan", lambda: self._run_health("dism-scan")).pack(side="left", padx=9)
        view = self._panel(page)
        view.pack(fill="both", expand=True, pady=(15, 0))
        self.health_text = tk.Text(view, bg="#0B111B", fg=WHITE,
                                   bd=0, font=("Consolas", 10), wrap="word")
        self.health_text.pack(fill="both", expand=True)
        self.health_text.insert("end", "No verification run yet. These checks do not repair or modify Windows.")
        self.health_text.configure(state="disabled")

    def _run_health(self, name: str) -> None:
        if self.busy:
            messagebox.showwarning("Operation running", "Finish the other operation first.")
            return
        if not messagebox.askyesno("Run system check?", f"Start {name}? Windows may require elevation and this may take time."):
            return
        self.busy = True
        self.status.configure(text="●  VERIFYING", fg=RED)
        def worker() -> None:
            try:
                code, output = health.run_check(name)
                self.events.put(("health_done", (code, output)))
            except Exception as exc:
                self.events.put(("health_done", (1, str(exc))))
        threading.Thread(target=worker, daemon=True).start()

    def _reports(self, page: tk.Frame) -> None:
        self._page_title(page, "Cleanup History & Audit Trail",
                         "Local JSON records of scans and cleanups. No uploads or file-content collection.")
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x")
        self._text(row, "REPORTS  /  LAST 30", 10, RED, True).pack(side="left")
        self._button(row, "Refresh", self._load_reports).pack(side="right")
        panel = self._panel(page)
        panel.pack(fill="both", expand=True, pady=(14, 0))
        self.report_table = self._make_tree(panel, ("Time", "Mode", "Eligible", "Removed"),
                                            (190, 90, 120, 130), height=9)
        self.report_table.bind("<<TreeviewSelect>>", self._select_report)
        self.report_detail = tk.Text(panel, height=9, bg="#0B111B", fg=WHITE, bd=0,
                                     font=("Consolas", 9), wrap="word", state="disabled")
        self.report_detail.pack(fill="both", expand=True, pady=(12, 0))
        self._text(page, "JSON report location: " + str(reports_path()), 9, MUTED,
                   wraplength=750).pack(anchor="w", pady=(12, 0))
        self.report_rows: list[dict] = []

    def _load_reports(self) -> None:
        self.report_rows = list_reports(30)
        self.report_table.delete(*self.report_table.get_children())
        for idx, item in enumerate(self.report_rows):
            totals = item.get("totals") or {}
            self.report_table.insert("", "end", iid=str(idx), values=(
                item.get("when", "?").replace("T", " ")[:19], item.get("action", "?"),
                human_bytes(totals.get("eligible_bytes", 0)),
                human_bytes(totals.get("deleted_bytes", 0))))

    def _select_report(self, _event: Any) -> None:
        selection = self.report_table.selection()
        if not selection:
            return
        try:
            item = self.report_rows[int(selection[0])]
        except (IndexError, ValueError):
            return
        self.report_detail.configure(state="normal")
        self.report_detail.delete("1.0", "end")
        self.report_detail.insert("end", json.dumps(item, indent=2))
        self.report_detail.configure(state="disabled")

    def _poll_performance(self) -> None:
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        # Read-only snapshot may take ~0.1s. Kept separate from cleanup worker.
        try:
            s = performance_snapshot()
            disk, mem, cpu = s["disk"], s["ram"], s["cpu"]
            self.metrics["CPU UTILIZATION"].configure(text=f"{cpu:.1f}%" if cpu is not None else "N/A")
            self.metrics["PHYSICAL MEMORY"].configure(text=f"{mem['percent']:.1f}%" if mem else "N/A")
            self.metrics["SYSTEM DRIVE"].configure(text=f"{disk['percent']:.1f}%" if disk else "N/A")
            self.metrics["CPU UTILIZATION subtitle"].configure(text="Live sampled CPU" if cpu is not None else "Install psutil")
            self.metrics["PHYSICAL MEMORY subtitle"].configure(
                text=f"{human_bytes(mem['available'])} available" if mem else "Unavailable")
            self.metrics["SYSTEM DRIVE subtitle"].configure(
                text=f"{human_bytes(disk['free'])} free" if disk else "Unavailable")
            self._update_sparkline("CPU UTILIZATION", cpu)
            self._update_sparkline(
                "PHYSICAL MEMORY", mem["percent"] if mem else None
            )
            self._update_sparkline(
                "SYSTEM DRIVE", disk["percent"] if disk else None
            )
            self._draw_health_gauge(performance_health_score(s))
            self.advice.configure(text="  •  ".join(performance_advice(s)))
            self.processes.delete(*self.processes.get_children())
            for p in s["top_processes"][:10]:
                self.processes.insert("", "end", values=(p["name"], p["pid"], human_bytes(p["ram_bytes"])))
        except Exception as exc:
            self.advice.configure(text=f"Monitoring unavailable: {type(exc).__name__}")
        if self.root.winfo_exists():
            self._poll_job = self.root.after(5000, self._poll_performance)

    def _update_sparkline(self, name: str, value: float | None) -> None:
        history = self.metric_history[name]
        if value is not None:
            history.append(max(0.0, min(100.0, float(value))))
            del history[:-24]

        canvas = self.sparklines[name]
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        canvas.create_line(0, height - 2, width, height - 2, fill=LINE)
        if not history:
            return

        points = []
        for index, sample in enumerate(history):
            x = (width - 4) * index / max(len(history) - 1, 1) + 2
            y = height - 3 - sample / 100 * (height - 6)
            points.extend((x, y))
        if len(history) > 1:
            canvas.create_line(*points, fill=RED, width=2, smooth=True)
        x, y = points[-2:]
        canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=RED, outline=RED)

    def _draw_health_gauge(self, score: int | None) -> None:
        gauge = self.health_gauge
        gauge.delete("all")
        gauge.create_arc(9, 9, 73, 73, start=90, extent=-359,
                         style="arc", outline=LINE, width=5)
        if score is not None:
            gauge.create_arc(9, 9, 73, 73, start=90, extent=-3.6 * score,
                             style="arc", outline=RED, width=5)
        gauge.create_text(41, 36, text=str(score) if score is not None else "N/A",
                          fill=WHITE, font=("Segoe UI Semibold", 15))
        gauge.create_text(41, 54, text="SAMPLE", fill=MUTED,
                          font=("Segoe UI", 7, "bold"))

    def _consume_events(self) -> None:
        for _ in range(100):
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self._log(payload)
            elif event == "cleanup_done":
                t = payload["totals"]
                self._log(f"DONE: {t['eligible_files']} eligible ({human_bytes(t['eligible_bytes'])}).")
                self._log(f"REMOVED: {t['deleted_files']} files ({human_bytes(t['deleted_bytes'])}).")
                self._log(f"SKIPPED: {t['skipped_recent']} recent, {t['skipped_links']} links, {t['errors']} inaccessible/errors")
                for note in payload["skipped"]:
                    self._log("NOTICE: " + note)
                self._log("Report saved under: " + str(reports_path()))
                self._end_busy()
            elif event == "error":
                self._log(payload)
                self._end_busy()
                messagebox.showerror("Operation error", payload)
            elif event == "disk_progress":
                self.disk_status.configure(text=f"Scanning… {payload:,} files", fg=RED)
            elif event == "disk_done":
                self._show_disk_result(payload)
            elif event == "disk_error":
                self._finish_disk_scan()
                self.disk_status.configure(text=payload, fg=RED)
            elif event == "insight_progress":
                count, phase = payload
                self.insight_status.configure(
                    text=f"{phase.title()}… {count:,} files", fg=RED
                )
            elif event == "insight_done":
                self._show_file_insight_result(payload)
            elif event == "insight_error":
                self.insight_busy = False
                self.insight_scan_button.configure(state="normal")
                self.insight_stop_button.configure(state="disabled")
                self.insight_status.configure(text=payload, fg=RED)
            elif event == "process_snapshot":
                self.process_refresh_busy = False
                self.process_refresh_button.configure(state="normal")
                self.process_rows = {str(item["pid"]): item for item in payload}
                self._render_process_rows()
                can_end = sum(bool(item["can_end"]) for item in payload)
                self.process_status.configure(
                    text=(f"{len(payload):,} processes · {can_end:,} verified current-user apps "
                          "eligible for confirmed end action"),
                    fg=MUTED,
                )
            elif event == "process_snapshot_error":
                self.process_refresh_busy = False
                self.process_refresh_button.configure(state="normal")
                self.process_status.configure(text=payload, fg=RED)
            elif event == "process_ended":
                self.process_action_busy = False
                self.process_status.configure(
                    text=f"End request sent for {payload}. Refreshing the process list…", fg=GREEN
                )
                self._refresh_processes()
            elif event == "process_action_error":
                self.process_action_busy = False
                self.process_status.configure(text=payload, fg=RED)
                self._select_process(None)
            elif event == "health_done":
                code, output = payload
                self.health_text.configure(state="normal")
                self.health_text.delete("1.0", "end")
                self.health_text.insert("end", f"Exit code: {code}\n\n{output}")
                self.health_text.configure(state="disabled")
                self.busy = False
                self.status.configure(text="●  READY", fg=GREEN)
        if self.root.winfo_exists():
            self._event_job = self.root.after(250, self._consume_events)

    def close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Close during operation?",
                                       "An operation is still running. Close the window anyway?"):
                return
            self.cancel_flag.set()
        self.disk_cancel.set()
        self.insight_cancel.set()
        if self._rain_job is not None:
            self.root.after_cancel(self._rain_job)
            self._rain_job = None
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self.root.after_cancel(self._event_job)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui(script_path: Path) -> None:
    DPNWindow(script_path).run()
