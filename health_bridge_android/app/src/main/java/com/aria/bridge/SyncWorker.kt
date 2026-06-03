package com.aria.bridge

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        Log.d("SyncWorker", "Background sync worker started execution.")
        
        val healthManager = HealthConnectManager(applicationContext)
        
        if (!healthManager.isAvailable()) {
            Log.e("SyncWorker", "Health Connect SDK not available on this device.")
            return Result.failure()
        }

        if (!healthManager.hasPermissions()) {
            Log.w("SyncWorker", "Read permissions are missing. Postponing sync.")
            return Result.retry()
        }

        return try {
            val fitnessData = healthManager.readFitnessData()
            val uploader = FirestoreUploader()
            
            val success = uploader.uploadHealthData(
                steps = fitnessData.steps,
                calories = fitnessData.calories,
                sleepHours = fitnessData.sleepHours,
                sleepQuality = fitnessData.sleepQuality,
                heartRate = fitnessData.heartRate,
                spo2 = fitnessData.spo2
            )

            if (success) {
                Log.d("SyncWorker", "Metrics successfully posted to Firestore.")
                Result.success()
            } else {
                Log.w("SyncWorker", "Firestore write failed, scheduling retry.")
                Result.retry()
            }
        } catch (e: Exception) {
            Log.e("SyncWorker", "Fatal error during background sync: ${e.message}", e)
            Result.retry()
        }
    }
}
