package com.aria.bridge

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.google.firebase.firestore.FirebaseFirestore

/**
 * Handles inline Approve / Reject taps directly from the FCM approval notification.
 * Updates Firestore approvals/latest.status so ARIA's polling loop picks it up immediately.
 * Dismisses the notification after the decision is recorded.
 */
class ApprovalActionReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_APPROVE = "com.aria.bridge.APPROVE_ACTION"
        const val ACTION_REJECT  = "com.aria.bridge.REJECT_ACTION"
        const val NOTIF_ID       = 8001
    }

    override fun onReceive(context: Context, intent: Intent) {
        val decision = when (intent.action) {
            ACTION_APPROVE -> "approved"
            ACTION_REJECT  -> "rejected"
            else           -> return
        }

        Log.d("ApprovalReceiver", "User tapped $decision from notification")

        val db = FirebaseFirestore.getInstance()
        db.collection("approvals").document("latest")
            .update("status", decision)
            .addOnSuccessListener {
                Log.d("ApprovalReceiver", "Firestore updated: status=$decision")
            }
            .addOnFailureListener { e ->
                Log.e("ApprovalReceiver", "Firestore update failed: ${e.message}")
            }

        // Dismiss the ongoing approval notification
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.cancel(NOTIF_ID)

        // Show brief toast-style feedback via a new notification (auto-cancels in 3s)
        val feedbackTitle = if (decision == "approved") "✅ Approved" else "❌ Rejected"
        val feedbackBody  = if (decision == "approved")
            "ARIA will proceed with the action."
        else
            "ARIA action has been rejected."

        val feedbackNotif = androidx.core.app.NotificationCompat.Builder(
            context, AriaMessagingService.CHANNEL_APPROVALS
        )
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(feedbackTitle)
            .setContentText(feedbackBody)
            .setPriority(androidx.core.app.NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()

        nm.notify(8002, feedbackNotif)
    }
}
