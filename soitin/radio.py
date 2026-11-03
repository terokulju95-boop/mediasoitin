"""Netradio: suomalaiset asemat radio-browser.info-hakemistosta + omat suosikit."""
import json
from urllib.parse import urlencode

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QToolButton, QVBoxLayout, QWidget, QApplication)

# Hakemistolla on useita palvelimia; jos yksi ei vastaa, kokeillaan seuraavaa.
SERVERS = ["https://de1.api.radio-browser.info", "https://fi1.api.radio-browser.info",
           "https://nl1.api.radio-browser.info", "https://at1.api.radio-browser.info"]
USER_AGENT = b"Mediasoitin/1.4"


def search_stations(query="", limit=120):
    """Hakee asemia radio-browser.info:sta (ei Qt:ta, käytetään kaukosäätimen palvelimelta).
    Tyhjä haku = suosituimmat suomalaiset asemat."""
    import urllib.request
    params = ({"name": query, "hidebroken": "true", "order": "clickcount", "reverse": "true", "limit": limit}
              if query else {"countrycode": "FI", "hidebroken": "true", "order": "clickcount",
                             "reverse": "true", "limit": limit})
    for server in SERVERS:
        try:
            req = urllib.request.Request(f"{server}/json/stations/search?{urlencode(params)}",
                                         headers={"User-Agent": USER_AGENT.decode()})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            seen, out = set(), []
            for d in data:
                st = RadioPanel._station(d)
                if st["url"] and st["name"] and st["name"].lower() not in seen:
                    seen.add(st["name"].lower())
                    out.append(st)
            return out
        except Exception:
            continue
    return None


class StationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lisää oma asema")
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://… (striimin osoite)")
        f = QFormLayout(self)
        f.addRow("Nimi:", self.name)
        f.addRow("Osoite:", self.url)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Lisää")
        b.button(QDialogButtonBox.Cancel).setText("Peruuta")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        f.addRow(b)
        self.resize(460, 120)


