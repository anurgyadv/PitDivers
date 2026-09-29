package com.pitdivers.rovercontroller.lidar

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.sin

class LidarMapView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {
    private var frame = LidarFrame(source = LidarSource.OFFLINE, offline = true, reason = "Waiting for LiDAR")
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()

    fun setFrame(value: LidarFrame) {
        frame = value
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(BACKGROUND)
        val transform = LidarViewport.fit(frame, width.toFloat(), height.toFloat(), 12f * resources.displayMetrics.density)
        drawGrid(canvas, transform)
        drawCells(canvas, transform)
        drawPath(canvas, transform)
        drawScan(canvas, transform)
        drawRover(canvas, transform)
    }

    private fun drawGrid(canvas: Canvas, transform: WorldTransform) {
        paint.color = GRID
        paint.strokeWidth = resources.displayMetrics.density
        val bounds = transform.bounds
        for (x in floor(bounds.minX).toInt()..ceil(bounds.maxX).toInt()) {
            val a = transform.toScreen(x.toDouble(), bounds.minY)
            val b = transform.toScreen(x.toDouble(), bounds.maxY)
            canvas.drawLine(a.x, a.y, b.x, b.y, paint)
        }
        for (y in floor(bounds.minY).toInt()..ceil(bounds.maxY).toInt()) {
            val a = transform.toScreen(bounds.minX, y.toDouble())
            val b = transform.toScreen(bounds.maxX, y.toDouble())
            canvas.drawLine(a.x, a.y, b.x, b.y, paint)
        }
    }

    private fun drawCells(canvas: Canvas, transform: WorldTransform) {
        val halfCell = (frame.resolution * transform.scale / 2.0).toFloat().coerceAtLeast(1f)
        frame.cells.forEach { cell ->
            val point = transform.toScreen(cell.x * frame.resolution, cell.y * frame.resolution)
            paint.color = if (cell.value > 0) WALL else EXPLORED
            paint.style = Paint.Style.FILL
            canvas.drawRect(point.x - halfCell, point.y - halfCell, point.x + halfCell, point.y + halfCell, paint)
        }
    }

    private fun drawPath(canvas: Canvas, transform: WorldTransform) {
        if (frame.path.size < 2) return
        paint.color = PATH_COLOR
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f * resources.displayMetrics.density
        path.reset()
        frame.path.forEachIndexed { index, point ->
            val screen = transform.toScreen(point.x, point.y)
            if (index == 0) path.moveTo(screen.x, screen.y) else path.lineTo(screen.x, screen.y)
        }
        canvas.drawPath(path, paint)
    }

    private fun drawScan(canvas: Canvas, transform: WorldTransform) {
        val pose = frame.pose ?: RoverPose(0.0, 0.0, 0.0)
        val origin = transform.toScreen(pose.x, pose.y)
        paint.strokeWidth = resources.displayMetrics.density
        LidarGeometry.scanWorldPoints(frame).forEachIndexed { index, point ->
            val screen = transform.toScreen(point.x, point.y)
            if (index % 5 == 0) {
                paint.color = SCAN_RAY
                canvas.drawLine(origin.x, origin.y, screen.x, screen.y, paint)
            }
            paint.color = SCAN_POINT
            canvas.drawCircle(screen.x, screen.y, 1.6f * resources.displayMetrics.density, paint)
        }
    }

    private fun drawRover(canvas: Canvas, transform: WorldTransform) {
        val pose = frame.pose ?: RoverPose(0.0, 0.0, 0.0)
        val centre = transform.toScreen(pose.x, pose.y)
        val size = 10f * resources.displayMetrics.density
        val heading = pose.yaw
        val tipX = centre.x + cos(heading).toFloat() * size
        val tipY = centre.y - sin(heading).toFloat() * size
        val leftX = centre.x + cos(heading + 2.5).toFloat() * size * 0.75f
        val leftY = centre.y - sin(heading + 2.5).toFloat() * size * 0.75f
        val rightX = centre.x + cos(heading - 2.5).toFloat() * size * 0.75f
        val rightY = centre.y - sin(heading - 2.5).toFloat() * size * 0.75f
        path.reset()
        path.moveTo(tipX, tipY)
        path.lineTo(leftX, leftY)
        path.lineTo(rightX, rightY)
        path.close()
        paint.style = Paint.Style.FILL
        paint.color = ROVER
        canvas.drawPath(path, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f * resources.displayMetrics.density
        paint.color = ROVER_EDGE
        canvas.drawPath(path, paint)
        paint.style = Paint.Style.FILL
    }

    companion object {
        private val BACKGROUND = Color.rgb(7, 24, 34)
        private val GRID = Color.rgb(20, 49, 62)
        private val EXPLORED = Color.rgb(24, 58, 72)
        private val WALL = Color.rgb(176, 205, 216)
        private val PATH_COLOR = Color.rgb(255, 184, 92)
        private val SCAN_RAY = Color.argb(45, 79, 224, 197)
        private val SCAN_POINT = Color.rgb(111, 226, 199)
        private val ROVER = Color.rgb(111, 226, 199)
        private val ROVER_EDGE = Color.rgb(255, 188, 95)
    }
}
