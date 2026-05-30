import os
import json
import sqlite3
import time
import numpy as np

class SceneMemory:
    """Handles scene/environment memory for ARIA, utilizing ChromaDB and SQLite."""
    
    def __init__(self, vector_memory, db_path="aria_memory.db"):
        self.vector_mem = vector_memory
        self.db_path = db_path
        self.scenes_collection = None
        self._init_chroma()
        self._init_sqlite()

    def _init_chroma(self):
        if self.vector_mem and self.vector_mem.chroma_client:
            try:
                self.scenes_collection = self.vector_mem.chroma_client.get_or_create_collection(
                    name="aria_scenes",
                    metadata={"hnsw:space": "cosine"}
                )
                print("[SceneMemory] ChromaDB collection 'aria_scenes' initialized.")
            except Exception as e:
                print(f"[SceneMemory] Failed to create ChromaDB collection: {e}")

    def _init_sqlite(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scene_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name TEXT UNIQUE NOT NULL,
                    objects_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SceneMemory] SQLite table creation error: {e}")

    def learn_scene(self, room_name, objects_list):
        """
        Associate a list of objects with a room name and store in ChromaDB and SQLite.
        """
        if not objects_list:
            return False, "No objects detected in the current environment to learn."
            
        room_name = room_name.strip().lower()
        sorted_objects = sorted([obj.lower().strip() for obj in objects_list])
        objects_str = ", ".join(sorted_objects)
        document_text = f"Objects present: {objects_str}"
        now = time.time()
        
        # 1. Save to SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO scene_memory (room_name, objects_json, created_at)
                VALUES (?, ?, ?)
            """, (room_name, json.dumps(sorted_objects), now))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[SceneMemory] SQLite save error: {e}")

        # 2. Save/Upsert to ChromaDB
        if self.scenes_collection:
            try:
                self.scenes_collection.upsert(
                    documents=[document_text],
                    metadatas=[{"room_name": room_name, "objects": objects_str}],
                    ids=[room_name]
                )
                print(f"[SceneMemory] Saved scene '{room_name}' with objects [{objects_str}] to ChromaDB.")
                return True, f"I have associated this environment with '{room_name}'."
            except Exception as e:
                print(f"[SceneMemory] ChromaDB upsert error: {e}")
                return False, f"Failed to save scene memory to vector DB: {e}"
        
        return True, f"I have saved '{room_name}' locally (ChromaDB offline)."

    def recognize_scene(self, current_objects, threshold=0.75):
        """
        Query ChromaDB with the current list of objects to recognize the room.
        Returns a tuple (room_name, similarity, description) or (None, 0.0, None)
        """
        if not current_objects:
            return None, 0.0, "I do not see any objects to determine the environment."
            
        sorted_objects = sorted([obj.lower().strip() for obj in current_objects])
        objects_str = ", ".join(sorted_objects)
        query_text = f"Objects present: {objects_str}"
        
        pattern_guess = self._check_activity_patterns(sorted_objects)
        
        if self.scenes_collection:
            try:
                results = self.scenes_collection.query(
                    query_texts=[query_text],
                    n_results=1
                )
                if results and 'ids' in results and results['ids'] and results['ids'][0]:
                    room_name = results['ids'][0][0]
                    dist = results['distances'][0][0]
                    sim = 1.0 - dist
                    
                    print(f"[SceneMemory] Query match: '{room_name}' similarity: {sim:.3f}")
                    if sim >= threshold:
                        description = f"You seem to be in the {room_name}."
                        if pattern_guess:
                            description += f" Based on what I see, you might be {pattern_guess}."
                        return room_name, sim, description
            except Exception as e:
                print(f"[SceneMemory] ChromaDB query error: {e}")

        # Fallback keyword match in SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT room_name, objects_json FROM scene_memory")
            rows = cursor.fetchall()
            conn.close()
            
            best_room = None
            best_overlap = 0.0
            
            current_set = set(sorted_objects)
            for room, obj_json in rows:
                saved_list = json.loads(obj_json)
                saved_set = set(saved_list)
                if not saved_set:
                    continue
                intersection = current_set.intersection(saved_set)
                union = current_set.union(saved_set)
                jaccard = len(intersection) / len(union) if union else 0.0
                if jaccard > best_overlap:
                    best_overlap = jaccard
                    best_room = room
                    
            if best_room and best_overlap >= 0.3:
                description = f"You seem to be in the {best_room}."
                if pattern_guess:
                    description += f" Based on what I see, you might be {pattern_guess}."
                return best_room, best_overlap, description
        except Exception as e:
            print(f"[SceneMemory] SQLite fallback query error: {e}")
            
        if pattern_guess:
            return None, 0.5, f"I don't recognize this room, but it looks like you are {pattern_guess}."

        return None, 0.0, "I don't recognize this environment. Say 'learn this room as [name]' to teach me."

    def _check_activity_patterns(self, sorted_objects):
        """
        Advanced rule engine to infer context/activities:
        - bed + darkness / dim lights / person -> resting
        - monitor + keyboard + mouse + chair -> working
        - stove + utensils / oven / refrigerator -> cooking
        - backpack + shoes / handbag -> going out
        """
        objs_set = set(sorted_objects)
        
        # working
        if len(objs_set.intersection({"monitor", "keyboard", "laptop", "mouse", "desk", "chair"})) >= 2:
            return "working at your computer"
        
        # cooking
        if len(objs_set.intersection({"stove", "oven", "refrigerator", "sink", "microwave", "bowl", "fork", "knife", "spoon", "plate", "dining table"})) >= 2:
            return "cooking or preparing food in the kitchen"
            
        # resting
        if "bed" in objs_set:
            return "resting or winding down in your bedroom"
            
        # going out
        if len(objs_set.intersection({"backpack", "shoes", "umbrella", "handbag", "suitcase"})) >= 1:
            return "getting ready to go out"
            
        return None
