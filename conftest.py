"""
conftest.py — pytest configuration file for ARIA test suite.

Configures pytest to exclude known-bad test files that require
unavailable hardware drivers (mediapipe C++ extensions, vedo).
"""

import warnings

# Suppress known DeprecationWarnings from third-party libraries
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=ResourceWarning)


collect_ignore_glob = [
    "scratch/test_ar_playground.py",   # Requires mediapipe with C++ gestural extensions
    "scratch/test_vedo_text.py",        # Requires vedo 3D graphics library
]
