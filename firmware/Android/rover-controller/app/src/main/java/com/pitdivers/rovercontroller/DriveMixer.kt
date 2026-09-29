package com.pitdivers.rovercontroller

import kotlin.math.abs
import kotlin.math.max

data class TankCommand(val left: Int, val right: Int)

object DriveMixer {
    fun mix(
        x: Float,
        y: Float,
        deadzone: Float = 0.18f,
        maxSpeed: Int = 180
    ): TankCommand {
        val throttle = if (abs(y) < deadzone) 0f else -y
        val steering = if (abs(x) < deadzone) 0f else x
        val left = throttle + steering
        val right = throttle - steering
        val normalizer = max(1f, max(abs(left), abs(right)))
        return TankCommand(
            (left / normalizer * maxSpeed).toInt(),
            (right / normalizer * maxSpeed).toInt()
        )
    }
}
