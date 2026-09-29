package com.pitdivers.rovercontroller.lidar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class LidarModelsTest {
    @Test
    fun dashboardParserReadsMapPoseScanAndStatus() {
        val frame = LidarJsonParser.parseDashboard(
            """{
              "map": {
                "resolution": 0.05,
                "cells": [[1,2,8],[3,4,-8],["bad",5,8]],
                "path": [[1.0,2.0,0.25,9]],
                "pose": [3.0,4.0,1.5],
                "points": [[5.0,6.0],["NaN",2.0]],
                "tracking": "tracking",
                "reason": "Localized at current position"
              },
              "network": {"lidar":{"running":true,"rpm":241.5}}
            }"""
        )

        assertEquals(LidarSource.WINDOWS_MAP, frame.source)
        assertEquals(0.05, frame.resolution, 0.0001)
        assertEquals(listOf(MapCell(1, 2, 8), MapCell(3, 4, -8)), frame.cells)
        assertEquals(listOf(MapPoint(1.0, 2.0)), frame.path)
        assertEquals(RoverPose(3.0, 4.0, 1.5), frame.pose)
        assertEquals(listOf(MapPoint(5.0, 6.0)), frame.scanPoints)
        assertEquals("tracking", frame.tracking)
        assertEquals("Localized at current position", frame.reason)
        assertTrue(frame.lidarRunning == true)
        assertEquals(241.5, frame.rpm!!, 0.001)
    }

    @Test
    fun dashboardParserAllowsMissingOptionalArrays() {
        val frame = LidarJsonParser.parseDashboard("""{"map":{"resolution":0.1}}""")
        assertTrue(frame.cells.isEmpty())
        assertTrue(frame.path.isEmpty())
        assertTrue(frame.scanPoints.isEmpty())
        assertEquals(null, frame.pose)
        assertEquals(null, frame.lidarRunning)
    }

    @Test
    fun dashboardParserRejectsMissingMapObject() {
        assertThrows(IllegalArgumentException::class.java) {
            LidarJsonParser.parseDashboard("""{"network":{}}""")
        }
    }

    @Test
    fun revolutionParserConvertsFirmwareRangesToMetres() {
        val ranges = MutableList(360) { 0 }
        ranges[0] = 1000
        ranges[90] = 2000
        val frame = LidarJsonParser.parseRevolution(
            """{"seq":17,"rpm":238.0,"ranges_mm":[${ranges.joinToString(",")}]}"""
        )

        assertEquals(LidarSource.ROVER_SCAN, frame.source)
        assertEquals(2, frame.scanPoints.size)
        assertEquals(1.0, frame.scanPoints[0].x, 0.0001)
        assertEquals(0.0, frame.scanPoints[0].y, 0.0001)
        assertEquals(0.0, frame.scanPoints[1].x, 0.0001)
        assertEquals(2.0, frame.scanPoints[1].y, 0.0001)
        assertEquals(238.0, frame.rpm!!, 0.001)
        assertFalse(frame.lidarRunning == false)
    }

    @Test
    fun revolutionParserRejectsPayloadWithoutRanges() {
        assertThrows(IllegalArgumentException::class.java) {
            LidarJsonParser.parseRevolution("""{"seq":1}""")
        }
    }
}
