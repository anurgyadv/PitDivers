package com.pitdivers.rovercontroller.lidar

import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

data class WorldBounds(val minX: Double, val maxX: Double, val minY: Double, val maxY: Double)
data class ScreenPoint(val x: Float, val y: Float)

data class WorldTransform(
    val bounds: WorldBounds,
    val scale: Double,
    val offsetX: Double,
    val offsetY: Double
) {
    val scaleX: Double get() = scale
    val scaleY: Double get() = scale

    fun toScreen(x: Double, y: Double): ScreenPoint = ScreenPoint(
        (offsetX + x * scale).toFloat(),
        (offsetY - y * scale).toFloat()
    )
}

object LidarGeometry {
    private const val MAX_SCAN_RANGE_METRES = 12.0

    fun scanWorldPoints(frame: LidarFrame): List<MapPoint> {
        val pose = frame.pose ?: RoverPose(0.0, 0.0, 0.0)
        val cosine = cos(pose.yaw)
        val sine = sin(pose.yaw)
        return frame.scanPoints.mapNotNull { point ->
            if (!point.x.isFinite() || !point.y.isFinite()) return@mapNotNull null
            if (hypot(point.x, point.y) > MAX_SCAN_RANGE_METRES) return@mapNotNull null
            MapPoint(
                pose.x + point.x * cosine - point.y * sine,
                pose.y + point.x * sine + point.y * cosine
            )
        }
    }
}

object LidarViewport {
    fun fit(frame: LidarFrame, width: Float, height: Float, padding: Float): WorldTransform {
        val points = buildList {
            frame.cells.forEach { cell ->
                add(MapPoint(cell.x * frame.resolution, cell.y * frame.resolution))
            }
            frame.path.filterTo(this) { it.x.isFinite() && it.y.isFinite() }
            frame.pose?.takeIf { it.x.isFinite() && it.y.isFinite() }?.let { add(MapPoint(it.x, it.y)) }
            addAll(LidarGeometry.scanWorldPoints(frame))
        }

        val bounds = if (points.isEmpty()) {
            WorldBounds(-5.0, 5.0, -5.0, 5.0)
        } else {
            var minX = points.minOf { it.x }
            var maxX = points.maxOf { it.x }
            var minY = points.minOf { it.y }
            var maxY = points.maxOf { it.y }
            if (maxX - minX < 1.0) {
                val centre = (minX + maxX) / 2.0
                minX = centre - 0.5
                maxX = centre + 0.5
            }
            if (maxY - minY < 1.0) {
                val centre = (minY + maxY) / 2.0
                minY = centre - 0.5
                maxY = centre + 0.5
            }
            WorldBounds(minX, maxX, minY, maxY)
        }

        val safeWidth = max(1.0, width.toDouble() - padding * 2.0)
        val safeHeight = max(1.0, height.toDouble() - padding * 2.0)
        val scale = min(
            safeWidth / (bounds.maxX - bounds.minX),
            safeHeight / (bounds.maxY - bounds.minY)
        ).takeIf { it.isFinite() && it > 0 } ?: 1.0
        val centreX = (bounds.minX + bounds.maxX) / 2.0
        val centreY = (bounds.minY + bounds.maxY) / 2.0
        return WorldTransform(
            bounds = bounds,
            scale = scale,
            offsetX = width / 2.0 - centreX * scale,
            offsetY = height / 2.0 + centreY * scale
        )
    }
}
