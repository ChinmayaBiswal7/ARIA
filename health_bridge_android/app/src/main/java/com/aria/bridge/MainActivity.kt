package com.aria.bridge

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.health.connect.client.PermissionController
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebViewAssetLoader
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.util.Log

class MainActivity : AppCompatActivity() {

    private lateinit var healthConnectManager: HealthConnectManager
    private lateinit var webView: WebView

    private val healthPermissionLauncher = registerForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        if (granted.containsAll(healthConnectManager.permissions)) {
            schedulePeriodicSync()
        } else {
            Toast.makeText(this, "Health permissions not fully granted.", Toast.LENGTH_SHORT).show()
        }
    }

    private val requestMicPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (!isGranted) {
            Toast.makeText(this, "Microphone permission is required for Voice UI", Toast.LENGTH_LONG).show()
        }
    }

    private val requestNotificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            Log.d("MainActivity", "Notification permission granted. Starting service...")
        } else {
            Toast.makeText(this, "Notification permission is needed for reliable background operation", Toast.LENGTH_LONG).show()
        }
        startAriaBridgeService()
    }

    private fun startAriaBridgeService() {
        try {
            val serviceIntent = Intent(this, AriaBridgeService::class.java)
            ContextCompat.startForegroundService(this, serviceIntent)
            Log.d("MainActivity", "Foreground service launch triggered.")
        } catch (e: Exception) {
            Log.e("MainActivity", "Failed to launch AriaBridgeService: ${e.message}", e)
        }
    }

    private fun checkBatteryOptimizations() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            val packageName = packageName
            if (!pm.isIgnoringBatteryOptimizations(packageName)) {
                try {
                    val intent = Intent().apply {
                        action = Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
                        data = Uri.parse("package:$packageName")
                    }
                    startActivity(intent)
                    Log.d("MainActivity", "Requested to ignore battery optimizations.")
                } catch (e: Exception) {
                    Log.e("MainActivity", "Failed to request battery optimizations ignore: ${e.message}", e)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Extend layout under notch/cutout area to eliminate white border letterboxing
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
            window.attributes.layoutInDisplayCutoutMode =
                android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }

        setContentView(R.layout.activity_main)

        healthConnectManager = HealthConnectManager(this)
        webView = findViewById(R.id.webView)

        setupWebView()

        // Request Android Microphone Permission for the UI
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestMicPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        checkHealthConnectStatus()

        // Request Notification permission for Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                startAriaBridgeService()
            }
        } else {
            startAriaBridgeService()
        }

        // Prompt to whitelist app from battery optimizations
        checkBatteryOptimizations()
    }

    private fun setupWebView() {
        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: android.webkit.WebResourceRequest
            ): android.webkit.WebResourceResponse? {
                return assetLoader.shouldInterceptRequest(request.url)
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                // Auto-grant all requested permissions for our internal local-assets WebView
                request.grant(request.resources)
            }
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = true
            allowContentAccess = true
        }

        // Expose AndroidInterface to let the web app toggle status bar/immersive fullscreen
        webView.addJavascriptInterface(object {
            @android.webkit.JavascriptInterface
            fun setImmersive(enabled: Boolean) {
                runOnUiThread {
                    if (enabled) {
                        this@MainActivity.requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
                        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
                            window.insetsController?.let { controller ->
                                controller.hide(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
                                controller.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                            }
                        } else {
                            @Suppress("DEPRECATION")
                            window.decorView.systemUiVisibility = (
                                android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                                or android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                                or android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
                            )
                        }
                    } else {
                        this@MainActivity.requestedOrientation = android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
                            window.insetsController?.show(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.navigationBars())
                        } else {
                            @Suppress("DEPRECATION")
                            window.decorView.systemUiVisibility = (
                                android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            )
                        }
                    }
                }
            }
        }, "AndroidInterface")

        webView.setBackgroundColor(android.graphics.Color.parseColor("#050505"))
        webView.loadUrl("https://appassets.androidplatform.net/assets/www/index.html")
    }

    private fun checkHealthConnectStatus() {
        lifecycleScope.launch {
            if (!healthConnectManager.isAvailable()) {
                Toast.makeText(this@MainActivity, "Health Connect not available on this device.", Toast.LENGTH_LONG).show()
                return@launch
            }

            if (healthConnectManager.hasPermissions()) {
                schedulePeriodicSync()
                // Sync on startup for good measure
                performInitialSync()
            } else {
                // Launch Health Connect permissions automatically
                healthPermissionLauncher.launch(healthConnectManager.permissions)
            }
        }
    }
    
    private fun performInitialSync() {
        lifecycleScope.launch {
            try {
                val fitnessData = healthConnectManager.readFitnessData()
                val uploader = FirestoreUploader()
                uploader.uploadHealthData(
                    steps = fitnessData.steps,
                    calories = fitnessData.calories,
                    sleepHours = fitnessData.sleepHours,
                    sleepQuality = fitnessData.sleepQuality,
                    heartRate = fitnessData.heartRate,
                    spo2 = fitnessData.spo2
                )
            } catch (e: Exception) {
                // Ignore silent background sync errors on startup
            }
        }
    }

    private fun schedulePeriodicSync() {
        val syncRequest = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
            .build()
            
        WorkManager.getInstance(applicationContext).enqueueUniquePeriodicWork(
            "AriaHealthBridgeSync",
            ExistingPeriodicWorkPolicy.KEEP,
            syncRequest
        )
    }
}
