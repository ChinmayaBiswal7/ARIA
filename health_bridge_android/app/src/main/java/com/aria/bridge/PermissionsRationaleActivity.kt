package com.aria.bridge

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class PermissionsRationaleActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Just finish immediately, or show permission request.
        finish()
    }
}
