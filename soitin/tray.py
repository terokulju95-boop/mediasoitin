"""Taustalla pysyminen: ilmaisinalueen kuvake, Windowsin mukana käynnistys ja yksi kopio kerrallaan.

- Kun ikkuna suljetaan, soitin jää ilmaisinalueelle (kaukosäädin toimii edelleen).
- "Käynnistä Windowsin mukana" lisää soittimen kirjautumisen yhteydessä käynnistyviin
  ohjelmiin parametrilla --tausta, jolloin ikkunaa ei avata.
- Jos soitin on jo käynnissä ja käyttäjä avaa sen uudelleen (tai tuplaklikkaa videota),
  uusi kopio välittää tiedostot jo käynnissä olevalle ja sulkeutuu.
"""
import getpass
import json
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

HIDDEN_ARG = "--tausta"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Mediasoitin"


# ------------------------------------------------------------------ Windowsin mukana käynnistys
def _launch_command():
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):            # PyInstallerin Mediasoitin.exe
        return f'"{exe}" {HIDDEN_ARG}'
    # Kehitysversio: pythonw.exe, ettei konsoli-ikkunaa avaudu.
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    script = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{script}" {HIDDEN_ARG}'


def autostart_supported():
    return sys.platform == "win32"


def autostart_enabled():
    if not autostart_supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(value)
    except OSError:
        return False


def set_autostart(on):
    """Palauttaa (onnistui, virheviesti)."""
    if not autostart_supported():
        return False, "Toimii vain Windowsissa."
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as e:
        return False, f"Automaattista käynnistystä ei voitu muuttaa: {e}"


def refresh_autostart():
    """Päivittää käynnistyskomennon, jos soitin on siirretty toiseen kansioon (esim. päivityksen jälkeen)."""
    if autostart_enabled():
        set_autostart(True)


# ------------------------------------------------------------------ Yksi kopio kerrallaan
def _server_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = "kayttaja"
    return f"Mediasoitin-{''.join(c for c in user if c.isalnum()) or 'kayttaja'}"


def send_to_running(files, show):
    """Jos soitin on jo käynnissä, lähettää sille tiedostot ja palauttaa True."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(500):
        return False
    msg = json.dumps({"files": [os.path.abspath(f) for f in files], "show": bool(show)}).encode("utf-8")
    sock.write(msg + b"\n")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Kuuntelee myöhemmin käynnistettyjä kopioita."""
    message = Signal(list, bool)          # tiedostot, näytetäänkö ikkuna

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        name = _server_name()
        if not self.server.listen(name):
            QLocalServer.removeServer(name)   # edellinen kaatunut kopio jätti nimen varatuksi
            self.server.listen(name)
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()

            def ready(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))
                if b"\n" in buf:
                    try:
                        data = json.loads(bytes(buf).split(b"\n", 1)[0].decode("utf-8"))
                    except Exception:
                        data = {}
                    self.message.emit([str(f) for f in data.get("files", [])], bool(data.get("show", True)))
                    sock.disconnectFromServer()
            sock.readyRead.connect(ready)
            sock.disconnected.connect(sock.deleteLater)
