package com.aria.bridge

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import android.view.Menu
import android.view.View
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
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
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.ListenerRegistration
import com.google.firebase.firestore.Query
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.tasks.await
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.io.File
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import com.google.firebase.storage.FirebaseStorage

class MainActivity : AppCompatActivity() {

    private lateinit var healthConnectManager: HealthConnectManager
    private lateinit var webView: WebView

    // Scanner Views
    private lateinit var layoutScanner: ScrollView
    private lateinit var btnScanCamera: Button
    private lateinit var btnScanGallery: Button
    private lateinit var scanPreviewImage: ImageView
    private lateinit var textOcrConfidence: TextView
    private lateinit var editScanTitle: EditText
    private lateinit var editScanText: EditText
    private lateinit var btnIngestScan: Button
    private var tempPhotoUri: Uri? = null

    // Native Tab Views
    private lateinit var bottomNavigation: BottomNavigationView
    private lateinit var layoutAlerts: LinearLayout
    private lateinit var layoutIncidentsContainer: LinearLayout
    private lateinit var layoutMissions: ScrollView
    private lateinit var layoutApprovals: LinearLayout
    private lateinit var layoutCareer: LinearLayout
    private lateinit var layoutCareersContainer: LinearLayout
    private lateinit var textNoCareers: TextView

    // Mission Monitor Views
    private lateinit var textNoMissions: TextView
    private lateinit var cardActiveMission: LinearLayout
    private lateinit var missionGoal: TextView
    private lateinit var missionStatus: TextView
    private lateinit var missionStepsTrace: TextView
    private lateinit var layoutMissionControls: LinearLayout
    private lateinit var btnPauseMission: Button
    private lateinit var btnResumeMission: Button
    private lateinit var btnCancelMission: Button

    // Approval Queue Views
    private lateinit var textNoApprovals: TextView
    private lateinit var cardPendingApproval: LinearLayout
    private lateinit var approvalRiskLevel: TextView
    private lateinit var approvalActionTag: TextView
    private lateinit var approvalDescription: TextView
    private lateinit var approvalTimestamp: TextView
    private lateinit var btnApproveRequest: Button
    private lateinit var btnRejectRequest: Button

    // Firestore listener registrations
    private var activeTasksListenerRegistration: ListenerRegistration? = null
    private var approvalsListenerRegistration: ListenerRegistration? = null
    private var incidentsListenerRegistration: ListenerRegistration? = null
    private var careerListenerRegistration: ListenerRegistration? = null
    private var profileInsightsListenerRegistration: ListenerRegistration? = null

    // Profile Insights Views
    private lateinit var layoutProfileInsights: LinearLayout
    private lateinit var containerStrengths: LinearLayout
    private lateinit var containerFocusChips: LinearLayout
    private lateinit var containerLedger: LinearLayout

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

