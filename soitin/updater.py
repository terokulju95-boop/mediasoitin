"""Automaattinen päivitys GitHub Releases -sivulta.

1. Tarkistetaan uusin julkaisu (GitHubin rajapinta).
2. Ladataan Mediasoitin-windows-x64.zip ja puretaan väliaikaiskansioon.
3. Pieni apuskripti odottaa, että soitin sulkeutuu, kopioi uudet tiedostot
   vanhojen päälle ja käynnistää soittimen uudelleen.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import UPDATE_REPO, __version__

ASSET_SUFFIX = "-windows-x64.zip"
UA = {"User-Agent": f"Mediasoitin/{__version__}", "Accept": "application/vnd.github+json"}


def parse_version(v):
    v = (v or "").strip().lstrip("vV")
    out = []
    for part in v.split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def can_self_update():
    """Itsepäivitys toimii vain valmiissa Windows-exessä (ei lähdekoodista ajettaessa)."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def app_dir():
    return Path(sys.executable).resolve().parent


class UpdateChecker(QThread):
    result = Signal(dict)      # {"version", "notes", "url", "page"} tai {"error"}

    def run(self):
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest", headers=UA)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            asset = next((a for a in data.get("assets", []) if a.get("name", "").endswith(ASSET_SUFFIX)), None)
            self.result.emit({
                "version": data.get("tag_name", ""),
                "notes": data.get("body") or "",
                "url": asset.get("browser_download_url") if asset else "",
                "size": asset.get("size", 0) if asset else 0,
                "page": data.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases",
            })
        except Exception as e:
            self.result.emit({"error": str(e)})


class UpdateDownloader(QThread):
    progress = Signal(int, int)     # ladattu Mt, yhteensä Mt
    ready = Signal(str)             # purettu kansio
    failed = Signal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            tmp = Path(tempfile.mkdtemp(prefix="mediasoitin_update_"))
            zpath = tmp / "update.zip"
            req = urllib.request.Request(self.url, headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    if self._abort:
                        self.failed.emit("Päivitys peruttiin.")
                        return
                    buf = r.read(256 * 1024)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    self.progress.emit(done // 2**20, max(1, total // 2**20))
            out = tmp / "uusi"
            with zipfile.ZipFile(zpath) as z:
                z.extractall(out)
            # zipin sisällä voi olla yksi alikansio
            entries = list(out.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                out = entries[0]
            if not (out / "Mediasoitin.exe").exists():
                self.failed.emit("Ladatusta paketista puuttuu Mediasoitin.exe.")
                return
            self.ready.emit(str(out))
        except Exception as e:
            self.failed.emit(f"Lataus epäonnistui: {e}")


def install_and_restart(new_dir):
    """Käynnistää apuskriptin ja palauttaa True. Soittimen pitää sulkeutua heti tämän jälkeen."""
    dst = app_dir()
    src = Path(new_dir)
    tmp_root = src.parent if src.parent.name.startswith("mediasoitin_update_") else src.parent.parent
    bat = Path(tempfile.gettempdir()) / f"mediasoitin_paivitys_{os.getpid()}.cmd"
    pid = os.getpid()
    script = f"""@echo off
chcp 65001 >nul
rem Odotetaan, että Mediasoitin sulkeutuu
:odota
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto odota
)
rem Uusi ohjelmakirjasto korvaa vanhan kokonaan, muut tiedostot kopioidaan päälle
if exist "{src}\\_internal" robocopy "{src}\\_internal" "{dst}\\_internal" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
robocopy "{src}" "{dst}" /E /XD "{src}\\_internal" /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul
start "" "{dst}\\Mediasoitin.exe"
rmdir /s /q "{tmp_root}" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""
    bat.write_text(script, encoding="utf-8")
    flags = 0x08000000 | 0x00000008   # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(["cmd.exe", "/c", str(bat)], creationflags=flags, close_fds=True)
    return True


def dir_writable():
    try:
        test = app_dir() / ".paivitystesti"
        test.write_text("x")
        test.unlink()
        return True
    except OSError:
        return False
