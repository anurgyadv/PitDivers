package com.pitdivers.rovercontroller

import android.content.Context
import java.net.URI

data class EndpointConfig(
    val cameraUrl: String,
    val dashboardUrl: String,
    val lidarRoverUrl: String
) {
    companion object {
        val DEFAULT = EndpointConfig(
            cameraUrl = "http://192.168.0.119/",
            dashboardUrl = "http://192.168.0.57:8767",
            lidarRoverUrl = "http://192.168.0.99"
        )
    }
}

object UrlNormalizer {
    fun normalizeHttpUrl(value: String): String {
        val trimmed = value.trim()
        require(trimmed.isNotEmpty()) { "URL is required" }
        val uri = try {
            URI(trimmed)
        } catch (error: Exception) {
            throw IllegalArgumentException("Enter a valid URL", error)
        }
        require(uri.scheme.equals("http", true) || uri.scheme.equals("https", true)) {
            "URL must start with http:// or https://"
        }
        require(!uri.host.isNullOrBlank()) { "URL must include a host" }
        return if (uri.path == "/" && uri.query == null && uri.fragment == null) {
            trimmed.dropLast(1)
        } else {
            trimmed
        }
    }
}

class AppConfigStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    fun load(): EndpointConfig = EndpointConfig(
        cameraUrl = preferences.getString(CAMERA, EndpointConfig.DEFAULT.cameraUrl)
            ?: EndpointConfig.DEFAULT.cameraUrl,
        dashboardUrl = preferences.getString(DASHBOARD, EndpointConfig.DEFAULT.dashboardUrl)
            ?: EndpointConfig.DEFAULT.dashboardUrl,
        lidarRoverUrl = preferences.getString(LIDAR, EndpointConfig.DEFAULT.lidarRoverUrl)
            ?: EndpointConfig.DEFAULT.lidarRoverUrl
    )

    fun save(config: EndpointConfig) {
        preferences.edit()
            .putString(CAMERA, config.cameraUrl)
            .putString(DASHBOARD, config.dashboardUrl)
            .putString(LIDAR, config.lidarRoverUrl)
            .apply()
    }

    companion object {
        private const val PREFERENCES = "pitdivers_connection_settings"
        private const val CAMERA = "camera_url"
        private const val DASHBOARD = "dashboard_url"
        private const val LIDAR = "lidar_rover_url"
    }
}
