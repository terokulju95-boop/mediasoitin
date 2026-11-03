"""Kaukosäädin puhelimesta.

Soitin käynnistää pienen www-palvelimen kotiverkkoon.
- Selaimella: QR-koodin osoite (sisältää satunnaisen avaimen).
- Android-sovelluksella: sovellus löytää soittimen itse (UDP-haku) ja muodostaa
  laiteparin kerran 4-numeroisella koodilla. Sen jälkeen yhteys toimii aina.
"""
import json
import platform
import secrets
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

from . import __version__
from .remote_page import PAGE

DISCOVERY_PORT = 41234
DISCOVERY_MAGIC = b"MEDIASOITIN_DISCOVER"


def local_ip():
    """Koneen osoite kotiverkossa (ei lähetä mitään verkkoon)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def fix_firewall():
    """Sallii Mediasoittimen Windowsin palomuurissa (kysyy järjestelmänvalvojan luvan).
    Poistaa ensin vanhat säännöt (myös mahdolliset estosäännöt) ja luo uuden sallivan säännön.
    Palauttaa (onnistui, viesti)."""
    import base64
    import subprocess
    import sys
    if sys.platform != "win32":
        return False, "Toimii vain Windowsissa."
    exe = sys.executable
    q = "'" + exe.replace("'", "''") + "'"
    inner = (
        f"Get-NetFirewallApplicationFilter -Program {q} -ErrorAction SilentlyContinue | "
        "Get-NetFirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName 'Mediasoitin (kaukosäädin)' -Direction Inbound -Program {q} "
        "-Action Allow -Profile Any | Out-Null"
    )
    enc = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    outer = ("try { $p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
             f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{enc}'; exit $p.ExitCode }} "
             "catch { exit 1223 }")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", outer],
                           creationflags=0x08000000, timeout=180,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, f"Palomuurin asetusta ei voitu muuttaa: {e}"
    if r.returncode == 0:
        return True, "Palomuuri sallii nyt Mediasoittimen. Kokeile hakua puhelimella uudelleen."
    if r.returncode == 1223:
        return False, "Lupaa ei annettu. Palomuurin asetusta ei muutettu."
    return False, f"Palomuurin asetusta ei voitu muuttaa (virhekoodi {r.returncode})."


def computer_name():
    return platform.node() or socket.gethostname() or "Tietokone"


class RemoteServer(QObject):
    command = Signal(str, object)          # komento, arvo (käsitellään käyttöliittymäsäikeessä)
    pair_requested = Signal(str, str)      # koodi, laitteen nimi
    pair_finished = Signal(bool, str)      # onnistui, laitteen nimi

    def __init__(self, parent=None):
        super().__init__(parent)
        self.qs = QSettings("Mediasoitin", "Mediasoitin")
        self.token = self.qs.value("remote/token", "", type=str)
        if not self.token:
            self.token = secrets.token_urlsafe(8)
            self.qs.setValue("remote/token", self.token)
        self.server_id = self.qs.value("remote/id", "", type=str)
        if not self.server_id:
            self.server_id = uuid.uuid4().hex[:12]
            self.qs.setValue("remote/id", self.server_id)
        self.state = {}        # käyttöliittymä päivittää tätä
        self.cover = None      # (mime, tavut, avain)
        self.httpd = None
        self.udp = None
        self.port = None
        self.error = ""
        self._pair = None      # {"code", "device", "expires", "tries"}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- Laitteet
    def devices(self):
        try:
            return json.loads(self.qs.value("remote/devices", "[]", type=str))
        except Exception:
            return []

    def _save_devices(self, devs):
        self.qs.setValue("remote/devices", json.dumps(devs, ensure_ascii=False))

    def remove_device(self, token):
        self._save_devices([d for d in self.devices() if d.get("token") != token])

    def valid_token(self, tok):
        if not tok:
            return False
        if secrets.compare_digest(tok, self.token):
            return True
        return any(secrets.compare_digest(tok, d.get("token", "")) for d in self.devices())

    # ---------------------------------------------------------- Pariutus
    def start_pairing(self, device):
        with self._lock:
            code = f"{secrets.randbelow(10000):04d}"
            self._pair = {"code": code, "device": device[:40] or "Puhelin",
                          "expires": time.time() + 180, "tries": 0}
        self.pair_requested.emit(code, self._pair["device"])

    def confirm_pairing(self, code, device):
        with self._lock:
            p = self._pair
            if not p or time.time() > p["expires"]:
                return None, "Pariutus on vanhentunut. Aloita uudelleen."
            p["tries"] += 1
            if p["tries"] > 5:
                self._pair = None
                return None, "Liian monta yritystä. Aloita uudelleen."
            if not secrets.compare_digest(str(code).strip(), p["code"]):
                return None, "Väärä koodi."
            self._pair = None
        tok = secrets.token_urlsafe(24)
        devs = self.devices()
        devs.append({"token": tok, "name": device[:40] or "Puhelin", "added": time.strftime("%d.%m.%Y")})
        self._save_devices(devs)
        self.pair_finished.emit(True, device)
        return tok, ""

    # ---------------------------------------------------------- Palvelin
    @property
    def running(self):
        return self.httpd is not None

    def url(self):
        return f"http://{local_ip()}:{self.port}/?k={self.token}"

    def info(self):
        return {"app": "mediasoitin", "name": computer_name(), "id": self.server_id,
                "port": self.port, "version": __version__}

    def start(self, port):
        if self.httpd:
            return True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _token(self, q):
                return q.get("k", [""])[0] or self.headers.get("X-Token", "")

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body, ensure_ascii=False)
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self):
                n = min(int(self.headers.get("Content-Length", 0) or 0), 10000)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if u.path == "/api/info":
                    self._send(200, owner.info())
                    return
                if not owner.valid_token(self._token(q)):
                    self._send(403, "<h1>Väärä tai puuttuva avain</h1><p>Skannaa QR-koodi soittimesta uudelleen "
                               "tai muodosta laitepari sovelluksessa.</p>", "text/html; charset=utf-8")
                    return
                if u.path == "/":
                    self._send(200, PAGE, "text/html; charset=utf-8")
                elif u.path == "/api/state":
                    self._send(200, owner.state)
                elif u.path == "/api/cover":
                    if owner.cover:
                        self._send(200, owner.cover[1], owner.cover[0])
                    else:
                        self._send(404, {})
                else:
                    self._send(404, {})

            def do_POST(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                try:
                    data = self._json()
                except Exception:
                    self._send(400, {})
                    return
                if u.path == "/api/pair/request":
                    owner.start_pairing(str(data.get("device", "")))
                    self._send(200, {"ok": True})
                    return
                if u.path == "/api/pair/confirm":
                    tok, err = owner.confirm_pairing(data.get("code", ""), str(data.get("device", "")))
                    if tok:
                        self._send(200, dict(owner.info(), token=tok))
                    else:
                        self._send(403, {"error": err})
                    return
                if u.path != "/api/cmd" or not owner.valid_token(self._token(q)):
                    self._send(403, {})
                    return
                owner.command.emit(str(data.get("cmd", "")), data.get("value"))
                self._send(200, {"ok": True})

        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", int(port)), Handler)
            self.httpd.daemon_threads = True
        except OSError as e:
            self.error = f"Porttia {port} ei voitu avata ({e.strerror or e})."
            self.httpd = None
            return False
        self.port = int(port)
        self.error = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._start_discovery()
        return True

    def _start_discovery(self):
        """Vastaa Android-sovelluksen hakuun (UDP-yleislähetys)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(1.0)
        except OSError:
            self.udp = None
            return
        self.udp = sock

        def loop():
            while self.udp is sock:
                try:
                    data, addr = sock.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if data.strip() == DISCOVERY_MAGIC and self.port:
                    try:
                        sock.sendto(json.dumps(self.info()).encode("utf-8"), addr)
                    except OSError:
                        pass
            try:
                sock.close()
            except OSError:
                pass
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.udp = None
        if self.httpd:
            h = self.httpd
            self.httpd = None
            threading.Thread(target=lambda: (h.shutdown(), h.server_close()), daemon=True).start()


