package com.pitdivers.rovercontroller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DriveMixerTest {
    @Test
    fun centreAndDeadzoneStopBothTracks() {
        assertEquals(TankCommand(0, 0), DriveMixer.mix(0f, 0f))
        assertEquals(TankCommand(0, 0), DriveMixer.mix(0.17f, -0.17f))
    }

    @Test
    fun fullForwardAndReverseDriveStraight() {
        assertEquals(TankCommand(180, 180), DriveMixer.mix(0f, -1f))
        assertEquals(TankCommand(-180, -180), DriveMixer.mix(0f, 1f))
    }

    @Test
    fun fullSteeringTurnsTracksInOppositeDirections() {
        assertEquals(TankCommand(-180, 180), DriveMixer.mix(-1f, 0f))
        assertEquals(TankCommand(180, -180), DriveMixer.mix(1f, 0f))
    }

    @Test
    fun diagonalInputNormalizesWithoutExceedingMaximum() {
        assertEquals(TankCommand(180, 0), DriveMixer.mix(1f, -1f))
        listOf(-1f, -0.5f, 0f, 0.5f, 1f).forEach { x ->
            listOf(-1f, -0.5f, 0f, 0.5f, 1f).forEach { y ->
                val command = DriveMixer.mix(x, y)
                assertTrue(command.left in -180..180)
                assertTrue(command.right in -180..180)
            }
        }
    }
}
