"""Kaukosäädin puhelimesta.

Soitin käynnistää pienen www-palvelimen kotiverkkoon.
- Selaimella: QR-koodin osoite (sisältää satunnaisen avaimen).
- Android-sovelluksella: sovellus löytää soittimen itse (UDP-haku) ja muodostaa
  laiteparin kerran. Sen jälkeen yhteys toimii aina.

Laiteparin turvallisuus (kaukosäädin voi ohjata hiirtä ja näppäimistöä, joten tämä on tärkeää):
- Laiteparia voi pyytää vain, kun Kaukosäädin-ikkuna on auki tietokoneella.
- Pyyntö pitää hyväksyä tietokoneella Salli-napilla. Vasta sitten arvotaan 6-numeroinen koodi.
- Kolme väärää koodia mitätöi pyynnön. Kymmenen väärää koodia tunnissa lukitsee pariutuksen tunniksi.
- Pyyntöjä hyväksytään enintään kolme kymmenessä minuutissa.
"""
import html
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

# Laiteparin rajat
PAIR_CODE_DIGITS = 6
PAIR_APPROVE_TIMEOUT = 120      # s: aika painaa Salli tietokoneella
PAIR_CODE_TIMEOUT = 180         # s: koodin voimassaolo Sallin jälkeen
PAIR_MAX_TRIES = 3              # väärää koodia / pyyntö
PAIR_MAX_REQUESTS = 3           # pyyntöä ...
PAIR_REQUEST_WINDOW = 600       # ... kymmenessä minuutissa
PAIR_MAX_FAILS = 10             # väärää koodia ...
PAIR_FAIL_WINDOW = 3600         # ... tunnissa → lukitus
PAIR_LOCK_TIME = 3600           # s


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
    Sääntö koskee vain yksityisiä verkkoja (kotiverkko), ei julkisia wifejä.
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
        "-Action Allow -Profile Private | Out-Null"
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
        return True, ("Palomuuri sallii nyt Mediasoittimen kotiverkossa (yksityiset verkot). Kokeile hakua puhelimella "
                      "uudelleen.\n\nJos puhelin ei vieläkään löydä konetta, tarkista, että kotiverkon tyyppi on "
                      "Windowsissa Yksityinen verkko.")
    if r.returncode == 1223:
        return False, "Lupaa ei annettu. Palomuurin asetusta ei muutettu."
    return False, f"Palomuurin asetusta ei voitu muuttaa (virhekoodi {r.returncode})."


def computer_name():
    return platform.node() or socket.gethostname() or "Tietokone"


