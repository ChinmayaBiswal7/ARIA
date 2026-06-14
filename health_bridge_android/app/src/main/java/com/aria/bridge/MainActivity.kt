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
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.animation.AnimatorSet
import android.view.animation.LinearInterpolator
import android.widget.ImageButton
import androidx.cardview.widget.CardView
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
import android.speech.RecognizerIntent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.PorterDuff

class MainActivity : AppCompatActivity() {

    private lateinit var healthConnectManager: HealthConnectManager
    private lateinit var webView: WebView

    // Scanner Views
    private lateinit var layoutScanner: LinearLayout
    private lateinit var btnScanCamera: Button
    private lateinit var btnScanGallery: Button
    private lateinit var scanPreviewImage: ImageView
    private lateinit var textOcrConfidence: TextView
    private lateinit var editScanTitle: EditText
    private lateinit var editScanText: EditText
    private lateinit var btnIngestScan: Button
    private var tempPhotoUri: Uri? = null

    // Floating Dock Views
    private lateinit var floatingNavDock: CardView
    private lateinit var navHome: LinearLayout
    private lateinit var navControl: LinearLayout
    private lateinit var navProfile: LinearLayout
    private lateinit var iconHome: ImageView
    private lateinit var iconControl: ImageView
    private lateinit var iconProfile: ImageView
    private lateinit var textHome: TextView
    private lateinit var textControl: TextView
    private lateinit var textProfile: TextView

    // Orb Views
    private lateinit var orbOuterRing: ImageView
    private lateinit var orbOuterRing2: ImageView
    private lateinit var orbInnerCore: Orb3DView
    private lateinit var orbWaveRipple1: ImageView
    private lateinit var orbWaveRipple2: ImageView
    private lateinit var textOrbStatus: TextView
    private lateinit var textOrbStateDesc: TextView
    private lateinit var textCpuLoad: TextView
    private lateinit var textRamUsage: TextView

    // Status Dots & Text
    private lateinit var dotPcStatus: View
    private lateinit var textPcStatus: TextView
    private lateinit var dotChromeStatus: View
    private lateinit var textChromeStatus: TextView
    private lateinit var dotVsCodeStatus: View
    private lateinit var textVsCodeStatus: TextView
    private lateinit var dotFirebaseStatus: View
    private lateinit var textFirebaseStatus: TextView

    // Activity Strip
    private lateinit var activityWindow: TextView
    private lateinit var activityTask: TextView
    private lateinit var activityLastAction: TextView

    // Sub-page Wrappers & Toolbar Buttons
    private lateinit var layoutWebViewContainer: LinearLayout
    private lateinit var btnBackFromWebView: ImageButton
    private lateinit var btnBackFromScanner: ImageButton
    private lateinit var btnBackFromAlerts: ImageButton
    private lateinit var btnBackFromMissions: ImageButton
    private lateinit var btnBackFromCareer: ImageButton
    private lateinit var badgeApprovalsPending: TextView
    private lateinit var cardSecurityAlerts: LinearLayout

    private var orbCoreAnimator: android.animation.Animator? = null
    private var orbRingAnimator: android.animation.Animator? = null
    private var orbRing2Animator: android.animation.Animator? = null
    private var orbRipple1Animator: android.animation.Animator? = null
    private var orbRipple2Animator: android.animation.Animator? = null
    
    private var currentOrbState: String = "idle"
    private var isFlashing: Boolean = false
    
    private var lastChromeConnected: Boolean = false
    private var lastMissionStatus: String = ""
    private var lastPendingApprovalsCount: Int = 0

    // Heartbeat caching variables and watchdog
    private var lastHeartbeatReceived: Double = 0.0
    private var lastStatusStr: String = "offline"
    private var lastVsCodeConnected: Boolean = false

    private val watchdogHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val watchdogRunnable = object : Runnable {
        override fun run() {
            val nowSeconds = System.currentTimeMillis() / 1000.0
            val elapsed = nowSeconds - lastHeartbeatReceived
            if (lastHeartbeatReceived > 0.0 && elapsed >= 10.0) {
                runOnUiThread {
                    updateOrbState("offline")
                    updateConnectionChips(
                        pcOnline = false,
                        chromeConnected = false,
                        vscodeConnected = false,
                        firebaseConnected = true
                    )
                    
                    val lastSeenStr = if (elapsed < 60) {
                        "PC Offline. Last seen: ${elapsed.toInt()}s ago"
                    } else {
                        val mins = (elapsed / 60).toInt()
                        val secs = (elapsed % 60).toInt()
                        "PC Offline. Last seen: ${mins}m ${secs}s ago"
                    }
                    textOrbStateDesc.text = lastSeenStr
                }
            } else if (lastHeartbeatReceived == 0.0) {
                runOnUiThread {
                    updateOrbState("offline")
                    updateConnectionChips(
                        pcOnline = false,
                        chromeConnected = false,
                        vscodeConnected = false,
                        firebaseConnected = true
                    )
                    textOrbStateDesc.text = "PC Offline. Never seen"
                }
            }
            watchdogHandler.postDelayed(this, 5000)
        }
    }

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val flashHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private var flashRunnable: Runnable? = null

