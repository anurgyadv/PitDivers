package com.pitdivers.rovercontroller

import android.os.Bundle
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.pitdivers.rovercontroller.lidar.LidarFrame
import com.pitdivers.rovercontroller.lidar.LidarMapView
import com.pitdivers.rovercontroller.lidar.LidarRepository
import com.pitdivers.rovercontroller.lidar.LidarSource
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    companion object {
        var ROVER_IP = "192.168.0.118"
        var API_KEY = "RANDOMKEY"

        const val CONTROL_INTERVAL_MS = 75L
        const val MAX_SPEED = 180
        const val DEADZONE = 0.18f
        const val HTTP_TIMEOUT_MS = 220
    }

    @Volatile private var leftStickX = 0f
    @Volatile private var leftStickY = 0f
    @Volatile private var emergencyStop = false

    private val controlExecutor = Executors.newSingleThreadScheduledExecutor()
    private val lidarActionExecutor = Executors.newSingleThreadExecutor()
    private var controllerTask: ScheduledFuture<*>? = null

    private lateinit var cameraView: WebView
    private lateinit var controllerStatus: TextView
    private lateinit var lidarMiniMap: LidarMapView
    private lateinit var lidarExpandedMap: LidarMapView
    private lateinit var lidarMiniCard: View
    private lateinit var lidarExpandedOverlay: FrameLayout
    private lateinit var lidarMiniStatus: TextView
    private lateinit var lidarExpandedStatus: TextView
    private lateinit var lidarMiniToggle: Button
    private lateinit var lidarExpandedToggle: Button
    private lateinit var configStore: AppConfigStore
    @Volatile private var endpoints = EndpointConfig.DEFAULT
    @Volatile private var activityActive = false
    private var lidarRunning: Boolean? = null
    private lateinit var lidarRepository: LidarRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        cameraView = findViewById(R.id.webViewCamera)
        controllerStatus = findViewById(R.id.controllerStatus)
        lidarMiniMap = findViewById(R.id.lidarMiniMap)
        lidarExpandedMap = findViewById(R.id.lidarExpandedMap)
        lidarMiniCard = findViewById(R.id.lidarMiniCard)
        lidarExpandedOverlay = findViewById(R.id.lidarExpandedOverlay)
        lidarMiniStatus = findViewById(R.id.lidarMiniStatus)
        lidarExpandedStatus = findViewById(R.id.lidarExpandedStatus)
        lidarMiniToggle = findViewById(R.id.lidarMiniToggle)
        lidarExpandedToggle = findViewById(R.id.lidarExpandedToggle)

        configStore = AppConfigStore(this)
        endpoints = configStore.load()
        lidarRepository = LidarRepository({ endpoints }) { frame ->
            if (!activityActive || isDestroyed) return@LidarRepository
            runOnUiThread {
                if (activityActive && !isDestroyed) renderLidarFrame(frame)
            }
        }

        cameraView.settings.javaScriptEnabled = true
        cameraView.settings.loadsImagesAutomatically = true
        cameraView.settings.builtInZoomControls = false
        cameraView.settings.displayZoomControls = false
        cameraView.settings.useWideViewPort = true
        cameraView.webViewClient = WebViewClient()
        cameraView.loadUrl(endpoints.cameraUrl)

        lidarMiniMap.setOnClickListener { setMapExpanded(true) }
        findViewById<Button>(R.id.closeExpandedMap).setOnClickListener { setMapExpanded(false) }
        lidarMiniToggle.setOnClickListener { toggleLidar() }
        lidarExpandedToggle.setOnClickListener { toggleLidar() }
        findViewById<Button>(R.id.settingsButton).setOnClickListener { showConnectionSettings() }
        findViewById<Button>(R.id.expandedSettingsButton).setOnClickListener { showConnectionSettings() }
        onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (lidarExpandedOverlay.visibility == View.VISIBLE) setMapExpanded(false)
                else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    private fun setMapExpanded(expanded: Boolean) {
        lidarMiniCard.visibility = if (expanded) View.GONE else View.VISIBLE
        lidarExpandedOverlay.visibility = if (expanded) View.VISIBLE else View.GONE
    }

    private fun renderLidarFrame(frame: LidarFrame) {
        lidarMiniMap.setFrame(frame)
        lidarExpandedMap.setFrame(frame)
        if (frame.lidarRunning != null) lidarRunning = frame.lidarRunning
        val source = when (frame.source) {
            LidarSource.WINDOWS_MAP -> "PC MAP"
            LidarSource.ROVER_SCAN -> "ROVER SCAN"
            LidarSource.OFFLINE -> "OFFLINE"
        }
        val rpm = frame.rpm?.let { " · ${it.toInt()} RPM" }.orEmpty()
        val state = if (frame.offline) "OFFLINE" else source
        val detail = frame.reason?.takeIf { it.isNotBlank() } ?: frame.tracking.orEmpty()
        val text = listOf("$state$rpm", detail).filter { it.isNotBlank() }.joinToString(" · ")
        lidarMiniStatus.text = text
        lidarExpandedStatus.text = text
        updateLidarButtons()
    }

    private fun updateLidarButtons(enabled: Boolean = true) {
        val label = if (lidarRunning == true) "STOP" else "START"
        lidarMiniToggle.text = label
        lidarExpandedToggle.text = label
        lidarMiniToggle.isEnabled = enabled
        lidarExpandedToggle.isEnabled = enabled
    }

    private fun toggleLidar() {
        val enable = lidarRunning != true
        updateLidarButtons(false)
        val pending = if (enable) "Starting LiDAR…" else "Stopping LiDAR…"
        lidarMiniStatus.text = pending
        lidarExpandedStatus.text = pending
        lidarActionExecutor.execute {
            val succeeded = lidarRepository.setLidarEnabled(enable)
            if (!activityActive || isDestroyed) return@execute
            runOnUiThread {
                if (!activityActive || isDestroyed) return@runOnUiThread
                if (succeeded) {
                    lidarRunning = enable
                    val message = if (enable) "LiDAR starting · waiting for scan" else "LiDAR stopped"
                    lidarMiniStatus.text = message
                    lidarExpandedStatus.text = message
                } else {
                    lidarMiniStatus.text = "LiDAR command failed"
                    lidarExpandedStatus.text = "LiDAR command failed · check rover Wi-Fi"
                }
                updateLidarButtons()
            }
        }
    }

    private fun showConnectionSettings() {
        val content = layoutInflater.inflate(R.layout.dialog_connection_settings, null)
        val cameraInput = content.findViewById<EditText>(R.id.cameraUrlInput)
        val dashboardInput = content.findViewById<EditText>(R.id.dashboardUrlInput)
        val lidarInput = content.findViewById<EditText>(R.id.lidarRoverUrlInput)
        cameraInput.setText(endpoints.cameraUrl)
        dashboardInput.setText(endpoints.dashboardUrl)
        lidarInput.setText(endpoints.lidarRoverUrl)
        val dialog = AlertDialog.Builder(this)
            .setTitle("Connection settings")
            .setView(content)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Save", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                cameraInput.error = null
                dashboardInput.error = null
                lidarInput.error = null
                fun validated(field: EditText): String? = try {
                    UrlNormalizer.normalizeHttpUrl(field.text.toString())
                } catch (error: IllegalArgumentException) {
                    field.error = error.message
                    null
                }
                val cameraUrl = validated(cameraInput)
                val dashboardUrl = validated(dashboardInput)
                val lidarUrl = validated(lidarInput)
                if (cameraUrl == null || dashboardUrl == null || lidarUrl == null) return@setOnClickListener
                val updated = EndpointConfig(cameraUrl, dashboardUrl, lidarUrl)
                endpoints = updated
                configStore.save(updated)
                cameraView.loadUrl(updated.cameraUrl)
                lidarRepository.stop()
                if (activityActive) lidarRepository.start()
                lidarMiniStatus.text = "LiDAR · Connecting…"
                lidarExpandedStatus.text = "LiDAR · Connecting…"
                dialog.dismiss()
            }
        }
        dialog.show()
    }

    override fun dispatchGenericMotionEvent(event: MotionEvent): Boolean {
        if (event.source and InputDevice.SOURCE_JOYSTICK == InputDevice.SOURCE_JOYSTICK &&
            event.action == MotionEvent.ACTION_MOVE) {
            leftStickX = event.getAxisValue(MotionEvent.AXIS_X)
            leftStickY = event.getAxisValue(MotionEvent.AXIS_Y)
            return true
        }
        return super.dispatchGenericMotionEvent(event)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BUTTON_B) {
            if (!emergencyStop) {
                emergencyStop = true
                controllerStatus.text = "EMERGENCY STOP • Release B to resume"
                controlExecutor.execute { sendTankBlocking(0, 0) }
            }
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BUTTON_B) {
            emergencyStop = false
            controllerStatus.text = "Controller active • Left stick drives • B stops"
            return true
        }
        return super.onKeyUp(keyCode, event)
    }

    private fun sendCurrentCommand() {
        if (emergencyStop) {
            sendTankBlocking(0, 0)
        } else {
            val command = DriveMixer.mix(leftStickX, leftStickY, DEADZONE, MAX_SPEED)
            sendTankBlocking(command.left, command.right)
        }
    }

    private fun sendTankBlocking(left: Int, right: Int) {
        sendRequest("/api/controller?left=$left&right=$right", "POST")
    }

    private fun sendRequest(path: String, method: String) {
        try {
            val connection = URL("http://$ROVER_IP$path").openConnection() as HttpURLConnection
            connection.requestMethod = method
            connection.setRequestProperty("X-API-Key", API_KEY)
            connection.setRequestProperty("Connection", "keep-alive")
            connection.useCaches = false
            connection.connectTimeout = HTTP_TIMEOUT_MS
            connection.readTimeout = HTTP_TIMEOUT_MS

            val response = if (connection.responseCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            response?.use { it.readBytes() }
            // Do not call disconnect(): consuming the response lets Android reuse
            // the persistent connection for the next ordered controller update.
        } catch (_: Exception) {
            // The rover lease stops the motors if Wi-Fi or the app disappears.
        }
    }

    override fun onResume() {
        super.onResume()
        activityActive = true
        lidarRepository.start()
        controllerTask?.cancel(false)
        controlExecutor.execute { sendRequest("/mode?value=controller", "POST") }
        controllerTask = controlExecutor.scheduleAtFixedRate(
            ::sendCurrentCommand,
            CONTROL_INTERVAL_MS,
            CONTROL_INTERVAL_MS,
            TimeUnit.MILLISECONDS
        )
    }

    override fun onPause() {
        activityActive = false
        lidarRepository.stop()
        controllerTask?.cancel(false)
        controllerTask = null
        controlExecutor.execute {
            sendTankBlocking(0, 0)
            sendRequest("/mode?value=human", "POST")
        }
        super.onPause()
    }

    override fun onDestroy() {
        activityActive = false
        lidarRepository.close()
        lidarActionExecutor.shutdownNow()
        cameraView.loadUrl("about:blank")
        cameraView.destroy()
        controlExecutor.shutdown()
        super.onDestroy()
    }
}
