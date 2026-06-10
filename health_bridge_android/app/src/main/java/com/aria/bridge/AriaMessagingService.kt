package com.aria.bridge

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import java.net.HttpURLConnection
import java.net.URL

class AriaMessagingService : FirebaseMessagingService() {

    companion object {
        const val CHANNEL_SECURITY   = "aria_security_alerts"
        const val CHANNEL_APPROVALS  = "aria_approvals"
    }

    override fun onMessageReceived(message: RemoteMessage) {
        Log.d("AriaMessagingService", "Message received from: ${message.from}")

        val title    = message.notification?.title ?: message.data["title"] ?: "ARIA Alert"
        val body     = message.notification?.body  ?: message.data["body"]  ?: ""
        val msgType  = message.data["type"] ?: ""
        val imageUrl = message.data["security_image_url"] ?: message.data["image_url"]

        if (msgType == "approval_request") {
            showApprovalNotification(
                title    = title,
                body     = body,
                actionTag = message.data["action_tag"] ?: "",
                riskLevel = message.data["risk_level"] ?: "HIGH"
            )
        } else {
            showSecurityNotification(title, body, imageUrl)
        }
    }

    // ── Approval Notification ────────────────────────────────────────────────
    private fun showApprovalNotification(
        title: String,
        body: String,
        actionTag: String,
        riskLevel: String
    ) {
        val notificationManager = getSystemService(NotificationManager::class.java)

        // Create high-priority approval channel
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_APPROVALS,
                "ARIA Approval Requests",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 300, 200, 300, 200, 300)
                enableLights(true)
                lightColor = Color.parseColor("#F59E0B")
                lockscreenVisibility = NotificationCompat.VISIBILITY_PUBLIC
                description = "Approval requests for HIGH/CRITICAL ARIA actions"
            }
            notificationManager.createNotificationChannel(channel)
        }

        // PendingIntent that opens MainActivity and navigates to the Approvals tab
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("open_tab", "approvals")
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 1001, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Approve action
        val approveIntent = Intent(this, ApprovalActionReceiver::class.java).apply {
            action = ApprovalActionReceiver.ACTION_APPROVE
        }
        val approvePending = PendingIntent.getBroadcast(
            this, 1002, approveIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Reject action
        val rejectIntent = Intent(this, ApprovalActionReceiver::class.java).apply {
            action = ApprovalActionReceiver.ACTION_REJECT
        }
        val rejectPending = PendingIntent.getBroadcast(
            this, 1003, rejectIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notif = NotificationCompat.Builder(this, CHANNEL_APPROVALS)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(pendingIntent)
            .setAutoCancel(false)                       // stays until user acts
            .setOngoing(true)                           // can't swipe away
            .addAction(android.R.drawable.ic_menu_send, "✅ Approve", approvePending)
            .addAction(android.R.drawable.ic_delete,    "❌ Reject",  rejectPending)
            .build()

        notificationManager.notify(8001, notif)        // fixed ID so it's updated/dismissed cleanly
        Log.d("AriaMessagingService", "Approval notification shown for: $actionTag ($riskLevel)")
    }

    // ── Security / Generic Notification ─────────────────────────────────────
    private fun showSecurityNotification(
        title: String,
        body: String,
        imageUrl: String?
    ) {
        Log.d("AriaMessagingService", "Showing security notification: $title - $body")

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("open_security", true)
            putExtra("security_image_url", imageUrl)
        }

        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notificationManager = getSystemService(NotificationManager::class.java)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_SECURITY,
                "ARIA Security Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                enableVibration(true)
                enableLights(true)
                lightColor = Color.RED
                description = "Security Alert Notifications for ARIA"
            }
            notificationManager.createNotificationChannel(channel)
        }

        val notificationBuilder = NotificationCompat.Builder(this, CHANNEL_SECURITY)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)

        if (!imageUrl.isNullOrEmpty()) {
            val bitmap = downloadBitmap(imageUrl)
            if (bitmap != null) {
                notificationBuilder.setLargeIcon(bitmap)
                notificationBuilder.setStyle(
                    NotificationCompat.BigPictureStyle()
                        .bigPicture(bitmap)
                        .bigLargeIcon(null as Bitmap?)
                )
            }
        }

        notificationManager.notify(
            System.currentTimeMillis().toInt(),
            notificationBuilder.build()
        )
    }

    private fun downloadBitmap(urlStr: String): Bitmap? {
        return try {
            val url = URL(urlStr)
            val connection = url.openConnection() as HttpURLConnection
            connection.doInput = true
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.connect()
            val input = connection.inputStream
            BitmapFactory.decodeStream(input)
        } catch (e: Exception) {
            Log.e("AriaMessagingService", "Error downloading notification image: ${e.message}", e)
            null
        }
    }

    override fun onNewToken(token: String) {
        Log.d("AriaMessagingService", "Refreshed token: $token")
        val db = FirebaseFirestore.getInstance()
        val data = hashMapOf("token" to token)
        db.collection("aria_config")
            .document("fcm")
            .set(data)
            .addOnSuccessListener {
                Log.d("AriaMessagingService", "Token saved to Firestore successfully.")
            }
            .addOnFailureListener { e ->
                Log.e("AriaMessagingService", "Error saving token: ${e.message}", e)
            }
    }
}
