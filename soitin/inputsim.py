"""Hiiren ja näppäimistön ohjaus puhelimesta (Windows).

- Kosketuslevy: hiiri, klikkaukset, rullaus, tekstin kirjoitus.
- Suoratoisto: Netflixin, YouTuben, Disney+:n, Viaplayn ym. ohjaus selaimessa
  painamalla samoja näppäimiä, joita käyttäjä painaisi itse.
"""
import ctypes
import sys
import time

IS_WIN = sys.platform == "win32"

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOVE, LDOWN, LUP, RDOWN, RUP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800
EXTENDED, KEYUP, UNICODE = 0x0001, 0x0002, 0x0004
VK = {"enter": 0x0D, "backspace": 0x08, "esc": 0x1B, "tab": 0x09, "space": 0x20,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
VK_F, VK_F11 = 0x46, 0x7A
VK_MUTE, VK_VOL_DOWN, VK_VOL_UP, VK_PLAY_PAUSE = 0xAD, 0xAE, 0xAF, 0xB3
# Nämä näppäimet ovat "laajennettuja": ilman lippua osa ohjelmista tulkitsee nuolet numeronäppäimistöksi.
_EXTENDED_VK = {0x25, 0x26, 0x27, 0x28, VK_MUTE, VK_VOL_DOWN, VK_VOL_UP, VK_PLAY_PAUSE}

# Ohjelmat, joissa suoratoistopalveluita katsotaan. Näppäimet ohjataan näille.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe",
            "vivaldi.exe", "arc.exe", "librewolf.exe", "waterfox.exe", "chromium.exe", "yandex.exe",
            "netflix.exe", "disneyplus.exe", "viaplay.exe"}


def _send(*inputs):
    if not IS_WIN:
        return
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.mi = MOUSEINPUT(dx, dy, ctypes.c_uint32(data).value, flags, 0, 0)
    return i


def _key(vk=0, scan=0, flags=0):
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def move(dx, dy):
    if not IS_WIN:
        return
    _send(_mouse(MOVE, int(dx), int(dy)))


def click(button="left"):
    if not IS_WIN:
        return
    if button == "right":
        _send(_mouse(RDOWN), _mouse(RUP))
    else:
        _send(_mouse(LDOWN), _mouse(LUP))


def scroll(amount):
    """amount > 0 = ylös. 120 = yksi rullan pykälä."""
    if not IS_WIN:
        return
    _send(_mouse(WHEEL, data=int(amount)))


def key(name):
    if not IS_WIN:
        return
    vk = VK.get(name)
    if vk:
        _send(_key(vk), _key(vk, flags=KEYUP))


def _tap(vk, times=1):
    """Painaa ja vapauttaa näppäimen (laajennettu lippu ja näppäinkoodi mukana)."""
    if not IS_WIN:
        return
    flags = EXTENDED if vk in _EXTENDED_VK else 0
    scan = user32.MapVirtualKeyW(vk, 0) & 0xFF
    seq = []
    for _ in range(max(1, int(times))):
        seq += [_key(vk, scan, flags), _key(vk, scan, flags | KEYUP)]
    _send(*seq)


# ------------------------------------------------------------------ Selaimen etsiminen
def _process_name(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def _is_player_window(hwnd):
    return bool(hwnd) and _process_name(hwnd) in BROWSERS


def _find_player_window():
    """Ylimmäinen näkyvä selain- tai suoratoistosovelluksen ikkuna (EnumWindows kulkee päällimmäisestä alaspäin)."""
    found = []

    def cb(hwnd, _):
        if (user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0
                and not user32.GetWindow(hwnd, 4)       # GW_OWNER: ei ponnahdusikkunoita
                and _is_player_window(hwnd)):
            found.append(hwnd)
            return False
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def focus_player():
    """Tuo selaimen eteen, jos jokin muu ohjelma on aktiivisena. Palauttaa True, jos selain on edessä."""
    if not IS_WIN:
        return False
    fg = user32.GetForegroundWindow()
    if _is_player_window(fg):
        return True
    hwnd = _find_player_window()
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)                      # SW_RESTORE
    # Windows sallii taustaohjelman vaihtaa aktiivista ikkunaa vain, jos se on juuri "painanut näppäintä".
    # Alt-painallus menee vielä vanhalle ikkunalle, ei selaimelle.
    _send(_key(0x12), _key(0x12, flags=KEYUP))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.06)                                    # annetaan ikkunan vaihtua ennen näppäintä
    return True


# ------------------------------------------------------------------ Suoratoisto
STREAM_ACTIONS = ("playpause", "back", "fwd", "fullscreen", "exit_fullscreen", "f11",
                  "vol_up", "vol_down", "mute", "space")


def stream(action):
    """Ohjaa suoratoistopalvelua selaimessa. Palauttaa False, jos selainta ei löytynyt
    (vain toimintoihin, jotka tarvitsevat selaimen eteen)."""
    if not IS_WIN or action not in STREAM_ACTIONS:
        return True
    # Toisto/tauko ja äänenvoimakkuus toimivat Windowsin medianäppäimillä, vaikka selain ei olisi edessä.
    if action == "playpause":
        _tap(VK_PLAY_PAUSE)
        return True
    if action == "vol_up":
        _tap(VK_VOL_UP, 2)          # yksi painallus = 2 %, kaksi = 4 %
        return True
    if action == "vol_down":
        _tap(VK_VOL_DOWN, 2)
        return True
    if action == "mute":
        _tap(VK_MUTE)
        return True
    if not focus_player():
        return False               # ei painella nuolia väärään ohjelmaan
    vk = {"back": VK["left"], "fwd": VK["right"], "fullscreen": VK_F, "exit_fullscreen": VK["esc"],
          "f11": VK_F11, "space": VK["space"]}[action]
    _tap(vk)
    return True


def type_text(text):
    if not IS_WIN:
        return
    seq = []
    for ch in str(text)[:500]:
        raw = ch.encode("utf-16-le")
        for cu in (int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)):
            seq.append(_key(0, cu, UNICODE))
            seq.append(_key(0, cu, UNICODE | KEYUP))
    if seq:
        _send(*seq)
