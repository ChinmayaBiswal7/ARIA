package com.aria.bridge

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.AttributeSet
import android.util.Log
import androidx.appcompat.widget.AppCompatImageView
import java.util.ArrayList
import java.util.Collections
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

class Orb3DView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : AppCompatImageView(context, attrs, defStyleAttr), SensorEventListener {

    private val particles = ArrayList<Particle>()
    private var rx = 0.35f // Tilt slightly forward so 3D depth is naturally apparent
    private var ry = 0.0f
    private var audioLevel = 0.0f
    private var orbState = "idle"
    private var lastTime = System.currentTimeMillis()
    private var time = 0.0f

    // Parallax sensor variables
    private var tiltX = 0f
    private var tiltY = 0f
    private var sensorRegistered = false

    private class Particle(
        var x: Float,
        var y: Float,
        var z: Float,
        val speed: Float,
        val phase: Float,
        val layer: Int
    )

    private class ProjectedParticle(
        val screenX: Float,
        val screenY: Float,
        val z: Float,
        val size: Float,
        val alpha: Float,
        val color: Int
    ) : Comparable<ProjectedParticle> {
        override fun compareTo(other: ProjectedParticle): Int {
            // Sort by Z coordinate (back to front) so 3D occlusion is correct
            return this.z.compareTo(other.z)
        }
    }

    init {
        initParticles()
    }

    private fun initParticles() {
        particles.clear()
        val nPoints = 2000 // 2000 particles for high-fidelity density on Samsung M35 and flagship devices
        val goldenRatio = (1.0 + sqrt(5.0)) / 2.0
        val goldenAngle = ((2.0 - goldenRatio) * (2.0 * Math.PI)).toFloat()

        for (i in 0 until nPoints) {
            val z = 1.0f - (i / (nPoints - 1.0f)) * 2.0f // ranges from 1.0 to -1.0
            val radiusAtZ = sqrt(1.0f - z * z)
            val theta = i * goldenAngle
            val x = (cos(theta.toDouble()) * radiusAtZ).toFloat()
            val y = (sin(theta.toDouble()) * radiusAtZ).toFloat()

            particles.add(Particle(
                x, y, z,
                speed = 0.3f + Math.random().toFloat() * 1.0f,
                phase = (Math.random() * 2.0 * Math.PI).toFloat(),
                layer = 0 // Layer will be computed dynamically per frame now
            ))
        }
    }