    private val requestCameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            launchCamera()
        } else {
            Toast.makeText(this, "Camera permission is required to scan documents.", Toast.LENGTH_LONG).show()
        }
    }

    private val pickImageLauncher = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let { processSelectedImage(it) }
    }

    private val captureImageLauncher = registerForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success: Boolean ->
        if (success) {
            tempPhotoUri?.let { processSelectedImage(it) }
        } else {
            Toast.makeText(this, "Camera capture cancelled.", Toast.LENGTH_SHORT).show()
        }
    }

    private fun launchCamera() {
        tempPhotoUri = getTempPhotoUri()
        tempPhotoUri?.let { captureImageLauncher.launch(it) }
    }

    private fun getTempPhotoUri(): Uri {
        val cacheDir = File(cacheDir, "shared_images")
        if (!cacheDir.exists()) cacheDir.mkdirs()
        val file = File(cacheDir, "temp_scan.jpg")
        return androidx.core.content.FileProvider.getUriForFile(
            this,
            "com.aria.bridge.fileprovider",
            file
        )
    }

    private fun processSelectedImage(uri: Uri) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val inputStream = contentResolver.openInputStream(uri)
                val bitmap = BitmapFactory.decodeStream(inputStream)
                inputStream?.close()

                if (bitmap == null) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@MainActivity, "Failed to load image.", Toast.LENGTH_SHORT).show()
                    }
                    return@launch
                }

                // Show preview and do OCR
                withContext(Dispatchers.Main) {
                    scanPreviewImage.setImageBitmap(bitmap)
                    scanPreviewImage.visibility = View.VISIBLE
                    textOcrConfidence.visibility = View.GONE
                    editScanText.setText("Performing OCR... please wait.")
                    btnIngestScan.isEnabled = false
                }

                val image = InputImage.fromBitmap(bitmap, 0)
                val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

                recognizer.process(image)
                    .addOnSuccessListener { visionText ->
                        val text = visionText.text
                        // Calculate average confidence
                        var totalConf = 0.0
                        var totalElements = 0
                        for (block in visionText.textBlocks) {
                            for (line in block.lines) {
                                val confidence = line.confidence ?: 0f
                                if (confidence > 0) {
                                    totalConf += confidence
                                    totalElements++
                                }
                            }
                        }
                        val avgConf = if (totalElements > 0) totalConf / totalElements else 0.0
                        
                        lifecycleScope.launch(Dispatchers.Main) {
                            textOcrConfidence.text = String.format(Locale.US, "OCR Confidence: %.0f%%", avgConf * 100)
                            textOcrConfidence.visibility = View.VISIBLE
                            
                            editScanText.setText(text)
                            
                            val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault())
                            editScanTitle.setText("Scan ${sdf.format(Date())}")

                            if (avgConf < 0.60 && text.trim().isNotEmpty()) {
                                Toast.makeText(this@MainActivity, "⚠️ Low OCR Quality. Please retake image.", Toast.LENGTH_LONG).show()
                                textOcrConfidence.setTextColor(android.graphics.Color.RED)
                                btnIngestScan.isEnabled = false
                            } else if (text.trim().isEmpty()) {
                                Toast.makeText(this@MainActivity, "No text detected.", Toast.LENGTH_SHORT).show()
                                btnIngestScan.isEnabled = false
                            } else {
                                textOcrConfidence.setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                                btnIngestScan.isEnabled = true
                                btnIngestScan.setOnClickListener {
                                    uploadAndIngestDocument(uri, text, editScanTitle.text.toString(), avgConf)
                                }
                            }
                        }
                    }
                    .addOnFailureListener { e ->
                        lifecycleScope.launch(Dispatchers.Main) {
                            editScanText.setText("")
                            Toast.makeText(this@MainActivity, "OCR Failed: ${e.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "Error loading image: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun uploadAndIngestDocument(uri: Uri, text: String, title: String, confidence: Double) {
        btnIngestScan.isEnabled = false
        btnIngestScan.text = "Uploading image..."

        lifecycleScope.launch(Dispatchers.IO) {
            try {
                // 1. Upload original photo to Firebase Storage
                val storageRef = FirebaseStorage.getInstance().reference
                val scanId = "doc_${System.currentTimeMillis()}"
                val imageRef = storageRef.child("scans/$scanId.jpg")

                val inputStream = contentResolver.openInputStream(uri)
                val bytes = inputStream?.readBytes()
                inputStream?.close()

                if (bytes == null) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@MainActivity, "Failed to read image data for upload.", Toast.LENGTH_SHORT).show()
                        btnIngestScan.isEnabled = true
                        btnIngestScan.text = "Ingest to Knowledge Vault"
                    }
                    return@launch
                }

                val uploadTask = imageRef.putBytes(bytes).await()
                val imagePath = imageRef.path

                // 2. Upload structured scan record to Firestore
                withContext(Dispatchers.Main) {
                    btnIngestScan.text = "Saving document..."
                }

                val db = FirebaseFirestore.getInstance()
                val docData = hashMapOf(
                    "id" to scanId,
                    "title" to title,
                    "text" to text,
                    "ocr_confidence" to confidence,
                    "image_path" to imagePath,
                    "timestamp" to (System.currentTimeMillis() / 1000.0),
                    "synced_to_pc" to false,
                    "created_at" to SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date()),
                    "source" to "mobile_scan"
                )

                db.collection("scanned_documents").document(scanId).set(docData).await()

                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "Ingestion request queued! Syncing with ARIA...", Toast.LENGTH_LONG).show()
                    btnIngestScan.text = "Ingested ✓"
                    btnIngestScan.isEnabled = false
                    
                    // Clear inputs
                    editScanText.setText("")
                    editScanTitle.setText("")
                    scanPreviewImage.visibility = View.GONE
                    textOcrConfidence.visibility = View.GONE
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "Upload failed: ${e.message}", Toast.LENGTH_LONG).show()
                    btnIngestScan.isEnabled = true
                    btnIngestScan.text = "Ingest to Knowledge Vault"
                    Log.e("MainActivity", "Failed to ingest scan", e)
                }
            }
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

        // Native Tabs Setup
        bottomNavigation = findViewById(R.id.bottomNavigation)
        bottomNavigation.visibility = android.view.View.GONE // Hide until splash screen completes in WebView
        layoutAlerts = findViewById(R.id.layoutAlerts)
        layoutIncidentsContainer = findViewById(R.id.layoutIncidentsContainer)
        layoutMissions = findViewById(R.id.layoutMissions)
        layoutApprovals = findViewById(R.id.layoutApprovals)
        layoutCareer = findViewById(R.id.layoutCareer)
        layoutCareersContainer = findViewById(R.id.layoutCareersContainer)
        textNoCareers = findViewById(R.id.textNoCareers)
        layoutProfileInsights = findViewById(R.id.layoutProfileInsights)
        containerStrengths = findViewById(R.id.containerStrengths)
        containerFocusChips = findViewById(R.id.containerFocusChips)
        containerLedger = findViewById(R.id.containerLedger)

        // Scanner Views Initialization
        layoutScanner = findViewById(R.id.layoutScanner)
        btnScanCamera = findViewById(R.id.btnScanCamera)
        btnScanGallery = findViewById(R.id.btnScanGallery)
        scanPreviewImage = findViewById(R.id.scanPreviewImage)
        textOcrConfidence = findViewById(R.id.textOcrConfidence)
        editScanTitle = findViewById(R.id.editScanTitle)
        editScanText = findViewById(R.id.editScanText)
        btnIngestScan = findViewById(R.id.btnIngestScan)

        // Configure Bottom Navigation menu programmatically
        val menu = bottomNavigation.menu
        menu.add(Menu.NONE, ITEM_WEBVIEW, Menu.NONE, "Remote").setIcon(android.R.drawable.ic_menu_slideshow)
        menu.add(Menu.NONE, ITEM_SCANNER, Menu.NONE, "Scanner").setIcon(android.R.drawable.ic_menu_camera)
        menu.add(Menu.NONE, ITEM_ALERTS, Menu.NONE, "Alerts").setIcon(android.R.drawable.ic_dialog_alert)
        menu.add(Menu.NONE, ITEM_MISSIONS, Menu.NONE, "Missions").setIcon(android.R.drawable.ic_menu_today)
        menu.add(Menu.NONE, ITEM_APPROVALS, Menu.NONE, "Approvals").setIcon(android.R.drawable.ic_menu_info_details)
        menu.add(Menu.NONE, ITEM_CAREER, Menu.NONE, "Career").setIcon(android.R.drawable.ic_menu_myplaces)

        bottomNavigation.setOnItemSelectedListener { item ->
            webView.visibility = if (item.itemId == ITEM_WEBVIEW) View.VISIBLE else View.GONE
            layoutScanner.visibility = if (item.itemId == ITEM_SCANNER) View.VISIBLE else View.GONE
            layoutAlerts.visibility = if (item.itemId == ITEM_ALERTS) View.VISIBLE else View.GONE
            layoutMissions.visibility = if (item.itemId == ITEM_MISSIONS) View.VISIBLE else View.GONE
            layoutApprovals.visibility = if (item.itemId == ITEM_APPROVALS) View.VISIBLE else View.GONE
            layoutCareer.visibility = if (item.itemId == ITEM_CAREER) View.VISIBLE else View.GONE
            true
        }




        // Bind Alerts checkin
        findViewById<Button>(R.id.btnLiveCheckin).setOnClickListener { sendCustomCommandNative("laptop check in") }

        // Setup Scanner click listeners
        btnScanGallery.setOnClickListener {
            pickImageLauncher.launch("image/*")
        }

        btnScanCamera.setOnClickListener {
            val cameraPermission = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            if (cameraPermission != PackageManager.PERMISSION_GRANTED) {
                requestCameraPermissionLauncher.launch(Manifest.permission.CAMERA)
            } else {
                launchCamera()
            }
        }

        // Mission Views Setup
        textNoMissions = findViewById(R.id.textNoMissions)
        cardActiveMission = findViewById(R.id.cardActiveMission)
        missionGoal = findViewById(R.id.missionGoal)
        missionStatus = findViewById(R.id.missionStatus)
        missionStepsTrace = findViewById(R.id.missionStepsTrace)
        layoutMissionControls = findViewById(R.id.layoutMissionControls)

        btnPauseMission = findViewById(R.id.btnPauseMission)
        btnResumeMission = findViewById(R.id.btnResumeMission)
        btnCancelMission = findViewById(R.id.btnCancelMission)

        btnPauseMission.setOnClickListener { sendCustomCommandNative("laptop pause task") }
        btnResumeMission.setOnClickListener { sendCustomCommandNative("laptop resume task") }
        btnCancelMission.setOnClickListener { sendCustomCommandNative("laptop cancel task") }

        // Approval Views Setup
        textNoApprovals    = findViewById(R.id.textNoApprovals)
        cardPendingApproval = findViewById(R.id.cardPendingApproval)
        approvalRiskLevel  = findViewById(R.id.approvalRiskLevel)
        approvalActionTag  = findViewById(R.id.approvalActionTag)
        approvalDescription = findViewById(R.id.approvalDescription)
        approvalTimestamp  = findViewById(R.id.approvalTimestamp)
        btnApproveRequest  = findViewById(R.id.btnApproveRequest)
        btnRejectRequest   = findViewById(R.id.btnRejectRequest)

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

        // Fetch and register FCM token
        registerFcmToken()

        // Start Firestore Listener Loops
        startFirestoreListeners()

        // Handle security intent if launched from notification
        handleSecurityIntent(intent)
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

            @android.webkit.JavascriptInterface
            fun onSplashCompleted() {
                runOnUiThread {
                    bottomNavigation.visibility = android.view.View.VISIBLE
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
                performInitialSync()
            } else {
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

    private fun registerFcmToken() {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (!task.isSuccessful) {
                Log.w("MainActivity", "Fetching FCM registration token failed", task.exception)
                return@addOnCompleteListener
            }
            val token = task.result
            Log.d("MainActivity", "FCM Token fetched: $token")
            if (!token.isNullOrEmpty()) {
                val db = FirebaseFirestore.getInstance()
                db.collection("aria_config")
                    .document("fcm")
                    .set(hashMapOf("token" to token))
                    .addOnSuccessListener {
                        Log.d("MainActivity", "FCM token saved to Firestore successfully.")
                    }
                    .addOnFailureListener { e ->
                        Log.e("MainActivity", "Failed to save FCM token to Firestore: ${e.message}")
                    }
            }
        }
    }

    private fun handleSecurityIntent(intent: Intent?) {
        if (intent == null) return

        // Deep-link: open_tab=approvals (from approval FCM notification tap)
        if (intent.getStringExtra("open_tab") == "approvals") {
            Log.d("MainActivity", "Launched from approval notification – switching to Approvals tab")
            // Switch visibility
            webView.visibility          = android.view.View.GONE
            layoutAlerts.visibility     = android.view.View.GONE
            layoutMissions.visibility   = android.view.View.GONE
            layoutApprovals.visibility  = android.view.View.VISIBLE
            layoutCareer.visibility     = android.view.View.GONE
            // Sync bottom nav selection
            bottomNavigation.selectedItemId = ITEM_APPROVALS
            return
        }

        // Deep-link: open_security=true (from security alert FCM notification tap)
        if (intent.getBooleanExtra("open_security", false)) {
            val imageUrl = intent.getStringExtra("security_image_url")
            Log.d("MainActivity", "Launched/Resumed with Security Alert. Image: $imageUrl")
            showNativeSecurityAlertDialog(imageUrl)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleSecurityIntent(intent)
    }

    companion object {
        private const val ITEM_WEBVIEW = 1
        private const val ITEM_SCANNER = 2
        private const val ITEM_ALERTS = 3
        private const val ITEM_MISSIONS = 4
        private const val ITEM_APPROVALS = 5
        private const val ITEM_CAREER = 6
    }

    private fun sendCustomCommandNative(commandText: String) {
        val db = FirebaseFirestore.getInstance()
        val commandData = hashMapOf(
            "id" to "cmd_${System.currentTimeMillis()}",
            "source" to "phone",
            "text" to commandText,
            "timestamp" to System.currentTimeMillis()
        )
        db.collection("commands").document("latest").set(commandData)
            .addOnSuccessListener {
                Toast.makeText(this, "Sent: \"$commandText\"", Toast.LENGTH_SHORT).show()
            }
            .addOnFailureListener { e ->
                Toast.makeText(this, "Failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
    }

    private fun startFirestoreListeners() {
        val db = FirebaseFirestore.getInstance()

        // 1. Listen to active tasks (missions)
        activeTasksListenerRegistration = db.collection("active_tasks").document("latest")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to active tasks failed: $error")
                    return@addSnapshotListener
                }
                if (snapshot != null && snapshot.exists() && snapshot.getString("status") != null) {
                    textNoMissions.visibility = View.GONE
                    cardActiveMission.visibility = View.VISIBLE
                    layoutMissionControls.visibility = View.VISIBLE

                    val goal = snapshot.getString("goal") ?: ""
                    val status = snapshot.getString("status") ?: ""
                    
                    missionGoal.text = "Goal: $goal"
                    missionStatus.text = "Status: $status"

                    // Parse steps trace graph
                    val steps = snapshot.get("steps") as? List<Map<String, Any>>
                    val sb = StringBuilder("Steps Graph:\n")
                    steps?.forEach { step ->
                        val num = step["step_number"] ?: 0
                        val act = step["action"] ?: ""
                        val tgt = step["target"] ?: ""
                        val stat = step["status"] ?: ""
                        sb.append(" ├── Step $num: $act $tgt -> $stat\n")
                    }
                    missionStepsTrace.text = sb.toString()
                } else {
                    textNoMissions.visibility = View.VISIBLE
                    cardActiveMission.visibility = View.GONE
                    layoutMissionControls.visibility = View.GONE
                }
            }

        // 2. Listen to pending approvals
        approvalsListenerRegistration = db.collection("approvals").document("latest")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to approvals failed: $error")
                    return@addSnapshotListener
                }
                if (snapshot != null && snapshot.exists() && snapshot.getString("status") == "pending") {
                    textNoApprovals.visibility = View.GONE
                    cardPendingApproval.visibility = View.VISIBLE

                    val risk = snapshot.getString("risk_level") ?: "HIGH"
                    val tag  = snapshot.getString("action_tag") ?: ""
                    val desc = snapshot.getString("description")
                        ?: "ARIA wants to: $tag"
                    val tsRaw = snapshot.getDouble("timestamp")
                    val tsStr = if (tsRaw != null) {
                        val sdf = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault())
                        "Requested at " + sdf.format(java.util.Date((tsRaw * 1000).toLong()))
                    } else "Requested just now"

                    // Risk badge colour
                    val riskColor = if (risk == "CRITICAL") "#EF4444" else "#F59E0B"
                    approvalRiskLevel.text = "⚠ $risk RISK"
                    approvalRiskLevel.setTextColor(android.graphics.Color.parseColor(riskColor))
                    approvalActionTag.text  = tag
                    approvalDescription.text = desc
                    approvalTimestamp.text   = tsStr

                    btnApproveRequest.setOnClickListener {
                        db.collection("approvals").document("latest").update("status", "approved")
                        textNoApprovals.visibility  = View.VISIBLE
                        cardPendingApproval.visibility = View.GONE
                    }
                    btnRejectRequest.setOnClickListener {
                        db.collection("approvals").document("latest").update("status", "rejected")
                        textNoApprovals.visibility  = View.VISIBLE
                        cardPendingApproval.visibility = View.GONE
                    }
                } else {
                    textNoApprovals.visibility = View.VISIBLE
                    cardPendingApproval.visibility = View.GONE
                }
            }

        // 3. Listen to incident history (security)
        incidentsListenerRegistration = db.collection("security_incidents")
            .orderBy("timestamp", Query.Direction.DESCENDING)
            .limit(10)
            .addSnapshotListener { snapshots, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to security incidents failed: $error")
                    return@addSnapshotListener
                }
                if (snapshots != null) {
                    layoutIncidentsContainer.removeAllViews()
                    for (doc in snapshots) {
                        val title = doc.getString("type") ?: "Unknown Incident"
                        val timestamp = doc.getString("timestamp") ?: ""
                        val resolved = doc.getBoolean("resolved") ?: false
                        val images = doc.get("images") as? List<String>

                        val cardView = layoutInflater.inflate(R.layout.dialog_security_alert, null)
                        cardView.background = ContextCompat.getDrawable(this, R.drawable.card_background)
                        
                        val titleText = cardView.findViewById<TextView>(R.id.alertTitle)
                        titleText.text = if (resolved) "✓ RESOLVED: $title" else "🚨 ACTIVE: $title"
                        titleText.setTextColor(
                            if (resolved) android.graphics.Color.GREEN else android.graphics.Color.RED
                        )
                        cardView.findViewById<TextView>(R.id.alertBody).text = "Time: $timestamp"

                        val iv = cardView.findViewById<ImageView>(R.id.alertImageView)
                        if (!images.isNullOrEmpty()) {
                            loadUrlIntoImageView(images.first(), iv)
                            iv.visibility = View.VISIBLE
                        } else {
                            iv.visibility = View.GONE
                        }

                        val dismissBtn = cardView.findViewById<Button>(R.id.btnDismiss)
                        dismissBtn.text = if (resolved) "resolved" else "Mark Resolved"
                        dismissBtn.isEnabled = !resolved
                        dismissBtn.setOnClickListener {
                            db.collection("security_incidents").document(doc.id).update(
                                "resolved", true,
                                "resolved_at", SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date())
                            )
                        }

                        cardView.findViewById<LinearLayout>(R.id.layoutAlertActions).visibility = View.GONE // Hide response buttons in inbox list items
                        
                        val lp = LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT,
                            LinearLayout.LayoutParams.WRAP_CONTENT
                        )
                        lp.setMargins(0, 0, 0, 24)
                        cardView.layoutParams = lp
                        
                        layoutIncidentsContainer.addView(cardView)
                    }
                }
            }

        // 4. Listen to career opportunities
        careerListenerRegistration = db.collection("career_opportunities").document("latest")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to career opportunities failed: $error")
                    return@addSnapshotListener
                }
                if (snapshot != null && snapshot.exists()) {
                    val opps = snapshot.get("opportunities") as? List<Map<String, Any>>
                    if (!opps.isNullOrEmpty()) {
                        textNoCareers.visibility = View.GONE
                        layoutCareersContainer.removeAllViews()
                        
                        for (opp in opps) {
                            val id = (opp["id"] as? Number)?.toDouble() ?: 0.0
                            val company = opp["company"] as? String ?: ""
                            val role = opp["role"] as? String ?: ""
                            val location = opp["location"] as? String
                            val applyLink = opp["apply_link"] as? String
                            val postedDate = opp["posted_date"] as? String
                            val matchScore = (opp["match_score"] as? Number)?.toDouble()
                            val status = opp["status"] as? String ?: "bookmarked"
                            val deadline = opp["deadline"] as? String
                            
                            val cardView = LinearLayout(this@MainActivity).apply {
                                orientation = LinearLayout.VERTICAL
                                val paddingPx = (16 * resources.displayMetrics.density).toInt()
                                setPadding(paddingPx, paddingPx, paddingPx, paddingPx)
                                background = ContextCompat.getDrawable(this@MainActivity, R.drawable.card_background)
                                
                                val lp = LinearLayout.LayoutParams(
                                    LinearLayout.LayoutParams.MATCH_PARENT,
                                    LinearLayout.LayoutParams.WRAP_CONTENT
                                ).apply {
                                    setMargins(0, 0, 0, (16 * resources.displayMetrics.density).toInt())
                                }
                                layoutParams = lp
                            }
                            
                            val textTitle = TextView(this@MainActivity).apply {
                                text = "$company\n$role"
                                setTextColor(android.graphics.Color.WHITE)
                                textSize = 15f
                                setTypeface(null, android.graphics.Typeface.BOLD)
                            }
                            cardView.addView(textTitle)
                            
                            val subInfo = "Location: ${location ?: "Remote"}" + 
                                          if (!deadline.isNullOrEmpty()) " | Deadline: $deadline" else ""
                            val textSub = TextView(this@MainActivity).apply {
                                text = subInfo
                                setTextColor(android.graphics.Color.parseColor("#A3B8CC"))
                                textSize = 12f
                                setPadding(0, 4, 0, 8)
                            }
                            cardView.addView(textSub)
                            
                            if (matchScore != null) {
                                val textScore = TextView(this@MainActivity).apply {
                                    text = "Match Score: ${matchScore.toInt()}%"
                                    setTextColor(if (matchScore >= 70) android.graphics.Color.GREEN else android.graphics.Color.parseColor("#E59866"))
                                    textSize = 13f
                                    setTypeface(null, android.graphics.Typeface.BOLD)
                                    setPadding(0, 0, 0, 8)
                                }
                                cardView.addView(textScore)
                            }
                            
                            val btnContainer = LinearLayout(this@MainActivity).apply {
                                orientation = LinearLayout.HORIZONTAL
                            }
                            
                            if (!applyLink.isNullOrEmpty()) {
                                val btnApply = Button(this@MainActivity).apply {
                                    text = "Apply Link"
                                    backgroundTintList = ContextCompat.getColorStateList(this@MainActivity, android.R.color.holo_blue_dark)
                                    setTextColor(android.graphics.Color.WHITE)
                                    textSize = 11f
                                    setOnClickListener {
                                        try {
                                            val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse(applyLink))
                                            startActivity(browserIntent)
                                        } catch (e: Exception) {
                                            Toast.makeText(this@MainActivity, "Invalid URL", Toast.LENGTH_SHORT).show()
                                        }
                                    }
                                    layoutParams = LinearLayout.LayoutParams(
                                        0,
                                        LinearLayout.LayoutParams.WRAP_CONTENT,
                                        1.0f
                                    ).apply {
                                        setMargins(0, 0, 8, 0)
                                    }
                                }
                                btnContainer.addView(btnApply)
                            }
                            
                            val btnStatus = Button(this@MainActivity).apply {
                                text = status.uppercase()
                                backgroundTintList = ContextCompat.getColorStateList(this@MainActivity, android.R.color.darker_gray)
                                setTextColor(android.graphics.Color.WHITE)
                                textSize = 11f
                                setOnClickListener {
                                    val nextStatus = when (status) {
                                        "bookmarked" -> "applied"
                                        "applied" -> "interviewing"
                                        "interviewing" -> "offered"
                                        "offered" -> "rejected"
                                        else -> "bookmarked"
                                    }
                                    updateFirestoreOpportunityStatus(id, nextStatus)
                                }
                                layoutParams = LinearLayout.LayoutParams(
                                    0,
                                    LinearLayout.LayoutParams.WRAP_CONTENT,
                                    1.0f
                                )
                            }
                            btnContainer.addView(btnStatus)
                            
                            cardView.addView(btnContainer)
                            
                            layoutCareersContainer.addView(cardView)
                        }
                    } else {
                        textNoCareers.visibility = View.VISIBLE
                        layoutCareersContainer.removeAllViews()
                    }
                } else {
                    textNoCareers.visibility = View.VISIBLE
                    layoutCareersContainer.removeAllViews()
                }
            }

        // 5. Listen to profile insights
        profileInsightsListenerRegistration = db.collection("profile_insights").document("latest")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to profile insights failed: $error")
                    return@addSnapshotListener
                }
                if (snapshot != null && snapshot.exists()) {
                    layoutProfileInsights.visibility = View.VISIBLE
                    
                    // Render Strengths & Languages
                    containerStrengths.removeAllViews()
                    
                    val strengths = snapshot.get("strengths") as? Map<String, Any>
                    val languages = snapshot.get("languages") as? Map<String, Any>
                    val careerConf = snapshot.get("career_confidence") as? Map<String, Any>
                    
                    val allBars = mutableListOf<Pair<String, Double>>()
                    
                    strengths?.forEach { (k, v) ->
                        val d = (v as? Number)?.toDouble() ?: 0.0
                        allBars.add(k to d)
                    }
                    languages?.forEach { (k, v) ->
                        val d = (v as? Number)?.toDouble() ?: 0.0
                        allBars.add(k to d)
                    }
                    careerConf?.forEach { (k, v) ->
                        val d = (v as? Number)?.toDouble() ?: 0.0
                        allBars.add(k to d)
                    }
                    
                    // Sort descending by percentage
                    allBars.sortByDescending { it.second }
                    
                    // Show top 5
                    for (item in allBars.take(5)) {
                        val key = item.first
                        val value = item.second
                        
                        val barLayout = LinearLayout(this@MainActivity).apply {
                            orientation = LinearLayout.VERTICAL
                            val lp = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.MATCH_PARENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT
                            ).apply {
                                setMargins(0, 0, 0, (12 * resources.displayMetrics.density).toInt())
                            }
                            layoutParams = lp
                        }
                        
                        val headerLayout = LinearLayout(this@MainActivity).apply {
                            orientation = LinearLayout.HORIZONTAL
                            layoutParams = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.MATCH_PARENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT
                            )
                        }
                        
                        val labelText = TextView(this@MainActivity).apply {
                            text = key.replace("_", " ").toUpperCase(Locale.getDefault())
                            setTextColor(android.graphics.Color.parseColor("#E2E8F0"))
                            textSize = 12f
                            typeface = android.graphics.Typeface.DEFAULT_BOLD
                            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                        }
                        
                        val percentText = TextView(this@MainActivity).apply {
                            text = "$value%"
                            setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                            textSize = 12f
                            typeface = android.graphics.Typeface.DEFAULT_BOLD
                            layoutParams = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.WRAP_CONTENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT
                            )
                        }
                        
                        headerLayout.addView(labelText)
                        headerLayout.addView(percentText)
                        barLayout.addView(headerLayout)
                        
                        val progressTrack = android.widget.FrameLayout(this@MainActivity).apply {
                            val trackLp = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.MATCH_PARENT,
                                (8 * resources.displayMetrics.density).toInt()
                            ).apply {
                                setMargins(0, (6 * resources.displayMetrics.density).toInt(), 0, 0)
                            }
                            layoutParams = trackLp
                            
                            val shape = android.graphics.drawable.GradientDrawable().apply {
                                shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                                cornerRadius = (4 * resources.displayMetrics.density)
                                setColor(android.graphics.Color.parseColor("#0F172A"))
                            }
                            background = shape
                        }
                        
                        val progressFill = View(this@MainActivity).apply {
                            val fillLp = android.widget.FrameLayout.LayoutParams(
                                0,
                                android.widget.FrameLayout.LayoutParams.MATCH_PARENT
                            )
                            layoutParams = fillLp
                            
                            val shape = android.graphics.drawable.GradientDrawable().apply {
                                shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                                cornerRadius = (4 * resources.displayMetrics.density)
                                setColor(android.graphics.Color.parseColor("#00E5FF"))
                            }
                            background = shape
                        }
                        
                        progressTrack.addView(progressFill)
                        barLayout.addView(progressTrack)
                        
                        progressTrack.post {
                            val totalWidth = progressTrack.width
                            val fillWidth = (totalWidth * (value / 100.0)).toInt()
                            val lp = progressFill.layoutParams as android.widget.FrameLayout.LayoutParams
                            lp.width = fillWidth
                            progressFill.layoutParams = lp
                        }
                        
                        containerStrengths.addView(barLayout)
                    }
                    
                    // Render Focus Chips
                    containerFocusChips.removeAllViews()
                    val focusList = snapshot.get("current_focus") as? List<Map<String, Any>>
                    if (focusList != null) {
                        for (f in focusList.take(3)) {
                            val topic = f["topic"] as? String ?: ""
                            val chip = TextView(this@MainActivity).apply {
                                text = topic
                                setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                                textSize = 11f
                                typeface = android.graphics.Typeface.DEFAULT_BOLD
                                setPadding(
                                    (12 * resources.displayMetrics.density).toInt(),
                                    (6 * resources.displayMetrics.density).toInt(),
                                    (12 * resources.displayMetrics.density).toInt(),
                                    (6 * resources.displayMetrics.density).toInt()
                                )
                                
                                val shape = android.graphics.drawable.GradientDrawable().apply {
                                    shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                                    cornerRadius = (16 * resources.displayMetrics.density)
                                    setColor(android.graphics.Color.parseColor("#1A365D"))
                                    setStroke(1, android.graphics.Color.parseColor("#3300E5FF"))
                                }
                                background = shape
                                
                                val lp = LinearLayout.LayoutParams(
                                    LinearLayout.LayoutParams.WRAP_CONTENT,
                                    LinearLayout.LayoutParams.WRAP_CONTENT
                                ).apply {
                                    setMargins(0, 0, (8 * resources.displayMetrics.density).toInt(), 0)
                                }
                                layoutParams = lp
                            }
                            containerFocusChips.addView(chip)
                        }
                    }
                    
                    // Render Recent Ledger Logs (Last 3)
                    containerLedger.removeAllViews()
                    val changes = snapshot.get("recent_changes") as? List<Map<String, Any>>
                    if (changes != null) {
                        for (ch in changes.take(3)) {
                            val key = ch["vector_key"] as? String ?: ""
                            val delta = ch["delta"] as? String ?: ""
                            val source = ch["source"] as? String ?: ""
                            val description = ch["description"] as? String ?: ""
                            
                            val entryLayout = LinearLayout(this@MainActivity).apply {
                                orientation = LinearLayout.HORIZONTAL
                                val lp = LinearLayout.LayoutParams(
                                    LinearLayout.LayoutParams.MATCH_PARENT,
                                    LinearLayout.LayoutParams.WRAP_CONTENT
                                ).apply {
                                    setMargins(0, 0, 0, (10 * resources.displayMetrics.density).toInt())
                                }
                                layoutParams = lp
                            }
                            
                            val badge = TextView(this@MainActivity).apply {
                                text = source
                                setTextColor(android.graphics.Color.parseColor("#94A3B8"))
                                textSize = 9f
                                typeface = android.graphics.Typeface.DEFAULT_BOLD
                                setPadding(
                                    (6 * resources.displayMetrics.density).toInt(),
                                    (2 * resources.displayMetrics.density).toInt(),
                                    (6 * resources.displayMetrics.density).toInt(),
                                    (2 * resources.displayMetrics.density).toInt()
                                )
                                val shape = android.graphics.drawable.GradientDrawable().apply {
                                    shape = android.graphics.drawable.GradientDrawable.RECTANGLE
                                    cornerRadius = (4 * resources.displayMetrics.density)
                                    setColor(android.graphics.Color.parseColor("#1E293B"))
                                }
                                background = shape
                                layoutParams = LinearLayout.LayoutParams(
                                    LinearLayout.LayoutParams.WRAP_CONTENT,
                                    LinearLayout.LayoutParams.WRAP_CONTENT
                                )
                            }
                            
                            val descText = TextView(this@MainActivity).apply {
                                text = description
                                setTextColor(android.graphics.Color.parseColor("#CBD5E1"))
                                textSize = 11f
                                setPadding((8 * resources.displayMetrics.density).toInt(), 0, (8 * resources.displayMetrics.density).toInt(), 0)
                                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                            }
                            
                            val deltaText = TextView(this@MainActivity).apply {
                                text = delta
                                val isPositive = !delta.startsWith("-")
                                setTextColor(android.graphics.Color.parseColor(if (isPositive) "#10B981" else "#EF4444"))
                                textSize = 11f
                                typeface = android.graphics.Typeface.DEFAULT_BOLD
                                layoutParams = LinearLayout.LayoutParams(
                                    LinearLayout.LayoutParams.WRAP_CONTENT,
                                    LinearLayout.LayoutParams.WRAP_CONTENT
                                )
                            }
                            
                            entryLayout.addView(badge)
                            entryLayout.addView(descText)
                            entryLayout.addView(deltaText)
                            containerLedger.addView(entryLayout)
                        }
                    }
                } else {
                    layoutProfileInsights.visibility = View.GONE
                }
            }
    }

    private fun updateFirestoreOpportunityStatus(oppId: Double, newStatus: String) {
        val db = FirebaseFirestore.getInstance()
        db.collection("career_opportunities").document("latest").get()
            .addOnSuccessListener { doc ->
                if (doc.exists()) {
                    val oppsList = doc.get("opportunities") as? List<Map<String, Any>>
                    if (oppsList != null) {
                        val updatedOpps = oppsList.map { opp ->
                            val currentId = (opp["id"] as? Number)?.toDouble() ?: 0.0
                            if (currentId == oppId) {
                                val newMap = opp.toMutableMap()
                                newMap["status"] = newStatus
                                newMap
                            } else {
                                opp
                            }
                        }
                        db.collection("career_opportunities").document("latest")
                            .update("opportunities", updatedOpps)
                            .addOnSuccessListener {
                                Toast.makeText(this, "Status updated to $newStatus", Toast.LENGTH_SHORT).show()
                            }
                    }
                }
            }
    }

    private fun loadUrlIntoImageView(url: String, imageView: ImageView) {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val connection = java.net.URL(url).openConnection() as java.net.HttpURLConnection
                connection.doInput = true
                connection.connectTimeout = 5000
                connection.readTimeout = 5000
                connection.connect()
                val input = connection.inputStream
                val bitmap = android.graphics.BitmapFactory.decodeStream(input)
                withContext(Dispatchers.Main) {
                    imageView.setImageBitmap(bitmap)
                }
            } catch (e: Exception) {
                Log.e("MainActivity", "Failed to load image: ${e.message}")
            }
        }
    }

    private fun showNativeSecurityAlertDialog(imageUrl: String?) {
        val dialogView = layoutInflater.inflate(R.layout.dialog_security_alert, null)
        val imageView = dialogView.findViewById<ImageView>(R.id.alertImageView)
        val textTitle = dialogView.findViewById<TextView>(R.id.alertTitle)
        val textBody = dialogView.findViewById<TextView>(R.id.alertBody)
        val btnDismiss = dialogView.findViewById<Button>(R.id.btnDismiss)
        val btnCheckCameras = dialogView.findViewById<Button>(R.id.btnCheckCameras)
        val btnLockScreen = dialogView.findViewById<Button>(R.id.btnLockScreen)

        textTitle.text = "🚨 SECURITY ALERT"
        textBody.text = "Potential unauthorized access detected on your PC."

        if (!imageUrl.isNullOrEmpty()) {
            loadUrlIntoImageView(imageUrl, imageView)
            imageView.visibility = View.VISIBLE
        } else {
            imageView.visibility = View.GONE
        }

        val builder = android.app.AlertDialog.Builder(this)
            .setView(dialogView)
            .setCancelable(true)
        
        val alertDialog = builder.create()
        alertDialog.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT))

        btnDismiss.setOnClickListener {
            alertDialog.dismiss()
        }
        btnCheckCameras.setOnClickListener {
            sendCustomCommandNative("laptop check security cameras")
            alertDialog.dismiss()
        }
        btnLockScreen.setOnClickListener {
            sendCustomCommandNative("laptop lock screen")
            alertDialog.dismiss()
        }

        alertDialog.show()
    }

    override fun onDestroy() {
        super.onDestroy()
        activeTasksListenerRegistration?.remove()
        approvalsListenerRegistration?.remove()
        incidentsListenerRegistration?.remove()
        careerListenerRegistration?.remove()
        profileInsightsListenerRegistration?.remove()
    }
}
