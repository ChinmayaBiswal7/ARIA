package com.aria.bridge

import android.util.Log
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import kotlinx.coroutines.tasks.await

class FirestoreUploader {
    private val db: FirebaseFirestore by lazy { FirebaseFirestore.getInstance() }

    suspend fun uploadHealthData(
        steps: Int,
        calories: Double,
        sleepHours: Double,
        sleepQuality: String,
        heartRate: Int,
        spo2: Double
    ): Boolean {
        val data = hashMapOf(
            "steps" to steps,
            "calories" to calories,
            "sleep_hours" to sleepHours,
            "sleep_quality" to sleepQuality,
            "heart_rate" to heartRate,
            "spo2" to spo2,
            "timestamp" to (System.currentTimeMillis() / 1000.0)
        )
        return try {
            Log.d("FirestoreUploader", "Attempting upload to health/latest: $data")
            db.collection("health").document("latest")
                .set(data, SetOptions.merge())
                .await()
            Log.d("FirestoreUploader", "Upload successful.")
            true
        } catch (e: Exception) {
            Log.e("FirestoreUploader", "Upload failed: ${e.message}", e)
            false
        }
    }
}
