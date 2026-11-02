"""Asemien tunnistus: kiintolevyt, ulkoiset levyt/muistitikut ja CD/DVD-asemat."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path

FIXED, REMOVABLE, OPTICAL, NETWORK, OTHER = "fixed", "removable", "optical", "network", "other"


@dataclass
class Drive:
    root: str            # esim. "D:\\"
    label: str           # aseman nimi
    kind: str            # FIXED / REMOVABLE / OPTICAL / NETWORK / OTHER
    ready: bool = True   # onko levy asemassa
    disc: str = ""       # "audio-cd", "dvd", "bluray" tai ""

    @property
    def device(self) -> str:
        """Laitenimi mpv:lle (Windowsissa 'D:')."""
        return self.root.rstrip("\\/") if sys.platform == "win32" else self.root

    @property
    def title(self) -> str:
        name = self.label or {
            FIXED: "Paikallinen levy", REMOVABLE: "Siirrettävä levy",
            OPTICAL: "CD/DVD-asema", NETWORK: "Verkkoasema",
        }.get(self.kind, "Asema")
        if self.kind == OPTICAL:
            if not self.ready:
                name = "CD/DVD-asema (tyhjä)"
            elif self.disc == "audio-cd":
                name = f"Musiikki-CD{' – ' + self.label if self.label and self.label.lower() != 'audio cd' else ''}"
            elif self.disc == "dvd":
                name = f"DVD – {self.label}" if self.label else "DVD"
            elif self.disc == "bluray":
                name = f"Blu-ray – {self.label}" if self.label else "Blu-ray"
        root = self.device if sys.platform == "win32" else self.root
        return f"{name} ({root})"


def detect_disc(root: str) -> str:
    p = Path(root)
    try:
        if (p / "VIDEO_TS").is_dir():
            return "dvd"
        if (p / "BDMV").is_dir():
            return "bluray"
        entries = list(p.iterdir())
        if entries and all(e.suffix.lower() == ".cda" for e in entries):
            return "audio-cd"
        if any(e.suffix.lower() == ".cda" for e in entries):
            return "audio-cd"
    except OSError:
        pass
    return ""


def _windows_drives():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    # Ei "Asemassa ei ole levyä" -ikkunoita tyhjistä asemista
    k32.SetErrorMode(0x0001 | 0x8000)
    mask = k32.GetLogicalDrives()
    kinds = {2: REMOVABLE, 3: FIXED, 4: NETWORK, 5: OPTICAL}
    result = []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        dtype = k32.GetDriveTypeW(root)
        kind = kinds.get(dtype, OTHER)
        name_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        serial, maxlen, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        ready = bool(k32.GetVolumeInformationW(
            root, name_buf, 261, ctypes.byref(serial), ctypes.byref(maxlen),
            ctypes.byref(flags), fs_buf, 261))
        d = Drive(root=root, label=name_buf.value if ready else "", kind=kind, ready=ready)
        if kind == OPTICAL and ready:
            d.disc = detect_disc(root)
        result.append(d)
    return result


def _posix_drives():
    from PySide6.QtCore import QStorageInfo

    result = []
    home = str(Path.home())
    result.append(Drive(root=home, label="Kotikansio", kind=FIXED))
    for vol in QStorageInfo.mountedVolumes():
        if not vol.isValid() or not vol.isReady():
            continue
        root = vol.rootPath()
        fs = bytes(vol.fileSystemType()).decode(errors="ignore")
        if root.startswith(("/proc", "/sys", "/dev", "/run/user", "/snap", "/boot")) or fs in {
            "tmpfs", "overlay", "squashfs", "devtmpfs", "proc", "sysfs", "cgroup2", "autofs"
        }:
            continue
        if root != "/" and not root.startswith(("/media", "/mnt", "/run/media", "/Volumes")):
            continue
        kind = FIXED
        if fs in {"iso9660", "udf", "cdfs"}:
            kind = OPTICAL
        elif root != "/":
            kind = REMOVABLE
        d = Drive(root=root, label=vol.displayName() if root != "/" else "Järjestelmä", kind=kind)
        if kind == OPTICAL:
            d.disc = detect_disc(root)
        result.append(d)
    return result


def list_drives():
    try:
        return _windows_drives() if sys.platform == "win32" else _posix_drives()
    except Exception:
        return []


def quick_locations():
    """Musiikki, Videot jne. jos olemassa."""
    from PySide6.QtCore import QStandardPaths as SP

    out = []
    for loc, name in [(SP.MusicLocation, "Musiikki"), (SP.MoviesLocation, "Videot"),
                      (SP.DownloadLocation, "Lataukset"), (SP.DesktopLocation, "Työpöytä")]:
        path = SP.writableLocation(loc)
        if path and os.path.isdir(path):
            out.append((name, path))
    return out
