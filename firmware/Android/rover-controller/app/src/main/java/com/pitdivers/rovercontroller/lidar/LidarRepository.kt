package com.pitdivers.rovercontroller.lidar

import com.pitdivers.rovercontroller.EndpointConfig
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

interface HttpTransport {
    fun get(url: String, timeoutMs: Int): String
    fun post(url: String, timeoutMs: Int): String
}

class UrlConnectionHttpTransport : HttpTransport {
    override fun get(url: String, timeoutMs: Int): String = request(url, "GET", timeoutMs)

    override fun post(url: String, timeoutMs: Int): String = request(url, "POST", timeoutMs)

    private fun request(url: String, method: String, timeoutMs: Int): String {
        val connection = URL(url).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = method
            connection.connectTimeout = timeoutMs
            connection.readTimeout = timeoutMs
            connection.useCaches = false
            val code = connection.responseCode
            val body = (if (code in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IOException("HTTP $code${body.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()}")
            body
        } finally {
            connection.disconnect()
        }
    }
}

class LidarSourceSelector {
    var current: LidarSource = LidarSource.WINDOWS_MAP
        private set
    private var dashboardFailures = 0

    fun recordDashboardSuccess() {
        dashboardFailures = 0
        current = LidarSource.WINDOWS_MAP
    }

    fun recordDashboardFailure(): LidarSource {
        dashboardFailures += 1
        if (dashboardFailures >= DASHBOARD_FAILURES_BEFORE_FALLBACK) {
            current = LidarSource.ROVER_SCAN
        }
        return current
    }

    companion object {
        private const val DASHBOARD_FAILURES_BEFORE_FALLBACK = 3
    }
}

class LidarRepository(
    private val configProvider: () -> EndpointConfig,
    private val transport: HttpTransport = UrlConnectionHttpTransport(),
    private val listener: (LidarFrame) -> Unit
) {
    private val executor = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "retroid-lidar").apply { isDaemon = true }
    }
    private val selector = LidarSourceSelector()
    private val stateLock = Any()
    private var scheduled: ScheduledFuture<*>? = null
    @Volatile private var active = false
    @Volatile private var closed = false
    private var lastFrame: LidarFrame? = null

    fun start() {
        synchronized(stateLock) {
            if (closed || active) return
            active = true
            scheduled = executor.scheduleAtFixedRate(
                { pollInternal { active && !closed } },
                0,
                POLL_INTERVAL_MS,
                TimeUnit.MILLISECONDS
            )
        }
    }

    fun stop() {
        synchronized(stateLock) {
            active = false
            scheduled?.cancel(false)
            scheduled = null
        }
    }

    fun close() {
        synchronized(stateLock) {
            if (closed) return
            closed = true
            active = false
            scheduled?.cancel(false)
            scheduled = null
        }
        executor.shutdownNow()
    }

    fun pollOnce(): LidarFrame? = pollInternal { !closed }

    fun setLidarEnabled(enabled: Boolean): Boolean {
        if (closed) return false
        val base = configProvider().lidarRoverUrl.trimEnd('/')
        val action = if (enabled) "start" else "stop"
        return try {
            transport.post("$base/api/lidar/$action", HTTP_TIMEOUT_MS)
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun pollInternal(shouldDeliver: () -> Boolean): LidarFrame? {
        if (closed) return null
        val config = configProvider()
        try {
            val dashboardJson = transport.get(
                config.dashboardUrl.trimEnd('/') + "/api/state",
                HTTP_TIMEOUT_MS
            )
            val dashboardFrame = LidarJsonParser.parseDashboard(dashboardJson)
            selector.recordDashboardSuccess()
            return deliver(dashboardFrame, shouldDeliver)
        } catch (dashboardError: Exception) {
            if (selector.recordDashboardFailure() != LidarSource.ROVER_SCAN) return null
            try {
                val roverJson = transport.get(
                    config.lidarRoverUrl.trimEnd('/') + "/api/lidar/revolution",
                    HTTP_TIMEOUT_MS
                )
                return deliver(LidarJsonParser.parseRevolution(roverJson), shouldDeliver)
            } catch (roverError: Exception) {
                val retained = synchronized(stateLock) { lastFrame } ?: return null
                val detail = roverError.message?.takeIf { it.isNotBlank() } ?: "LiDAR unavailable"
                return deliver(retained.copy(offline = true, reason = detail), shouldDeliver)
            }
        }
    }

    private fun deliver(frame: LidarFrame, shouldDeliver: () -> Boolean): LidarFrame {
        synchronized(stateLock) { lastFrame = frame }
        if (shouldDeliver()) listener(frame)
        return frame
    }

    companion object {
        const val HTTP_TIMEOUT_MS = 700
        const val POLL_INTERVAL_MS = 800L
    }
}
