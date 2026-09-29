package com.pitdivers.rovercontroller.lidar

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

enum class LidarSource { WINDOWS_MAP, ROVER_SCAN, OFFLINE }

data class MapCell(val x: Int, val y: Int, val value: Int)
data class MapPoint(val x: Double, val y: Double)
data class RoverPose(val x: Double, val y: Double, val yaw: Double)

data class LidarFrame(
    val source: LidarSource,
    val resolution: Double = 0.05,
    val cells: List<MapCell> = emptyList(),
    val path: List<MapPoint> = emptyList(),
    val pose: RoverPose? = null,
    val scanPoints: List<MapPoint> = emptyList(),
    val tracking: String? = null,
    val reason: String? = null,
    val lidarRunning: Boolean? = null,
    val rpm: Double? = null,
    val offline: Boolean = false
)

object LidarJsonParser {
    private const val MAX_RANGE_METRES = 12.0

    fun parseDashboard(json: String): LidarFrame {
        val root = JSONObject(json)
        val map = root.optJSONObject("map")
            ?: throw IllegalArgumentException("Dashboard response has no map")
        val resolution = finite(map.optDouble("resolution", 0.05))?.takeIf { it > 0 } ?: 0.05
        val networkLidar = root.optJSONObject("network")?.optJSONObject("lidar")
        return LidarFrame(
            source = LidarSource.WINDOWS_MAP,
            resolution = resolution,
            cells = parseCells(map.optJSONArray("cells")),
            path = parsePoints(map.optJSONArray("path")),
            pose = parsePose(map.optJSONArray("pose")),
            scanPoints = parsePoints(map.optJSONArray("points")),
            tracking = map.optString("tracking").takeIf { it.isNotBlank() },
            reason = map.optString("reason").takeIf { it.isNotBlank() },
            lidarRunning = networkLidar?.optionalBoolean("running"),
            rpm = networkLidar?.let { finite(it.optDouble("rpm", Double.NaN)) }
        )
    }

    fun parseRevolution(json: String): LidarFrame {
        val value = JSONTokener(json).nextValue()
        val root = value as? JSONObject
        val ranges = when (value) {
            is JSONArray -> value
            is JSONObject -> listOf("ranges_mm", "mm", "distances", "scan")
                .firstNotNullOfOrNull { value.optJSONArray(it) }
            else -> null
        } ?: throw IllegalArgumentException("Rover response has no scan ranges")

        val points = ArrayList<MapPoint>(ranges.length())
        for (index in 0 until ranges.length()) {
            val millimetres = finite(ranges.optDouble(index, Double.NaN)) ?: continue
            val metres = millimetres / 1000.0
            if (metres <= 0.0 || metres > MAX_RANGE_METRES) continue
            val angle = index * PI / 180.0
            points += MapPoint(cos(angle) * metres, sin(angle) * metres)
        }
        return LidarFrame(
            source = LidarSource.ROVER_SCAN,
            scanPoints = points,
            pose = RoverPose(0.0, 0.0, 0.0),
            tracking = "direct",
            reason = "Direct rover scan",
            lidarRunning = true,
            rpm = root?.let { finite(it.optDouble("rpm", Double.NaN)) }
        )
    }

    private fun parseCells(array: JSONArray?): List<MapCell> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                val row = array.optJSONArray(index) ?: continue
                if (row.length() < 3) continue
                val x = finite(row.optDouble(0, Double.NaN)) ?: continue
                val y = finite(row.optDouble(1, Double.NaN)) ?: continue
                val value = finite(row.optDouble(2, Double.NaN)) ?: continue
                add(MapCell(x.toInt(), y.toInt(), value.toInt()))
            }
        }
    }

    private fun parsePoints(array: JSONArray?): List<MapPoint> {
        if (array == null) return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                val row = array.optJSONArray(index) ?: continue
                if (row.length() < 2) continue
                val x = finite(row.optDouble(0, Double.NaN)) ?: continue
                val y = finite(row.optDouble(1, Double.NaN)) ?: continue
                add(MapPoint(x, y))
            }
        }
    }

    private fun parsePose(array: JSONArray?): RoverPose? {
        if (array == null || array.length() < 3) return null
        val x = finite(array.optDouble(0, Double.NaN)) ?: return null
        val y = finite(array.optDouble(1, Double.NaN)) ?: return null
        val yaw = finite(array.optDouble(2, Double.NaN)) ?: return null
        return RoverPose(x, y, yaw)
    }

    private fun finite(value: Double): Double? = value.takeIf { it.isFinite() }

    private fun JSONObject.optionalBoolean(name: String): Boolean? =
        if (has(name) && !isNull(name)) optBoolean(name) else null
}
