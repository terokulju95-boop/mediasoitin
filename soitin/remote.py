"""Kaukosäädin puhelimesta.

Soitin käynnistää pienen www-palvelimen kotiverkkoon. Puhelimen selaimella
avataan QR-koodin osoite, ja toistoa ohjataan sohvalta. Osoitteessa on
satunnainen avain, joten muut samassa verkossa eivät pääse ohjaamaan soitinta.
"""
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)


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


class RemoteServer(QObject):
    command = Signal(str, object)     # komento, arvo (käsitellään käyttöliittymäsäikeessä)

    def __init__(self, parent=None):
        super().__init__(parent)
        qs = QSettings("Mediasoitin", "Mediasoitin")
        self.token = qs.value("remote/token", "", type=str)
        if not self.token:
            self.token = secrets.token_urlsafe(8)
            qs.setValue("remote/token", self.token)
        self.state = {}        # käyttöliittymä päivittää tätä
        self.cover = None      # (mime, tavut)
        self.httpd = None
        self.port = None
        self.error = ""

    @property
    def running(self):
        return self.httpd is not None

    def url(self):
        return f"http://{local_ip()}:{self.port}/?k={self.token}"

    def start(self, port):
        if self.httpd:
            return True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok_token(self, q):
                return q.get("k", [""])[0] == owner.token

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if not self._ok_token(q):
                    self._send(403, "<h1>Väärä tai puuttuva avain</h1><p>Skannaa QR-koodi soittimesta uudelleen.</p>",
                               "text/html; charset=utf-8")
                    return
                if u.path == "/":
                    self._send(200, PAGE, "text/html; charset=utf-8")
                elif u.path == "/api/state":
                    self._send(200, json.dumps(owner.state, ensure_ascii=False))
                elif u.path == "/api/cover":
                    if owner.cover:
                        self._send(200, owner.cover[1], owner.cover[0])
                    else:
                        self._send(404, "{}")
                else:
                    self._send(404, "{}")

            def do_POST(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if not self._ok_token(q) or u.path != "/api/cmd":
                    self._send(403, "{}")
                    return
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), 10000)
                    data = json.loads(self.rfile.read(n) or b"{}")
                    owner.command.emit(str(data.get("cmd", "")), data.get("value"))
                    self._send(200, '{"ok":true}')
                except Exception:
                    self._send(400, "{}")

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
        return True

    def stop(self):
        if self.httpd:
            h = self.httpd
            self.httpd = None
            threading.Thread(target=lambda: (h.shutdown(), h.server_close()), daemon=True).start()


def qr_pixmap(text, size=280):
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


class RemoteDialog(QDialog):
    def __init__(self, server: RemoteServer, cfg, parent=None):
        super().__init__(parent)
        self.server = server
        self.cfg = cfg
        self.setWindowTitle("Kaukosäädin puhelimesta")
        self.setMinimumWidth(420)
        self.enable = QCheckBox("Kaukosäädin käytössä")
        self.enable.setChecked(server.running)
        self.enable.toggled.connect(self._toggle)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.url = QLabel()
        self.url.setAlignment(Qt.AlignCenter)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("pathLabel")
        new_key = QPushButton("Vaihda avain")
        new_key.setToolTip("Luo uusi QR-koodi. Vanhalla koodilla avatut puhelimet eivät enää pääse ohjaamaan.")
        new_key.clicked.connect(self._new_key)
        close = QPushButton("Sulje")
        close.setDefault(True)
        close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(new_key)
        btns.addStretch()
        btns.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.enable)
        lay.addWidget(self.qr)
        lay.addWidget(self.url)
        lay.addWidget(self.help)
        lay.addLayout(btns)
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
        QSettings("Mediasoitin", "Mediasoitin").setValue("remote/token", self.server.token)
        self._refresh()

    def _refresh(self):
        if self.server.running:
            url = self.server.url()
            pm = qr_pixmap(url)
            if pm:
                self.qr.setPixmap(pm)
            self.qr.show()
            self.url.setText(url)
            self.help.setText(
                "1. Yhdistä puhelin samaan wifiin kuin tämä tietokone.\n"
                "2. Avaa puhelimen kamera ja osoita QR-koodia, tai kirjoita osoite selaimeen.\n"
                "3. Vinkki: lisää sivu puhelimen aloitusnäyttöön, niin kaukosäädin on aina käden ulottuvilla.\n\n"
                "Jos sivu ei aukea, salli Mediasoitin Windowsin palomuurissa "
                "(kysytään ensimmäisellä kerralla – valitse Yksityiset verkot).")
        else:
            self.qr.hide()
            self.url.setText(self.server.error or "")
            self.help.setText("Ota kaukosäädin käyttöön, niin tähän tulee QR-koodi puhelimella skannattavaksi.")
        self.adjustSize()


