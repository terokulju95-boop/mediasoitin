"""Musiikki-CD:n luku suoraan asemalta (Windows).

CD-raidat luetaan raakana digitaalisena äänenä (2352 tavua/sektori,
16-bit/44.1 kHz stereo) ja syötetään mpv:lle WAV-virtana. Ääni on siis
täsmälleen sama kuin levyllä – ei pakkausta eikä muunnosta.

URL-muoto: cdtrack://D/5  (asema D:, kappale 5)
"""
import struct
import sys

SECTOR = 2352            # tavua per CD-äänisektori
SECTORS_PER_READ = 20    # ~46 kt kerralla (alle Windowsin 64 kt rajan)
WAV_HEADER = 44


def wav_header(data_bytes: int) -> bytes:
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + data_bytes, b"WAVE", b"fmt ", 16,
                       1, 2, 44100, 44100 * 4, 4, 16, b"data", data_bytes)


class CdTrack:
    __slots__ = ("number", "lba", "sectors")

    def __init__(self, number, lba, sectors):
        self.number, self.lba, self.sectors = number, lba, sectors

    @property
    def seconds(self):
        return self.sectors / 75.0


class TrackStream:
    """mpv:n stream-protokollan mukainen olio: WAV-otsake + raaka PCM."""

    def __init__(self, reader, track: CdTrack):
        self.reader = reader
        self.track = track
        self.data_size = track.sectors * SECTOR
        self.size = WAV_HEADER + self.data_size
        self.header = wav_header(self.data_size)
        self.pos = 0
        self._cache_start = -1
        self._cache = b""

    def read(self, n):
        if self.pos >= self.size:
            return b""
        if self.pos < WAV_HEADER:
            out = self.header[self.pos:self.pos + n]
            self.pos += len(out)
            return out
        off = self.pos - WAV_HEADER
        sector = off // SECTOR
        if not (self._cache_start <= sector < self._cache_start + len(self._cache) // SECTOR):
            count = min(SECTORS_PER_READ, self.track.sectors - sector)
            self._cache = self.reader.read_sectors(self.track.lba + sector, count)
            self._cache_start = sector
        start = off - self._cache_start * SECTOR
        out = self._cache[start:start + min(n, self.size - self.pos)]
        self.pos += len(out)
        return out

    def seek(self, pos):
        self.pos = max(0, min(int(pos), self.size))
        return self.pos

    def close(self):
        self.reader.close()


class WinCdReader:
    IOCTL_CDROM_READ_TOC = 0x00024000
    IOCTL_CDROM_RAW_READ = 0x0002403E

    def __init__(self, letter: str):
        import ctypes
        from ctypes import wintypes

        self.ct = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.DeviceIoControl.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                        ctypes.c_void_p]
        k32.DeviceIoControl.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.k32 = k32
        self.DWORD = wintypes.DWORD

        class RAW_READ_INFO(ctypes.Structure):
            _fields_ = [("DiskOffset", ctypes.c_longlong), ("SectorCount", wintypes.ULONG),
                        ("TrackMode", ctypes.c_int)]
        self.RAW_READ_INFO = RAW_READ_INFO

        letter = letter.strip().rstrip(":\\/")[:1].upper()
        h = k32.CreateFileW(f"\\\\.\\{letter}:", 0x80000000, 0x1 | 0x2, None, 3, 0, None)
        if h is None or h == ctypes.c_void_p(-1).value:
            raise ValueError(f"CD-asemaa {letter}: ei voitu avata")
        self.h = h

    def _ioctl(self, code, inbuf, outsize):
        ct = self.ct
        out = ct.create_string_buffer(outsize)
        ret = self.DWORD(0)
        inptr, insize = (ct.byref(inbuf), ct.sizeof(inbuf)) if inbuf is not None else (None, 0)
        ok = self.k32.DeviceIoControl(self.h, code, inptr, insize, out, outsize, ct.byref(ret), None)
        return out.raw[:ret.value] if ok else None

    def read_toc(self):
        raw = self._ioctl(self.IOCTL_CDROM_READ_TOC, None, 804)
        if not raw or len(raw) < 12:
            raise ValueError("Levyn sisällysluetteloa ei voitu lukea (onko levy asemassa?)")
        first, last = raw[2], raw[3]
        entries = []
        for i in range(last - first + 2):  # +1 lead-out
            b = raw[4 + i * 8: 12 + i * 8]
            if len(b) < 8:
                break
            control = b[1] & 0x0F
            num = b[2]
            m, s, f = b[5], b[6], b[7]
            entries.append((num, (m * 60 + s) * 75 + f - 150, bool(control & 0x4)))
        tracks = []
        for i in range(len(entries) - 1):
            num, lba, is_data = entries[i]
            nxt_lba, nxt_data = entries[i + 1][1], entries[i + 1][2]
            if is_data:
                continue
            length = nxt_lba - lba
            if nxt_data and entries[i + 1][0] != 0xAA:
                length -= 11400  # Enhanced CD: istuntojen välinen tauko
            if length > 0:
                tracks.append(CdTrack(num, lba, length))
        if not tracks:
            raise ValueError("Levyllä ei ole ääniraitoja")
        return tracks

    def read_sectors(self, lba, count):
        info = self.RAW_READ_INFO(lba * 2048, count, 2)  # 2 = CDDA
        for _ in range(3):
            data = self._ioctl(self.IOCTL_CDROM_RAW_READ, info, count * SECTOR)
            if data and len(data) == count * SECTOR:
                return data
        if count > 1:  # yritä sektori kerrallaan
            return b"".join(self.read_sectors(lba + i, 1) for i in range(count))
        return b"\0" * SECTOR  # lukuvirhe: hiljaisuus mieluummin kuin pysähdys

    def close(self):
        if getattr(self, "h", None):
            self.k32.CloseHandle(self.h)
            self.h = None


def open_reader(letter):
    if sys.platform != "win32":
        raise ValueError("Suora CD-luku toimii vain Windowsissa")
    return WinCdReader(letter)


def read_toc(letter):
    r = open_reader(letter)
    try:
        return r.read_toc()
    finally:
        r.close()


def track_url(letter, number):
    letter = letter.strip().rstrip(":/\\")[:1].upper()
    return f"cdtrack://{letter}/{number}"


def parse_url(url):
    rest = url.split("://", 1)[1]
    letter, num = rest.split("/", 1)
    return letter, int(num)


def open_stream(url, reader_factory=open_reader):
    """mpv kutsuu tätä avatessaan cdtrack://-osoitteen."""
    letter, num = parse_url(url)
    reader = reader_factory(letter)
    try:
        track = next(t for t in reader.read_toc() if t.number == num)
    except StopIteration:
        reader.close()
        raise ValueError(f"Kappaletta {num} ei löydy")
    return TrackStream(reader, track)
