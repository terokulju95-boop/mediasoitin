package fi.mediasoitin.kaukosaadin

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Tarkistaa GitHubista, onko sovelluksesta uudempi versio. Lataa sen sovelluksen sisällä
 * ja avaa Androidin asennusikkunan – selainta ei tarvita.
 */
object Updater {
    private const val REPO = "terokulju95-boop/mediasoitin"
    private const val ASSET = "Mediasoitin-kaukosaadin.apk"
    private val main = Handler(Looper.getMainLooper())

    private fun parse(v: String): List<Int> {
        val parts = v.trim().removePrefix("v").split(".").map { p -> p.filter { it.isDigit() }.toIntOrNull() ?: 0 }
        return parts + List((3 - parts.size).coerceAtLeast(0)) { 0 }
    }

    private fun newer(remote: String, local: String): Boolean {
        val a = parse(remote)
        val b = parse(local)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    private fun localVersion(activity: Activity): String = try {
        @Suppress("DEPRECATION")
        activity.packageManager.getPackageInfo(activity.packageName, 0).versionName ?: "0"
    } catch (e: Exception) {
        "0"
    }

    fun check(activity: Activity) {
        val local = localVersion(activity)
        Thread {
            try {
                val c = URL("https://api.github.com/repos/$REPO/releases/latest").openConnection() as HttpURLConnection
                c.connectTimeout = 6000
                c.readTimeout = 6000
                c.setRequestProperty("Accept", "application/vnd.github+json")
                c.setRequestProperty("User-Agent", "Mediasoitin-kaukosaadin")
                if (c.responseCode != 200) return@Thread
                val o = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
                val tag = o.optString("tag_name")
                val assets = o.optJSONArray("assets") ?: return@Thread
                var url = ""
                var size = 0L
                for (i in 0 until assets.length()) {
                    val a = assets.getJSONObject(i)
                    if (a.optString("name") == ASSET) {
                        url = a.optString("browser_download_url")
                        size = a.optLong("size", 0L)
                    }
                }
                if (url.isEmpty() || !newer(tag, local)) return@Thread
                main.post {
                    if (activity.isFinishing) return@post
                    AlertDialog.Builder(activity)
                        .setTitle("Päivitys saatavilla")
                        .setMessage("Kaukosäätimestä on uusi versio ${tag.removePrefix("v")} (käytössä $local).\n\n" +
                            "Asetukset ja laitepari säilyvät.")
                        .setPositiveButton("Päivitä") { _, _ -> download(activity, url, size) }
                        .setNegativeButton("Myöhemmin", null)
                        .show()
                }
            } catch (e: Exception) {
                // ei nettiä tai GitHub ei vastaa – ei haittaa
            }
        }.start()
    }

    private fun download(activity: Activity, url: String, size: Long) {
        val bar = ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal)
        bar.setMax(100)
        val label = TextView(activity)
        label.text = "Ladataan…"
        val box = LinearLayout(activity)
        box.orientation = LinearLayout.VERTICAL
        val pad = (20 * activity.resources.displayMetrics.density).toInt()
        box.setPadding(pad, pad, pad, pad / 2)
        box.addView(label)
        box.addView(bar)
        val dialog = AlertDialog.Builder(activity)
            .setTitle("Päivitetään kaukosäädintä")
            .setView(box)
            .setCancelable(false)
            .show()

        Thread {
            try {
                val dir = File(activity.cacheDir, "updates")
                dir.mkdirs()
                dir.listFiles()?.forEach { it.delete() }
                val file = File(dir, "kaukosaadin.apk")
                val c = URL(url).openConnection() as HttpURLConnection
                c.instanceFollowRedirects = true
                c.connectTimeout = 15000
                c.readTimeout = 30000
                c.setRequestProperty("User-Agent", "Mediasoitin-kaukosaadin")
                val total = if (c.contentLengthLong > 0) c.contentLengthLong else size
                c.inputStream.use { input ->
                    file.outputStream().use { out ->
                        val buf = ByteArray(64 * 1024)
                        var done = 0L
                        var last = -1
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            done += n
                            val pct = if (total > 0) (done * 100 / total).toInt() else 0
                            if (pct != last) {
                                last = pct
                                val mb = done / 1_048_576.0
                                main.post {
                                    bar.setProgress(pct)
                                    label.text = String.format("Ladataan… %.1f Mt", mb)
                                }
                            }
                        }
                    }
                }
                main.post {
                    dialog.dismiss()
                    install(activity, file)
                }
            } catch (e: Exception) {
                main.post {
                    dialog.dismiss()
                    AlertDialog.Builder(activity)
                        .setTitle("Päivitys epäonnistui")
                        .setMessage("Latausta ei saatu valmiiksi. Tarkista nettiyhteys ja yritä uudelleen.")
                        .setPositiveButton("OK", null)
                        .show()
                }
            }
        }.start()
    }

    private fun install(activity: Activity, file: File) {
        if (activity.isFinishing) return
        // Android 8+: sovellus tarvitsee kerran luvan asentaa päivityksiä.
        if (Build.VERSION.SDK_INT >= 26 && !activity.packageManager.canRequestPackageInstalls()) {
            AlertDialog.Builder(activity)
                .setTitle("Salli päivitysten asennus")
                .setMessage("Android kysyy kerran luvan, jotta kaukosäädin voi asentaa omat päivityksensä.\n\n" +
                    "Paina Asetukset, ota käyttöön “Salli tästä lähteestä” ja palaa takaisin. Paina sitten Asenna.")
                .setPositiveButton("Asetukset") { _, _ ->
                    try {
                        activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:${activity.packageName}")))
                    } catch (e: Exception) {
                        // vanhoissa laitteissa asetus on muualla
                    }
                    askInstall(activity, file)
                }
                .setNegativeButton("Peruuta", null)
                .show()
            return
        }
        openInstaller(activity, file)
    }

    private fun askInstall(activity: Activity, file: File) {
        main.postDelayed({
            if (activity.isFinishing) return@postDelayed
            AlertDialog.Builder(activity)
                .setTitle("Asenna päivitys")
                .setMessage("Kun olet antanut luvan, paina Asenna.")
                .setPositiveButton("Asenna") { _, _ -> install(activity, file) }
                .setNegativeButton("Peruuta", null)
                .show()
        }, 800)
    }

    private fun openInstaller(activity: Activity, file: File) {
        try {
            val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", file)
            val i = Intent(Intent.ACTION_VIEW)
            i.setDataAndType(uri, "application/vnd.android.package-archive")
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(i)
        } catch (e: Exception) {
            AlertDialog.Builder(activity)
                .setTitle("Päivitys")
                .setMessage("Asennusikkunaa ei voitu avata: ${e.message}")
                .setPositiveButton("OK", null)
                .show()
        }
    }
}
