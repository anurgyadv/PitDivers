package com.pitdivers.rovercontroller.lidar

import com.pitdivers.rovercontroller.EndpointConfig
import java.io.IOException
import java.util.ArrayDeque
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LidarRepositoryTest {
    private val config = EndpointConfig(
        cameraUrl = "http://camera/",
        dashboardUrl = "http://pc:8767",
        lidarRoverUrl = "http://rover"
    )

    @Test
    fun selectorChangesToRoverOnThirdFailureAndRecoversImmediately() {
        val selector = LidarSourceSelector()
        assertEquals(LidarSource.WINDOWS_MAP, selector.recordDashboardFailure())
        assertEquals(LidarSource.WINDOWS_MAP, selector.recordDashboardFailure())
        assertEquals(LidarSource.ROVER_SCAN, selector.recordDashboardFailure())
        selector.recordDashboardSuccess()
        assertEquals(LidarSource.WINDOWS_MAP, selector.current)
    }

    @Test
    fun repositoryFallsBackAfterThreeDashboardFailures() {
        val transport = FakeTransport().apply {
            repeat(3) { enqueueGet(IOException("PC offline")) }
            enqueueGet("""{"rpm":240,"ranges_mm":[1000,0,0]}""")
        }
        val delivered = mutableListOf<LidarFrame>()
        val repository = LidarRepository({ config }, transport, delivered::add)

        assertNull(repository.pollOnce())
        assertNull(repository.pollOnce())
        val fallback = repository.pollOnce()

        assertEquals(LidarSource.ROVER_SCAN, fallback?.source)
        assertEquals(listOf("http://pc:8767/api/state", "http://pc:8767/api/state", "http://pc:8767/api/state", "http://rover/api/lidar/revolution"), transport.getUrls)
        assertEquals(fallback, delivered.last())
        repository.close()
    }

    @Test
    fun validDashboardResponseRestoresWindowsSource() {
        val transport = FakeTransport().apply {
            repeat(3) { enqueueGet(IOException("PC offline")) }
            enqueueGet("""{"ranges_mm":[1000]}""")
            enqueueGet("""{"map":{"resolution":0.05,"tracking":"tracking"}}""")
        }
        val repository = LidarRepository({ config }, transport) {}
        repeat(3) { repository.pollOnce() }

        val recovered = repository.pollOnce()

        assertEquals(LidarSource.WINDOWS_MAP, recovered?.source)
        assertEquals("tracking", recovered?.tracking)
        repository.close()
    }

    @Test
    fun malformedDashboardCountsAsFailure() {
        val transport = FakeTransport().apply {
            repeat(3) { enqueueGet("""{"not_map":true}""") }
            enqueueGet("""{"ranges_mm":[1500]}""")
        }
        val repository = LidarRepository({ config }, transport) {}

        repeat(2) { assertNull(repository.pollOnce()) }
        assertEquals(LidarSource.ROVER_SCAN, repository.pollOnce()?.source)
        repository.close()
    }

    @Test
    fun failedFallbackRetainsLastFrameAndMarksItOffline() {
        val transport = FakeTransport().apply {
            repeat(3) { enqueueGet(IOException("PC offline")) }
            enqueueGet("""{"ranges_mm":[1000]}""")
            enqueueGet(IOException("PC still offline"))
            enqueueGet(IOException("rover offline"))
        }
        val repository = LidarRepository({ config }, transport) {}
        repeat(3) { repository.pollOnce() }

        val offline = repository.pollOnce()

        assertTrue(offline?.offline == true)
        assertEquals(listOf(MapPoint(1.0, 0.0)), offline?.scanPoints)
        assertTrue(offline?.reason?.contains("rover offline") == true)
        repository.close()
    }

    @Test
    fun powerControlPostsToExactRoverEndpoint() {
        val transport = FakeTransport().apply {
            enqueuePost("""{"running":true}""")
            enqueuePost("""{"running":false}""")
        }
        val repository = LidarRepository({ config }, transport) {}

        assertTrue(repository.setLidarEnabled(true))
        assertTrue(repository.setLidarEnabled(false))
        assertEquals(listOf("http://rover/api/lidar/start", "http://rover/api/lidar/stop"), transport.postUrls)
        assertFalse(transport.postUrls.any { it.contains("pc:8767") })
        repository.close()
    }

    private class FakeTransport : HttpTransport {
        private val gets = ArrayDeque<Any>()
        private val posts = ArrayDeque<Any>()
        val getUrls = mutableListOf<String>()
        val postUrls = mutableListOf<String>()

        fun enqueueGet(value: Any) { gets.add(value) }
        fun enqueuePost(value: Any) { posts.add(value) }

        override fun get(url: String, timeoutMs: Int): String {
            getUrls += url
            return result(gets.removeFirst())
        }

        override fun post(url: String, timeoutMs: Int): String {
            postUrls += url
            return result(posts.removeFirst())
        }

        private fun result(value: Any): String {
            if (value is IOException) throw value
            return value as String
        }
    }
}
