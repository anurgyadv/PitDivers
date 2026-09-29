package com.pitdivers.rovercontroller.lidar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LidarViewportTest {
    @Test
    fun emptyFrameUsesCentredTenMetreExtent() {
        val transform = LidarViewport.fit(
            LidarFrame(source = LidarSource.ROVER_SCAN),
            width = 200f,
            height = 100f,
            padding = 10f
        )

        assertEquals(-5.0, transform.bounds.minX, 0.0001)
        assertEquals(5.0, transform.bounds.maxX, 0.0001)
        assertEquals(-5.0, transform.bounds.minY, 0.0001)
        assertEquals(5.0, transform.bounds.maxY, 0.0001)
        assertEquals(8.0, transform.scale, 0.0001)
        assertEquals(ScreenPoint(100f, 50f), transform.toScreen(0.0, 0.0))
    }

    @Test
    fun boundsIncludeCellsPathPoseAndRotatedScan() {
        val frame = LidarFrame(
            source = LidarSource.WINDOWS_MAP,
            resolution = 0.5,
            cells = listOf(MapCell(-4, -2, 8), MapCell(4, 2, -8)),
            path = listOf(MapPoint(-3.0, 1.0)),
            pose = RoverPose(2.0, 3.0, Math.PI / 2.0),
            scanPoints = listOf(MapPoint(2.0, 0.0))
        )

        val transform = LidarViewport.fit(frame, 300f, 200f, 10f)

        assertTrue(transform.bounds.minX <= -3.0)
        assertTrue(transform.bounds.maxX >= 2.0)
        assertTrue(transform.bounds.minY <= -1.0)
        assertTrue(transform.bounds.maxY >= 5.0)
    }

    @Test
    fun screenCoordinatesInvertYAndPreserveAspectRatio() {
        val frame = LidarFrame(
            source = LidarSource.ROVER_SCAN,
            scanPoints = listOf(MapPoint(-2.0, -1.0), MapPoint(2.0, 1.0))
        )
        val transform = LidarViewport.fit(frame, 220f, 120f, 10f)
        val bottomLeft = transform.toScreen(-2.0, -1.0)
        val topRight = transform.toScreen(2.0, 1.0)

        assertTrue(bottomLeft.x >= 10f && topRight.x <= 210f)
        assertTrue(bottomLeft.y > topRight.y)
        assertTrue(transform.scale.isFinite() && transform.scale > 0)
        assertEquals(transform.scale, transform.scaleX, 0.0001)
        assertEquals(transform.scale, transform.scaleY, 0.0001)
    }

    @Test
    fun ignoresNonFiniteAndOutOfRangeScanPoints() {
        val frame = LidarFrame(
            source = LidarSource.ROVER_SCAN,
            scanPoints = listOf(
                MapPoint(Double.POSITIVE_INFINITY, 1.0),
                MapPoint(1000.0, 1000.0),
                MapPoint(1.0, 1.0)
            )
        )

        val transform = LidarViewport.fit(frame, 200f, 100f, 8f)

        assertTrue(transform.scale.isFinite())
        assertTrue(transform.offsetX.isFinite())
        assertTrue(transform.offsetY.isFinite())
        assertTrue(transform.bounds.maxX < 20.0)
        assertTrue(transform.bounds.maxY < 20.0)
    }
}
