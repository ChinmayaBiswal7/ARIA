# ARIA Health Bridge Android App

A background utility app in Kotlin that reads steps, active calories, sleep duration, and heart rate from Android Health Connect (Google Fit / Samsung Health) and syncs it to your ARIA Firebase project.

## File Structure

- `app/src/main/java/com/aria/bridge/`
  - `MainActivity.kt`: Status interface, manual sync button, and permission request.
  - `HealthConnectManager.kt`: Reads daily steps, sleep, active calories, and heart rate from Health Connect API.
  - `SyncWorker.kt`: Periodic `WorkManager` job executing every 30 minutes in the background.
  - `FirestoreUploader.kt`: Writes metrics payload directly to your Firestore collection `health`, document `latest`.

---

## Setup & Deployment Instructions

### Prerequisites
1. **Android Studio**: Ensure you have Android Studio installed.
2. **Health Connect**: Install the [Health Connect app](https://play.google.com/store/apps/details?id=com.google.android.apps.healthdata) on your Android device (built-in on Android 14+).
3. **Fitness Provider**: Connect Samsung Health or Google Fit to Health Connect so fitness data is populated.

### Step 1: Import Project in Android Studio
1. Open Android Studio.
2. Select **File > Open** or **Import Project**.
3. Choose the directory `health_bridge_android/` from your workspace.

### Step 2: Download `google-services.json`
Since this app uses the official Firebase Android SDK to sync metrics to Firestore:
1. Go to your **Firebase Console** (select your project `aria-3e1da`).
2. Add a new **Android App** to the project:
   - Package name: `com.aria.bridge`
3. Download the generated `google-services.json`.
4. Copy `google-services.json` and paste it inside the `health_bridge_android/app/` folder.

### Step 3: Run & Authorize Permissions
1. Connect your Android device via USB (with Developer Options and USB Debugging enabled).
2. Press **Run** in Android Studio to build and deploy the APK.
3. Once the app launches on your phone:
   - Click **Grant Permissions**.
   - Toggle all read permissions on (Steps, Active Calories, Sleep, Heart Rate).
   - Click **Sync Data Now** to trigger an immediate verification sync.
   - Verify that your Firestore console shows updated fields in `/health/latest`.

### Step 4: Silent Background Operation
The app automatically schedules a background `WorkManager` sync task every 30 minutes. To ensure Samsung or Android OS does not sleep the task:
1. Go to your phone's **Settings > Apps > ARIA Health Bridge**.
2. Select **Battery**.
3. Set it to **Unrestricted** (disables battery optimization for background WorkManager).
