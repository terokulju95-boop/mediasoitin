"""DVD-levyn kopiointi kansioksi (VIDEO_TS) – suojaamattomille levyille.

Tiedostot kopioidaan sellaisinaan. Kopiosuojattuja (CSS) kaupallisia levyjä
ei pureta: niiden luku keskeytyy ja käyttäjälle kerrotaan syy.
"""
import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

CHUNK = 4 * 1024 * 1024


def disc_size(root):
    total = 0
    for sub in ("VIDEO_TS", "AUDIO_TS"):
        d = Path(root) / sub
        if d.is_dir():
            total += sum(f.stat().st_size for f in d.iterdir() if f.is_file())
    return total


class DvdCopyWorker(QThread):
    progress = Signal(int, int, str)       # kopioitu Mt, yhteensä Mt, tiedosto
    done = Signal(str)                     # kohdekansio
    failed = Signal(str)                   # virheilmoitus

    def __init__(self, root, dest_folder, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.dest = Path(dest_folder)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            total = max(1, disc_size(self.root))
            copied = 0
            self.dest.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(self.dest).free
            if free < total:
                self.failed.emit(f"Kohdelevyllä ei ole tarpeeksi tilaa ({total // 2**20} Mt tarvitaan).")
                return
            for sub in ("VIDEO_TS", "AUDIO_TS"):
                src_dir = self.root / sub
                if not src_dir.is_dir():
                    continue
                dst_dir = self.dest / sub
                dst_dir.mkdir(parents=True, exist_ok=True)
                for f in sorted(src_dir.iterdir()):
                    if not f.is_file():
                        continue
                    with open(f, "rb") as src, open(dst_dir / f.name, "wb") as dst:
                        while True:
                            if self._abort:
                                self.failed.emit("Kopiointi keskeytettiin.")
                                return
                            try:
                                buf = src.read(CHUNK)
                            except OSError:
                                self.failed.emit(
                                    f"Levyn lukeminen epäonnistui ({f.name}).\n\n"
                                    "Levy on todennäköisesti kopiosuojattu (kaupallinen DVD). "
                                    "Suojattuja levyjä ei voi kopioida, mutta niitä voi katsoa "
                                    "soittimella normaalisti.\n\nMuussa tapauksessa levy voi olla "
                                    "naarmuuntunut tai likainen.")
                                return
                            if not buf:
                                break
                            dst.write(buf)
                            copied += len(buf)
                            self.progress.emit(copied // 2**20, total // 2**20, f.name)
            self.done.emit(str(self.dest))
        except OSError as e:
            self.failed.emit(f"Kopiointi epäonnistui: {e}")


def safe_name(label):
    name = "".join(c for c in (label or "DVD") if c not in '<>:"/\\|?*').strip()
    return name or "DVD"


def unique_folder(parent, name):
    p = Path(parent) / name
    i = 2
    while p.exists():
        p = Path(parent) / f"{name} ({i})"
        i += 1
    return p

