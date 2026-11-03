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

/** Tarkistaa GitHubista, onko sovelluksesta uudempi versio, ja tarjoaa latausta. */
object Updater {
    private const val REPO = "terokulju95-boop/mediasoitin"
    private const val ASSET = "Mediasoitin-kaukosaadin.apk"

    private fun parse(v: String): List<Int> =
        v.trim().removePrefix("v").split(".").map { part -> part.filter { it.isDigit() }.toIntOrNull() ?: 0 }
            .let { it + List((3 - it.size).coerceAtLeast(0)) { 0 } }

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

    fun check(activity: Activity) {
        val local = try {
            @Suppress("DEPRECATION")
            activity.packageManager.getPackageInfo(activity.packageName, 0).versionName ?: "0"
        } catch (e: Exception) {
            "0"
        }
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
                if (url.isEmpty() || !newer(tag, local)) return@Thread
                Handler(Looper.getMainLooper()).post {
                    if (activity.isFinishing) return@post
                    AlertDialog.Builder(activity)
                        .setTitle("Päivitys saatavilla")
                        .setMessage("Kaukosäätimestä on uusi versio ${tag.removePrefix("v")} (käytössä $local).\n\n" +
                            "Lataa ja asenna se – asetukset ja laitepari säilyvät.")
                        .setPositiveButton("Lataa") { _, _ ->
                            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        }
                        .setNegativeButton("Myöhemmin", null)
                        .show()
                }
            } catch (e: Exception) {
                // ei nettiä tai GitHub ei vastaa – ei haittaa
            }
        }.start()
    }
}