# ------------------------------------------------------------------ Mobiilisivu
PAGE = r"""<!DOCTYPE html>
<html lang="fi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="theme-color" content="#000000">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Mediasoitin</title>
<style>
:root{--a:#D35400;--t:#E6E6E6;--m:#8C8C8C;--s:#121212}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#000;color:var(--t);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 display:flex;flex-direction:column;min-height:100vh;user-select:none}
header{padding:14px 16px 4px;color:var(--m);font-size:13px;letter-spacing:1px;text-transform:uppercase}
#cover{width:min(62vw,280px);aspect-ratio:1;margin:12px auto 0;border-radius:14px;background:#141414 center/cover no-repeat;
 display:flex;align-items:center;justify-content:center;font-size:64px;color:var(--a)}
#title{font-size:21px;font-weight:700;text-align:center;margin:18px 16px 4px;line-height:1.25}
#artist{color:var(--a);text-align:center;font-size:16px;min-height:20px;margin:0 16px}
.time{display:flex;justify-content:space-between;color:var(--m);font-size:13px;margin:18px 22px 4px;font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;width:calc(100% - 44px);margin:0 22px;height:6px;border-radius:3px;
 background:#2a2a2a;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:22px;height:22px;border-radius:50%;background:var(--a)}
input[type=range]::-moz-range-thumb{width:22px;height:22px;border-radius:50%;background:var(--a);border:0}
.row{display:flex;justify-content:center;align-items:center;gap:14px;margin:18px 0}
button{background:var(--s);color:var(--t);border:0;border-radius:50%;width:62px;height:62px;font-size:22px;display:flex;
 align-items:center;justify-content:center;touch-action:manipulation}
button:active{background:#2a2a2a}
#play{width:84px;height:84px;background:var(--a);color:#fff;font-size:32px}
.small{width:auto;height:44px;border-radius:22px;padding:0 16px;font-size:15px}
.vol{display:flex;align-items:center;gap:10px;margin:8px 22px}
.vol input{margin:0;width:100%}
#list{margin:10px 0 20px;border-top:1px solid #222}
.item{padding:13px 18px;border-bottom:1px solid #161616;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item.cur{color:var(--a);font-weight:700}
#off{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);align-items:center;justify-content:center;
 text-align:center;padding:30px;color:var(--m)}
svg{width:26px;height:26px;fill:currentColor}
</style></head><body>
<header>Mediasoitin · kaukosäädin</header>
<div id="cover">♪</div>
<div id="title">–</div>
<div id="artist"></div>
<div class="time"><span id="pos">0:00</span><span id="dur">0:00</span></div>
<input type="range" id="seek" min="0" max="1000" value="0">
<div class="row">
 <button onclick="cmd('seek',-10)" title="-10 s"><svg viewBox="0 0 24 24"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6 8.5 6V6l-8.5 6z"/></svg></button>
 <button onclick="cmd('prev')"><svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg></button>
 <button id="play" onclick="cmd('toggle')"><svg id="pi" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></button>
 <button onclick="cmd('next')"><svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg></button>
 <button onclick="cmd('seek',10)" title="+10 s"><svg viewBox="0 0 24 24"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg></button>
</div>
<div class="vol"><button class="small" onclick="cmd('mute')" id="mute">🔊</button>
 <input type="range" id="vol" min="0" max="100" value="100"></div>
<div class="row">
 <button class="small" onclick="cmd('fullscreen')">⛶ Koko näyttö</button>
 <button class="small" onclick="cmd('stop')">■ Pysäytä</button>
</div>
<div id="list"></div>
<div id="off">Yhteys soittimeen katkesi.<br><br>Onko soitin auki ja puhelin samassa wifissä?</div>
<script>
const K=new URLSearchParams(location.search).get('k');
const $=id=>document.getElementById(id);
let st={},dragging=false,volDrag=false,lastCover='';
function fmt(s){if(s==null||s<0)return'0:00';s=Math.floor(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
 return h?`${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`:`${m}:${String(x).padStart(2,'0')}`}
async function cmd(c,v){try{await fetch('/api/cmd?k='+K,{method:'POST',body:JSON.stringify({cmd:c,value:v})});setTimeout(poll,150)}catch(e){}}
async function poll(){
 try{const r=await fetch('/api/state?k='+K,{cache:'no-store'});st=await r.json();$('off').style.display='none'}
 catch(e){$('off').style.display='flex';return}
 document.documentElement.style.setProperty('--a',st.accent||'#D35400');
 $('title').textContent=st.title||'Ei toistoa';$('artist').textContent=st.artist||'';
 $('pos').textContent=fmt(st.pos);$('dur').textContent=fmt(st.dur);
 if(!dragging)$('seek').value=st.dur?Math.round(1000*st.pos/st.dur):0;
 if(!volDrag)$('vol').value=st.volume??100;
 $('mute').textContent=st.mute?'🔇':'🔊';
 $('pi').innerHTML=st.paused?'<path d="M8 5v14l11-7z"/>':'<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
 if(st.cover_id!==lastCover){lastCover=st.cover_id;
  if(st.cover_id){$('cover').style.backgroundImage=`url(/api/cover?k=${K}&v=${st.cover_id})`;$('cover').textContent=''}
  else{$('cover').style.backgroundImage='';$('cover').textContent=st.video?'▶':'♪'}}
 const L=$('list');const items=st.playlist||[];
 if(L.dataset.sig!==JSON.stringify([items,st.current])){L.dataset.sig=JSON.stringify([items,st.current]);
  L.innerHTML='';items.forEach((n,i)=>{const d=document.createElement('div');d.className='item'+(i===st.current?' cur':'');
   d.textContent=(i+1)+'. '+n;d.onclick=()=>cmd('play_index',i);L.appendChild(d)})}
}
$('seek').addEventListener('input',()=>{dragging=true;$('pos').textContent=fmt(st.dur*$('seek').value/1000)});
$('seek').addEventListener('change',()=>{cmd('seek_abs',st.dur*$('seek').value/1000);dragging=false});
$('vol').addEventListener('input',()=>{volDrag=true;cmd('volume',+$('vol').value)});
$('vol').addEventListener('change',()=>{volDrag=false});
setInterval(poll,1000);poll();
</script></body></html>"""
