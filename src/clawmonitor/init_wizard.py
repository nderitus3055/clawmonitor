from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
import os
import sys

from .config import default_config_path


@dataclass(frozen=True)
class InitResult:
    ok: bool
    path: Optional[Path]
    reason: Optional[str] = None


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _looks_like_openclaw_root(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir() and (p / "agents").exists()
    except Exception:
        return False


def detect_openclaw_root() -> Optional[Path]:
    candidates = [
        Path(os.path.expanduser("~/.openclaw")),
        Path(os.getcwd()),
    ]
    for c in candidates:
        if _looks_like_openclaw_root(c):
            return c
    # fallback: suggest ~/.openclaw even if absent
    return candidates[0]


def _prompt(text: str, default: Optional[str] = None) -> str:
    if default is None:
        return input(text).strip()
    resp = input(f"{text} [{default}] ").strip()
    return resp if resp else default


def _prompt_yesno(text: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    resp = input(f"{text} {suffix} ").strip().lower()
    if not resp:
        return default_yes
    return resp in ("y", "yes")


def _messages(lang: str) -> Dict[str, str]:
    if lang.lower().startswith("zh"):
        return {
            "welcome": "ClawMonitor init: create a config file for this machine.",
            "lang": "Choose language (en/zh):",
            "config_exists": "Config already exists at:",
            "overwrite": "Overwrite existing config?",
            "openclaw_root": "OpenClaw state directory path:",
            "root_warn": "Warning: directory does not look like an OpenClaw root (missing agents/). Continue anyway?",
            "openclaw_bin": "OpenClaw CLI binary (name or full path):",
            "ui_seconds": "TUI refresh interval seconds (press 'f' in TUI to cycle):",
            "write_ok": "Wrote config:",
            "aborted": "Aborted.",
        }
    return {
        "welcome": "ClawMonitor init: create a config file for this machine.",
        "lang": "Choose language (en/zh):",
        "config_exists": "Config already exists at:",
        "overwrite": "Overwrite existing config?",
        "openclaw_root": "OpenClaw state directory path:",
        "root_warn": "Warning: directory does not look like an OpenClaw root (missing agents/). Continue anyway?",
        "openclaw_bin": "OpenClaw CLI binary (name or full path):",
        "ui_seconds": "TUI refresh interval seconds (press 'f' in TUI to cycle):",
        "write_ok": "Wrote config:",
        "aborted": "Aborted.",
    }


def _render_config(openclaw_root: Path, openclaw_bin: str, ui_seconds: float) -> str:
    # Keep it clean (no secrets). Values are per-machine.
    root_s = str(openclaw_root).replace("\\", "\\\\")
    bin_s = str(openclaw_bin).replace("\\", "\\\\")
    return (
        "# ClawMonitor configuration (TOML)\n"
        "\n"
        "[openclaw]\n"
        f'root = "{root_s}"\n'
        f'openclaw_bin = "{bin_s}"\n'
        "\n"
        "[refresh]\n"
        f"ui_seconds = {float(ui_seconds)}\n"
        "gateway_log_poll_seconds = 2.0\n"
        "channels_status_poll_seconds = 5.0\n"
        "delivery_queue_poll_seconds = 30.0\n"
        "\n"
        "[limits]\n"
        "transcript_tail_bytes = 65536\n"
        "gateway_log_ring_lines = 5000\n"
        "report_max_log_lines = 200\n"
        "\n"
        "[ui]\n"
        "hide_system_sessions = false\n"
    )


def run_init(
    *,
    config_path: Optional[Path] = None,
    lang: Optional[str] = None,
    openclaw_root: Optional[Path] = None,
    openclaw_bin: Optional[str] = None,
    ui_seconds: Optional[float] = None,
    defaults: bool = False,
    force: bool = False,
) -> InitResult:
    cfg_path = config_path or default_config_path()
    cfg_path = cfg_path.expanduser()

    chosen_lang = (lang or "en").strip() if defaults else ""
    if not defaults:
        if not _is_tty():
            return InitResult(ok=False, path=None, reason="not a tty")
        chosen_lang = (lang or _prompt(_messages("en")["lang"], default="en")).strip() or "en"

    msg = _messages(chosen_lang)
    if not defaults:
        print(msg["welcome"])

    if cfg_path.exists() and not force:
        if defaults:
            return InitResult(ok=False, path=None, reason=f"config exists: {cfg_path}")
        print(f'{msg["config_exists"]} {cfg_path}')
        if not _prompt_yesno(msg["overwrite"], default_yes=False):
            print(msg["aborted"])
            return InitResult(ok=False, path=None, reason="user aborted")

    suggested_root = openclaw_root or detect_openclaw_root()
    if defaults:
        root = suggested_root or Path(os.path.expanduser("~/.openclaw"))
    else:
        root_in = _prompt(msg["openclaw_root"], default=str(suggested_root) if suggested_root else "~/.openclaw")
        root = Path(os.path.expanduser(root_in))
        if not _looks_like_openclaw_root(root):
            if not _prompt_yesno(msg["root_warn"], default_yes=True):
                print(msg["aborted"])
                return InitResult(ok=False, path=None, reason="root rejected")

    bin_value = openclaw_bin or "openclaw"
    if defaults:
        oc_bin = bin_value
    else:
        oc_bin = _prompt(msg["openclaw_bin"], default=str(bin_value))

    ui_val = float(ui_seconds) if ui_seconds is not None else 5.0
    if defaults:
        ui = ui_val
    else:
        ui_s = _prompt(msg["ui_seconds"], default=str(ui_val))
        try:
            ui = float(ui_s)
        except Exception:
            ui = ui_val

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_render_config(root, oc_bin, ui), encoding="utf-8")
    if not defaults:
        print(f'{msg["write_ok"]} {cfg_path}')
    return InitResult(ok=True, path=cfg_path)


def maybe_run_first_time_init(*, config_flag: Optional[str], openclaw_root_flag: Optional[str]) -> Tuple[bool, Optional[Path]]:
    """
    If no config exists and running interactively, offer to run init.
    Returns (ran_init, path_written).
    """
    if config_flag or openclaw_root_flag:
        return (False, None)
    cfg_path = default_config_path()
    if cfg_path.exists():
        return (False, None)
    if not _is_tty():
        return (False, None)

    msg = _messages("en")
    print(f"No config found at {cfg_path}.")
    if not _prompt_yesno("Run `clawmonitor init` now?", default_yes=True):
        return (False, None)
    res = run_init(config_path=cfg_path, defaults=False, force=False)
    return (res.ok, res.path)

