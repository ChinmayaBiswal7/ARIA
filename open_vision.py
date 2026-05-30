"""
open_vision.py  -  Standalone ARIA Vision Teach Mode
=====================================================
Run this directly to open the OpenCV camera window.
Keyboard shortcuts (no voice needed):

  L  ->  Type an object name in console -> ARIA learns it from the current frame
  I  ->  Identify what's in the current frame
  S  ->  Show a list of all learned objects
  F  ->  Forget an object (type name in console)
  Q / ESC  ->  Quit

Usage:
    python open_vision.py
"""

import sys
import os

# Make sure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vision_learn import VisionLearner
import cv2
import time
import threading


def console_input_thread(learner: VisionLearner):
    """
    Separate thread that reads keyboard-triggered commands from stdin
    so the camera display loop never blocks.
    """
    print("\n" + "="*52)
    print("  ARIA VISION  -  Standalone Teach Mode")
    print("="*52)
    print("  Press keys IN THE CAMERA WINDOW:")
    print("    L  ->  learn object (type name in console)")
    print("    I  ->  identify what you're holding")
    print("    S  ->  show learned objects")
    print("    F  ->  forget an object")
    print("    Q / ESC  ->  quit")
    print("="*52 + "\n")

    while learner.running:
        time.sleep(0.05)   # just keep thread alive; keys handled in main loop


def main():
    learner = VisionLearner()

    ok = learner.start_camera()
    if not ok:
        print("\n[open_vision] ERROR: Could not open the camera.")
        print("  • Make sure your webcam is connected.")
        print("  • Close any other app using the camera (Teams, Zoom, etc.).")
        input("\nPress Enter to exit...")
        return

    print("\n[open_vision] Camera open! Click the ARIA VISION window and use keys L / I / S / F / Q.\n")

    # ── patch _loop to intercept key presses ──────────────────────────────────
    # We monkey-patch the running flag approach: we re-implement the key loop
    # since vision_learn._loop already does cv2.imshow + cv2.waitKey.
    # The simplest approach: let _loop run normally (it handles Q/ESC),
    # and poll waitKey in the MAIN thread via a wrapper — but since _loop
    # is already in a daemon thread, we just read keys from the WINDOW here.

    while learner.running:
        # waitKey on the ARIA VISION window (created by the background thread)
        # We can call it from any thread — OpenCV on Windows handles this fine.
        key = cv2.waitKey(80) & 0xFF

        if key == ord('q') or key == 27:        # Q or ESC
            learner.stop_camera()
            break

        elif key == ord('l') or key == ord('L'):  # Learn
            name = input("\n  Object name to learn -> ").strip()
            if name:
                success, msg = learner.capture_and_learn(name)
                if success:
                    print(f"  [SUCCESS] Learned '{name}'  ({msg})")
                else:
                    print(f"  [FAILED] {msg}")
            else:
                print("  (no name entered, skipped)")

        elif key == ord('i') or key == ord('I'):  # Identify
            result = learner.identify_object()
            print(f"\n  [Identify] {result}\n")

        elif key == ord('s') or key == ord('S'):  # Show list
            result = learner.list_learned()
            print(f"\n  [Learned Objects] {result}\n")

        elif key == ord('f') or key == ord('F'):  # Forget
            name = input("\n  Object name to forget -> ").strip()
            if name:
                removed = learner.forget_object(name)
                print(f"  {'[SUCCESS] Forgot' if removed else '[FAILED] Not found:'} '{name}'")
            else:
                print("  (no name entered, skipped)")

    # Give background thread a moment to release camera
    time.sleep(0.5)
    print("\n[open_vision] Vision session ended. Goodbye!")


if __name__ == "__main__":
    main()
