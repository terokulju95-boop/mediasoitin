"""Hiiren ja näppäimistön ohjaus puhelimen kosketuslevyltä (Windows)."""
import ctypes
import sys

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

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOVE, LDOWN, LUP, RDOWN, RUP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800
KEYUP, UNICODE = 0x0002, 0x0004
VK = {"enter": 0x0D, "backspace": 0x08, "esc": 0x1B, "tab": 0x09, "space": 0x20,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


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
