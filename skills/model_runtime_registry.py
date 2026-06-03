"""
model_runtime_registry.py — Model Health and Cooldown Registry for ARIA
========================================================================
Tracks model health, failure rates, latencies, and quota cooldowns.
Uses adaptive cooldown intervals to prevent cascade latency and dead-API retries.
"""

import time
import math

class ModelHealth:
    def __init__(self, name, provider, capabilities, quality_score, internet_required=True):
        self.name = name
        self.provider = provider
        self.capabilities = capabilities  # ['text', 'vision', 'planning', 'coding', 'chat']
        self.quality_score = quality_score  # Integer, higher is better
        self.internet_required = internet_required
        
        self.status = "HEALTHY"  # HEALTHY, COOLDOWN, UNAVAILABLE
        self.cooldown_until = 0.0
        self.failure_count = 0
        self.last_success_time = 0.0
        self.avg_latency = 0.0
        self.latency_samples = []
        self.quota_failures = 0

    def record_success(self, latency):
        self.failure_count = 0
        self.status = "HEALTHY"
        self.cooldown_until = 0.0
        self.last_success_time = time.time()
        
        # Keep running average of latency
        self.latency_samples.append(latency)
        if len(self.latency_samples) > 10:
            self.latency_samples.pop(0)
        self.avg_latency = sum(self.latency_samples) / len(self.latency_samples)

    def record_failure(self, is_quota_error=False):
        self.failure_count += 1
        if is_quota_error:
            self.quota_failures += 1
            
        # Calculate adaptive cooldown
        # Failure 1: 1 minute (60s)
        # Failure 2: 5 minutes (300s)
        # Failure 3: 15 minutes (900s)
        # Failure 4+: 1 hour (3600s)
        if self.failure_count == 1:
            cooldown_duration = 60
        elif self.failure_count == 2:
            cooldown_duration = 300
        elif self.failure_count == 3:
            cooldown_duration = 900
        else:
            cooldown_duration = 3600
            
        self.status = "COOLDOWN"
        self.cooldown_until = time.time() + cooldown_duration
        print(f"[ModelRegistry] {self.name} failed (count: {self.failure_count}). Cooldown for {cooldown_duration}s.")

    def is_available(self, internet_available=True):
        if self.status == "UNAVAILABLE":
            return False
        if self.internet_required and not internet_available:
            return False
            
        now = time.time()
        if self.status == "COOLDOWN":
            if now > self.cooldown_until:
                # Cooldown expired! Reset status
                self.status = "HEALTHY"
                return True
            return False
        return True


class ModelRuntimeRegistry:
    def __init__(self):
        self.models = {}
        self._register_default_models()

    def _register_default_models(self):
        # Register Gemini models
        self.register_model(ModelHealth("gemini-2.5-flash", "gemini", ["text", "vision", "planning", "coding", "chat"], 10, internet_required=True))
        self.register_model(ModelHealth("gemini-2.0-flash", "gemini", ["text", "vision", "chat"], 8, internet_required=True))
        
        # Register Groq models
        self.register_model(ModelHealth("llama-3.3-70b-versatile", "groq", ["text", "planning", "chat"], 7, internet_required=True))
        self.register_model(ModelHealth("gemma2-9b-it", "groq", ["text", "chat"], 6, internet_required=True))
        self.register_model(ModelHealth("llama-3.1-8b-instant", "groq", ["text", "chat"], 5, internet_required=True))
        
        # Register local/Ollama models
        self.register_model(ModelHealth("ollama_local", "ollama", ["text", "chat"], 4, internet_required=False))
        self.register_model(ModelHealth("moondream", "ollama", ["vision"], 3, internet_required=False))

    def register_model(self, model_health):
        self.models[model_health.name] = model_health

    def get_model(self, name):
        return self.models.get(name)

    def record_success(self, name, latency):
        m = self.get_model(name)
        if m:
            m.record_success(latency)

    def record_failure(self, name, is_quota_error=False):
        m = self.get_model(name)
        if m:
            m.record_failure(is_quota_error)
            
        # Shared provider key/quota logic: If one model of a provider hits a 429 quota failure,
        # cooldown all models under the same provider since they share the key/quota.
        if m and m.provider in ["gemini", "groq"] and is_quota_error:
            provider = m.provider
            for other_name, other_m in self.models.items():
                if other_m.provider == provider and other_name != name:
                    other_m.record_failure(is_quota_error=True)

    def get_best_model(self, task_type, has_image=False, internet_available=True):
        """
        Retrieves the highest-quality healthy model that supports the required capabilities.
        Uses task preferences to tailor the candidate order.
        """
        # Capability required
        req_cap = "vision" if has_image else "text"
        
        # Task type preferences (ordered highest priority first)
        preferences = {
            "fast_chat":  ["llama-3.1-8b-instant", "gemma2-9b-it", "llama-3.3-70b-versatile", "gemini-2.0-flash", "gemini-2.5-flash", "ollama_local"],
            "chat":       ["gemini-2.5-flash", "gemini-2.0-flash", "llama-3.3-70b-versatile", "gemma2-9b-it", "llama-3.1-8b-instant", "ollama_local"],
            "search":     ["gemini-2.5-flash", "gemini-2.0-flash", "llama-3.3-70b-versatile", "ollama_local"],
            "planning":   ["gemini-2.5-flash", "llama-3.3-70b-versatile", "gemini-2.0-flash", "ollama_local"],
            "coding":     ["gemini-2.5-flash", "gemini-2.0-flash", "llama-3.3-70b-versatile", "ollama_local"],
            "vision":     ["gemini-2.5-flash", "gemini-2.0-flash", "moondream"]
        }
        
        pref_order = preferences.get(task_type, preferences["chat"])
        
        # Filter and rank candidates
        candidates = []
        for name in pref_order:
            m = self.get_model(name)
            if m and m.is_available(internet_available) and req_cap in m.capabilities:
                candidates.append(m)
                
        # Fallback to any healthy model if preference list yielded nothing
        if not candidates:
            for m in self.models.values():
                if m.is_available(internet_available) and req_cap in m.capabilities:
                    candidates.append(m)
                    
        if candidates:
            # First candidate in preference order is chosen
            selected = candidates[0]
            print(f"[ModelRegistry] Selected best model: '{selected.name}' ({selected.provider}) for task '{task_type}' (image: {has_image})")
            return selected
            
        print("[ModelRegistry] WARNING: No healthy models found! Falling back to offline local parser.")
        return None
