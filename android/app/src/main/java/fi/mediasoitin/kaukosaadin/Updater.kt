package fi.mediasoitin.kaukosaadin

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Tarkistaa GitHubista, onko sovelluksesta uudempi versio, ja kertoo siitä.
 *
 * Sovellus EI lataa eikä asenna päivitystä itse. Sovellus, joka lataa APK:n internetistä ja avaa
 * asennusikkunan, toimii samoin kuin haittaohjelmat, ja Google Play Protect estää sen. Päivitys avataan
 * siksi selaimessa: selain lataa APK:n ja Android asentaa sen tavalliseen tapaan vanhan päälle.
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
                for (i in 0 until assets.length()) {
                    val a = assets.getJSONObject(i)
                    if (a.optString("name") == ASSET) url = a.optString("browser_download_url")
                }
                // Hyväksytään vain oman repon julkaisut (ei koskaan muita osoitteita).
                if (url.isEmpty() || !url.startsWith("https://github.com/$REPO/releases/download/")) return@Thread
                if (!newer(tag, local)) return@Thread
                main.post {
                    if (activity.isFinishing) return@post
                    AlertDialog.Builder(activity)
                        .setTitle("Päivitys saatavilla")
                        .setMessage("Kaukosäätimestä on uusi versio ${tag.removePrefix("v")} (käytössä $local).\n\n" +
                            "Lataa-napin jälkeen selain lataa päivityksen. Avaa ladattu tiedosto ja paina Asenna. " +
                            "Asetukset ja laitepari säilyvät.")
                        .setPositiveButton("Lataa") { _, _ -> open(activity, url) }
                        .setNegativeButton("Myöhemmin", null)
                        .show()
                }
            } catch (e: Exception) {
                // ei nettiä tai GitHub ei vastaa – ei haittaa
            }
        }.start()
    }

    private fun open(activity: Activity, url: String) {
        try {
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: Exception) {
            AlertDialog.Builder(activity)
                .setTitle("Päivitys")
                .setMessage("Selainta ei voitu avata. Lataa päivitys osoitteesta\nhttps://github.com/$REPO/releases")
                .setPositiveButton("OK", null)
                .show()
        }
    }
}
