import sys
import os
import json
import time

CONFIG_PATH = "firebase_config.json"
SERVICE_ACCOUNT_PATH = "serviceAccountKey.json"

def verify_sdk_connection(project_id):
    print("\n[SDK Mode] Initializing secure Firebase Admin SDK...")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
            firebase_admin.initialize_app(cred)
            
        db = firestore.client()
        print("[SDK Mode] Successfully connected. Attempting to write test document...")
        
        doc_ref = db.collection("status").document("latest")
        doc_ref.set({
            "status": "idle",
            "last_response": "SDK diagnostic connection test passed! ARIA realtime sync is fully working.",
            "timestamp": time.time()
        })
        
        print("[SDK Mode] SUCCESS: Written status to 'status/latest' document in Firestore!")
        return True
    except Exception as e:
        print(f"[SDK Mode] Connection failed: {e}")
        return False

def verify_rest_connection(project_id):
    import urllib.request
    print("\n[REST Mode] Testing public REST API fallback...")
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/status/latest"
    payload = {
        "fields": {
            "status": {"stringValue": "idle"},
            "last_response": {"stringValue": "REST diagnostic connection test passed!"},
            "timestamp": {"doubleValue": time.time()}
        }
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={'Content-Type': 'application/json'},
            method="PATCH"
        )
        with urllib.request.urlopen(req) as response:
            print("[REST Mode] SUCCESS: Written status via public REST API!")
            return True
    except Exception as e:
        print(f"[REST Mode] Public write failed (expected if rules are locked): {e}")
        return False

def main():
    print("==================================================")
    print("   ARIA Cloud Firestore Diagnostic Tool")
    print("==================================================")
    
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: {CONFIG_PATH} not found.")
        return
        
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
        
    project_id = config.get("project_id", "").strip()
    enabled = config.get("enabled", False)
    
    print(f"Target Project ID: {project_id}")
    print(f"Integration Enabled: {enabled}")
    
    if not enabled:
        print("\nNote: FirebaseSync is disabled in config.")
        return

    # Check for service account key
    sdk_available = os.path.exists(SERVICE_ACCOUNT_PATH)
    print(f"Service Account File Found: {sdk_available}")

    if sdk_available:
        sdk_success = verify_sdk_connection(project_id)
        if sdk_success:
            print("\n[CONCLUSION] Realtime SDK Mode is FULLY OPERATIONAL. You can lock your Firestore rules now.")
            return
            
    # Try REST fallback
    rest_success = verify_rest_connection(project_id)
    
    if not sdk_available and not rest_success:
        print("\n[CONCLUSION] Action Required: Please verify your Firebase settings and rules.")

if __name__ == "__main__":
    main()
