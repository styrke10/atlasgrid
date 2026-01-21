
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-platform deploy script for QGIS plugins (Qt6 / PyQt6).

- Compiles .ui --> .py using pyuic6 (or python -m PyQt6.uic.pyuic as fallback)
- Compiles .qrc --> .py using Qt's rcc (preferred) or optional pyside6-rcc fallback
- Fixes PySide6 header to PyQt6 in generated resources if fallback is used
- Runs `pb_tool deploy -q` to copy files without pb_tool attempting PyQt5 tools

Author: Morten-ready version
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent

# --------- Helpers ----------------------------------------------------------------

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)

def run(cmd: List[str], cwd: Optional[Path] = None) -> None:
    print(f"[run] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)

def detect_pyuic6() -> List[str]:
    exe = which("pyuic6")
    if exe:
        return [exe]
    # Fallback: run as module
    return [sys.executable, "-m", "PyQt6.uic.pyuic"]

def common_qt_locations() -> Iterable[Path]:
    # Extra probes for rcc if not found on PATH
    candidates: List[Path] = []
    if os.name == "nt":
        # Typical Qt installations
        candidates += list(Path("C:/Qt").glob("6.*/*/bin/rcc.exe"))
        # OSGeo4W Qt6 bins if present
        candidates += list(Path("C:/OSGeo4W").glob("apps/Qt6/bin/rcc.exe"))
        candidates += list(Path("C:/OSGeo4W64").glob("apps/Qt6/bin/rcc.exe"))
    else:
        # Linux common locations
        candidates += [Path("/usr/lib/qt6/bin/rcc"), Path("/usr/bin/rcc")]
        # Homebrew/macOS
        candidates += [Path("/opt/homebrew/opt/qt/bin/rcc"), Path("/usr/local/opt/qt/bin/rcc")]
    return [p for p in candidates if p.exists()]

def find_rcc(user_path: Optional[str], allow_fallback: bool) -> Tuple[str, bool]:
    """
    Returns (compiler_cmd, used_pyside6_fallback?)
    Prefers Qt's `rcc`; if allow_fallback True and rcc missing, tries pyside6-rcc.
    """
    # Highest priority: explicit path or env var
    if user_path:
        p = Path(user_path)
        if p.exists():
            return (str(p), False)
        raise FileNotFoundError(f"--rcc path does not exist: {user_path}")
    env = os.environ.get("QT_RCC")
    if env and Path(env).exists():
        return (env, False)

    # PATH
    exe = which("rcc")
    if exe:
        return (exe, False)

    # Probed locations
    for p in common_qt_locations():
        return (str(p), False)

    # Optional fallback
    if allow_fallback:
        pyside = which("pyside6-rcc")
        if pyside:
            return (pyside, True)

    raise FileNotFoundError(
        "Qt rcc not found. Install Qt6 tools or provide --rcc / set QT_RCC.\n"
        "Tip (Windows): Install Qt via Qt Online Installer and ensure <Qt>/bin is on PATH.\n"
        "Tip (Linux/macOS): Install qt6-tools / qt@6 so `rcc` is available."
    )

def read_pbtool_cfg() -> Tuple[List[Path], List[Path]]:
    """
    Parse pb_tool.cfg if present to obtain [files] compiled_ui_files and resource_files.
    Falls back to auto-discovery if not present.
    """
    cfg = ROOT / "pb_tool.cfg"
    ui_files: List[Path] = []
    qrc_files: List[Path] = []

    if not cfg.exists():
        # Auto-discover .ui and .qrc in repo
        ui_files = [p for p in ROOT.rglob("*.ui") if ".venv" not in str(p) and ".git" not in str(p)]
        qrc_files = [p for p in ROOT.rglob("*.qrc") if ".venv" not in str(p) and ".git" not in str(p)]
        return (ui_files, qrc_files)

    section = None
    files_map = {}
    with cfg.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1].lower()
                continue
            if section == "files" and ":" in s:
                key, val = s.split(":", 1)
                key = key.strip()
                # Values can be space or newline separated; gather words
                items = val.strip().split()
                files_map[key] = files_map.get(key, []) + items

    for u in files_map.get("compiled_ui_files", []):
        ui_files.append((ROOT / u).resolve())
    for r in files_map.get("resource_files", []):
        qrc_files.append((ROOT / r).resolve())

    # If lists are still empty, auto-discover
    if not ui_files:
        ui_files = [p for p in ROOT.rglob("*.ui") if ".venv" not in str(p) and ".git" not in str(p)]
    if not qrc_files:
        qrc_files = [p for p in ROOT.rglob("*.qrc") if ".venv" not in str(p) and ".git" not in str(p)]

    return (ui_files, qrc_files)

def ui_output_path(ui_path: Path) -> Path:
    # Conventional output: same folder, .ui -> _ui.py or .py; we’ll use <name>.py
    return ui_path.with_suffix(".py")

