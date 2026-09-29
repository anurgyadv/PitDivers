package com.pitdivers.rovercontroller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class AppConfigTest {
    @Test
    fun defaultsMatchCurrentPitDiversNetwork() {
        assertEquals("http://192.168.0.119/", EndpointConfig.DEFAULT.cameraUrl)
        assertEquals("http://192.168.0.57:8767", EndpointConfig.DEFAULT.dashboardUrl)
        assertEquals("http://192.168.0.99", EndpointConfig.DEFAULT.lidarRoverUrl)
    }

    @Test
    fun normalizerRemovesOnlyRootTrailingSlash() {
        assertEquals("http://192.168.0.99", UrlNormalizer.normalizeHttpUrl(" http://192.168.0.99/ "))
    }

    @Test
    fun normalizerPreservesStreamPathAndQuery() {
        assertEquals(
            "https://camera.local/live.mjpg?quality=high",
            UrlNormalizer.normalizeHttpUrl("https://camera.local/live.mjpg?quality=high")
        )
    }

    @Test
    fun normalizerRejectsUnsupportedOrHostlessUrls() {
        listOf("", "ftp://192.168.0.99/scan", "http:///missing-host").forEach { value ->
            assertThrows(IllegalArgumentException::class.java) {
                UrlNormalizer.normalizeHttpUrl(value)
            }
        }
    }
}
