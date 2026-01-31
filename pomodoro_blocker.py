#!/usr/bin/env python3
"""Pomodoro timer that blocks specified domains via the OS hosts file."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import platform
import sys
import time
import tkinter as tk
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Iterable, List, Optional
import subprocess

BLOCK_MARKER_START = "# POMODORO_BLOCK_START"
BLOCK_MARKER_END = "# POMODORO_BLOCK_END"
REDIRECT_IP = "127.0.0.1"
BLOCK_IPS = ("0.0.0.0", "127.0.0.1", "::1")


@dataclass(frozen=True)
class PomodoroConfig:
    focus_minutes: int
    break_minutes: int
    cycles: int
    domains: List[str]
    dry_run: bool
    hosts_path: Path


class HostsFileError(RuntimeError):
    pass


class HostsFileManager:
    def __init__(self, hosts_path: Path, dry_run: bool = False) -> None:
        self._hosts_path = hosts_path
        self._dry_run = dry_run
        self._backup_path = hosts_path.with_suffix(hosts_path.suffix + ".pomodoro.bak")

    def ensure_writable(self) -> None:
        if self._dry_run:
            return
        if not self._hosts_path.exists():
            raise HostsFileError(f"Hosts file not found: {self._hosts_path}")
        if not os.access(self._hosts_path, os.W_OK):
            raise HostsFileError(
                "Hosts file is not writable. Run with elevated privileges (sudo/administrator)."
            )
        backup_dir = self._backup_path.parent
        if not os.access(backup_dir, os.W_OK):
            raise HostsFileError(
                "Backup location is not writable. Run with elevated privileges (sudo/administrator)."
            )

    def read_hosts(self) -> str:
        try:
            return self._hosts_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HostsFileError(f"Failed to read hosts file: {exc}") from exc

    def write_hosts(self, content: str) -> None:
        if self._dry_run:
            return
        try:
            self._hosts_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise HostsFileError(f"Failed to write hosts file: {exc}") from exc

    def backup(self) -> None:
        if self._dry_run:
            return
        if not self._backup_path.exists():
            try:
                self._backup_path.write_text(self.read_hosts(), encoding="utf-8")
            except OSError as exc:
                raise HostsFileError(f"Failed to write backup hosts file: {exc}") from exc

    def restore(self) -> None:
        if self._dry_run:
            return
        if self._backup_path.exists():
            try:
                original = self._backup_path.read_text(encoding="utf-8")
                self._hosts_path.write_text(original, encoding="utf-8")
                self._backup_path.unlink()
            except OSError as exc:
                raise HostsFileError(f"Failed to restore hosts file backup: {exc}") from exc

    def apply_block(self, domains: Iterable[str]) -> None:
        if self._dry_run:
            return
        hosts_content = self.read_hosts()
        cleaned = self._remove_existing_block(hosts_content)
        block_lines = [f"{ip} {domain}" for ip in BLOCK_IPS for domain in domains]
        block_section = (
            f"{BLOCK_MARKER_START}\n" + "\n".join(block_lines) + f"\n{BLOCK_MARKER_END}\n"
        )
        updated = cleaned.rstrip() + "\n\n" + block_section
        self.write_hosts(updated)

    def clear_block(self) -> None:
        if self._dry_run:
            return
        hosts_content = self.read_hosts()
        cleaned = self._remove_existing_block(hosts_content)
        self.write_hosts(cleaned.rstrip() + "\n")

    def _remove_existing_block(self, content: str) -> str:
        if BLOCK_MARKER_START not in content:
            return content
        before, _marker, remainder = content.partition(BLOCK_MARKER_START)
        _blocked, _marker_end, after = remainder.partition(BLOCK_MARKER_END)
        return before + after

    @contextlib.contextmanager
    def blocking(self, domains: Iterable[str]):
        self.ensure_writable()
        self.backup()
        try:
            self.apply_block(domains)
            yield
        finally:
            self.clear_block()
            self.restore()


def detect_hosts_path() -> Path:
    system = platform.system().lower()
    if "windows" in system:
        return Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    if "darwin" in system:
        return Path("/etc/hosts")
    return Path("/etc/hosts")

def get_settings_path() -> Path:
    system = platform.system().lower()
    if "windows" in system:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "PomodoroUrlBlocker" / "settings.json"
    if "darwin" in system:
        return Path.home() / "Library" / "Application Support" / "PomodoroUrlBlocker" / "settings.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "pomodoro-url-blocker" / "settings.json"

def load_settings() -> dict:
    settings_path = get_settings_path()
    if not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def save_settings(settings: dict) -> None:
    settings_path = get_settings_path()
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def parse_cli_args(argv: List[str]) -> PomodoroConfig:
    parser = argparse.ArgumentParser(
        description="Pomodoro timer that blocks specified domains across browsers by editing the hosts file."
    )
    parser.add_argument("--focus", type=int, default=25, help="Focus minutes per cycle.")
    parser.add_argument("--break", dest="break_minutes", type=int, default=5, help="Break minutes per cycle.")
    parser.add_argument("--cycles", type=int, default=4, help="Number of Pomodoro cycles.")
    parser.add_argument(
        "--domain",
        action="append",
        dest="domains",
        default=[],
        help="Domain to block (repeatable).",
    )
    parser.add_argument(
        "--domains-file",
        type=Path,
        help="Path to a text file with domains (one per line).",
    )
    parser.add_argument(
        "--hosts",
        type=Path,
        default=detect_hosts_path(),
        help="Override hosts file path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not modify the hosts file; log what would happen.",
    )

    args = parser.parse_args(argv)

    domains = [domain for domain in (normalize_domain(item) for item in args.domains) if domain]
    if args.domains_file:
        file_domains = [
            line.strip()
            for line in args.domains_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        domains.extend(
            domain for domain in (normalize_domain(item) for item in file_domains) if domain
        )

    if not domains:
        parser.error("At least one --domain or --domains-file entry is required.")

    return PomodoroConfig(
        focus_minutes=args.focus,
        break_minutes=args.break_minutes,
        cycles=args.cycles,
        domains=sorted(set(domains)),
        dry_run=args.dry_run,
        hosts_path=args.hosts,
    )


def log(message: str) -> None:
    timestamp = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def run_timer(minutes: int, label: str) -> None:
    total_seconds = minutes * 60
    log(f"Starting {label} for {minutes} minutes.")
    for remaining in range(total_seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        print(f"{label}: {mins:02d}:{secs:02d}", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")
    log(f"Completed {label}.")


def run_cli(config: PomodoroConfig) -> None:
    manager = HostsFileManager(config.hosts_path, dry_run=config.dry_run)

    log(
        "Pomodoro session starting. Domains blocked: "
        + ", ".join(config.domains)
        + (" (dry-run)" if config.dry_run else "")
    )

    with manager.blocking(expand_domains(config.domains)):
        flush_dns_cache()
        for cycle in range(1, config.cycles + 1):
            log(f"Cycle {cycle}/{config.cycles} focus started.")
            run_timer(config.focus_minutes, label="Focus")
            if cycle != config.cycles:
                log("Break started.")
                run_timer(config.break_minutes, label="Break")

    log("Pomodoro session complete. Domains unblocked.")


def normalize_domain(raw: str) -> Optional[str]:
    value = raw.strip()
    if not value:
        return None
    if "://" in value:
        parsed = urllib.parse.urlparse(value)
        host = parsed.hostname
    else:
        host = value.split("/")[0]
    if not host:
        return None
    host = host.split(":")[0].strip().strip(".")
    if not host:
        return None
    return host.lower()


def parse_domains_text(raw_text: str) -> List[str]:
    domains: List[str] = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        for chunk in cleaned.split(","):
            item = chunk.strip()
            if item:
                normalized = normalize_domain(item)
                if normalized:
                    domains.append(normalized)
    return sorted(set(domains))


def expand_domains(domains: Iterable[str]) -> List[str]:
    expanded: List[str] = []
    for domain in domains:
        cleaned = domain.strip()
        if not cleaned:
            continue
        expanded.append(cleaned)
        if "." in cleaned and not cleaned.startswith("www.") and cleaned.count(".") == 1:
            expanded.append(f"www.{cleaned}")
    return sorted(set(expanded))


def flush_dns_cache() -> None:
    system = platform.system().lower()
    if "windows" in system:
        _run_flush_command(["ipconfig", "/flushdns"])
    elif "darwin" in system:
        _run_flush_command(["dscacheutil", "-flushcache"])
        _run_flush_command(["killall", "-HUP", "mDNSResponder"])
    else:
        _run_flush_command(["systemd-resolve", "--flush-caches"])
        _run_flush_command(["resolvectl", "flush-caches"])


def _run_flush_command(command: List[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return

def format_time(seconds: int) -> str:
    mins, secs = divmod(max(0, seconds), 60)
    return f"{mins:02d}:{secs:02d}"


def build_cycle_plan(focus_minutes: int, break_minutes: int, cycles: int) -> List[tuple[str, int]]:
    plan: List[tuple[str, int]] = []
    for cycle in range(1, cycles + 1):
        plan.append((f"Focus {cycle}/{cycles}", focus_minutes * 60))
        if cycle != cycles:
            plan.append((f"Break {cycle}/{cycles}", break_minutes * 60))
    return plan


class PomodoroApp:
    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._root.title("Pomodoro URL Blocker")

        self._hosts_path = detect_hosts_path()
        self._manager: Optional[HostsFileManager] = None
        self._plan: List[tuple[str, int]] = []
        self._current_index = 0
        self._remaining_seconds = 0
        self._running = False

        saved = load_settings()
        self._focus_var = tk.StringVar(value=str(saved.get("focus_minutes", 25)))
        self._break_var = tk.StringVar(value=str(saved.get("break_minutes", 5)))
        self._cycles_var = tk.StringVar(value=str(saved.get("cycles", 4)))

        self._status_var = tk.StringVar(value="Ready")
        self._timer_var = tk.StringVar(value="00:00")

        self._build_ui()
        self._root.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _build_ui(self) -> None:
        settings_frame = tk.Frame(self._root, padx=10, pady=10)
        settings_frame.pack(fill=tk.X)

        tk.Label(settings_frame, text="Focus (min)").grid(row=0, column=0, sticky="w")
        self._focus_entry = tk.Entry(settings_frame, textvariable=self._focus_var, width=8)
        self._focus_entry.grid(row=0, column=1, padx=5)

        tk.Label(settings_frame, text="Break (min)").grid(row=0, column=2, sticky="w")
        self._break_entry = tk.Entry(settings_frame, textvariable=self._break_var, width=8)
        self._break_entry.grid(row=0, column=3, padx=5)

        tk.Label(settings_frame, text="Cycles").grid(row=0, column=4, sticky="w")
        self._cycles_entry = tk.Entry(settings_frame, textvariable=self._cycles_var, width=8)
        self._cycles_entry.grid(row=0, column=5, padx=5)

        domains_frame = tk.Frame(self._root, padx=10, pady=10)
        domains_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(domains_frame, text="Blocked domains (one per line or comma-separated)").pack(anchor="w")
        self._domains_text = scrolledtext.ScrolledText(domains_frame, height=6, wrap=tk.WORD)
        self._domains_text.pack(fill=tk.BOTH, expand=True)
        saved_domains = saved.get("domains", [])
        if isinstance(saved_domains, list) and saved_domains:
            self._domains_text.insert(tk.END, "\n".join(saved_domains))

        status_frame = tk.Frame(self._root, padx=10, pady=10)
        status_frame.pack(fill=tk.X)
        tk.Label(status_frame, textvariable=self._status_var).pack(anchor="w")
        tk.Label(status_frame, textvariable=self._timer_var, font=("Helvetica", 24, "bold")).pack(anchor="center")

        controls_frame = tk.Frame(self._root, padx=10, pady=10)
        controls_frame.pack(fill=tk.X)
        self._start_button = tk.Button(controls_frame, text="Start", command=self._start)
        self._start_button.pack(side=tk.LEFT)

        self._hosts_label = tk.Label(
            self._root,
            text=f"Hosts file: {self._hosts_path}",
            padx=10,
            pady=5,
            fg="gray",
        )
        self._hosts_label.pack(anchor="w")

    def _set_inputs_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self._focus_entry, self._break_entry, self._cycles_entry, self._domains_text):
            widget.configure(state=state)
        self._start_button.configure(state=state)

    def _start(self) -> None:
        if self._running:
            return
        try:
            focus = int(self._focus_var.get())
            break_minutes = int(self._break_var.get())
            cycles = int(self._cycles_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Focus, break, and cycles must be numbers.")
            return

        if focus <= 0 or break_minutes < 0 or cycles <= 0:
            messagebox.showerror("Invalid input", "Focus and cycles must be positive numbers.")
            return

        domains = parse_domains_text(self._domains_text.get("1.0", tk.END))
        if not domains:
            messagebox.showerror("Invalid input", "Please enter at least one domain to block.")
            return

        manager = HostsFileManager(self._hosts_path)
        try:
            manager.ensure_writable()
        except HostsFileError as exc:
            messagebox.showerror("Hosts file error", str(exc))
            return

        expanded_domains = expand_domains(domains)
        self._plan = build_cycle_plan(focus, break_minutes, cycles)
        self._current_index = 0
        self._remaining_seconds = self._plan[0][1]
        self._manager = manager
        save_settings(
            {
                "focus_minutes": focus,
                "break_minutes": break_minutes,
                "cycles": cycles,
                "domains": domains,
            }
        )

        try:
            manager.backup()
            manager.apply_block(expanded_domains)
            flush_dns_cache()
        except HostsFileError as exc:
            messagebox.showerror("Hosts file error", str(exc))
            return

        self._running = True
        self._set_inputs_state(False)
        self._status_var.set("Session running. Settings are locked until completion.")
        self._update_timer_label()
        self._tick()

    def _tick(self) -> None:
        if not self._running:
            return

        if self._remaining_seconds <= 0:
            self._advance_segment()
        else:
            self._remaining_seconds -= 1

        self._update_timer_label()
        if self._running:
            self._root.after(1000, self._tick)

    def _advance_segment(self) -> None:
        self._current_index += 1
        if self._current_index >= len(self._plan):
            self._finish_session()
            return
        self._remaining_seconds = self._plan[self._current_index][1]

    def _update_timer_label(self) -> None:
        if not self._running:
            self._timer_var.set("00:00")
            return
        label, _duration = self._plan[self._current_index]
        self._timer_var.set(f"{label} - {format_time(self._remaining_seconds)}")

    def _finish_session(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._manager:
            try:
                self._manager.clear_block()
                self._manager.restore()
            finally:
                self._manager = None
        self._status_var.set("Session complete. Settings unlocked.")
        self._timer_var.set("00:00")
        self._set_inputs_state(True)

    def _handle_close(self) -> None:
        if self._running:
            messagebox.showinfo("Session running", "Pomodoro is running. Settings cannot be changed until it ends.")
            return
        self._root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    PomodoroApp(root)
    root.mainloop()


def main() -> None:
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        launch_gui()
        return
    try:
        config = parse_cli_args(sys.argv[1:])
        run_cli(config)
    except HostsFileError as exc:
        log(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
