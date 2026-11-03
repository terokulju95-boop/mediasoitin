package fi.mediasoitin.kaukosaadin

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.media.VolumeProviderCompat
import java.util.concurrent.Executors

/**
 * Pitää yhteyttä soittimeen taustalla: ohjaimet ilmoituksissa ja lukitusnäytöllä,
 * ja äänenvoimakkuusnapit toimivat myös näytön ollessa lukittuna.
 */
class RemoteService : Service() {

    companion object {
        const val ACTION_START = "fi.mediasoitin.kaukosaadin.START"
        const val ACTION_STOP = "fi.mediasoitin.kaukosaadin.STOP"
        private const val CHANNEL = "kaukosaadin"
        private const val NOTIF_ID = 7
        private const val POLL_MS = 1500L
    }

    private lateinit var session: MediaSessionCompat
    private lateinit var volumeProvider: VolumeProviderCompat
    private val main = Handler(Looper.getMainLooper())
    private val bg = Executors.newSingleThreadExecutor()
    private var host = ""
    private var port = 8765
    private var token = ""
    private var running = false

    private var title = "Mediasoitin"
    private var artist = ""
    private var paused = true
    private var positionMs = 0L
    private var durationMs = 0L
    private var coverId = ""
    private var cover: Bitmap? = null
    private var failures = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= 26) {
            val ch = NotificationChannel(CHANNEL, "Kaukosäädin", NotificationManager.IMPORTANCE_LOW)
            ch.description = "Soittimen ohjaimet ilmoituksissa ja lukitusnäytöllä"
            ch.setShowBadge(false)
            getSystemService(NotificationManager::class.java).createNotificationChannel(ch)
        }
        session = MediaSessionCompat(this, "Mediasoitin")
        session.setCallback(object : MediaSessionCompat.Callback() {
            override fun onPlay() = send("play", null)
            override fun onPause() = send("pause", null)
            override fun onSkipToNext() = send("next", null)
            override fun onSkipToPrevious() = send("prev", null)
            override fun onSeekTo(pos: Long) = send("seek_abs", pos / 1000.0)
            override fun onStop() = stopEverything()
        })
        volumeProvider = object : VolumeProviderCompat(VolumeProviderCompat.VOLUME_CONTROL_ABSOLUTE, 100, 100) {
            override fun onSetVolumeTo(volume: Int) {
                currentVolume = volume.coerceIn(0, 100)
                send("volume", currentVolume)
            }

            override fun onAdjustVolume(direction: Int) {
                if (direction == 0) return
                currentVolume = (currentVolume + direction * 5).coerceIn(0, 100)
                send("volume", currentVolume)
            }
        }
        session.setPlaybackToRemote(volumeProvider)
        session.isActive = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                host = intent.getStringExtra("host") ?: host
                port = intent.getIntExtra("port", port)
                token = intent.getStringExtra("token") ?: token
                val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0
                ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(), type)
                if (!running) {
                    running = true
                    main.post(poller)
                }
            }
            "toggle" -> send("toggle", null)
            "next" -> send("next", null)
            "prev" -> send("prev", null)
            ACTION_STOP -> stopEverything()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        main.removeCallbacksAndMessages(null)
        session.isActive = false
        session.release()
        bg.shutdownNow()
        super.onDestroy()
    }

    private fun stopEverything() {
        running = false
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun send(cmd: String, value: Any?) {
        if (host.isEmpty()) return
        val h = host
        val p = port
        val t = token
        bg.execute {
            Api.cmd(h, p, t, cmd, value)
            main.postDelayed({ poll() }, 150)
        }
    }

    private val poller = object : Runnable {
        override fun run() {
            if (!running) return
            poll()
            main.postDelayed(this, POLL_MS)
        }
    }

    private fun poll() {
        if (host.isEmpty()) return
        val h = host
        val p = port
        val t = token
        bg.execute {
            val o = Api.request("${Api.base(h, p)}/api/state?k=$t", timeoutMs = 2000).json()
            var newCover: Bitmap? = null
            var coverChanged = false
            if (o != null) {
                val cid = o.optString("cover_id", "")
                if (cid != coverId) {
                    coverChanged = true
                    if (cid.isNotEmpty()) {
                        val r = Api.request("${Api.base(h, p)}/api/cover?k=$t&v=$cid", timeoutMs = 3000)
                        if (r.code == 200) newCover = BitmapFactory.decodeByteArray(r.body, 0, r.body.size)
                    }
                }
            }
            main.post {
                if (o == null) {
                    failures++
                    if (failures == 3) {
                        title = "Ei yhteyttä soittimeen"
                        artist = "Avaa sovellus yhdistääksesi uudelleen"
                        update()
                    }
                    return@post
                }
                failures = 0
                title = o.optString("title", "").ifEmpty { "Mediasoitin" }
                artist = o.optString("artist", "")
                paused = o.optBoolean("paused", true)
                positionMs = (o.optDouble("pos", 0.0) * 1000).toLong()
                durationMs = (o.optDouble("dur", 0.0) * 1000).toLong()
                if (coverChanged) {
                    coverId = o.optString("cover_id", "")
                    cover = newCover
                }
                volumeProvider.currentVolume = o.optDouble("volume", 100.0).toInt().coerceIn(0, 100)
                update()
            }
        }
    }

    private fun update() {
        val md = MediaMetadataCompat.Builder()
            .putString(MediaMetadataCompat.METADATA_KEY_TITLE, title)
            .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, artist)
            .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, durationMs)
        cover?.let { md.putBitmap(MediaMetadataCompat.METADATA_KEY_ALBUM_ART, it) }
        session.setMetadata(md.build())
        val actions = PlaybackStateCompat.ACTION_PLAY or PlaybackStateCompat.ACTION_PAUSE or
            PlaybackStateCompat.ACTION_PLAY_PAUSE or PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
            PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or PlaybackStateCompat.ACTION_SEEK_TO or
            PlaybackStateCompat.ACTION_STOP
        val state = PlaybackStateCompat.Builder()
            .setActions(actions)
            .setState(
                if (paused) PlaybackStateCompat.STATE_PAUSED else PlaybackStateCompat.STATE_PLAYING,
                positionMs, if (paused) 0f else 1f
            )
            .build()
        session.setPlaybackState(state)
        try {
            NotificationManagerCompat.from(this).notify(NOTIF_ID, buildNotification())
        } catch (e: SecurityException) {
            // ilmoituslupaa ei ole annettu
        }
    }

    private fun action(name: String, code: Int): PendingIntent {
        val i = Intent(this, RemoteService::class.java)
        i.action = name
        return PendingIntent.getService(this, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun buildNotification(): android.app.Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val style = androidx.media.app.NotificationCompat.MediaStyle()
            .setMediaSession(session.sessionToken)
            .setShowActionsInCompactView(0, 1, 2)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notif)
            .setContentTitle(title)
            .setContentText(artist)
            .setLargeIcon(cover)
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .setShowWhen(false)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(R.drawable.ic_prev, "Edellinen", action("prev", 1))
            .addAction(if (paused) R.drawable.ic_play else R.drawable.ic_pause, "Toista / tauko", action("toggle", 2))
            .addAction(R.drawable.ic_next, "Seuraava", action("next", 3))
            .addAction(R.drawable.ic_close, "Sulje", action(ACTION_STOP, 4))
            .setStyle(style)
            .build()
    }
}
