package com.aria.bridge

import android.content.Context
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class FitnessData(
    val steps: Int = 0,
    val calories: Double = 0.0,
    val sleepHours: Double = 0.0,
    val sleepQuality: String = "Unknown",
    val heartRate: Int = 0,
    val spo2: Double = 0.0
)

class HealthConnectManager(private val context: Context) {
    
    val healthConnectClient by lazy {
        try {
            HealthConnectClient.getOrCreate(context)
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Failed to retrieve Health Connect client: ${e.message}")
            null
        }
    }

    val permissions = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class)
    )

    fun isAvailable(): Boolean {
        return try {
            HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE
        } catch (e: Exception) {
            false
        }
    }

    suspend fun hasPermissions(): Boolean {
        val client = healthConnectClient ?: return false
        return try {
            val granted = client.permissionController.getGrantedPermissions()
            granted.containsAll(permissions)
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Error checking permissions: ${e.message}")
            false
        }
    }

    suspend fun readFitnessData(): FitnessData {
        val client = healthConnectClient ?: return FitnessData()
        
        if (!hasPermissions()) {
            Log.w("HealthConnectManager", "Read permissions are missing or revoked. Returning empty metrics.")
            return FitnessData()
        }

        // Today only (midnight local time to now)
        val todayStart = LocalDate.now().atStartOfDay().atZone(ZoneId.systemDefault()).toInstant()
        val now = Instant.now()
        val timeFilter = TimeRangeFilter.between(todayStart, now)

        var steps = 0
        var calories = 0.0
        var sleepHours = 0.0
        var sleepQuality = "Unknown"
        var heartRate = 0

        // 1. Read Steps
        try {
            val stepsRequest = ReadRecordsRequest(
                recordType = StepsRecord::class,
                timeRangeFilter = timeFilter
            )
            val stepsResponse = client.readRecords(stepsRequest)
            steps = stepsResponse.records.sumOf { it.count }.toInt()
            Log.d("HealthConnectManager", "Steps fetched: $steps")
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Error fetching steps: ${e.message}")
        }

        // 2. Read Calories
        try {
            val caloriesRequest = ReadRecordsRequest(
                recordType = TotalCaloriesBurnedRecord::class,
                timeRangeFilter = timeFilter
            )
            val caloriesResponse = client.readRecords(caloriesRequest)
            calories = caloriesResponse.records.sumOf { it.energy.inKilocalories }
            Log.d("HealthConnectManager", "Calories fetched: $calories")
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Error fetching calories: ${e.message}")
        }

        // 3. Read Sleep
        try {
            // Read starting from yesterday to capture overnight sleep session
            val yesterdayStart = LocalDate.now().minusDays(1).atStartOfDay().atZone(ZoneId.systemDefault()).toInstant()
            val sleepRequest = ReadRecordsRequest(
                recordType = SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(yesterdayStart, now)
            )
            val sleepResponse = client.readRecords(sleepRequest)
            var totalSleepSec = 0L
            for (record in sleepResponse.records) {
                totalSleepSec += Duration.between(record.startTime, record.endTime).seconds
            }
            sleepHours = totalSleepSec / 3600.0
            
            // Map sleep duration to qualitative score
            sleepQuality = when {
                sleepHours >= 7.0 -> "Good"
                sleepHours >= 6.0 -> "Average"
                sleepHours > 0.0 -> "Poor"
                else -> "Unknown"
            }
            Log.d("HealthConnectManager", "Sleep fetched: $sleepHours hrs ($sleepQuality)")
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Error fetching sleep: ${e.message}")
        }

        // 4. Read Heart Rate
        try {
            val hrRequest = ReadRecordsRequest(
                recordType = HeartRateRecord::class,
                timeRangeFilter = timeFilter
            )
            val hrResponse = client.readRecords(hrRequest)
            var sumHr = 0L
            var hrCount = 0
            for (record in hrResponse.records) {
                for (sample in record.samples) {
                    sumHr += sample.beatsPerMinute
                    hrCount++
                }
            }
            if (hrCount > 0) {
                heartRate = (sumHr / hrCount).toInt()
            }
            Log.d("HealthConnectManager", "Avg heart rate calculated: $heartRate")
        } catch (e: Exception) {
            Log.e("HealthConnectManager", "Error fetching heart rate: ${e.message}")
        }

        return FitnessData(
            steps = steps,
            calories = calories,
            sleepHours = sleepHours,
            sleepQuality = sleepQuality,
            heartRate = heartRate,
            spo2 = 98.0 // Default/average SpO2 mapping
        )
    }
}