class RemoteServer(QObject):
    command = Signal(str, object)          # komento, arvo (käsitellään käyttöliittymäsäikeessä)
    pair_requested = Signal(str, str)      # pyynnön tunniste, laitteen nimi
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
        self._pair = None      # {"id", "device", "approved", "code", "expires", "tries"}
        self.pairing_open = False   # True, kun Kaukosäädin-ikkuna on auki (vain silloin voi pariuttaa)
        self._req_times = []        # laiteparipyyntöjen ajat (raja: PAIR_MAX_REQUESTS / PAIR_REQUEST_WINDOW)
        self._fail_times = []       # väärien koodien ajat (raja: PAIR_MAX_FAILS / PAIR_FAIL_WINDOW)
        self._locked_until = 0.0
        self.providers = {}    # sovellus asettaa: browse, library, album, radio_search
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
        """Puhelin pyytää laiteparia. Palauttaa (onnistui, virheilmoitus)."""
        device = (device or "").strip()[:40] or "Puhelin"
        with self._lock:
            now = time.time()
            if not self.pairing_open:
                return False, ("Avaa tietokoneella Mediasoittimen Kaukosäädin-ikkuna "
                               "(valikosta tai ilmaisinalueen kuvakkeesta) ja yritä uudelleen.")
            if now < self._locked_until:
                return False, "Laiteparin muodostus on lukittu liian monen väärän koodin takia. Yritä myöhemmin."
            self._req_times = [t for t in self._req_times if now - t < PAIR_REQUEST_WINDOW]
            if len(self._req_times) >= PAIR_MAX_REQUESTS:
                return False, "Liian monta laiteparipyyntöä. Odota hetki ja yritä uudelleen."
            self._req_times.append(now)
            pid = secrets.token_hex(6)
            self._pair = {"id": pid, "device": device, "approved": False, "code": None,
                          "expires": now + PAIR_APPROVE_TIMEOUT, "tries": 0}
        self.pair_requested.emit(pid, device)
        return True, ""

    def approve_pairing(self, pid):
        """Tietokoneen käyttäjä painoi Salli. Palauttaa puhelimeen syötettävän koodin (tai None)."""
        with self._lock:
            p = self._pair
            if not p or p["id"] != pid or time.time() > p["expires"]:
                return None
            p["code"] = f"{secrets.randbelow(10 ** PAIR_CODE_DIGITS):0{PAIR_CODE_DIGITS}d}"
            p["approved"] = True
            p["expires"] = time.time() + PAIR_CODE_TIMEOUT
            return p["code"]

    def deny_pairing(self, pid):
        """Estä tai ikkunan sulkeminen: pyyntö mitätöidään (vain tämä pyyntö, ei myöhempää)."""
        with self._lock:
            if self._pair and self._pair["id"] == pid:
                self._pair = None

    def confirm_pairing(self, code, device=""):
        """Puhelin lähettää koodin. Palauttaa (avain, virheilmoitus)."""
        failed_device = None
        with self._lock:
            now = time.time()
            if now < self._locked_until:
                return None, "Laiteparin muodostus on lukittu liian monen väärän koodin takia. Yritä myöhemmin."
            p = self._pair
            if not p or now > p["expires"]:
                return None, "Pariutus on vanhentunut. Aloita uudelleen."
            if not p["approved"]:
                return None, "Hyväksy pyyntö ensin tietokoneella (Salli)."
            if not secrets.compare_digest(str(code).strip(), p["code"]):
                p["tries"] += 1
                self._fail_times = [t for t in self._fail_times if now - t < PAIR_FAIL_WINDOW] + [now]
                if len(self._fail_times) >= PAIR_MAX_FAILS:
                    self._locked_until = now + PAIR_LOCK_TIME
                    self._pair = None
                    msg = "Liian monta väärää koodia. Laiteparin muodostus on lukittu tunniksi."
                    failed_device = p["device"]
                elif p["tries"] >= PAIR_MAX_TRIES:
                    self._pair = None
                    msg = "Liian monta väärää koodia. Aloita uudelleen."
                    failed_device = p["device"]
                else:
                    return None, "Väärä koodi."
            else:
                name = p["device"]
                self._pair = None
                msg = ""
        if failed_device is not None:
            self.pair_finished.emit(False, failed_device)
            return None, msg
        tok = secrets.token_urlsafe(24)
        devs = self.devices()
        devs.append({"token": tok, "name": name, "added": time.strftime("%d.%m.%Y")})
        self._save_devices(devs)
        self.pair_finished.emit(True, name)
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
                elif u.path in ("/api/browse", "/api/library", "/api/album", "/api/radio"):
                    name = u.path.rsplit("/", 1)[-1]
                    fn = owner.providers.get("radio_search" if name == "radio" else name)
                    if fn is None:
                        self._send(404, {})
                        return
                    arg = lambda k: q.get(k, [""])[0]  # noqa: E731
                    try:
                        if name == "browse":
                            res = fn(arg("path"))
                        elif name == "album":
                            res = fn(arg("artist"), arg("album"))
                        elif name == "radio":
                            res = fn(arg("q"))
                        else:
                            res = fn()
                        self._send(200, res)
                    except Exception as e:
                        self._send(500, {"error": str(e)})
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
                    ok, err = owner.start_pairing(str(data.get("device", "")))
                    self._send(200 if ok else 403, {"ok": True} if ok else {"error": err})
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
    """Näytetään, kun puhelin pyytää laiteparia: ensin Salli / Estä, sitten koodi."""

    def __init__(self, server, pid, device, parent=None):
        super().__init__(parent)
        self.server = server
        self.pid = pid
        self.setWindowTitle("Laitepari")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        lay = QVBoxLayout(self)
        self.title = QLabel(f"<b>{html.escape(device)}</b> haluaa ohjata tätä tietokonetta.")
        self.title.setTextFormat(Qt.RichText)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        self.info = QLabel("Kaukosäädin voi ohjata soitinta sekä tietokoneen hiirtä ja näppäimistöä.\n"
                           "Salli vain, jos aloitit laiteparin itse omalla puhelimellasi.")
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setWordWrap(True)
        self.code = QLabel()
        self.code.setAlignment(Qt.AlignCenter)
        self.code.setStyleSheet("font-size: 40pt; font-weight: bold; letter-spacing: 6px; padding: 10px 24px;")
        self.code.hide()
        self.deny_btn = QPushButton("Estä")
        self.deny_btn.clicked.connect(self.close)
        self.allow_btn = QPushButton("Salli")
        self.allow_btn.setDefault(False)
        self.allow_btn.setAutoDefault(False)
        self.allow_btn.clicked.connect(self._allow)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(self.deny_btn)
        btns.addWidget(self.allow_btn)
        for w in (self.title, self.info, self.code):
            lay.addWidget(w)
        lay.addLayout(btns)
        self.setMinimumWidth(420)

    def _allow(self):
        code = self.server.approve_pairing(self.pid)
        if code is None:
            self.info.setText("Pyyntö ehti vanhentua. Aloita laitepari puhelimesta uudelleen.")
            self.allow_btn.hide()
            self.deny_btn.setText("Sulje")
            return
        self.code.setText(" ".join([code[:3], code[3:]]))
        self.code.show()
        self.info.setText("Syötä tämä koodi puhelimeen. Koodi on voimassa 3 minuuttia.")
        self.allow_btn.hide()
        self.deny_btn.setText("Peru")

    def closeEvent(self, e):
        # Ikkunan sulkeminen (Estä, Peru, rasti) mitätöi juuri tämän pyynnön.
        self.server.deny_pairing(self.pid)
        super().closeEvent(e)


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

    def showEvent(self, e):
        self.server.pairing_open = True
        super().showEvent(e)

    def hideEvent(self, e):
        self.server.pairing_open = False
        super().hideEvent(e)

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
                "<b>Android-sovellus:</b> pidä tämä ikkuna auki ja avaa Mediasoitin-kaukosäädin puhelimessa, "
                "niin se löytää tämän koneen itse. Uutta laiteparia muodostettaessa tähän ruutuun tulee pyyntö: "
                "paina <i>Salli</i> ja syötä puhelimeen näkyviin tuleva koodi. Laiteparia voi muodostaa vain, "
                "kun tämä ikkuna on auki.")
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