def qrc_output_path(qrc_path: Path) -> Path:
    # Typical name: resources.py, or <name>_rc.py; we’ll use <name>_rc.py
    stem = qrc_path.stem
    # if user already named it 'resources.qrc' produce 'resources.py'
    if stem == "resources":
        return qrc_path.with_suffix(".py")
    return qrc_path.with_name(f"{stem}_rc.py")

def compile_ui(pyuic_cmd: List[str], ui_files: Iterable[Path], dry_run: bool) -> None:
    if not ui_files:
        print("[ui] No .ui files found.")
        return
    print(f"[ui] Using pyuic6 command: {' '.join(pyuic_cmd)}")
    for ui in sorted(set(ui_files)):
        out = ui_output_path(ui)
        cmd = pyuic_cmd + ["-x", str(ui), "-o", str(out)]
        if dry_run:
            print(f"[dry-run] {' '.join(cmd)}")
        else:
            run(cmd)
        print(f"[ui] {ui.name} -> {out.name}")

def compile_qrc(rcc_cmd: str, qrc_files: Iterable[Path], used_pyside_fallback: bool, dry_run: bool) -> None:
    if not qrc_files:
        print("[qrc] No .qrc files found.")
        return
    print(f"[qrc] Using compiler: {rcc_cmd}  (fallback={used_pyside_fallback})")
    for qrc in sorted(set(qrc_files)):
        out = qrc_output_path(qrc)
        if "pyside6-rcc" in rcc_cmd.lower():
            cmd = [rcc_cmd, "-o", str(out), str(qrc)]
        else:
            cmd = [rcc_cmd, "-g", "python", "-o", str(out), str(qrc)]
        if dry_run:
            print(f"[dry-run] {' '.join(cmd)}")
            continue
        run(cmd)
        # If we used pyside6-rcc, fix the top import: PySide6 -> PyQt6 (per community guidance)
        if used_pyside_fallback:
            text = out.read_text(encoding="utf-8")
            fixed = re.sub(r"from\s+PySide6\s+import\s+QtCore", "from PyQt6 import QtCore", text, count=1)
            if fixed != text:
                out.write_text(fixed, encoding="utf-8")
                print(f"[qrc] Patched PySide6 -> PyQt6 in {out.name}")
        print(f"[qrc] {qrc.name} -> {out.name}")

def run_pb_tool(deploy_quick: bool, config: Optional[str], dry_run: bool) -> None:
    # Prefer 'pbt' alias if available, else 'pb_tool'
    pb = which("pb_tool") or which("pbt")
    if not pb:
        raise FileNotFoundError("pb_tool (or pbt) not found on PATH. Install pb_tool first.")
    cmd = [pb, "deploy"]
    if deploy_quick:
        # -q ensures pb_tool does NOT recompile UI/resources using pyuic5/pyrcc5
        cmd.append("-q")
    if config:
        cmd += ["--config_file", config]
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
    else:
        run(cmd)

# --------- CLI --------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Compile Qt6 resources/UIs and deploy QGIS plugin with pb_tool.")
    ap.add_argument("--rcc", help="Path to Qt6 rcc executable. If omitted, script searches PATH and common locations.")
    ap.add_argument("--allow-pyside6-rcc-fallback", action="store_true",
                    help="Allow fallback to pyside6-rcc if Qt rcc is not found.")
    ap.add_argument("--config", default="pb_tool.cfg", help="Path to pb_tool.cfg (default: pb_tool.cfg).")
    ap.add_argument("--no-quick", action="store_true",
                    help="Do NOT pass -q to pb_tool deploy (not recommended for Qt6).")
    ap.add_argument("--dry-run", action="store_true", help="Show commands without executing them.")
    args = ap.parse_args()

    # 1) Discover files
    ui_files, qrc_files = read_pbtool_cfg()
    print(f"[info] Found {len(ui_files)} .ui files and {len(qrc_files)} .qrc files")

    # 2) Tools
    pyuic_cmd = detect_pyuic6()
    rcc_cmd, used_pyside_fallback = find_rcc(args.rcc, allow_fallback=args.allow_pyside6_rcc_fallback)

    # 3) Compile
    compile_ui(pyuic_cmd, ui_files, dry_run=args.dry_run)
    compile_qrc(rcc_cmd, qrc_files, used_pyside_fallback, dry_run=args.dry_run)

    # 4) Deploy with pb_tool (quick to skip its PyQt5 compilers)
    cfg = args.config if args.config and Path(args.config).exists() else None
    run_pb_tool(deploy_quick=not args.no_quick, config=cfg, dry_run=args.dry_run)

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"\nERROR: Command failed with exit code {e.returncode}\n")
        sys.exit(e.returncode)
    except Exception as e:
        sys.stderr.write(f"\nERROR: {e}\n")
        sys.exit(1)