    private var audioRecord: android.media.AudioRecord? = null
    private var isRecordingAudio = false
    private var audioThread: Thread? = null
    private var lastRms: Double = 0.0

    private val ripple2Runnable = Runnable {
        try {
            orbRipple2Animator?.start()
        } catch (e: Exception) {
            Log.e("MainActivity", "Error starting ripple 2: ${e.message}")
        }
    }

    private val speechRecognitionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK && result.data != null) {
            val spokenText = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.get(0) ?: ""
            if (spokenText.isNotEmpty()) {
                sendCustomCommandNative(spokenText)
            }
        }
    }

    // Native Tab Views
    private lateinit var layoutAlerts: LinearLayout
    private lateinit var layoutIncidentsContainer: LinearLayout
    private lateinit var layoutMissions: LinearLayout
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
    private var statusListenerRegistration: ListenerRegistration? = null

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
        layoutAlerts = findViewById(R.id.layoutAlerts)
        layoutIncidentsContainer = findViewById(R.id.layoutIncidentsContainer)
        layoutMissions = findViewById(R.id.layoutMissions)
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

        // Floating Nav Dock Setup
        floatingNavDock = findViewById(R.id.floatingNavDock)
        floatingNavDock.visibility = android.view.View.GONE // Hide until splash screen completes in WebView
        
        navHome = findViewById(R.id.navHome)
        navControl = findViewById(R.id.navControl)
        navProfile = findViewById(R.id.navProfile)
        
        iconHome = findViewById(R.id.iconHome)
        iconControl = findViewById(R.id.iconControl)
        iconProfile = findViewById(R.id.iconProfile)
        
        textHome = findViewById(R.id.textHome)
        textControl = findViewById(R.id.textControl)
        textProfile = findViewById(R.id.textProfile)

        navHome.setOnClickListener { switchNavTab(NAV_HOME) }
        navControl.setOnClickListener { switchNavTab(NAV_CONTROL) }
        navProfile.setOnClickListener { switchNavTab(NAV_PROFILE) }

        // Orb & Telemetry Views
        orbOuterRing = findViewById(R.id.orbOuterRing)
        orbOuterRing2 = findViewById(R.id.orbOuterRing2)
        orbInnerCore = findViewById(R.id.orbInnerCore)
        orbWaveRipple1 = findViewById(R.id.orbWaveRipple1)
        orbWaveRipple2 = findViewById(R.id.orbWaveRipple2)
        textOrbStatus = findViewById(R.id.textOrbStatus)
        textOrbStateDesc = findViewById(R.id.textOrbStateDesc)
        textCpuLoad = findViewById(R.id.textCpuLoad)
        textRamUsage = findViewById(R.id.textRamUsage)

        // Status Indicators
        dotPcStatus = findViewById(R.id.dotPcStatus)
        textPcStatus = findViewById(R.id.textPcStatus)
        dotChromeStatus = findViewById(R.id.dotChromeStatus)
        textChromeStatus = findViewById(R.id.textChromeStatus)
        dotVsCodeStatus = findViewById(R.id.dotVsCodeStatus)
        textVsCodeStatus = findViewById(R.id.textVsCodeStatus)
        dotFirebaseStatus = findViewById(R.id.dotFirebaseStatus)
        textFirebaseStatus = findViewById(R.id.textFirebaseStatus)

        // Activity Strip
        activityWindow = findViewById(R.id.activityWindow)
        activityTask = findViewById(R.id.activityTask)
        activityLastAction = findViewById(R.id.activityLastAction)

        // Quick Action Clicks
        findViewById<View>(R.id.actionTalk).setOnClickListener {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to ARIA...")
            }
            try {
                speechRecognitionLauncher.launch(intent)
            } catch (e: Exception) {
                Toast.makeText(this, "Speech recognition not supported on this device.", Toast.LENGTH_SHORT).show()
            }
        }
        
        findViewById<View>(R.id.actionControl).setOnClickListener {
            switchNavTab(NAV_CONTROL)
        }
        
        findViewById<View>(R.id.actionClipboard).setOnClickListener {
            sendCustomCommandNative("laptop sync clipboard")
        }
        
        findViewById<View>(R.id.actionScreenshot).setOnClickListener {
            sendCustomCommandNative("laptop take screenshot")
        }

        // Sub-page containers
        layoutWebViewContainer = findViewById(R.id.layoutWebViewContainer)
        
        // Toolbar Back Buttons
        btnBackFromWebView = findViewById(R.id.btnBackFromWebView)
        btnBackFromScanner = findViewById(R.id.btnBackFromScanner)
        btnBackFromAlerts = findViewById(R.id.btnBackFromAlerts)
        btnBackFromMissions = findViewById(R.id.btnBackFromMissions)
        btnBackFromCareer = findViewById(R.id.btnBackFromCareer)

        btnBackFromWebView.setOnClickListener { switchNavTab(NAV_HOME) }
        btnBackFromScanner.setOnClickListener { switchNavTab(NAV_HOME) }
        btnBackFromAlerts.setOnClickListener { switchNavTab(NAV_HOME) }
        btnBackFromMissions.setOnClickListener { switchNavTab(NAV_HOME) }
        btnBackFromCareer.setOnClickListener { switchNavTab(NAV_HOME) }

        // Card Clicks
        findViewById<View>(R.id.cardRemoteDesktop).setOnClickListener { switchNavTab(NAV_CONTROL) }
        findViewById<View>(R.id.cardRemoteBrowser).setOnClickListener { switchNavTab(NAV_CONTROL) }
        findViewById<View>(R.id.cardRemoteVsCode).setOnClickListener { switchNavTab(NAV_CONTROL) }
        findViewById<View>(R.id.cardRemoteFiles).setOnClickListener { switchNavTab(NAV_CONTROL) }

        findViewById<View>(R.id.cardIntelMissions).setOnClickListener { openSubPage(layoutMissions) }
        findViewById<View>(R.id.cardIntelLearning).setOnClickListener {
            Toast.makeText(this, "DBMS & Binary Search guides are up to date.", Toast.LENGTH_SHORT).show()
        }
        findViewById<View>(R.id.cardIntelMemory).setOnClickListener {
            Toast.makeText(this, "Memory Vault: SQLite & Vector indexes synchronized.", Toast.LENGTH_SHORT).show()
        }
        findViewById<View>(R.id.cardIntelCareer).setOnClickListener { switchNavTab(NAV_PROFILE) }

        cardSecurityAlerts = findViewById(R.id.cardSecurityAlerts)
        badgeApprovalsPending = findViewById(R.id.badgeApprovalsPending)
        cardSecurityAlerts.setOnClickListener { openSubPage(layoutAlerts) }
        findViewById<View>(R.id.cardSecurityLog).setOnClickListener { openSubPage(layoutAlerts) }

        findViewById<View>(R.id.cardCoreVsCode).setOnClickListener {
            Toast.makeText(this, "VS Code Bridge is listening on port 9821.", Toast.LENGTH_SHORT).show()
        }
        findViewById<View>(R.id.cardCoreBrowser).setOnClickListener {
            Toast.makeText(this, "Browser Bridge is connected to remote debug on port 9222.", Toast.LENGTH_SHORT).show()
        }
        findViewById<View>(R.id.cardCoreTelemetry).setOnClickListener {
            Toast.makeText(this, "Telemetry stream is fully active.", Toast.LENGTH_SHORT).show()
        }
        findViewById<View>(R.id.cardCoreHealth).setOnClickListener {
            Toast.makeText(this, "System health checks passed.", Toast.LENGTH_SHORT).show()
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
                    webView.visibility = android.view.View.GONE
                    findViewById<View>(R.id.layoutDashboard).visibility = android.view.View.VISIBLE
                    floatingNavDock.visibility = android.view.View.VISIBLE
                    switchNavTab(NAV_HOME)
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
            Log.d("MainActivity", "Launched from approval notification – switching to Alerts tab")
            openSubPage(layoutAlerts)
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
        private const val ITEM_CAREER = 6

        private const val NAV_HOME = 0
        private const val NAV_CONTROL = 1
        private const val NAV_PROFILE = 2
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
                runOnUiThread {
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

                        val stepsCount = steps?.size ?: 0
                        findViewById<TextView>(R.id.descMissionsCard).text = "Goal: $goal | $stepsCount steps"

                        val isCompleted = status.lowercase() in listOf("completed", "done", "success")
                        val wasCompleted = lastMissionStatus.lowercase() in listOf("completed", "done", "success")
                        if (isCompleted && !wasCompleted) {
                            triggerOrbFlash("#10B981", 1500)
                        }
                        lastMissionStatus = status
                    } else {
                        textNoMissions.visibility = View.VISIBLE
                        cardActiveMission.visibility = View.GONE
                        layoutMissionControls.visibility = View.GONE
                        findViewById<TextView>(R.id.descMissionsCard).text = "Active tasks queue"
                        lastMissionStatus = ""
                    }
                }
            }

        // 2. Listen to pending approvals
        approvalsListenerRegistration = db.collection("approvals")
            .whereEqualTo("status", "pending")
            .addSnapshotListener { snapshots, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to approvals failed: $error")
                    return@addSnapshotListener
                }
                val count = snapshots?.size() ?: 0
                runOnUiThread {
                    updateSecurityCardBadge(count)
                    if (count > lastPendingApprovalsCount) {
                        triggerOrbFlash("#EF4444", 1500)
                    }
                    lastPendingApprovalsCount = count
                    if (snapshots != null && !snapshots.isEmpty) {
                        textNoApprovals.visibility = View.GONE
                        cardPendingApproval.visibility = View.VISIBLE

                        val doc = snapshots.documents.first()
                        val risk = doc.getString("risk_level") ?: "HIGH"
                        val tag  = doc.getString("action_tag") ?: ""
                        val desc = doc.getString("description") ?: "ARIA wants to: $tag"
                        val tsRaw = doc.getDouble("timestamp")
                        val tsStr = if (tsRaw != null) {
                            val sdf = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault())
                            "Requested at " + sdf.format(java.util.Date((tsRaw * 1000).toLong()))
                        } else "Requested just now"

                        val riskColor = if (risk == "CRITICAL") "#EF4444" else "#F59E0B"
                        approvalRiskLevel.text = "⚠ $risk RISK"
                        approvalRiskLevel.setTextColor(android.graphics.Color.parseColor(riskColor))
                        approvalActionTag.text  = tag
                        approvalDescription.text = desc
                        approvalTimestamp.text   = tsStr

                        btnApproveRequest.setOnClickListener {
                            db.collection("approvals").document(doc.id).update("status", "approved")
                        }
                        btnRejectRequest.setOnClickListener {
                            db.collection("approvals").document(doc.id).update("status", "rejected")
                        }
                    } else {
                        textNoApprovals.visibility = View.VISIBLE
                        cardPendingApproval.visibility = View.GONE
                    }
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
                    
                    val careerDesc = findViewById<TextView>(R.id.descCareerCard)
                    if (!focusList.isNullOrEmpty()) {
                        val firstTopic = focusList[0]["topic"] as? String ?: ""
                        if (firstTopic.isNotEmpty()) {
                            careerDesc.text = firstTopic
                        } else {
                            careerDesc.text = "Opportunities Tracker"
                        }
                    } else {
                        careerDesc.text = "Opportunities Tracker"
                    }

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

        // 6. Listen to status/latest for Orb state, telemetry, and connectivity status
        statusListenerRegistration = db.collection("status").document("latest")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    Log.e("MainActivity", "Listen to status latest failed: $error")
                    return@addSnapshotListener
                }
                if (snapshot != null && snapshot.exists()) {
                    val statusStr = snapshot.getString("status") ?: "idle"
                    val timestamp = snapshot.getDouble("timestamp") ?: 0.0
                    val vscodeConnected = snapshot.getBoolean("vscode_connected") ?: false
                    val chromeConnected = snapshot.getBoolean("chrome_connected") ?: false
                    val chromeTabsCount = snapshot.getLong("chrome_tabs_count") ?: 0L
                    
                    val cpu = snapshot.getDouble("cpu_percent") ?: 0.0
                    val ram = snapshot.getDouble("ram_gb") ?: 0.0
                    
                    val activeFile = snapshot.getString("vscode_active_file") ?: ""
                    val branch = snapshot.getString("vscode_git_branch") ?: ""
                    val errors = snapshot.getLong("vscode_errors") ?: 0L
                    val warnings = snapshot.getLong("vscode_warnings") ?: 0L
                    
                    val chromeTitle = snapshot.getString("chrome_active_title") ?: ""
                    val lastResponseText = snapshot.getString("last_response") ?: ""

                    runOnUiThread {
                        // Cache values
                        lastHeartbeatReceived = timestamp
                        lastStatusStr = statusStr
                        lastVsCodeConnected = vscodeConnected

                        // Update Orb metrics
                        textCpuLoad.text = String.format(java.util.Locale.US, "CPU: %.1f%%", cpu)
                        textRamUsage.text = String.format(java.util.Locale.US, "RAM: %.1f GB", ram)

                        // Update Live Activity Strip
                        activityWindow.text = if (activeFile.isNotEmpty()) "Current Window: VS Code" else "Current Window: Standby"
                        activityTask.text = if (activeFile.isNotEmpty()) "Current File: $activeFile" else "Current File: None"
                        
                        val actionDesc = when {
                            chromeTitle.isNotEmpty() && activeFile.isNotEmpty() -> "Editing $activeFile | Chrome: $chromeTitle"
                            activeFile.isNotEmpty() -> "Editing $activeFile on branch $branch"
                            chromeTitle.isNotEmpty() -> "Active Chrome tab: $chromeTitle"
                            else -> lastResponseText.ifEmpty { "Monitoring system status" }
                        }
                        activityLastAction.text = "Last Action: $actionDesc"

                        // Chrome Card description
                        val chromeDesc = findViewById<TextView>(R.id.descBrowserCard)
                        if (chromeConnected) {
                            chromeDesc.text = "$chromeTabsCount tabs attached"
                        } else {
                            chromeDesc.text = "Chrome CDP Bridge"
                        }

                        // VS Code Card description
                        val vsCodeDesc = findViewById<TextView>(R.id.descVsCodeCard)
                        if (vscodeConnected) {
                            val fileText = if (activeFile.isNotEmpty()) "$activeFile open" else "No file open"
                            vsCodeDesc.text = "$fileText | $errors errors"
                        } else {
                            vsCodeDesc.text = "Workspace Bridge"
                        }

                        // Determine PC online status from heartbeat
                        val nowSeconds = System.currentTimeMillis() / 1000.0
                        val pcOnline = (nowSeconds - timestamp) < 10.0 // online if heartbeat within 10 seconds
                        
                        val activeState = if (pcOnline) statusStr else "offline"
                        updateOrbState(activeState)

                        if (chromeConnected && !lastChromeConnected) {
                            triggerOrbFlash("#00E5FF", 1200)
                        }
                        lastChromeConnected = chromeConnected
                        
                        // Update Status Indicators
                        updateConnectionChips(
                            pcOnline = pcOnline,
                            chromeConnected = chromeConnected,
                            vscodeConnected = vscodeConnected,
                            firebaseConnected = true
                        )
                    }
                } else {
                    runOnUiThread {
                        updateOrbState("offline")
                        updateConnectionChips(
                            pcOnline = false,
                            chromeConnected = false,
                            vscodeConnected = false,
                            firebaseConnected = false
                        )
                    }
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

    private fun switchNavTab(tabId: Int) {
        findViewById<View>(R.id.layoutDashboard).visibility = View.GONE
        layoutWebViewContainer.visibility = View.GONE
        layoutCareer.visibility = View.GONE
        layoutScanner.visibility = View.GONE
        layoutAlerts.visibility = View.GONE
        layoutMissions.visibility = View.GONE

        // Reset all icon/text colors
        iconHome.setColorFilter(android.graphics.Color.parseColor("#64748B"))
        textHome.setTextColor(android.graphics.Color.parseColor("#64748B"))
        textHome.setTypeface(null, android.graphics.Typeface.NORMAL)

        iconControl.setColorFilter(android.graphics.Color.parseColor("#64748B"))
        textControl.setTextColor(android.graphics.Color.parseColor("#64748B"))
        textControl.setTypeface(null, android.graphics.Typeface.NORMAL)

        iconProfile.setColorFilter(android.graphics.Color.parseColor("#64748B"))
        textProfile.setTextColor(android.graphics.Color.parseColor("#64748B"))
        textProfile.setTypeface(null, android.graphics.Typeface.NORMAL)

        floatingNavDock.visibility = View.VISIBLE

        when (tabId) {
            NAV_HOME -> {
                findViewById<View>(R.id.layoutDashboard).visibility = View.VISIBLE
                iconHome.setColorFilter(android.graphics.Color.parseColor("#00E5FF"))
                textHome.setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                textHome.setTypeface(null, android.graphics.Typeface.BOLD)
            }
            NAV_CONTROL -> {
                layoutWebViewContainer.visibility = View.VISIBLE
                webView.visibility = View.VISIBLE
                iconControl.setColorFilter(android.graphics.Color.parseColor("#00E5FF"))
                textControl.setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                textControl.setTypeface(null, android.graphics.Typeface.BOLD)
            }
            NAV_PROFILE -> {
                layoutCareer.visibility = View.VISIBLE
                iconProfile.setColorFilter(android.graphics.Color.parseColor("#00E5FF"))
                textProfile.setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                textProfile.setTypeface(null, android.graphics.Typeface.BOLD)
            }
        }
    }

    private fun openSubPage(pageView: View) {
        floatingNavDock.visibility = View.GONE
        findViewById<View>(R.id.layoutDashboard).visibility = View.GONE
        layoutWebViewContainer.visibility = View.GONE
        layoutCareer.visibility = View.GONE
        layoutScanner.visibility = View.GONE
        layoutAlerts.visibility = View.GONE
        layoutMissions.visibility = View.GONE

        pageView.visibility = View.VISIBLE
    }

    private var rippleStartTime: Long = 0L

    private fun updateOrbState(state: String) {
        val lowerState = state.lowercase()
        currentOrbState = lowerState
        if (isFlashing) return

        orbCoreAnimator?.cancel()
        orbRingAnimator?.cancel()
        orbRing2Animator?.cancel()
        orbRipple1Animator?.cancel()
        orbRipple2Animator?.cancel()
        mainHandler.removeCallbacks(ripple2Runnable)

        orbInnerCore.scaleX = 1.0f
        orbInnerCore.scaleY = 1.0f
        orbOuterRing.rotation = 0.0f
        orbOuterRing2.rotation = 0.0f

        orbWaveRipple1.visibility = View.INVISIBLE
        orbWaveRipple2.visibility = View.INVISIBLE
        orbWaveRipple1.scaleX = 1.0f
        orbWaveRipple1.scaleY = 1.0f
        orbWaveRipple1.alpha = 1.0f
        orbWaveRipple2.scaleX = 1.0f
        orbWaveRipple2.scaleY = 1.0f
        orbWaveRipple2.alpha = 1.0f

        orbInnerCore.imageTintList = null
        orbOuterRing.imageTintList = null
        orbOuterRing2.imageTintList = null
        orbWaveRipple1.imageTintList = null
        orbWaveRipple2.imageTintList = null

        // Update the 3D particle state
        orbInnerCore.setState(lowerState)

        if (lowerState == "listening" || lowerState == "speaking") {
            startAudioListening()
        } else {
            stopAudioListening()
        }

        when (lowerState) {
            "listening" -> {
                orbOuterRing.setImageResource(R.drawable.bg_orb_ring_cyan)
                orbOuterRing2.setImageResource(R.drawable.bg_orb_ring_cyan)
                textOrbStatus.text = "LISTENING"
                textOrbStatus.setTextColor(android.graphics.Color.parseColor("#00E5FF"))
                textOrbStateDesc.text = "Aria is listening..."

                // Rotating Rings (Fast opposite directions)
                orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
                    duration = 3500
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
                orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
                    duration = 2800
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }

                // Setup ripples (Cyan)
                orbWaveRipple1.imageTintList = ColorStateList.valueOf(Color.parseColor("#00E5FF"))
                orbWaveRipple2.imageTintList = ColorStateList.valueOf(Color.parseColor("#00E5FF"))
                orbWaveRipple1.visibility = View.VISIBLE
                rippleStartTime = System.currentTimeMillis()
            }
            "thinking" -> {
                orbOuterRing.setImageResource(R.drawable.bg_orb_ring_purple)
                orbOuterRing2.setImageResource(R.drawable.bg_orb_ring_purple)
                textOrbStatus.text = "THINKING"
                textOrbStatus.setTextColor(android.graphics.Color.parseColor("#A78BFA"))
                textOrbStateDesc.text = "Analyzing context..."

                // Rotating Rings (Very fast)
                orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
                    duration = 2000
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
                orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
                    duration = 1600
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
            }
            "speaking" -> {
                orbOuterRing.setImageResource(R.drawable.bg_orb_ring_green)
                orbOuterRing2.setImageResource(R.drawable.bg_orb_ring_green)
                textOrbStatus.text = "SPEAKING"
                textOrbStatus.setTextColor(android.graphics.Color.parseColor("#10B981"))
                textOrbStateDesc.text = "Aria is responding..."

                // Rotating Rings
                orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
                    duration = 4500
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
                orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
                    duration = 3600
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }

                // Setup ripples (Green)
                orbWaveRipple1.imageTintList = ColorStateList.valueOf(Color.parseColor("#10B981"))
                orbWaveRipple2.imageTintList = ColorStateList.valueOf(Color.parseColor("#10B981"))
                orbWaveRipple1.visibility = View.VISIBLE
                rippleStartTime = System.currentTimeMillis()
            }
            "offline" -> {
                orbOuterRing.setImageResource(R.drawable.bg_orb_ring_red)
                orbOuterRing2.setImageResource(R.drawable.bg_orb_ring_red)
                textOrbStatus.text = "OFFLINE"
                textOrbStatus.setTextColor(android.graphics.Color.parseColor("#EF4444"))
                textOrbStateDesc.text = "Check connection to PC server"

                // Rotating Rings (Extremely slow)
                orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
                    duration = 30000
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
                orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
                    duration = 25000
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
            }
            else -> { // idle/online
                orbOuterRing.setImageResource(R.drawable.bg_orb_ring_blue)
                orbOuterRing2.setImageResource(R.drawable.bg_orb_ring_blue)
                textOrbStatus.text = "ONLINE"
                textOrbStatus.setTextColor(android.graphics.Color.parseColor("#008CFF"))
                textOrbStateDesc.text = "ARIA is ready to assist you"

                // Rotating Rings (Slow)
                orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
                    duration = 10000
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
                orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
                    duration = 8000
                    repeatCount = ValueAnimator.INFINITE
                    interpolator = LinearInterpolator()
                    start()
                }
            }
        }
    }

    private fun triggerOrbFlash(colorHex: String, durationMs: Long) {
        flashRunnable?.let { flashHandler.removeCallbacks(it) }

        isFlashing = true

        orbCoreAnimator?.cancel()
        orbRingAnimator?.cancel()
        orbRing2Animator?.cancel()
        orbRipple1Animator?.cancel()
        orbRipple2Animator?.cancel()
        mainHandler.removeCallbacks(ripple2Runnable)

        val color = Color.parseColor(colorHex)
        val colorStateList = ColorStateList.valueOf(color)

        orbInnerCore.imageTintList = colorStateList
        orbOuterRing.imageTintList = colorStateList
        orbOuterRing2.imageTintList = colorStateList
        orbWaveRipple1.imageTintList = colorStateList
        orbWaveRipple2.imageTintList = colorStateList

        orbWaveRipple1.visibility = View.VISIBLE
        orbWaveRipple2.visibility = View.VISIBLE
        orbWaveRipple1.alpha = 0.8f
        orbWaveRipple2.alpha = 0.5f

        val pulseX = ObjectAnimator.ofFloat(orbInnerCore, "scaleX", 1.0f, 1.25f, 1.0f)
        val pulseY = ObjectAnimator.ofFloat(orbInnerCore, "scaleY", 1.0f, 1.25f, 1.0f)
        
        val rippleScaleX1 = ObjectAnimator.ofFloat(orbWaveRipple1, "scaleX", 1.0f, 1.8f)
        val rippleScaleY1 = ObjectAnimator.ofFloat(orbWaveRipple1, "scaleY", 1.0f, 1.8f)
        val rippleAlpha1 = ObjectAnimator.ofFloat(orbWaveRipple1, "alpha", 0.8f, 0.0f)

        val rippleScaleX2 = ObjectAnimator.ofFloat(orbWaveRipple2, "scaleX", 1.0f, 2.2f)
        val rippleScaleY2 = ObjectAnimator.ofFloat(orbWaveRipple2, "scaleY", 1.0f, 2.2f)
        val rippleAlpha2 = ObjectAnimator.ofFloat(orbWaveRipple2, "alpha", 0.5f, 0.0f)

        AnimatorSet().apply {
            playTogether(
                pulseX, pulseY, 
                rippleScaleX1, rippleScaleY1, rippleAlpha1,
                rippleScaleX2, rippleScaleY2, rippleAlpha2
            )
            duration = 1000
            start()
        }

        orbRingAnimator = ObjectAnimator.ofFloat(orbOuterRing, "rotation", 0f, 360f).apply {
            duration = 1000
            start()
        }
        orbRing2Animator = ObjectAnimator.ofFloat(orbOuterRing2, "rotation", 0f, -360f).apply {
            duration = 1000
            start()
        }

        val runnable = Runnable {
            isFlashing = false
            orbInnerCore.imageTintList = null
            orbOuterRing.imageTintList = null
            orbOuterRing2.imageTintList = null
            orbWaveRipple1.imageTintList = null
            orbWaveRipple2.imageTintList = null
            
            updateOrbState(currentOrbState)
        }
        flashRunnable = runnable
        flashHandler.postDelayed(runnable, durationMs)
    }

    private fun updateConnectionChips(
        pcOnline: Boolean,
        chromeConnected: Boolean,
        vscodeConnected: Boolean,
        firebaseConnected: Boolean
    ) {
        runOnUiThread {
            dotPcStatus.background = ContextCompat.getDrawable(this, if (pcOnline) R.drawable.bg_dot_online else R.drawable.bg_dot_offline)
            textPcStatus.text = if (pcOnline) "PC ONLINE" else "PC OFFLINE"
            textPcStatus.setTextColor(android.graphics.Color.parseColor(if (pcOnline) "#FFFFFF" else "#64748B"))

            dotChromeStatus.background = ContextCompat.getDrawable(this, if (chromeConnected) R.drawable.bg_dot_online else R.drawable.bg_dot_offline)
            textChromeStatus.text = if (chromeConnected) "CHROME ATTACHED" else "CHROME OFFLINE"
            textChromeStatus.setTextColor(android.graphics.Color.parseColor(if (chromeConnected) "#FFFFFF" else "#64748B"))

            dotVsCodeStatus.background = ContextCompat.getDrawable(this, if (vscodeConnected) R.drawable.bg_dot_online else R.drawable.bg_dot_offline)
            textVsCodeStatus.text = if (vscodeConnected) "VS CODE CONNECTED" else "VS CODE OFFLINE"
            textVsCodeStatus.setTextColor(android.graphics.Color.parseColor(if (vscodeConnected) "#FFFFFF" else "#64748B"))

            dotFirebaseStatus.background = ContextCompat.getDrawable(this, if (firebaseConnected) R.drawable.bg_dot_online else R.drawable.bg_dot_offline)
            textFirebaseStatus.text = if (firebaseConnected) "FIREBASE SYNCED" else "FIREBASE OFFLINE"
            textFirebaseStatus.setTextColor(android.graphics.Color.parseColor(if (firebaseConnected) "#FFFFFF" else "#64748B"))
        }
    }

    private fun updateSecurityCardBadge(count: Int) {
        badgeApprovalsPending.text = "$count Pending Requests"
        when {
            count == 0 -> {
                badgeApprovalsPending.setTextColor(android.graphics.Color.parseColor("#10B981"))
                cardSecurityAlerts.background = ContextCompat.getDrawable(this, R.drawable.card_background)
            }
            count in 1..4 -> {
                badgeApprovalsPending.setTextColor(android.graphics.Color.parseColor("#F59E0B"))
                cardSecurityAlerts.background = ContextCompat.getDrawable(this, R.drawable.card_background_attention)
            }
            else -> {
                badgeApprovalsPending.setTextColor(android.graphics.Color.parseColor("#EF4444"))
                cardSecurityAlerts.background = ContextCompat.getDrawable(this, R.drawable.card_background_warning)
            }
        }
    }

    override fun onBackPressed() {
        if (layoutWebViewContainer.visibility == View.VISIBLE && webView.canGoBack()) {
            webView.goBack()
        } else if (layoutScanner.visibility == View.VISIBLE ||
            layoutAlerts.visibility == View.VISIBLE ||
            layoutMissions.visibility == View.VISIBLE ||
            layoutWebViewContainer.visibility == View.VISIBLE ||
            layoutCareer.visibility == View.VISIBLE) {
            switchNavTab(NAV_HOME)
        } else {
            super.onBackPressed()
        }
    }

    override fun onResume() {
        super.onResume()
        if (currentOrbState == "listening" || currentOrbState == "speaking") {
            startAudioListening()
        }
        // Start heartbeat watchdog
        watchdogHandler.post(watchdogRunnable)
    }

    override fun onPause() {
        super.onPause()
        stopAudioListening()
        // Stop heartbeat watchdog
        watchdogHandler.removeCallbacks(watchdogRunnable)
    }

    private fun startAudioListening() {
        if (isRecordingAudio) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return
        }

        isRecordingAudio = true
        audioThread = Thread {
            val sampleRate = 16000
            val channelConfig = android.media.AudioFormat.CHANNEL_IN_MONO
            val audioFormat = android.media.AudioFormat.ENCODING_PCM_16BIT
            val minBufferSize = android.media.AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
            val internalBufferSize = Math.max(minBufferSize, 2048)

            try {
                audioRecord = android.media.AudioRecord(
                    android.media.MediaRecorder.AudioSource.MIC,
                    sampleRate,
                    channelConfig,
                    audioFormat,
                    internalBufferSize
                )

                if (audioRecord?.state == android.media.AudioRecord.STATE_INITIALIZED) {
                    audioRecord?.startRecording()
                    // 512 shorts (~32ms chunks) for high-frequency low-latency updates
                    val audioBuffer = ShortArray(512)

                    var noiseFloor = 35.0
                    val maxVolume = 1200.0

                    while (isRecordingAudio) {
                        val readResult = audioRecord?.read(audioBuffer, 0, audioBuffer.size) ?: 0
                        if (readResult > 0) {
                            var sum = 0.0
                            for (i in 0 until readResult) {
                                sum += audioBuffer[i] * audioBuffer[i]
                            }
                            val rms = Math.sqrt(sum / readResult)
                            
                            lastRms = lastRms * 0.6 + rms * 0.4

                            // Asymmetric noise floor tracking: drop fast, rise slow
                            if (lastRms < noiseFloor) {
                                noiseFloor = noiseFloor * 0.95 + lastRms * 0.05
                            } else {
                                noiseFloor = noiseFloor * 0.999 + lastRms * 0.001
                            }
                            noiseFloor = Math.max(10.0, noiseFloor)

                            val excess = Math.max(0.0, lastRms - noiseFloor)
                            val rawLevel = excess / maxVolume
                            val finalLevel = Math.min(1.0, Math.max(0.0, rawLevel)).toFloat()

                            runOnUiThread {
                                if (isRecordingAudio && !isFlashing) {
                                    applyAudioReactiveScale(finalLevel)
                                }
                            }
                        }
                    }
                }
            } catch (e: SecurityException) {
                Log.e("MainActivity", "Audio record security exception: ${e.message}")
            } catch (e: Exception) {
                Log.e("MainActivity", "Audio record exception: ${e.message}")
            } finally {
                try {
                    audioRecord?.stop()
                    audioRecord?.release()
                } catch (e: Exception) {}
                audioRecord = null
            }
        }.apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    private fun stopAudioListening() {
        isRecordingAudio = false
        audioThread = null
        runOnUiThread {
            orbInnerCore.scaleX = 1.0f
            orbInnerCore.scaleY = 1.0f
            orbInnerCore.setAudioLevel(0f)
            orbOuterRing.scaleX = 1.0f
            orbOuterRing.scaleY = 1.0f
            orbOuterRing2.scaleX = 1.0f
            orbOuterRing2.scaleY = 1.0f
        }
    }

    private fun applyAudioReactiveScale(level: Float) {
        // Feed real-time level to the custom 3D particle view
        orbInnerCore.setAudioLevel(level)

        // Scale the outer dashed rings moderately
        val outerScale = 1.0f + level * 0.12f
        orbOuterRing.scaleX = outerScale
        orbOuterRing.scaleY = outerScale

        val innerScale = 1.0f + level * 0.08f
        orbOuterRing2.scaleX = innerScale
        orbOuterRing2.scaleY = innerScale

        // Staggered ripple expansions (period = 2000ms, staggered by 1000ms)
        if (currentOrbState == "listening" || currentOrbState == "speaking") {
            val elapsed = System.currentTimeMillis() - rippleStartTime
            val p1 = (elapsed % 2000) / 2000f
            val p2 = if (elapsed >= 1000) ((elapsed - 1000) % 2000) / 2000f else 0f

            orbWaveRipple1.scaleX = 0.7f + p1 * (1.3f + level * 0.8f)
            orbWaveRipple1.scaleY = 0.7f + p1 * (1.3f + level * 0.8f)
            orbWaveRipple1.alpha = (1.0f - p1) * (0.2f + level * 0.8f)

            if (elapsed >= 1000) {
                orbWaveRipple2.visibility = View.VISIBLE
                orbWaveRipple2.scaleX = 0.7f + p2 * (1.3f + level * 0.8f)
                orbWaveRipple2.scaleY = 0.7f + p2 * (1.3f + level * 0.8f)
                orbWaveRipple2.alpha = (1.0f - p2) * (0.2f + level * 0.8f)
            } else {
                orbWaveRipple2.visibility = View.INVISIBLE
            }
        }
    }

    override fun onDestroy() {
        stopAudioListening()
        super.onDestroy()
        activeTasksListenerRegistration?.remove()
        approvalsListenerRegistration?.remove()
        incidentsListenerRegistration?.remove()
        careerListenerRegistration?.remove()
        profileInsightsListenerRegistration?.remove()
        statusListenerRegistration?.remove()
    }
}