def qr_pixmap(text, size=260):
    try:
        import qrcode
    except ImportError:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    pm = QPixmap(size, size)
    pm.fill(QColor("#FFFFFF"))
    p = QPainter(pm)
    cell = size / n
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(QRectF(x * cell, y * cell, cell + 0.6, cell + 0.6))
    p.end()
    return pm


class PairCodeDialog(QDialog):
    """Näytetään, kun puhelin pyytää laiteparia."""

    def __init__(self, code, device, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laitepari")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        lay = QVBoxLayout(self)
        t = QLabel(f"<b>{device}</b> haluaa ohjata soitinta.<br>Syötä puhelimeen tämä koodi:")
        t.setAlignment(Qt.AlignCenter)
        c = QLabel(" ".join(code))
        c.setAlignment(Qt.AlignCenter)
        c.setStyleSheet("font-size: 44pt; font-weight: bold; letter-spacing: 6px; padding: 10px 24px;")
        n = QLabel("Koodi on voimassa 3 minuuttia. Jos et tunnista laitetta, sulje tämä ikkuna.")
        n.setObjectName("pathLabel")
        n.setWordWrap(True)
        close = QPushButton("Sulje")
        close.clicked.connect(self.close)
        lay.addWidget(t)
        lay.addWidget(c)
        lay.addWidget(n)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.setMinimumWidth(380)


class RemoteDialog(QDialog):
    def __init__(self, server: RemoteServer, cfg, parent=None):
        super().__init__(parent)
        self.server = server
        self.cfg = cfg
        self.setWindowTitle("Kaukosäädin puhelimesta")
        self.setMinimumWidth(460)
        self.enable = QCheckBox("Kaukosäädin käytössä")
        self.enable.setChecked(server.running)
        self.enable.toggled.connect(self._toggle)
        self.app_info = QLabel()
        self.app_info.setWordWrap(True)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.url = QLabel()
        self.url.setAlignment(Qt.AlignCenter)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("pathLabel")
        self.dev_title = QLabel("<b>Laiteparit</b> (Android-sovellus)")
        self.dev_list = QListWidget()
        self.dev_list.setMaximumHeight(110)
        rm = QPushButton("Poista valittu laite")
        rm.clicked.connect(self._remove_device)
        self.fw_btn = QPushButton("Korjaa palomuuri")
        self.fw_btn.setToolTip("Jos puhelin ei löydä tätä konetta: sallii Mediasoittimen Windowsin palomuurissa.\n"
                               "Windows kysyy järjestelmänvalvojan luvan.")
        self.fw_btn.clicked.connect(self._fix_firewall)
        import sys as _sys
        self.fw_btn.setVisible(_sys.platform == "win32")
        self.status = QLabel()
        self.status.setWordWrap(True)
        new_key = QPushButton("Vaihda QR-avain")
        new_key.setToolTip("Luo uuden QR-koodin. Vanhalla koodilla avatut selaimet eivät enää pääse ohjaamaan.")
        new_key.clicked.connect(self._new_key)
        close = QPushButton("Sulje")
        close.setDefault(True)
        close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(rm)
        btns.addWidget(self.fw_btn)
        btns.addWidget(new_key)
        btns.addStretch()
        btns.addWidget(close)
        lay = QVBoxLayout(self)
        for w in (self.enable, self.status, self.app_info, self.qr, self.url, self.help, self.dev_title, self.dev_list):
            lay.addWidget(w)
        lay.addLayout(btns)
        server.pair_finished.connect(lambda *_: self._refresh())
        self._refresh()

    def _toggle(self, on):
        if on:
            ok = self.server.start(self.cfg.get("remote_port"))
            if not ok:
                self.enable.blockSignals(True)
                self.enable.setChecked(False)
                self.enable.blockSignals(False)
        else:
            self.server.stop()
        self.cfg.set("remote_enabled", self.server.running)
        self._refresh()

    def _new_key(self):
        self.server.token = secrets.token_urlsafe(8)
        self.server.qs.setValue("remote/token", self.server.token)
        self._refresh()

    def _fix_firewall(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, msg = fix_firewall()
        finally:
            QApplication.restoreOverrideCursor()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Palomuuri", msg)

    def _remove_device(self):
        it = self.dev_list.currentItem()
        if it and it.data(Qt.UserRole):
            self.server.remove_device(it.data(Qt.UserRole))
            self._refresh()

    def _refresh(self):
        self.dev_list.clear()
        for d in self.server.devices():
            it = QListWidgetItem(f"{d.get('name')}   (lisätty {d.get('added', '')})")
            it.setData(Qt.UserRole, d.get("token"))
            self.dev_list.addItem(it)
        if not self.server.devices():
            it = QListWidgetItem("Ei laitepareja")
            it.setFlags(Qt.NoItemFlags)
            self.dev_list.addItem(it)
        if self.server.running:
            ip = local_ip()
            ok_udp = self.server.udp is not None
            self.status.setText(
                f"<span style='color:#66bb6a'>●</span> Käynnissä: {computer_name()} · {ip}:{self.server.port}"
                + ("" if ok_udp else "<br><span style='color:#ffb74d'>Automaattinen haku ei ole käytössä "
                   "(portti 41234 varattu – onko soitin auki kahdesti?). Kirjoita osoite puhelimeen käsin.</span>"))
            self.app_info.setText(
                "<b>Android-sovellus:</b> avaa Mediasoitin-kaukosäädin puhelimessa, niin se löytää tämän "
                "koneen itse. Ensimmäisellä kerralla tähän ruutuun tulee koodi, jonka syötät puhelimeen.")
            url = self.server.url()
            pm = qr_pixmap(url)
            if pm:
                self.qr.setPixmap(pm)
            self.qr.show()
            self.url.setText(url)
            self.help.setText(
                "<b>Selaimella</b> (muut puhelimet): skannaa QR-koodi samasta wifistä.<br><br>"
                "<b>Jos puhelin ei löydä konetta:</b> paina <i>Korjaa palomuuri</i>. Näin käy usein, kun "
                "soittimen uusi versio on purettu eri kansioon kuin aiemmin. Voit myös kirjoittaa "
                "yllä näkyvän osoitteen puhelimen sovellukseen käsin.")
        else:
            self.status.setText("<span style='color:#777'>●</span> Ei käytössä")
            self.qr.hide()
            self.app_info.setText("")
            self.url.setText(self.server.error or "")
            self.help.setText("Ota kaukosäädin käyttöön, niin puhelin voi ohjata soitinta.")
        self.adjustSize()
