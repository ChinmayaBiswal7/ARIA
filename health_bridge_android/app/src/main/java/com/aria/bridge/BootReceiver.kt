package com.aria.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.ContextCompat

class BootReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "BootReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        Log.d(TAG, "onReceive action: ${intent.action}")
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Log.d(TAG, "Reboot detected. Launching AriaBridgeService...")
            try {
                val serviceIntent = Intent(context, AriaBridgeService::class.java)
                ContextCompat.startForegroundService(context, serviceIntent)
                Log.d(TAG, "AriaBridgeService started from boot.")
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start AriaBridgeService on boot: ${e.message}", e)
            }
        }
    }
}
