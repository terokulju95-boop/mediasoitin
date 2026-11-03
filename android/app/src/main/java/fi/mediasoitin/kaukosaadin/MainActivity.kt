package fi.mediasoitin.kaukosaadin

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputFilter
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var root: FrameLayout
    private var web: WebView? = null
    private var current: Pc? = null
    private val ui = Handler(Looper.getMainLooper())
    private val bg = Executors.newSingleThreadExecutor()

    private val accent = Color.parseColor("#D35400")
    private val text = Color.parseColor("#E6E6E6")
    private val muted = Color.parseColor("#8C8C8C")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        @Suppress("DEPRECATION")
        window.statusBarColor = Color.BLACK
        @Suppress("DEPRECATION")
        window.navigationBarColor = Color.BLACK
        root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)
        setContentView(root)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        connect()
        Updater.check(this)
    }

    override fun onResume() {
        super.onResume()
        val pc = current ?: return
        // Tarkistetaan yhteys: jos tietokoneen osoite on vaihtunut, etsitään se uudelleen.
        bg.execute {
            if (Api.ping(pc.host, pc.port, prefs.token) != 200) ui.post { connect() }
        }
    }

    override fun onDestroy() {
        web?.destroy()
        web = null
        super.onDestroy()
    }

    // ------------------------------------------------------------------ Yhdistäminen
    private fun connect() {
        showStatus("Etsitään tietokonetta…")
        bg.execute {
            var found: Pc? = null
            var revoked = false
            val token = prefs.token
            if (token.isNotEmpty()) {
                if (prefs.host.isNotEmpty()) {
                    when (Api.ping(prefs.host, prefs.port, token)) {
                        200 -> found = Pc(prefs.host, prefs.port, prefs.name, prefs.id)
                        403 -> revoked = true
                    }
                }
                if (found == null && !revoked) {
                    val pc = Discovery.find(this).firstOrNull { it.id == prefs.id }
                    if (pc != null) {
                        when (Api.ping(pc.host, pc.port, token)) {
                            200 -> {
                                prefs.host = pc.host
                                prefs.port = pc.port
                                found = pc
                            }
                            403 -> revoked = true
                        }
                    }
                }
            }
            ui.post {
                when {
                    found != null -> openRemote(found!!)
                    revoked -> {
                        prefs.clear()
                        showSetup("Laitepari on poistettu tietokoneelta. Muodosta uusi laitepari.")
                    }
                    token.isNotEmpty() -> showSetup(
                        "Tietokonetta “${prefs.name}” ei löytynyt. Onko soitin auki ja kaukosäädin " +
                            "käytössä (Näytä → Kaukosäädin puhelimesta)? Onko puhelin samassa wifissä?",
                        keepPairing = true
                    )
                    else -> showSetup(null)
                }
            }
        }
    }

    // ------------------------------------------------------------------ Näkymät
    private fun dp(v: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

    private fun label(s: String, size: Float = 15f, color: Int = text, bold: Boolean = false): TextView {
        val t = TextView(this)
        t.text = s
        t.setTextColor(color)
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
        t.setPadding(0, dp(6), 0, dp(6))
        return t
    }

    private fun button(s: String, primary: Boolean = false, onClick: () -> Unit): Button {
        val b = Button(this)
        b.text = s
        b.isAllCaps = false
        b.setTextColor(if (primary) Color.WHITE else text)
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        val bgd = GradientDrawable()
        bgd.cornerRadius = dp(12).toFloat()
        bgd.setColor(if (primary) accent else Color.parseColor("#161616"))
        b.background = bgd
        b.setPadding(dp(16), dp(14), dp(16), dp(14))
        b.setOnClickListener { onClick() }
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.topMargin = dp(10)
        b.layoutParams = lp
        return b
    }

    private fun input(hint: String, numeric: Boolean = false): EditText {
        val e = EditText(this)
        e.hint = hint
        e.setHintTextColor(muted)
        e.setTextColor(text)
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, if (numeric) 28f else 17f)
        e.isSingleLine = true
        val bgd = GradientDrawable()
        bgd.cornerRadius = dp(12).toFloat()
        bgd.setColor(Color.parseColor("#0D0D0D"))
        bgd.setStroke(dp(1), Color.parseColor("#2A2A2A"))
        e.background = bgd
        e.setPadding(dp(14), dp(12), dp(14), dp(12))
        if (numeric) {
            e.inputType = InputType.TYPE_CLASS_NUMBER
            e.filters = arrayOf(InputFilter.LengthFilter(4))
            e.gravity = Gravity.CENTER
            e.letterSpacing = 0.4f
        } else {
            e.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.topMargin = dp(10)
        e.layoutParams = lp
        return e
    }

    private fun page(build: (LinearLayout) -> Unit) {
        web?.visibility = View.GONE
        root.findViewWithTag<View>("page")?.let { root.removeView(it) }
        val scroll = ScrollView(this)
        scroll.tag = "page"
        scroll.isFillViewport = true
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(dp(24), dp(40), dp(24), dp(24))
        val logo = label("Mediasoitin", 28f, accent, true)
        col.addView(logo)
        col.addView(label("kaukosäädin", 14f, muted))
        build(col)
        scroll.addView(col)
        root.addView(scroll, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    }

    private fun showStatus(msg: String) {
        page { col ->
            val pb = ProgressBar(this)
            val lp = LinearLayout.LayoutParams(dp(48), dp(48))
            lp.topMargin = dp(40)
            lp.gravity = Gravity.CENTER_HORIZONTAL
            col.addView(pb, lp)
            val t = label(msg, 16f, muted)
            t.gravity = Gravity.CENTER
            col.addView(t)
        }
    }

    private fun showSetup(message: String?, keepPairing: Boolean = false) {
        current = null
        stopService(Intent(this, RemoteService::class.java))
        page { col ->
            if (message != null) col.addView(label(message, 15f, Color.parseColor("#FFB74D")))
            col.addView(label("Valitse tietokone", 18f, text, true).also { it.setPadding(0, dp(18), 0, dp(4)) })
            col.addView(label(
                "Avaa soitin tietokoneella ja ota kaukosäädin käyttöön: Näytä → Kaukosäädin puhelimesta. " +
                    "Puhelimen pitää olla samassa wifissä.", 14f, muted))
            val list = LinearLayout(this)
            list.orientation = LinearLayout.VERTICAL
            col.addView(list)
            val searching = label("Etsitään…", 15f, muted)
            list.addView(searching)
            col.addView(button("Etsi uudelleen") { showSetup(message, keepPairing) })
            if (keepPairing) {
                col.addView(button("Yritä yhdistää uudelleen") { connect() })
            }
            col.addView(label("Tai kirjoita tietokoneen osoite", 14f, muted).also { it.setPadding(0, dp(24), 0, 0) })
            val addr = input("esim. 192.168.1.20")
            col.addView(addr)
            col.addView(button("Yhdistä osoitteeseen") { manual(addr.text.toString()) })

            bg.execute {
                val pcs = Discovery.find(this, 2200)
                ui.post {
                    list.removeAllViews()
                    if (pcs.isEmpty()) {
                        list.addView(label(
                            "Yhtään tietokonetta ei löytynyt. Tarkista, että soitin on auki, kaukosäädin " +
                                "on käytössä ja Windowsin palomuuri sallii Mediasoittimen (yksityiset verkot).",
                            14f, Color.parseColor("#FFB74D")))
                    }
                    for (pc in pcs) {
                        list.addView(button("💻  ${pc.name}   (${pc.host})", primary = true) { pair(pc) })
                    }
                }
            }
        }
    }

    private fun manual(raw: String) {
        val s = raw.trim().removePrefix("http://").trimEnd('/')
        if (s.isEmpty()) return
        val host = s.substringBefore(":")
        val port = s.substringAfter(":", "8765").toIntOrNull() ?: 8765
        showStatus("Yhdistetään osoitteeseen $host…")
        bg.execute {
            val pc = Api.info(host, port)
            ui.post {
                if (pc != null) pair(pc) else showSetup("Osoitteesta $host ei löytynyt soitinta.")
            }
        }
    }

    private fun deviceName(): String {
        val m = Build.MODEL ?: "Puhelin"
        val b = Build.MANUFACTURER ?: ""
        return if (m.lowercase().startsWith(b.lowercase())) m else "$b $m".trim()
    }

    private fun pair(pc: Pc) {
        showStatus("Pyydetään laiteparia…")
        bg.execute {
            val r = Api.request("${Api.base(pc.host, pc.port)}/api/pair/request", "POST",
                JSONObject().put("device", deviceName()))
            ui.post {
                if (r.code == 200) askCode(pc) else showSetup("Tietokone ei vastannut. Yritä uudelleen.")
            }
        }
    }

    private fun askCode(pc: Pc, error: String? = null) {
        page { col ->
            col.addView(label("Laitepari: ${pc.name}", 18f, text, true).also { it.setPadding(0, dp(18), 0, dp(4)) })
            col.addView(label("Tietokoneen ruudulle tuli 4-numeroinen koodi. Kirjoita se tähän.", 15f, muted))
            if (error != null) col.addView(label(error, 15f, Color.parseColor("#FFB74D")))
            val code = input("0000", numeric = true)
            col.addView(code)
            val go = button("Yhdistä", primary = true) { confirm(pc, code.text.toString()) }
            col.addView(go)
            col.addView(button("Peruuta") { showSetup(null) })
            code.setOnEditorActionListener { _, actionId, _ ->
                if (actionId == EditorInfo.IME_ACTION_DONE) {
                    confirm(pc, code.text.toString()); true
                } else false
            }
            code.requestFocus()
        }
    }

    private fun confirm(pc: Pc, code: String) {
        if (code.length != 4) return
        showStatus("Yhdistetään…")
        bg.execute {
            val r = Api.request("${Api.base(pc.host, pc.port)}/api/pair/confirm", "POST",
                JSONObject().put("code", code).put("device", deviceName()))
            val o = r.json()
            ui.post {
                val token = o?.optString("token") ?: ""
                if (r.code == 200 && token.isNotEmpty()) {
                    val real = Pc(pc.host, o!!.optInt("port", pc.port), o.optString("name", pc.name),
                        o.optString("id", pc.id))
                    prefs.save(real, token)
                    openRemote(real)
                } else if (o?.optString("error")?.contains("Väärä") == true) {
                    askCode(pc, "Väärä koodi. Tarkista tietokoneen ruudulta.")
                } else {
                    showSetup(o?.optString("error")?.ifEmpty { null } ?: "Laitepari epäonnistui.")
                }
            }
        }
    }

    // ------------------------------------------------------------------ Kaukosäädin
    @SuppressLint("SetJavaScriptEnabled")
    private fun openRemote(pc: Pc) {
        current = pc
        root.findViewWithTag<View>("page")?.let { root.removeView(it) }
        val w = web ?: WebView(this).also { v ->
            v.setBackgroundColor(Color.BLACK)
            v.settings.javaScriptEnabled = true
            v.settings.domStorageEnabled = true
            v.settings.mediaPlaybackRequiresUserGesture = true
            v.isVerticalScrollBarEnabled = false
            v.webViewClient = WebViewClient()
            v.webChromeClient = WebChromeClient()
            v.addJavascriptInterface(Bridge(), "Android")
            root.addView(v, 0, FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            web = v
        }
        w.visibility = View.VISIBLE
        w.loadUrl("${Api.base(pc.host, pc.port)}/?k=${prefs.token}&app=1")
        val svc = Intent(this, RemoteService::class.java)
        svc.action = RemoteService.ACTION_START
        svc.putExtra("host", pc.host)
        svc.putExtra("port", pc.port)
        svc.putExtra("token", prefs.token)
        try {
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(svc) else startService(svc)
        } catch (e: Exception) {
            // ilmoitus ei ole välttämätön kaukosäätimen käytölle
        }
    }

    /** Puhelimen äänenvoimakkuusnapit säätävät soittimen äänenvoimakkuutta. */
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val pc = current
        if (pc != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            val step = if (keyCode == KeyEvent.KEYCODE_VOLUME_UP) 5 else -5
            val token = prefs.token
            bg.execute { Api.cmd(pc.host, pc.port, token, "volume_rel", step) }
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (current != null && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            return true
        }
        return super.onKeyUp(keyCode, event)
    }

    inner class Bridge {
        @JavascriptInterface
        fun forget() {
            ui.post {
                prefs.clear()
                web?.loadUrl("about:blank")
                showSetup(null)
            }
        }
    }
}
