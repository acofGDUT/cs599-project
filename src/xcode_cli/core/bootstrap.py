from __future__ import annotations

import os
import platform
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

from xcode_cli.paths import XCODE_DIR


def _rg_target_path() -> Path:
    bin_dir = XCODE_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = "rg.exe" if os.name == "nt" else "rg"
    return bin_dir / exe


def ensure_ripgrep_installed() -> str:
    target = _rg_target_path()
    if target.exists():
        return f"ripgrep already installed at {target}"

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        url = "https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-pc-windows-msvc.zip"
        member_suffix = "rg.exe"
    elif system == "linux" and machine in {"x86_64", "amd64"}:
        url = "https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz"
        return "Automatic ripgrep bootstrap for Linux is not implemented yet. Please install rg via your package manager."
    elif system == "darwin":
        return "Automatic ripgrep bootstrap for macOS is not implemented yet. Please install rg via brew."
    else:
        return f"Unsupported platform for automatic ripgrep bootstrap: {system}/{machine}"

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "rg.zip"
        urlretrieve(url, archive_path)
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            rg_member = next((n for n in names if n.endswith(member_suffix)), None)
            if not rg_member:
                return "Failed to locate rg executable in downloaded archive"
            extracted = Path(tmp) / member_suffix
            with zf.open(rg_member) as src, extracted.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            target.write_bytes(extracted.read_bytes())

    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return f"Installed ripgrep at {target}"
