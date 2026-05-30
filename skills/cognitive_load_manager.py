import os
import sqlite3
import psutil
import threading
import time

class CognitiveLoadManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CognitiveLoadManager, cls).__new__(cls)
                cls._instance.interruption_count = 0
                cls._instance.failure_count = 0
                cls._instance.last_reset = time.time()
            return cls._instance

    def log_interruption(self):
        self.interruption_count += 1

    def log_failure(self):
        self.failure_count += 1

    def get_load_metrics(self):
        # Reset counts every 10 minutes to maintain active rolling window
        now = time.time()
        if now - self.last_reset > 600:
            self.interruption_count = 0
            self.failure_count = 0
            self.last_reset = now

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        
        # Calculate load score (0.0 to 1.0)
        score = 0.0
        score += (cpu / 100.0) * 0.25
        score += (ram / 100.0) * 0.25
        score += min(self.interruption_count * 0.15, 0.25)
        score += min(self.failure_count * 0.15, 0.25)
        
        status = "NORMAL"
        if score > 0.7:
            status = "OVERLOADED"
        elif score > 0.4:
            status = "STRESSED"
            
        return {
            "load_score": round(score, 2),
            "status": status,
            "cpu": cpu,
            "ram": ram,
            "interrupts": self.interruption_count,
            "failures": self.failure_count
        }

    def regulate_cognition(self, main_agent):
        """Dynamically adjusts autonomy and initiates garbage collection based on load."""
        metrics = self.get_load_metrics()
        if metrics["status"] == "OVERLOADED":
            print(f"[CognitiveLoad] System OVERLOADED (Load score: {metrics['load_score']}). Regulating autonomy.")
            
            # 1. Enforce Safe Mode if in auto mode to protect user workspace
            from dashboard import CognitionState
            if CognitionState.mode == "auto":
                CognitionState.mode = "safe"
                main_agent._speak("Warning. I am experiencing high cognitive load. Switching to Safe Mode to ensure stable task verification.")
                
            # 2. Trigger aggressive database compression
            try:
                main_agent.memory_skill.compress_memories()
            except Exception as e:
                print(f"[CognitiveLoad] Compacting error: {e}")
                
            return True
        return False
