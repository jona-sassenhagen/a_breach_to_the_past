#!/usr/bin/env python3
"""Build the Pyxel web bundle for GitHub Pages."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "a_link_to_the_breach"
FILES_TO_COPY = [
    "main.py",
    "asset_manager.py",
    "entity.py",
    "combat.py",
    "constants.py",
    "map.py",
    "map_layout.py",
    "ai.py",
    "ui.py",
    "vfx.py",
    "decor.txt",
    "heart.txt",
    "assets.pyxres",
]
DIRS_TO_COPY = [
    "static_assets",
    "sprite_assets",
]
IGNORE_PATTERNS = ("__pycache__", ".DS_Store", "Thumbs.db")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def find_pyxel_executable(root: Path) -> str:
    env_override = os.environ.get("PYXEL_EXECUTABLE")
    if env_override:
        return env_override
    venv_candidate = root / "venv" / "bin" / "pyxel"
    if venv_candidate.exists():
        return str(venv_candidate)
    which_result = shutil.which("pyxel")
    if which_result:
        return which_result
    raise SystemExit("pyxel executable not found. Install dependencies or set PYXEL_EXECUTABLE.")


def copy_file(src: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)


def copy_directory(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*IGNORE_PATTERNS))


def main() -> None:
    root = repo_root()
    pyxel_cmd = find_pyxel_executable(root)

    build_root = root / "build"
    stage_root = build_root / "web_stage"
    app_stage = stage_root / APP_NAME
    output_dir = build_root / "web"

    if stage_root.exists():
        shutil.rmtree(stage_root)
    if output_dir.exists():
        shutil.rmtree(output_dir)

    app_stage.mkdir(parents=True)

    for relative in FILES_TO_COPY:
        src = root / relative
        if not src.exists():
            print(f"warning: {relative} not found, skipping", file=sys.stderr)
            continue
        copy_file(src, app_stage)

    for directory in DIRS_TO_COPY:
        src_dir = root / directory
        if not src_dir.exists():
            print(f"warning: {directory} not found, skipping", file=sys.stderr)
            continue
        copy_directory(src_dir, app_stage / directory)

    subprocess.run([pyxel_cmd, "package", ".", "main.py"], cwd=app_stage, check=True)
    subprocess.run([pyxel_cmd, "app2html", f"{APP_NAME}.pyxapp"], cwd=app_stage, check=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_stage / f"{APP_NAME}.pyxapp", output_dir / f"{APP_NAME}.pyxapp")
    shutil.copy2(app_stage / f"{APP_NAME}.html", output_dir / "index.html")

    print(f"Web build complete -> {output_dir}")


if __name__ == "__main__":
    main()