class RadioPanel(QWidget):
    play = Signal(str, str)      # osoite, aseman nimi

    def __init__(self, accent="#D35400", parent=None):
        super().__init__(parent)
        self.accent = accent
        self.settings = QSettings("Mediasoitin", "Mediasoitin")
        self.net = QNetworkAccessManager(self)
        self.stations = []          # hakemiston asemat
        self.logos = {}             # osoite -> QPixmap
        self._logo_req = set()
        self._server = 0
        self.loaded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Hae asemaa (Enter hakee kaikista maista)…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.filter_timer.start())
        self.search.returnPressed.connect(self.search_world)
        self.filter_timer = QTimer(self, singleShot=True, interval=150, timeout=self.rebuild)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(self._activate)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.status = QLabel("")
        self.status.setObjectName("pathLabel")
        self.status.setWordWrap(True)
        add = QToolButton(text="+ Oma asema")
        add.setFocusPolicy(Qt.NoFocus)
        add.clicked.connect(self.add_custom)
        refresh = QToolButton(text="Päivitä")
        refresh.setFocusPolicy(Qt.NoFocus)
        refresh.clicked.connect(self.load)
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 0)
        row.addWidget(add)
        row.addWidget(refresh)
        row.addStretch()
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.status)
        lay.addLayout(row)

    # ---------------------------------------------------------- Suosikit
    def favorites(self):
        try:
            return json.loads(self.settings.value("radio/favorites", "[]", type=str))
        except Exception:
            return []

    def _save_favorites(self, favs):
        self.settings.setValue("radio/favorites", json.dumps(favs, ensure_ascii=False))
        self.rebuild()

    def is_favorite(self, url):
        return any(f["url"] == url for f in self.favorites())

    def toggle_favorite(self, st):
        favs = self.favorites()
        if any(f["url"] == st["url"] for f in favs):
            favs = [f for f in favs if f["url"] != st["url"]]
        else:
            favs.append({"name": st["name"], "url": st["url"], "favicon": st.get("favicon", ""),
                         "info": st.get("info", "")})
        self._save_favorites(favs)

    def add_custom(self):
        d = StationDialog(self)
        if d.exec() and d.url.text().strip():
            url = d.url.text().strip()
            favs = self.favorites()
            favs.append({"name": d.name.text().strip() or url, "url": url, "favicon": "", "info": "Oma asema"})
            self._save_favorites(favs)

    # ---------------------------------------------------------- Haku
    def ensure_loaded(self):
        if not self.loaded:
            self.load()

    def _get(self, path, params, handler):
        url = QUrl(f"{SERVERS[self._server]}{path}?{urlencode(params)}")
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", USER_AGENT)
        req.setTransferTimeout(10000)
        reply = self.net.get(req)
        reply.finished.connect(lambda: self._done(reply, path, params, handler))

    def _done(self, reply, path, params, handler):
        reply.deleteLater()
        if reply.error() != QNetworkReply.NoError:
            if self._server < len(SERVERS) - 1:
                self._server += 1
                self._get(path, params, handler)
            else:
                self._server = 0
                self.status.setText("Asemalistaa ei saatu ladattua. Tarkista nettiyhteys ja paina Päivitä.")
            return
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
        except Exception:
            data = []
        handler(data)

    @staticmethod
    def _station(d):
        info = " · ".join(x for x in (
            (d.get("codec") or "").upper(),
            f"{d['bitrate']} kbit/s" if d.get("bitrate") else "",
            (d.get("tags") or "").split(",")[0]) if x)
        return {"name": (d.get("name") or "").strip(), "url": d.get("url_resolved") or d.get("url"),
                "favicon": d.get("favicon") or "", "info": info, "country": d.get("countrycode", "")}

    def load(self):
        self.status.setText("Ladataan suomalaisia asemia…")
        self._get("/json/stations/search", {"countrycode": "FI", "hidebroken": "true",
                                            "order": "clickcount", "reverse": "true", "limit": 400},
                  self._loaded)

    def _loaded(self, data):
        seen, out = set(), []
        for d in data:
            st = self._station(d)
            key = st["name"].lower()
            if st["url"] and st["name"] and key not in seen:
                seen.add(key)
                out.append(st)
        self.stations = out
        self.loaded = True
        self.rebuild()

    def search_world(self):
        q = self.search.text().strip()
        if len(q) < 2:
            return
        self.status.setText(f"Haetaan “{q}” kaikista maista…")
        self._get("/json/stations/search", {"name": q, "hidebroken": "true", "order": "clickcount",
                                            "reverse": "true", "limit": 100},
                  lambda data: self._world_results(q, data))

    def _world_results(self, q, data):
        known = {s["url"] for s in self.stations}
        for d in data:
            st = self._station(d)
            if st["url"] and st["url"] not in known:
                self.stations.append(st)
                known.add(st["url"])
        self.rebuild()

    # ---------------------------------------------------------- Lista
    def rebuild(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        favs = self.favorites()
        fav_urls = {f["url"] for f in favs}

        def add(st, fav):
            text = ("★  " if fav else "") + st["name"]
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, st)
            tip = st.get("info") or ""
            if st.get("country") and st["country"] != "FI":
                tip = f"{tip}  ({st['country']})"
            it.setToolTip(f"{st['name']}\n{tip}\n{st['url']}")
            if fav:
                it.setForeground(QColor(self.accent))
            pm = self.logos.get(st["url"])
            if pm is not None:
                it.setIcon(pm)
            else:
                self._fetch_logo(st)
            self.list.addItem(it)

        shown = 0
        for f in favs:
            if not q or q in f["name"].lower():
                add(f, True)
                shown += 1
        for st in self.stations:
            if st["url"] in fav_urls:
                continue
            if q and q not in st["name"].lower() and q not in st.get("info", "").lower():
                continue
            add(st, False)
            shown += 1
        if self.loaded:
            self.status.setText(f"{shown} asemaa · tuplaklikkaa kuunnellaksesi · hiiren oikea: suosikiksi")

    def _fetch_logo(self, st):
        url = st.get("favicon")
        if not url or st["url"] in self._logo_req or not url.startswith("http"):
            return
        self._logo_req.add(st["url"])
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT)
        req.setTransferTimeout(8000)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        reply = self.net.get(req)

        def done():
            reply.deleteLater()
            if reply.error() == QNetworkReply.NoError:
                pm = QPixmap()
                if pm.loadFromData(bytes(reply.readAll())) and not pm.isNull():
                    self.logos[st["url"]] = pm.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    for i in range(self.list.count()):
                        it = self.list.item(i)
                        if it.data(Qt.UserRole)["url"] == st["url"]:
                            it.setIcon(self.logos[st["url"]])
        reply.finished.connect(done)

    def logo_for(self, url):
        return self.logos.get(url)

    def name_for(self, url):
        for st in self.favorites() + self.stations:
            if st["url"] == url:
                return st["name"]
        return None

    def _activate(self, item):
        st = item.data(Qt.UserRole)
        self.play.emit(st["url"], st["name"])

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        st = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Kuuntele", lambda: self.play.emit(st["url"], st["name"]))
        m.addAction("Poista suosikeista" if self.is_favorite(st["url"]) else "Lisää suosikiksi ★",
                    lambda: self.toggle_favorite(st))
        m.addAction("Kopioi osoite", lambda: QApplication.clipboard().setText(st["url"]))
        m.exec(self.list.viewport().mapToGlobal(pos))
