"""
Live end-to-end test: simulates the phone sending a command and checks
that the laptop's FirebaseSync receives and executes it.
"""
import sys, time
import unittest
sys.path.insert(0, ".")

from skills.runtime_capabilities import CAPABILITIES

if not CAPABILITIES.has_firebase:
    raise unittest.SkipTest("firebase_admin unavailable; skipping live Firebase sync test")

received = []

def fake_callback(cmd):
    print(f"[TEST] PASS Command received on laptop: \"{cmd}\"")
    received.append(cmd)

from skills.firebase_sync import FirebaseSync

print("=" * 55)
print("  ARIA Phone->Laptop Sync -- Live End-to-End Test")
print("=" * 55)

fs = FirebaseSync(command_callback=fake_callback)
fs.start()
print("[TEST] FirebaseSync started. Waiting 2s for listener to attach...")
time.sleep(2)

# Simulate the phone writing a command to Firestore
import firebase_admin
from firebase_admin import firestore as _fs

db = _fs.client()
cmd_id  = "e2e_test_" + str(int(time.time()))
cmd_txt = "pc status"

db.collection("commands").document("latest").set({
    "id":        cmd_id,
    "text":      cmd_txt,
    "timestamp": time.time(),
})
print(f"[TEST] Phone command written -> id={cmd_id}, text=\"{cmd_txt}\"")
print("[TEST] Waiting 6 s for laptop to receive it...")
time.sleep(6)

# Result
if received:
    print(f"\n[TEST] PASS -- Laptop received {len(received)} command(s): {received}")
else:
    print("\n[TEST] FAIL -- No commands received. Check output above for errors.")

fs.stop()
print("[TEST] Done.")
