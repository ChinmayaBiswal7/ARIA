"""
skills/person_profile_manager.py — Known Person Profile Registry for ARIA
======================================================================
Manages registered profiles (names, roles, metadata) in a local JSON configuration.
Works in tandem with AriaFaceMemoryStore to support multi-person tracking.
"""

import os
import json
import time

class AriaPersonProfileManager:
    def __init__(self, db_dir: str = "data/face_memory"):
        self.db_dir = db_dir
        self.profiles_path = os.path.join(self.db_dir, "person_profiles.json")
        self.profiles = {}
        
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)
            
        self.load()

    def load(self):
        """Loads profile dictionary from disk."""
        if os.path.exists(self.profiles_path):
            try:
                with open(self.profiles_path, "r", encoding="utf-8") as f:
                    self.profiles = json.load(f)
            except Exception as e:
                print(f"[PersonProfileManager] Load error: {e}")
                self.profiles = {}
        else:
            self.profiles = {}

    def save(self):
        """Saves profile database to disk."""
        try:
            with open(self.profiles_path, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2)
        except Exception as e:
            print(f"[PersonProfileManager] Save error: {e}")

    def register_person(self, name: str, role: str = "User") -> bool:
        """Registers or updates a profile name in the local registry."""
        name_clean = name.strip()
        if not name_clean:
            return False

        if name_clean not in self.profiles:
            self.profiles[name_clean] = {
                "name": name_clean,
                "role": role,
                "created_at": int(time.time()),
                "total_face_samples": 0
            }
        else:
            self.profiles[name_clean]["role"] = role
            
        self.save()
        return True

    def increment_face_count(self, name: str):
        """Increments the indexed visual frame counter for a profile."""
        name_clean = name.strip()
        if name_clean in self.profiles:
            self.profiles[name_clean]["total_face_samples"] += 1
            self.save()

    def get_profile(self, name: str) -> dict:
        """Returns metadata for a given profile name."""
        return self.profiles.get(name.strip())

    def list_profiles(self) -> list:
        """Lists all registered profiles."""
        return list(self.profiles.values())
