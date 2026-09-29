package com.pitdivers.rovercontroller

import android.os.Bundle
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    companion object {
        var ROVER_IP = "192.168.0.118"
        var CAMERA_IP = "192.168.0.119"
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
    private var controllerTask: ScheduledFuture<*>? = null

    private lateinit var cameraView: WebView
    private lateinit var controllerStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        cameraView = findViewById(R.id.webViewCamera)
        controllerStatus = findViewById(R.id.controllerStatus)

        cameraView.settings.javaScriptEnabled = true
        cameraView.settings.loadsImagesAutomatically = true
        cameraView.settings.builtInZoomControls = false
        cameraView.settings.displayZoomControls = false
        cameraView.settings.useWideViewPort = true
        cameraView.webViewClient = WebViewClient()
        cameraView.loadUrl("http://$CAMERA_IP/")
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
        controllerTask?.cancel(false)
        controllerTask = null
        controlExecutor.execute {
            sendTankBlocking(0, 0)
            sendRequest("/mode?value=human", "POST")
        }
        super.onPause()
    }

    override fun onDestroy() {
        cameraView.loadUrl("about:blank")
        cameraView.destroy()
        controlExecutor.shutdown()
        super.onDestroy()
    }
}