    private fun drawCentralCore(
        canvas: Canvas,
        centerX: Float,
        centerY: Float,
        radius: Float,
        activeAudioLevel: Float,
        baseColor: Int
    ) {
        val coreRadius = radius * 0.24f
        val coreGlowSize = coreRadius * (1.1f + activeAudioLevel * 2.0f)
        val corePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            val alpha = if (orbState == "offline") 0.3f else 0.85f
            val colorInt = Color.argb(
                (alpha * 255).toInt(),
                Color.red(baseColor),
                Color.green(baseColor),
                Color.blue(baseColor)
            )
            shader = RadialGradient(
                centerX, centerY, coreGlowSize,
                colorInt, Color.TRANSPARENT,
                Shader.TileMode.CLAMP
            )
        }
        canvas.drawCircle(centerX, centerY, coreGlowSize, corePaint)
    }

    fun setState(state: String) {
        this.orbState = state.lowercase()
        postInvalidateOnAnimation()
    }

    fun setAudioLevel(level: Float) {
        this.audioLevel = level
        postInvalidateOnAnimation()
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        registerSensor()
    }

    override fun onDetachedFromWindow() {
        unregisterSensor()
        super.onDetachedFromWindow()
    }

    private fun registerSensor() {
        if (sensorRegistered) return
        try {
            val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
            val accel = sensorManager?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
            if (accel != null) {
                sensorManager.registerListener(this, accel, SensorManager.SENSOR_DELAY_GAME)
                sensorRegistered = true
            }
        } catch (e: Exception) {
            Log.e("Orb3DView", "Failed to register accelerometer: ${e.message}")
        }
    }

    private fun unregisterSensor() {
        if (!sensorRegistered) return
        try {
            val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
            sensorManager?.unregisterListener(this)
            sensorRegistered = false
        } catch (e: Exception) {}
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event == null) return
        if (event.sensor.type == Sensor.TYPE_ACCELEROMETER) {
            // Low-pass filter to smooth accelerometer noise (90% history, 10% new value)
            val ax = event.values[0]
            val ay = event.values[1]
            tiltX = tiltX * 0.9f + ax * 0.1f
            tiltY = tiltY * 0.9f + ay * 0.1f
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    override fun onDraw(canvas: Canvas) {
        // Skip super.onDraw() so we don't draw any static placeholder resource
        val w = width.toFloat()
        val h = height.toFloat()
        if (w == 0f || h == 0f) return

        val now = System.currentTimeMillis()
        val elapsed = now - lastTime
        lastTime = now

        // Determine Y rotation speed based on active state
        val speed = when(orbState) {
            "offline" -> 0.0004f
            "listening" -> 0.012f
            "thinking" -> 0.022f // Vortex spin
            "speaking" -> 0.016f
            else -> 0.003f // idle
        }
        
        // Normalize rotation velocity to 60 FPS
        val frameScale = (elapsed / 16.66f).coerceAtLeast(0.1f).coerceAtMost(3.0f)
        time += speed * frameScale
        ry = (ry + speed * frameScale) % (2f * Math.PI.toFloat())

        // Resolve active colors
        val tint = imageTintList
        val baseColor = if (tint != null) {
            tint.defaultColor
        } else {
            when (orbState) {
                "offline" -> Color.parseColor("#EF4444")
                "listening" -> Color.parseColor("#00E5FF")
                "thinking" -> Color.parseColor("#A78BFA")
                "speaking" -> Color.parseColor("#10B981")
                else -> Color.parseColor("#008CFF") // idle/online
            }
        }

        // Pulse core breathing envelope
        val breathing = sin(time.toDouble() * 1.8).toFloat() * 0.04f
        val corePulse = 1.0f + breathing

        val radius = Math.min(w, h) * 0.38f * corePulse
        val centerX = w / 2f
        val centerY = h / 2f

        // Simulated mouth-flap speaker level to look alive even in room silence
        var activeAudioLevel = audioLevel
        if (orbState == "speaking" && activeAudioLevel < 0.05f) {
            activeAudioLevel = 0.12f + Math.abs(sin(time.toDouble() * 5.5)).toFloat() * 0.22f
        }

        // 1. Ambient Background Glow
        val glowRadius = radius * 1.55f
        val bgGlowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            val alpha = if (orbState == "offline") 0.05f else (0.10f + activeAudioLevel * 0.18f)
            val colorInt = Color.argb(
                (alpha * 255).toInt(),
                Color.red(baseColor),
                Color.green(baseColor),
                Color.blue(baseColor)
            )
            shader = RadialGradient(
                centerX, centerY, glowRadius,
                colorInt, Color.TRANSPARENT,
                Shader.TileMode.CLAMP
            )
        }
        canvas.drawCircle(centerX, centerY, glowRadius, bgGlowPaint)

        // 2. Parallax offsets per layer based on low-pass accelerometer tilt
        // Shifting opposite directions generates natural stereoscopic 3D depth!
        val parallaxMaxShift = 2.0f
        val parallaxX = (-tiltX * parallaxMaxShift).coerceIn(-12f, 12f)
        val parallaxY = (tiltY * parallaxMaxShift).coerceIn(-12f, 12f)

        // 3. Project 3D Nodes
        val projected = ArrayList<ProjectedParticle>()
        val cosY = cos(ry.toDouble()).toFloat()
        val sinY = sin(ry.toDouble()).toFloat()
        val cosX = cos(rx.toDouble()).toFloat()
        val sinX = sin(rx.toDouble()).toFloat()

        val camDistance = 3.2f // projection focal length ratio

        for (p in particles) {
            // Rotate around Y
            var x1 = p.x * cosY + p.z * sinY
            val y1 = p.y
            var z1 = -p.x * sinY + p.z * cosY

            // Rotate around X
            var x2 = x1
            var y2 = y1 * cosX - z1 * sinX
            var z2 = y1 * sinX + z1 * cosX

            var displacement = 1.0f
            if (orbState == "thinking") {
                // Vortex effect: spiral around Z-axis and pull inward
                val angle = time * 2.8f + z2 * 4.5f
                val rxNew = x2 * cos(angle.toDouble()) - y2 * sin(angle.toDouble())
                val ryNew = x2 * sin(angle.toDouble()) + y2 * cos(angle.toDouble())
                x2 = rxNew.toFloat()
                y2 = ryNew.toFloat()
                displacement = 0.68f + 0.32f * Math.abs(sin((time * 1.5f + p.phase).toDouble())).toFloat()
            } else if (orbState == "listening" || orbState == "speaking") {
                // Audio spike displacement
                val ripple = sin((time * 18f * p.speed + p.phase).toDouble()).toFloat()
                displacement = 1.0f + (ripple * activeAudioLevel * 0.12f) + (activeAudioLevel * 0.20f)
            } else {
                // Gentle idle drift
                displacement = 1.0f + sin((time * 2.2f * p.speed + p.phase).toDouble()).toFloat() * 0.02f
            }

            // Camera perspective factor
            val scaleFactor = camDistance / (camDistance + z2 * 0.6f)

            // Dynamic layer determination based on rotated Z-coordinate (z2)
            val dynamicLayer = when {
                z2 < -0.3f -> 0  // Back
                z2 < 0.3f -> 1   // Middle
                else -> 2        // Front
            }

            // Parallax translation: smooth continuous function of Z-depth
            val layerShiftMult = z2
            val shiftX = parallaxX * layerShiftMult
            val shiftY = parallaxY * layerShiftMult

            val screenX = centerX + x2 * radius * displacement * scaleFactor + shiftX
            val screenY = centerY - y2 * radius * displacement * scaleFactor + shiftY

            // Calculate particle color and depth mapping
            val brightness = (z2 + 1.0f) / 2.0f // range 0.0 to 1.0
            
            val baseSize = when(dynamicLayer) {
                0 -> 1.8f  // Back Layer
                1 -> 3.2f  // Middle Layer
                else -> 5.2f // Front Layer
            }
            val size = baseSize * brightness * (1.0f + activeAudioLevel * 0.5f) * scaleFactor

            val baseAlpha = when(dynamicLayer) {
                0 -> 0.20f // Back
                1 -> 0.55f // Middle
                else -> 0.85f // Front
            }
            var alpha = baseAlpha * (0.25f + 0.75f * brightness)
            if (orbState == "offline") alpha *= 0.25f

            // Layered color styling for immersive depth
            val pColor = when(orbState) {
                "listening" -> {
                    when(dynamicLayer) {
                        0 -> Color.parseColor("#0022AA") // Deep cobalt back
                        1 -> Color.parseColor("#0099FF") // Electric blue middle
                        else -> Color.parseColor("#00E5FF") // Neon cyan front
                    }
                }
                "speaking" -> {
                    // Speaking uses a striking Green + Gold/Orange highlight pattern
                    when(dynamicLayer) {
                        0 -> Color.parseColor("#064E3B") // Forest green back
                        1 -> Color.parseColor("#10B981") // Emerald green middle
                        else -> Color.parseColor("#F59E0B") // Golden amber front highlights
                    }
                }
                "thinking" -> {
                    when(dynamicLayer) {
                        0 -> Color.parseColor("#3B0764") // Dark purple back
                        1 -> Color.parseColor("#8B5CF6") // Violet middle
                        else -> Color.parseColor("#C084FC") // Glowing light purple front
                    }
                }
                "offline" -> Color.parseColor("#EF4444")
                else -> { // idle
                    when(dynamicLayer) {
                        0 -> Color.parseColor("#001F66") // Dim navy back
                        1 -> Color.parseColor("#0055CC") // Royal blue middle
                        else -> Color.parseColor("#008CFF") // Neon blue front
                    }
                }
            }

            val finalColor = if (tint != null) baseColor else pColor
            projected.add(ProjectedParticle(screenX, screenY, z2, size, alpha, finalColor))
        }

        // 4. Draw Mesh Lines (between close particles on both front and back hemispheres)
        val maxConnectDist = 0.45f
        val maxConnectDistSq = maxConnectDist * maxConnectDist
        val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 1.0f
        }

        // Draw connections for subset of points to keep CPU usage low
        for (i in 0 until particles.size step 8) {
            val proji = projected[i]

            for (j in (i + 1) until particles.size step 12) {
                val projj = projected[j]

                val dx = particles[i].x - particles[j].x
                val dy = particles[i].y - particles[j].y
                val dz = particles[i].z - particles[j].z
                val distSq = dx*dx + dy*dy + dz*dz

                if (distSq < maxConnectDistSq) {
                    val zAvg = (proji.z + projj.z) / 2f
                    // Map zAvg (from -1.0 to 1.0) to depth fade multiplier (from 0.15 to 1.0)
                    val depthFade = 0.15f + 0.85f * ((zAvg + 1.0f) / 2.0f)
                    var alpha = 0.15f * depthFade * (1.0f + activeAudioLevel * 1.5f)
                    if (orbState == "offline") alpha *= 0.1f
                    
                    // Clamp alpha to safe range
                    alpha = alpha.coerceIn(0.01f, 0.5f)

                    linePaint.color = Color.argb(
                        (alpha * 255).toInt(),
                        Color.red(baseColor),
                        Color.green(baseColor),
                        Color.blue(baseColor)
                    )
                    canvas.drawLine(proji.screenX, proji.screenY, projj.screenX, projj.screenY, linePaint)
                }
            }
        }

        // 5. Depth Sort: Draw back particles first so front particles overlap them correctly
        Collections.sort(projected)

        var coreDrawn = false
        val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        for (p in projected) {
            // Draw central core glow when we transition from back particles (z < 0) to front particles (z >= 0)
            if (!coreDrawn && p.z >= 0.0f) {
                drawCentralCore(canvas, centerX, centerY, radius, activeAudioLevel, baseColor)
                coreDrawn = true
            }

            dotPaint.color = Color.argb(
                (p.alpha * 255).toInt(),
                Color.red(p.color),
                Color.green(p.color),
                Color.blue(p.color)
            )
            canvas.drawCircle(p.screenX, p.screenY, p.size / 2f, dotPaint)
        }

        // Safety fallback if no particles had z >= 0
        if (!coreDrawn) {
            drawCentralCore(canvas, centerX, centerY, radius, activeAudioLevel, baseColor)
        }

        // 7. Radial Equalizer Spikes (Audio reactions around perimeter)
        if ((orbState == "listening" || orbState == "speaking") && activeAudioLevel > 0.05f) {
            val spikeCount = 36
            val angleStep = (2f * Math.PI / spikeCount).toFloat()
            val spikePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.STROKE
                strokeWidth = 2.0f
                color = Color.argb(
                    ((0.2f + activeAudioLevel * 0.45f) * 255).toInt(),
                    Color.red(baseColor),
                    Color.green(baseColor),
                    Color.blue(baseColor)
                )
            }

            for (i in 0 until spikeCount) {
                val angle = i * angleStep + time * 0.35f
                val waveAmp = activeAudioLevel * (0.4f + 0.6f * sin((time * 8.5f + i).toDouble()).toFloat())

                val startR = radius * 0.95f
                val endR = radius * (0.95f + waveAmp * 0.55f)

                val sx = centerX + cos(angle.toDouble()).toFloat() * startR
                val sy = centerY + sin(angle.toDouble()).toFloat() * startR
                val ex = centerX + cos(angle.toDouble()).toFloat() * endR
                val ey = centerY + sin(angle.toDouble()).toFloat() * endR

                canvas.drawLine(sx, sy, ex, ey, spikePaint)
            }
        }

        // Loop invalidate to draw next animation frame at 60 FPS
        postInvalidateOnAnimation()
    }
}
