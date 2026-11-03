package fi.mediasoitin.kaukosaadin

import android.content.Context
import android.net.wifi.WifiManager
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.net.URL

/** Löydetty tai tallennettu tietokone, jossa Mediasoitin on käynnissä. */
data class Pc(val host: String, val port: Int, val name: String, val id: String)

/** Laiteparin tiedot tallennetaan puhelimeen, joten koodia ei tarvita uudelleen. */
class Prefs(ctx: Context) {
    private val p = ctx.getSharedPreferences("kaukosaadin", Context.MODE_PRIVATE)

    var host: String
        get() = p.getString("host", "") ?: ""
        set(v) = p.edit().putString("host", v).apply()
    var port: Int
        get() = p.getInt("port", 8765)
        set(v) = p.edit().putInt("port", v).apply()
    var token: String
        get() = p.getString("token", "") ?: ""
        set(v) = p.edit().putString("token", v).apply()
    var name: String
        get() = p.getString("name", "") ?: ""
        set(v) = p.edit().putString("name", v).apply()
    var id: String
        get() = p.getString("id", "") ?: ""
        set(v) = p.edit().putString("id", v).apply()

    fun save(pc: Pc, newToken: String) {
        p.edit()
            .putString("host", pc.host)
            .putInt("port", pc.port)
            .putString("name", pc.name)
            .putString("id", pc.id)
            .putString("token", newToken)
            .apply()
    }

    fun clear() {
        p.edit().clear().apply()
    }
}

object Api {
    class Response(val code: Int, val body: ByteArray) {
        fun json(): JSONObject? = try {
            JSONObject(String(body, Charsets.UTF_8))
        } catch (e: Exception) {
            null
        }
    }

    fun request(url: String, method: String = "GET", body: JSONObject? = null, timeoutMs: Int = 3000): Response {
        return try {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.requestMethod = method
            c.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (body != null) {
                c.doOutput = true
                c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val bytes = stream?.use { it.readBytes() } ?: ByteArray(0)
            c.disconnect()
            Response(code, bytes)
        } catch (e: Exception) {
            Response(-1, ByteArray(0))
        }
    }

    fun base(host: String, port: Int) = "http://$host:$port"

    /** 200 = yhteys ja avain kunnossa, 403 = laitepari poistettu, -1 = ei yhteyttä. */
    fun ping(host: String, port: Int, token: String): Int =
        request("${base(host, port)}/api/state?k=$token", timeoutMs = 2000).code

    fun info(host: String, port: Int): Pc? {
        val o = request("${base(host, port)}/api/info", timeoutMs = 2500).json() ?: return null
        if (o.optString("app") != "mediasoitin") return null
        return Pc(host, o.optInt("port", port), o.optString("name", "Tietokone"), o.optString("id"))
    }

    fun cmd(host: String, port: Int, token: String, cmd: String, value: Any?) {
        val body = JSONObject()
        body.put("cmd", cmd)
        body.put("value", value ?: JSONObject.NULL)
        request("${base(host, port)}/api/cmd?k=$token", "POST", body, 2500)
    }
}

/** Etsii Mediasoittimet kotiverkosta UDP-yleislähetyksellä. */
object Discovery {
    private const val PORT = 41234
    private val MAGIC = "MEDIASOITIN_DISCOVER".toByteArray()

    fun find(ctx: Context, timeoutMs: Long = 1800): List<Pc> {
        val wifi = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val lock = wifi.createMulticastLock("mediasoitin-haku")
        lock.setReferenceCounted(false)
        val found = LinkedHashMap<String, Pc>()
        try {
            lock.acquire()
            DatagramSocket().use { s ->
                s.broadcast = true
                s.soTimeout = 250
                val targets = mutableListOf(InetAddress.getByName("255.255.255.255"))
                subnetBroadcast(wifi)?.let { if (it !in targets) targets.add(it) }
                val end = System.currentTimeMillis() + timeoutMs
                var lastSend = 0L
                while (System.currentTimeMillis() < end) {
                    if (System.currentTimeMillis() - lastSend > 600) {
                        for (t in targets) {
                            try {
                                s.send(DatagramPacket(MAGIC, MAGIC.size, t, PORT))
                            } catch (e: Exception) {
                                // jatketaan muihin osoitteisiin
                            }
                        }
                        lastSend = System.currentTimeMillis()
                    }
                    val buf = ByteArray(2048)
                    val pkt = DatagramPacket(buf, buf.size)
                    try {
                        s.receive(pkt)
                        val o = JSONObject(String(pkt.data, 0, pkt.length, Charsets.UTF_8))
                        if (o.optString("app") == "mediasoitin") {
                            val id = o.optString("id")
                            val host = pkt.address?.hostAddress ?: continue
                            found[id] = Pc(host, o.optInt("port", 8765), o.optString("name", "Tietokone"), id)
                        }
                    } catch (e: SocketTimeoutException) {
                        // odotetaan lisää vastauksia
                    } catch (e: Exception) {
                        // virheellinen vastaus, ohitetaan
                    }
                }
            }
        } catch (e: Exception) {
            // ei verkkoa
        } finally {
            try {
                lock.release()
            } catch (e: Exception) {
                // ei haittaa
            }
        }
        return found.values.toList()
    }

    @Suppress("DEPRECATION")
    private fun subnetBroadcast(wifi: WifiManager): InetAddress? {
        return try {
            val dhcp = wifi.dhcpInfo ?: return null
            if (dhcp.ipAddress == 0) return null
            val mask = if (dhcp.netmask != 0) dhcp.netmask else 0x00FFFFFF
            val bc = (dhcp.ipAddress and mask) or mask.inv()
            val bytes = ByteArray(4) { i -> ((bc shr (i * 8)) and 0xFF).toByte() }
            InetAddress.getByAddress(bytes)
        } catch (e: Exception) {
            null
        }
    }
}
