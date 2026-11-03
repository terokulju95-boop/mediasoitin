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


def _ps_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def install_and_restart(new_dir):
    """Käynnistää piilotetun PowerShell-apuskriptin ja palauttaa True.
    Skripti odottaa soittimen sulkeutumista, vaihtaa tiedostot ja käynnistää soittimen uudelleen.
    Soittimen pitää sulkeutua heti tämän jälkeen."""
    dst = app_dir()
    src = Path(new_dir)
    tmp_root = src
    while tmp_root.parent != tmp_root and not tmp_root.name.startswith("mediasoitin_update_"):
        tmp_root = tmp_root.parent
    if not tmp_root.name.startswith("mediasoitin_update_"):
        tmp_root = src.parent
    pid = os.getpid()
    log = Path(tempfile.gettempdir()) / "mediasoitin_paivitys.log"
    ps1 = Path(tempfile.gettempdir()) / f"mediasoitin_paivitys_{pid}.ps1"
    q = _ps_quote
    script = f"""$ErrorActionPreference = 'Continue'
$log = {q(log)}
"Päivitys alkoi $(Get-Date)" | Out-File -FilePath $log -Encoding utf8
# Odotetaan, että Mediasoitin sulkeutuu (enintään 60 s)
try {{ Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{}}
Get-Process -Id {pid} -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 700
$src = {q(src)}
$dst = {q(dst)}
if (Test-Path (Join-Path $src '_internal')) {{
  robocopy (Join-Path $src '_internal') (Join-Path $dst '_internal') /MIR /R:10 /W:1 /NFL /NDL /NJH /NJS /NP | Out-File -FilePath $log -Append -Encoding utf8
}}
robocopy $src $dst /E /XD (Join-Path $src '_internal') /R:10 /W:1 /NFL /NDL /NJH /NJS /NP | Out-File -FilePath $log -Append -Encoding utf8
"Kopiointi valmis (robocopy $LASTEXITCODE)" | Out-File -FilePath $log -Append -Encoding utf8
Start-Process -FilePath (Join-Path $dst 'Mediasoitin.exe') -WorkingDirectory $dst
Remove-Item -LiteralPath {q(tmp_root)} -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
    ps1.write_text(script, encoding="utf-8-sig")     # BOM: Windows PowerShell lukee ääkköset oikein
    CREATE_NO_WINDOW = 0x08000000                     # ei konsoli-ikkunaa (myöskään apuohjelmille)
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                      "-WindowStyle", "Hidden", "-File", str(ps1)],
                     creationflags=CREATE_NO_WINDOW, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def dir_writable():
    try:
        test = app_dir() / ".paivitystesti"
        test.write_text("x")
        test.unlink()
        return True
    except OSError:
        return False
