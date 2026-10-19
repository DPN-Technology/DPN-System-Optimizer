"""Dark DPN-themed, responsive Windows desktop interface (standard Tkinter)."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from . import __version__
from .cleaner import CATEGORIES, DEFAULT_CATEGORIES, human_bytes, list_reports, reports_path, run_cleanup
from .diagnostics import performance_advice, performance_snapshot
from .startup import list_startup_items
from . import scheduler, health

BG = "#080B12"
SIDE = "#0D111B"
PANEL = "#131925"
PANEL2 = "#1B2431"
LINE = "#2B3444"
RED = "#EA353F"
WHITE = "#F3F6FA"
MUTED = "#93A1B3"
GREEN = "#47CCA5"


class DPNWindow:
    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.root = tk.Tk()
        self.root.title(f"DPN SYSTEM OPTIMIZER // v{__version__}")
        self.root.geometry("1120x760")
        self.root.minsize(930, 660)
        self.root.configure(bg=BG)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self._poll_job = None
        self.cancel_flag = threading.Event()
        self.page = "Dashboard"
        self.buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.metrics: dict[str, tk.Label] = {}
        self.choice = {key: tk.IntVar(value=int(key in DEFAULT_CATEGORIES)) for key in CATEGORIES}
        self.age = tk.StringVar(value="48")
        self.schedule_time = tk.StringVar(value="09:00")
        self._configure_style()
        self._layout()
        self.root.after(250, self._consume_events)
        self.root.after(300, self._poll_performance)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self) -> None:
        sty = ttk.Style(self.root)
        sty.theme_use("clam")
        sty.configure("DPN.Treeview", background=PANEL, foreground=WHITE,
                      fieldbackground=PANEL, borderwidth=0, rowheight=29,
                      font=("Segoe UI", 9))
        sty.configure("DPN.Treeview.Heading", background=PANEL2, foreground=WHITE,
                      relief="flat", borderwidth=0, font=("Segoe UI Semibold", 9))
        sty.map("DPN.Treeview", background=[("selected", "#77303A")],
                foreground=[("selected", WHITE)])
        sty.map("DPN.Treeview.Heading", background=[("active", "#2A3543")])
        sty.configure("DPN.Horizontal.TProgressbar", background=RED, troughcolor=PANEL2,
                      bordercolor=PANEL, lightcolor=RED, darkcolor=RED)

    def _text(self, parent: tk.Widget, value: str, size: int = 10,
              color: str = WHITE, bold: bool = False, **kwargs: Any) -> tk.Label:
        return tk.Label(parent, text=value, bg=parent.cget("bg"), fg=color,
                        font=("Segoe UI Semibold" if bold else "Segoe UI", size),
                        anchor="w", justify="left", **kwargs)

    def _button(self, parent: tk.Widget, title: str, action: Callable,
                primary: bool = False, **kwargs: Any) -> tk.Button:
        return tk.Button(parent, text=title, command=action,
                         bg=RED if primary else PANEL2, fg=WHITE,
                         activebackground="#F34C57" if primary else "#344254",
                         activeforeground=WHITE, relief="flat", bd=0, highlightthickness=0,
                         font=("Segoe UI Semibold", 10), cursor="hand2",
                         padx=15, pady=11, **kwargs)

    def _panel(self, parent: tk.Widget, padx: int = 17, pady: int = 15) -> tk.Frame:
        f = tk.Frame(parent, bg=PANEL, padx=padx, pady=pady, highlightthickness=1,
                     highlightbackground=LINE)
        return f

    def _page_title(self, parent: tk.Widget, heading: str, desc: str) -> None:
        self._text(parent, heading, 19, WHITE, True).pack(anchor="w", pady=(0, 4))
        self._text(parent, desc, 10, MUTED).pack(anchor="w", pady=(0, 18))

    def _layout(self) -> None:
        self.sidebar = tk.Frame(self.root, bg=SIDE, width=225)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self.sidebar, bg=RED, height=5).pack(fill="x")
        title = tk.Frame(self.sidebar, bg=SIDE, padx=19, pady=23)
        title.pack(fill="x")
        self._text(title, "DPN // TECHNOLOGY", 10, RED, True).pack(anchor="w")
        self._text(title, "SYSTEM", 22, WHITE, True).pack(anchor="w", pady=(13, 0))
        self._text(title, "OPTIMIZER", 22, WHITE, True).pack(anchor="w")
        self._text(title, "v2.0 · LOCAL-FIRST", 9, MUTED).pack(anchor="w", pady=(6, 0))
        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x", padx=18, pady=(0, 18))
        for tab in ("Dashboard", "Cleaner", "Startup", "Automation", "Windows Health", "Reports"):
            btn = tk.Button(self.sidebar, text="  ▸  " + tab, anchor="w", fg=WHITE,
                            bg=SIDE, relief="flat", bd=0, highlightthickness=0, activebackground=PANEL2,
                            activeforeground=WHITE, padx=15, pady=12,
                            cursor="hand2", font=("Segoe UI", 11),
                            command=lambda tab=tab: self.show(tab))
            btn.pack(fill="x", padx=9, pady=2)
            self.buttons[tab] = btn
        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x", padx=18, pady=(24, 10))
        self._text(self.sidebar, "SAFE BY DESIGN", 9, GREEN, True).pack(anchor="w", padx=20)
        self._text(self.sidebar, "Preview-first · No telemetry\nNo registry cleanup", 9, MUTED).pack(
            anchor="w", padx=20, pady=(6, 0))
        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(self.main, bg=BG, padx=27, pady=17)
        header.pack(fill="x")
        self._text(header, "COMMAND CENTER     /     WINDOWS PERFORMANCE", 10, MUTED, True).pack(side="left")
        self.status = tk.Label(header, text="●  READY", bg=BG, fg=GREEN,
                               font=("Segoe UI Semibold", 9))
        self.status.pack(side="right")
        tk.Frame(self.main, height=1, bg=LINE).pack(fill="x")
        container = tk.Frame(self.main, bg=BG)
        container.pack(fill="both", expand=True, padx=27, pady=23)
        for tab in self.buttons:
            page = tk.Frame(container, bg=BG)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[tab] = page
        self._dashboard(self.pages["Dashboard"])
        self._cleaner(self.pages["Cleaner"])
        self._startup(self.pages["Startup"])
        self._automation(self.pages["Automation"])
        self._health(self.pages["Windows Health"])
        self._reports(self.pages["Reports"])
        self.show("Dashboard")

    def show(self, name: str) -> None:
        self.page = name
        self.pages[name].lift()
        for key, b in self.buttons.items():
            b.configure(bg=PANEL2 if key == name else SIDE,
                        fg=RED if key == name else WHITE)
        if name == "Startup":
            self._load_startup()
        elif name == "Reports":
            self._load_reports()
        elif name == "Automation":
            self._load_scheduler()

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
        notes = self._panel(page, 13, 10)
        notes.pack(fill="x", pady=(14, 14))
        self._text(notes, "SYSTEM INTELLIGENCE", 10, RED, True).pack(anchor="w")
        self.advice = self._text(notes, "Checking resource health…", 10, WHITE,
                                 wraplength=685)
        self.advice.pack(anchor="w", pady=(7, 0), fill="x")
        processes = self._panel(page, 12, 10)
        processes.pack(fill="both", expand=True)
        row = tk.Frame(processes, bg=PANEL)
        row.pack(fill="x")
        self._text(row, "TOP MEMORY CONSUMERS", 10, WHITE, True).pack(side="left")
        self._button(row, "Refresh", self._poll_performance).pack(side="right")
        self.processes = self._make_tree(processes, ("Process", "PID", "RAM used"),
                                         (320, 90, 140), height=9)
        self._text(page, "Metrics are samples, not proof of sustained performance problems. psutil enables CPU and process monitoring.",
                   9, MUTED).pack(anchor="w", pady=(10, 0))

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

    def _startup(self, page: tk.Frame) -> None:
        self._page_title(page, "Windows Startup Inventory",
                         "Read-only registry and startup-folder inspection. Nothing is disabled or changed.")
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x")
        self._text(row, "Review suspicious or unnecessary entries before changing them in Windows Settings.",
                   10, MUTED).pack(side="left")
        self._button(row, "Refresh Inventory", self._load_startup).pack(side="right")
        panel = self._panel(page)
        panel.pack(fill="both", expand=True, pady=(16, 0))
        self.startup_table = self._make_tree(panel, ("Source", "Application", "Command (read-only)"),
                                              (145, 175, 410), height=16)
        self.startup_count = self._text(panel, "Not scanned yet.", 9, MUTED)
        self.startup_count.pack(anchor="w", pady=(12, 0))

    def _load_startup(self) -> None:
        self.startup_table.delete(*self.startup_table.get_children())
        try:
            items = list_startup_items()
            for item in items:
                self.startup_table.insert("", "end", values=(item["source"], item["name"], item["command"]))
            self.startup_count.configure(text=f"{len(items)} startup entries found. Read-only.")
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
            self.advice.configure(text="  •  ".join(performance_advice(s)))
            self.processes.delete(*self.processes.get_children())
            for p in s["top_processes"][:10]:
                self.processes.insert("", "end", values=(p["name"], p["pid"], human_bytes(p["ram_bytes"])))
        except Exception as exc:
            self.advice.configure(text=f"Monitoring unavailable: {type(exc).__name__}")
        if self.root.winfo_exists():
            self._poll_job = self.root.after(5000, self._poll_performance)

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
            elif event == "health_done":
                code, output = payload
                self.health_text.configure(state="normal")
                self.health_text.delete("1.0", "end")
                self.health_text.insert("end", f"Exit code: {code}\n\n{output}")
                self.health_text.configure(state="disabled")
                self.busy = False
                self.status.configure(text="●  READY", fg=GREEN)
        if self.root.winfo_exists():
            self.root.after(250, self._consume_events)

    def close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Close during operation?",
                                       "An operation is still running. Close the window anyway?"):
                return
            self.cancel_flag.set()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui(script_path: Path) -> None:
    DPNWindow(script_path).run()
