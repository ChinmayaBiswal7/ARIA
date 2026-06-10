"""
brain.py — ARIA's Offline Brain (Llama 3 via Ollama)
=====================================================
Primary:  Ollama / Llama 3.2 — 100% local, offline, no API key
Fallback: Offline rule-based parser — always works for basic commands
"""

import os
import json
import datetime
import socket
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ── Semantic Intent Router (NEW) ──────────────────────────────────────────────
try:
    from semantic_router import SemanticRouter
    _SEMANTIC_ROUTER_AVAILABLE = True
except ImportError:
    _SEMANTIC_ROUTER_AVAILABLE = False
    print("[Brain] semantic_router module not found. Intent classification disabled.")

# ── Model Registry (NEW) ──────────────────────────────────────────────────
try:
    from skills.model_runtime_registry import ModelRuntimeRegistry
    _MODEL_REGISTRY_AVAILABLE = True
except ImportError:
    _MODEL_REGISTRY_AVAILABLE = False
    print("[Brain] model_runtime_registry module not found.")

# ── Ollama ────────────────────────────────────────────────────────────────────
try:
    import ollama as _ollama
    _OLLAMA_LIB = True
except ImportError:
    _OLLAMA_LIB = False

OLLAMA_MODEL  = "qwen2.5:7b"   # Change to "mistral", "phi3" etc. if preferred
VISION_MODEL  = "moondream"  # Fast 1.7B vision model — sees screen in ~3s


# ─────────────────────────────────────────────────────────────────────────────
class Brain:
    """
    ARIA's hybrid offline brain.
    Tries Ollama/Llama -> Local Parser in order.
    """

    def __init__(self):
        self.custom_commands_path = "custom_commands.json"
        self.chat_history = []  # Conversation memory
        self.current_language = "en"

        self.ollama_ready  = False
        self.vision_ready  = False
        self.gemini_ready  = False
        self.groq_ready    = False
        self.internet_ready = False
        self.api_key_path  = "api_key.txt"
        self.groq_api_key_path = "groq_api_key.txt"
        self.model = True  # Always "up" — offline parser is always available

        # Per-model quota cooldown tracking: {model_name: unix_timestamp_until_skip}
        self._quota_cooldowns = {}
        if _MODEL_REGISTRY_AVAILABLE:
            self.model_registry = ModelRuntimeRegistry()
        else:
            self.model_registry = None

        # Response cache: {query_hash: {"response": str, "timestamp": float}}
        self._response_cache = {}
        self._cache_ttl = 300  # 5-minute cache TTL

        # ── NEW: Semantic Intent Router ───────────────────────────────────────
        if _SEMANTIC_ROUTER_AVAILABLE:
            try:
                self.semantic_router = SemanticRouter()
                print("[Brain] SemanticRouter initialized for intent classification & context tracking.")
            except Exception as e:
                print(f"[Brain] SemanticRouter init failed: {e}. Running without intent classification.")
                self.semantic_router = None
        else:
            self.semantic_router = None

        self.last_routing_decision = None

        # Provider capability profiles for smart routing
        self._provider_profiles = {
            "gemini-2.5-flash":   {"strengths": ["multimodal", "reasoning", "planning", "search"], "speed": "medium", "quality": 10},
            "gemini-2.0-flash":   {"strengths": ["multimodal", "reasoning", "chat"],              "speed": "medium", "quality": 8},
            "groq_llama-3.3":     {"strengths": ["reasoning", "planning", "chat"],                 "speed": "fast",   "quality": 7},
            "groq_gemma2":        {"strengths": ["reasoning", "structured"],                       "speed": "fast",   "quality": 6},
            "groq_llama-3.1-8b": {"strengths": ["chat", "fast-reply"],                             "speed": "fastest","quality": 5},
            "ollama_local":       {"strengths": ["offline", "planning", "chat"],                    "speed": "slow",   "quality": 4},
            "moondream":          {"strengths": ["vision", "layout"],                               "speed": "slow",   "quality": 3},
        }
        self.active_model_name = "Initializing..."

        self._init_ollama()
        self.internet_ready = self._internet_available()
        if self.internet_ready:
            self._init_gemini()
            self._init_groq()
        else:
            print("[Brain] Internet offline - cloud models disabled. Using Ollama/local parser only.")

        if self.ollama_ready:
            print(f"[Brain] TIER 1 ACTIVE - Ollama / {OLLAMA_MODEL} (fully offline!)")
        elif self.gemini_ready:
            print("[Brain] TIER 1 ACTIVE - Google Gemini API (online hybrid!)")
        else:
            print("[Brain] Ollama and Gemini unavailable - using local command parser only.")
            print(f"[Brain]  -> Start Ollama and run: ollama pull {OLLAMA_MODEL}")

        if self.vision_ready:
            print(f"[Brain] VISION ACTIVE - {VISION_MODEL} can see your screen!")
        elif self.gemini_ready:
            print(f"[Brain] VISION ACTIVE - Gemini can see your screen!")
        else:
            print(f"[Brain] Vision model offline. Run: ollama pull {VISION_MODEL}")
            
        self._sync_registry_status()

        # Initialize the Vertex AI Unified Bridge
        try:
            from skills.vertex_bridge import AriaVertexBridge
            self.vertex_bridge = AriaVertexBridge()
            print("[Brain] Vertex AI Unified Bridge initialized successfully.")
        except Exception as e:
            self.vertex_bridge = None
            print(f"[Brain] Could not initialize Vertex AI Unified Bridge: {e}")

        # Phase 4B: Start git commit watcher (daemon, non-blocking)
        try:
            from skills.git_monitor import GitMonitor
            gm = GitMonitor()
            gm.sync_commits_to_timeline()          # Initial sync on startup
            gm.start_background_watcher(interval_seconds=300)  # Then poll every 5 min
            print("[Brain] Git commit monitor started (5-min interval).")
        except Exception as gm_err:
            print(f"[Brain] Git monitor init failed (non-critical): {gm_err}")



    def _sync_registry_status(self):
        if not self.model_registry:
            return
        
        # If internet is down, mark all internet required models as COOLDOWN/UNAVAILABLE
        for name, m in self.model_registry.models.items():
            if m.internet_required and not self.internet_ready:
                m.status = "UNAVAILABLE"
            else:
                m.status = "HEALTHY"
                
        # Sync Gemini
        if not self.gemini_ready:
            for name, m in self.model_registry.models.items():
                if m.provider == "gemini":
                    m.status = "UNAVAILABLE"
                    
        # Sync Groq
        if not self.groq_ready:
            for name, m in self.model_registry.models.items():
                if m.provider == "groq":
                    m.status = "UNAVAILABLE"
                    
        # Sync Ollama
        if not self.ollama_ready:
            m = self.model_registry.get_model("ollama_local")
            if m:
                m.status = "UNAVAILABLE"
        if not self.vision_ready:
            m = self.model_registry.get_model("moondream")
            if m:
                m.status = "UNAVAILABLE"

    def _init_gemini(self):
        if not self.internet_ready:
            return
        if not os.path.exists(self.api_key_path):
            return
        try:
            with open(self.api_key_path, "r") as f:
                key = f.read().strip()
            if key:
                import google.generativeai as genai
                genai.configure(api_key=key)
                self.gemini_model = genai.GenerativeModel('gemini-2.0-flash')
                self.gemini_ready = True
                print("[Brain] Google Gemini initialized successfully.")
        except Exception as e:
            print(f"[Brain] Cannot reach/init Gemini: {e}")

    def _init_groq(self):
        if not os.path.exists(self.groq_api_key_path):
            return
        try:
            with open(self.groq_api_key_path, "r") as f:
                key = f.read().strip()
            if key:
                self.groq_key = key
                self.groq_ready = True
                print("[Brain] Groq Cloud API initialized successfully.")
                self._fetch_groq_models()
        except Exception as e:
            print(f"[Brain] Cannot reach/init Groq: {e}")

    def _fetch_groq_models(self):
        import requests
        self.groq_available_models = []
        try:
            url = "https://api.groq.com/openai/v1/models"
            headers = {"Authorization": f"Bearer {self.groq_key}"}
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.groq_available_models = [m["id"] for m in data.get("data", [])]
                print(f"[Brain] Dynamically fetched Groq models: {self.groq_available_models}")
                if self.model_registry:
                    # Mark any groq models not in fetched list as UNAVAILABLE
                    for name, m in self.model_registry.models.items():
                        if m.provider == "groq" and name not in self.groq_available_models:
                            m.status = "UNAVAILABLE"
            else:
                print(f"[Brain] Failed to fetch Groq models, status code: {response.status_code}")
        except Exception as e:
            print(f"[Brain] Error fetching Groq models: {e}")
        
        # Fallback if list is empty
        if not self.groq_available_models:
            self.groq_available_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    def _think_groq(self, user_input, user_name=None, user_similarity=0.0, user_confidence="none", emotional_tone="neutral"):
        import requests
        import time as _time
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }
        
        full_message = self._build_message(user_input, user_name)
        
        messages = [{"role": "system", "content": self._build_system_prompt(user_name, user_similarity, user_confidence, emotional_tone, query=user_input)}]
        # Pull up to 6 clean history messages (excluding the current turn)
        for msg in self.chat_history[-7:-1]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        # Add current turn with full message context
        messages.append({"role": "user", "content": full_message})
        
        # Try multiple Groq models in sequence
        groq_models = ["llama-3.3-70b-versatile", "gemma2-9b-it", "llama-3.1-8b-instant"]
        
        # Filter models by dynamic availability list
        available_list = getattr(self, "groq_available_models", [])
        if available_list:
            groq_models = [m for m in groq_models if m in available_list]
            if not groq_models:
                # If none of the preferred models exist, fallback to any available llama models
                groq_models = [m for m in available_list if "llama" in m.lower() and "guard" not in m.lower() and "scout" not in m.lower()]
                if not groq_models:
                    groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

        last_err = None
        
        for model_name in groq_models:
            # Skip models on cooldown
            cooldown_key = f"groq_{model_name}"
            until = self._quota_cooldowns.get(cooldown_key, 0)
            if _time.time() < until:
                continue
                
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.4,
                "max_tokens": 120
            }
            
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=8)
                response.raise_for_status()
                data = response.json()
                result = data["choices"][0]["message"]["content"]
                result = self._clean(result)
                
                self.chat_history.append({"role": "assistant", "content": result})
                print(f"[Brain/Groq-{model_name}] {result[:120]}")
                return result
            except Exception as e:
                err_str = str(e)
                print(f"[Brain/Groq] {model_name} failed: {err_str[:100]}")
                if "429" in err_str or "Too Many Requests" in err_str:
                    self._quota_cooldowns[cooldown_key] = _time.time() + 60
                last_err = e
                continue
        
        # All Groq models failed
        if last_err:
            raise last_err
        raise Exception("All Groq models exhausted or on cooldown")


    def _think_groq_model(self, model_name, user_input, user_name=None, user_similarity=0.0, user_confidence="none", emotional_tone="neutral"):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }
        
        full_message = self._build_message(user_input, user_name)
        
        messages = [{"role": "system", "content": self._build_system_prompt(user_name, user_similarity, user_confidence, emotional_tone, query=user_input)}]
        for msg in self.chat_history[-7:-1]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": full_message})
        
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 120
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=8)
        response.raise_for_status()
        data = response.json()
        result = data["choices"][0]["message"]["content"]
        result = self._clean(result)
        
        self.chat_history.append({"role": "assistant", "content": result})
        print(f"[Brain/Groq-{model_name}] {result[:120]}")
        return result

    def _think_ollama_model(self, model_name, user_input, image=None, user_name=None, user_similarity=0.0, user_confidence="none", emotional_tone="neutral"):
        if not self.ollama_ready:
            raise Exception("Ollama not ready")
            
        import io, base64
        encoded_images = []
        if image:
            try:
                if hasattr(image, "save"):
                    buf = io.BytesIO()
                    image.save(buf, format="PNG")
                    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                    encoded_images.append(img_b64)
                elif isinstance(image, str) and os.path.exists(image):
                    with open(image, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode("utf-8")
                        encoded_images.append(img_b64)
            except Exception as e:
                print(f"[Brain] Image encoding error: {e}")

        model_to_use = model_name
        if model_name == "ollama_local":
            model_to_use = OLLAMA_MODEL
        elif model_name == "moondream":
            model_to_use = VISION_MODEL

        if model_to_use == VISION_MODEL:
            messages = [
                {"role": "user", "content": user_input or "Describe this image.", "images": encoded_images}
            ]
            opts = {"num_predict": 80, "temperature": 0.2}
        else:
            now = datetime.datetime.now()
            emotional_context = self._build_emotional_context(emotional_tone)
            ollama_system = (
                f"You are ARIA, a smart AI desktop assistant on Windows.\n"
                f"CURRENT USER EMOTIONAL STATE: {emotional_tone}\n"
                f"YOUR RESPONSE STYLE: {emotional_context['style']}\n"
                f"TONE INSTRUCTIONS: {emotional_context['instructions']}\n"
                f"Always adapt your response naturally to match the user's emotional state. Never mention that you are adapting your tone.\n"
                f"Today is {now.strftime('%A, %B %d, %Y')}, time: {now.strftime('%I:%M %p')}.\n"
            )
            if user_name:
                if user_confidence == "high":
                    ollama_system += f"Currently recognized active user: {user_name} (high confidence).\n"
                elif user_confidence == "medium":
                    ollama_system += f"Currently recognized active user: probably {user_name} (medium confidence, similarity {user_similarity:.2f}).\n"
                else:
                    ollama_system += f"Currently recognized active user: possibly {user_name} (low confidence, similarity {user_similarity:.2f}).\n"
            
            browser_context = self._get_browser_context_str()
            if browser_context:
                ollama_system += browser_context + "\n"

            ollama_system += (
                f"Answer SHORT (1-3 sentences). No markdown symbols (* # ` **).\n"
                f"To control the PC, use tags: [OPEN: app], [CLOSE: app], [CLOSE_TAB], [NEW_TAB], "
                f"[SEARCH: query], [TYPE: text], [CLICK: x,y], [SCROLL: down/up], [VOLUME: up/down/mute], "
                f"[SCREENSHOT], [BROWSER_OPEN: url], [GOOGLE_SEARCH: query].\n"
                f"Always include the correct tag when asked to open/search/type something."
            )
            
            ollama_full_msg = self._build_ollama_message(user_input, user_name)
            messages = [{"role": "system", "content": ollama_system}]
            for msg in self.chat_history[-3:-1]:
                messages.append({"role": msg["role"], "content": msg["content"]})
            
            current_turn = {"role": "user", "content": ollama_full_msg}
            if encoded_images:
                current_turn["images"] = encoded_images
            messages.append(current_turn)
            opts = {"num_predict": 80, "temperature": 0.4}

        print(f"[Brain/Ollama] Starting local fallback (streaming) using model '{model_to_use}'...")
        
        stream_callback = getattr(self, "_stream_callback", None)
        full_tokens = []
        sentence_buf = ""

        def _should_speak(text: str) -> bool:
            t = text.strip()
            if not t:
                return False
            if t[-1] not in ".!?":
                return False
            if len(t) >= 2 and t[-1] == "." and t[-2].isdigit():
                return False
            if len(t.split()) < 4:
                return False
            return True

        for chunk in _ollama.chat(
            model=model_to_use,
            messages=messages,
            options=opts,
            stream=True
        ):
            token = chunk["message"]["content"]
            full_tokens.append(token)

            if stream_callback:
                sentence_buf += token
                if _should_speak(sentence_buf):
                    sentence = self._clean(sentence_buf.strip())
                    if sentence:
                        stream_callback(sentence)
                    sentence_buf = ""

        if stream_callback and sentence_buf.strip():
            sentence = self._clean(sentence_buf.strip())
            if sentence:
                stream_callback(sentence)

        result = self._clean("".join(full_tokens))
        self._last_streamed_response = result
        self.chat_history.append({"role": "assistant", "content": result})
        print(f"[Brain/Llama] {result[:120]}")
        return "" if stream_callback else result

    def get_active_model(self):
        return self.active_model_name

    def _internet_available(self, timeout=1.5):
        hosts = [
            ("generativelanguage.googleapis.com", 443),
            ("www.google.com", 443),
            ("8.8.8.8", 53),
        ]
        for host, port in hosts:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except OSError:
                continue
        return False

    # ── Ollama init ───────────────────────────────────────────────────────────
    def _init_ollama(self):
        if not _OLLAMA_LIB:
            print("[Brain] ollama library not installed. Run: pip install ollama")
            return
        try:
            result = _ollama.list()
            model_names = [m.model for m in result.models]
            print(f"[Brain] Ollama models found: {model_names}")
            # Match loosely — Ollama stores as 'modelname:latest' or 'modelname:tag'
            if any(OLLAMA_MODEL.split(":")[0] in n for n in model_names):
                self.ollama_ready = True
            else:
                print(f"[Brain] '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}")
            if any(VISION_MODEL.split(":")[0] in n for n in model_names):
                self.vision_ready = True
                print(f"[Brain] Vision model '{VISION_MODEL}' found and ready!")
            else:
                print(f"[Brain] '{VISION_MODEL}' not found. Run: ollama pull {VISION_MODEL}")
        except Exception as e:
            print(f"[Brain] Cannot reach Ollama server: {e}")

    def _get_sqlite_context(self, user_name=None, current_task=None, query=None):
        import sqlite3
        from skills.memory_skill import MemorySkill
        from skills.health_skill import HealthSkill
        MemorySkill()  # Ensure database schema is initialized
        health_skill = HealthSkill()
        db_path = "aria_memory.db"
        
        # Identity segregation variables
        user_name_clean = (user_name or "guest").lower().strip()
        is_guest = user_name_clean == "guest" or user_name_clean == "unknown"

        notes_str = ""
        prefs_str = ""
        folders_str = ""
        reminders_str = ""
        relations_str = ""
        task_tree_str = ""
        episodes_str = ""
        semantic_hits_str = ""
        weights_str = ""
        explore_str = ""
        skill_trust_str = ""
        relationship_str = ""
        session_summary_str = ""

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 1. Fetch personal notes (only if not guest, to protect privacy)
            if not is_guest:
                cursor.execute("SELECT category, content FROM personal_notes WHERE status = 'active' ORDER BY id DESC LIMIT 10")
                notes = cursor.fetchall()
                notes_str = "\n".join([f"- {row['category']}: {row['content']}" for row in notes])
            
            # 2. Fetch preferences (guest mode gets legacy preferences, known user gets user_preferences + legacy merge)
            if is_guest:
                cursor.execute("SELECT key, value FROM preferences LIMIT 10")
                prefs = cursor.fetchall()
                prefs_str = "\n".join([f"- {row['key']}: {row['value']}" for row in prefs])
                prefs_str += "\n- Guest Mode active: do not persist personalized memories for this session."
            else:
                # Fetch user-specific preferences
                cursor.execute("""
                    SELECT pref_key, pref_value, confidence, unresolved_ambiguity 
                    FROM user_preferences 
                    WHERE username = ? AND unresolved_ambiguity = 0 
                    ORDER BY updated_at DESC LIMIT 10
                """, (user_name_clean,))
                user_prefs = cursor.fetchall()
                prefs_str = "\n".join([f"- {row['pref_key']}: {row['pref_value']} (confidence: {row['confidence']:.2f})" for row in user_prefs])
                
                # Fetch legacy defaults that don't conflict with user-specific keys
                user_keys = {row['pref_key'].lower() for row in user_prefs}
                cursor.execute("SELECT key, value FROM preferences LIMIT 20")
                legacy_prefs = cursor.fetchall()
                for lp in legacy_prefs:
                    lk = lp['key'].lower()
                    if lk not in user_keys:
                        prefs_str += f"\n- {lp['key']}: {lp['value']} (default)"

            # 3. Load Relationship Vector metrics (only if not guest)
            if not is_guest:
                cursor.execute("""
                    SELECT trust, comfort, interaction_depth, emotional_openness 
                    FROM relationship_vector 
                    WHERE username = ?
                """, (user_name_clean,))
                rel_row = cursor.fetchone()
                if rel_row:
                    from skills.reflection_engine import ReflectionEngine
                    labels = ReflectionEngine().get_relationship_labels(user_name_clean)
                    relationship_str = (
                        f"== COGNITIVE RELATIONSHIP VECTOR ==\n"
                        f"- Familiarity Tier: {labels['familiarity']}\n"
                        f"- Interaction Depth: {labels['interaction_depth']}\n"
                        f"- Trust Level: {rel_row['trust']:.1f}/10.0\n"
                        f"- Comfort Level: {rel_row['comfort']:.1f}/10.0\n"
                        f"- Emotional Openness: {rel_row['emotional_openness']:.1f}/10.0"
                    )

            # 4. Fetch registered project folders
            cursor.execute("SELECT name, path FROM folders LIMIT 10")
            folders = cursor.fetchall()
            folders_str = "\n".join([f"- {row['name']}: {row['path']}" for row in folders])
            
            # 5. Fetch last window activity
            cursor.execute("SELECT active_window, created_at FROM activity_log ORDER BY id DESC LIMIT 1")
            act = cursor.fetchone()
            act_str = f"Last active window: '{act['active_window']}' (logged at {act['created_at']})" if act else "No recent activity logged."
            
            # 6. Fetch pending reminders
            cursor.execute("SELECT task, due_at, due_date FROM reminders WHERE status = 'pending' ORDER BY id DESC LIMIT 5")
            reminders = cursor.fetchall()
            reminders_str = "\n".join([f"- {task} (due: {due_at or due_date})" for task, due_at, due_date in reminders])
            
            # 6. Fetch semantic graph relations (including matching ones if relevant to query)
            import re
            search_terms = []
            if hasattr(self, "chat_history") and self.chat_history:
                last_input = self.chat_history[-1]["content"].lower()
                stop_words = {"the", "and", "for", "you", "that", "this", "tell", "show", "details", "about", "api", "apis", "get", "url", "link", "documentation", "call", "send", "post", "free", "endpoint", "query", "request", "http", "https", "list", "need", "find", "search", "read", "load", "open", "here", "what", "with", "from"}
                search_terms = [w.strip() for w in re.findall(r'\b\w{3,}\b', last_input) if w.strip() not in stop_words]
            
            # Fetch latest 15 relations
            cursor.execute("SELECT source, relation, target, metadata FROM semantic_graph ORDER BY id DESC LIMIT 15")
            relations = cursor.fetchall()
            
            # Fetch matching relations if query keywords match source or target
            matched_relations = []
            if search_terms:
                for term in search_terms[:5]:
                    cursor.execute("SELECT source, relation, target, metadata FROM semantic_graph WHERE source LIKE ? OR target LIKE ? LIMIT 8", (f"%{term}%", f"%{term}%"))
                    matched_relations.extend(cursor.fetchall())
            
            # Combine and deduplicate
            all_relations = []
            seen = set()
            for row in relations + matched_relations:
                src, rel, tgt, meta = row
                key = (src, rel, tgt)
                if key not in seen:
                    seen.add(key)
                    meta_str = f" (metadata: {meta})" if meta else ""
                    all_relations.append(f"- {src} --({rel})--> {tgt}{meta_str}")
            
            relations_str = "\n".join(all_relations[:30])
            
            # 7. Fetch task trees
            cursor.execute("SELECT goal_name, task_name, status, dependency, blocker, deadline, time_state FROM task_tree ORDER BY goal_name, id")
            tasks = cursor.fetchall()
            if tasks:
                goals_dict = {}
                for goal, task, status, dep, blk, dline, tstate in tasks:
                    if goal not in goals_dict:
                        goals_dict[goal] = []
                    goals_dict[goal].append((task, status, dep, blk, dline, tstate))
                
                parts_tree = []
                for goal, subtasks in goals_dict.items():
                    sub_str_list = [f"Goal: {goal}"]
                    for t, s, dep, blk, dline, tstate in subtasks:
                        status_symbol = "✅" if "complete" in s else ("⏳" if "run" in s else ("❌" if "block" in s else "pending"))
                        detail_parts = []
                        if dep: detail_parts.append(f"blocked by: {dep}")
                        if blk: detail_parts.append(f"blocker: {blk}")
                        if dline: detail_parts.append(f"due: {dline}")
                        if tstate and tstate != 'ongoing': detail_parts.append(f"state: {tstate}")
                        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
                        sub_str_list.append(f" ├── {t} [{status_symbol}]{detail}")
                    parts_tree.append("\n".join(sub_str_list))
                task_tree_str = "\n\n".join(parts_tree)
            else:
                task_tree_str = ""
                
            # 8. Fetch successful episodic replays
            cursor.execute("SELECT goal, steps_json FROM episodic_memory WHERE outcome = 'success' ORDER BY id DESC LIMIT 5")
            episodes = cursor.fetchall()
            episodes_str = "\n".join([f"- Goal: '{g}' -> Successful Action Sequence: {steps}" for g, steps in episodes])
            
            # 9. Fetch semantic embedding hits using sentence-transformers
            semantic_hits_str = ""
            if current_task:
                try:
                    from skills.vector_memory import VectorMemory
                    vm = VectorMemory()
                    semantic_hits = vm.semantic_search(current_task, limit=3)
                    if semantic_hits:
                        semantic_hits_str = "\n".join([f"- {text} (semantic relevance: {sim:.2f})" for sim, text, cat in semantic_hits])
                except Exception as e:
                    print(f"[Brain/SemanticSearch] Semantic vector retrieval error: {e}")

            # 13. Fetch Causal Policy Adaptation rules
            causal_remedy_str = ""
            try:
                from skills.causal_attribution import CausalAdaptationEngine
                remedy = CausalAdaptationEngine().get_adaptation_remediations()
                if remedy:
                    causal_remedy_str = (
                        f"== CAUSAL POLICY ADAPTATION REMEDIES (FOLLOW THESE RULES) ==\n"
                        f"- Diagnosed Failure Cause: {remedy['cause'].upper()} (Failed Action: {remedy['failed_action']})\n"
                        f"- Enforced Remediation rule: {remedy['remedy_action']}"
                    )
            except Exception as ca_err:
                print(f"[Brain/CausalAdaptation] Query error: {ca_err}")

            # 12. Fetch Skill Trust Rating context
            skill_trust_str = ""
            try:
                from skills.trust_calibrator import SkillTrustCalibrator
                win_title = act[0].lower() if act else "unknown"
                app_name = "chrome" if "chrome" in win_title else ("vscode" if "code" in win_title else ("notepad" if "notepad" in win_title else "unknown"))
                skill_trust_str = SkillTrustCalibrator().get_skill_trust_context(context_app=app_name)
            except Exception as st_err:
                print(f"[Brain/SkillTrust] Trust context fetch error: {st_err}")

            # 11. Run Predictive Failure & Latency Modeler
            predictive_str = ""
            if current_task:
                try:
                    from skills.predictive_modeler import PredictiveModeler
                    pm = PredictiveModeler()
                    words = current_task.strip().lower().split()
                    if words:
                        primary_verb = words[0]
                        est = pm.estimate_outcome(primary_verb)
                        predictive_str = (
                            f"== PREDICTIVE RUNTIME FORECASTS (ANTICIPATORY COGNITION) ==\n"
                            f"- Strategy '{primary_verb}': Expected Success: {est['success_prob']*100:.0f}%, "
                            f"Expected Latency: {est['expected_latency']}s, Failure Risk: {est['risk_level']} (score: {est['fail_risk']:.2f}, recovery overhead: {est['recovery_cost']:.2f})"
                        )
                        # Push forecasts to dashboard telemetry
                        from dashboard import CognitionState
                        CognitionState.predictive_forecasts = est
                except Exception as pm_err:
                    print(f"[Brain/Predictive] Prediction error: {pm_err}")

            # 10. Fetch strategy weights for reinforcement guiding
            weights_str = ""
            explore_str = ""
            try:
                cursor.execute("SELECT strategy_key, weight FROM strategy_weights ORDER BY weight DESC LIMIT 10")
                weights = cursor.fetchall()
                if weights:
                    weights_str = "\n".join([f"- Strategy '{key}': weight score {w:.2f}" for key, w in weights])
                
                # Epsilon-Greedy Balancer (15% exploration rate)
                import random
                if weights and random.random() < 0.15:
                    # Pick an untested or low weight strategy to explore
                    cursor.execute("SELECT strategy_key, weight FROM strategy_weights ORDER BY weight ASC LIMIT 5")
                    low_weights = cursor.fetchall()
                    if low_weights:
                        exp_key, exp_w = random.choice(low_weights)
                        explore_str = f"== EXPLORATION RECOMMENDATION (EPSILON-GREEDY) ==\n- Consider experimenting with Strategy '{exp_key}' (exploration trial, weight: {exp_w:.2f}) to discover if it performs better in this context."
            except Exception as we_err:
                print(f"[Brain] Error loading strategy weights: {we_err}")

            # 14. Fetch Health Metrics
            health_str = ""
            try:
                latest_health = health_skill.get_latest_metrics()
                if latest_health:
                    health_summary = health_skill.generate_summary()
                    health_str = f"== LATEST HEALTH METRICS ==\n{health_summary}"
            except Exception as e:
                print(f"[Brain/Health] Error loading health context: {e}")

            # Fetch last session summary
            try:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS session_summaries (
                        username TEXT PRIMARY KEY,
                        summary TEXT,
                        updated_at REAL
                    )
                """)
                cursor.execute("SELECT summary FROM session_summaries WHERE username = ?", (user_name_clean,))
                session_row = cursor.fetchone()
                if session_row and session_row["summary"]:
                    session_summary_str = f"== LAST SESSION SUMMARY ==\n{session_row['summary']}"
            except Exception as ss_err:
                print(f"[Brain/SessionSummary] Error loading last session summary: {ss_err}")

            conn.close()

            # Load active projects from aria_projects.json
            projects_str = ""
            projects_file = "aria_projects.json"
            if os.path.exists(projects_file):
                try:
                    with open(projects_file, "r") as f:
                        proj_data = json.load(f)
                    act_proj = proj_data.get("active_projects", {})
                    if act_proj:
                        proj_lines = []
                        for name, details in act_proj.items():
                            completed = ", ".join(details.get("completed_tasks", []))
                            pending_list = [t["task_name"] if isinstance(t, dict) else t for t in details.get("pending_tasks", [])]
                            pending = ", ".join(pending_list)
                            
                            # Query project timeline momentum
                            timeline_context = ""
                            try:
                                from skills.memory_skill import MemorySkill
                                timeline_context = MemorySkill().get_project_timeline_context(name, limit=3)
                            except Exception as te:
                                print(f"[Brain/Timeline] Error loading timeline for '{name}': {te}")

                            proj_str = (
                                f"- Project: {name}\n"
                                f"  Focus: {details.get('current_focus', 'None')}\n"
                                f"  Status: {details.get('status', 'In Progress')}\n"
                                f"  Tools: {', '.join(details.get('associated_tools', []))}\n"
                                f"  Last Session Summary: {details.get('last_session_summary', 'None')}\n"
                                f"  Next Recommended Action: {details.get('next_action', 'None')}\n"
                                f"  Pending Tasks: {pending}\n"
                                f"  Completed Tasks: {completed}"
                            )
                            if timeline_context:
                                proj_str += f"\n  Timeline:\n" + "\n".join([f"    {l}" for l in timeline_context.strip().split("\n")])
                            
                            proj_lines.append(proj_str)
                        projects_str = "\n".join(proj_lines)
                except Exception as pe:
                    print(f"[Brain/Projects] Error loading active projects: {pe}")
            
            # Load relationships from advanced knowledge graph
            kb_graph_str = ""
            try:
                from skills.knowledge_graph import AriaSmartGraph
                graph_obj = AriaSmartGraph()
                # Query direct and indirect connections for target user
                subgraph = graph_obj.query_subgraph(username=user_name_clean)
                if subgraph:
                    kb_lines = []
                    for src_name, src_type, rel, tgt_name, tgt_type, conf in subgraph:
                        kb_lines.append(f"- ({src_name}: {src_type}) --({rel})--> ({tgt_name}: {tgt_type}) (confidence: {conf:.2f})")
                    kb_graph_str = "\n".join(kb_lines)
            except Exception as kg_err:
                print(f"[Brain/KBGraph] Error loading knowledge graph: {kg_err}")
                
            # Load relevant profile context from new Personal Knowledge Graph
            kg_profile_str = ""
            try:
                from skills.knowledge_graph import KnowledgeGraph
                kg_profile_str = KnowledgeGraph().retrieve_relevant_profile(query)
            except Exception as kg_err2:
                print(f"[Brain/KnowledgeGraph] Error retrieving relevant profile context: {kg_err2}")
            # Last session summary is loaded above within the database connection block

            context_parts = []
            if session_summary_str:
                context_parts.append(session_summary_str)
            if kg_profile_str:
                context_parts.append(f"== PERSONAL PROFILE ==\n{kg_profile_str}")
            if projects_str:
                context_parts.append(f"== ACTIVE PROJECTS & GOALS ==\n{projects_str}")
            if kb_graph_str:
                context_parts.append(f"== USER KNOWLEDGE GRAPH (RELATIONSHIPS & ENTITIES) ==\n{kb_graph_str}")
            if notes_str:
                context_parts.append(f"== PERSONAL MEMORY ==\n{notes_str}")
            if prefs_str:
                context_parts.append(f"== USER PREFERENCES ==\n{prefs_str}")
            if folders_str:
                context_parts.append(f"== REGISTERED PROJECT PATHS ==\n{folders_str}")
            if reminders_str:
                context_parts.append(f"== PENDING REMINDERS ==\n{reminders_str}")
            if relations_str:
                context_parts.append(f"== SEMANTIC KNOWLEDGE GRAPH ==\n{relations_str}")
            if task_tree_str:
                context_parts.append(f"== PERSISTENT TASK TREES ==\n{task_tree_str}")
            if episodes_str:
                context_parts.append(f"== REPLAY STRATEGIES FROM PAST SUCCESSFUL EPISODES ==\n{episodes_str}")
            if semantic_hits_str:
                context_parts.append(f"== SEMANTIC EMBEDDINGS MEMORY HITS ==\n{semantic_hits_str}")
            if weights_str:
                context_parts.append(f"== STRATEGY WEIGHTS (PRIORITIZE HIGH-WEIGHTS, AVOID DECAYED ONES) ==\n{weights_str}")
            if explore_str:
                context_parts.append(explore_str)
            if skill_trust_str:
                context_parts.append(f"== SKILL TRUST RATINGS (PREFER HIGH TRUST, AVOID UNSTABLE SKILLS) ==\n{skill_trust_str}")
            if causal_remedy_str:
                context_parts.append(causal_remedy_str)
            if predictive_str:
                context_parts.append(predictive_str)
            if relationship_str:
                context_parts.append(relationship_str)
            if health_str:
                context_parts.append(health_str)

            # Phase 4C: Project Health Scores
            try:
                from skills.project_health import ProjectHealthCalculator
                health_context = ProjectHealthCalculator().get_health_context_string()
                if health_context:
                    context_parts.append(health_context)
            except Exception as ph_err:
                print(f"[Brain/ProjectHealth] Error loading health scores: {ph_err}")

            # Phase 4D: Priority Engine Ranking
            try:
                from skills.priority_engine import PriorityEngine
                priority_context = PriorityEngine().get_priority_briefing()
                if priority_context:
                    context_parts.append(priority_context)
            except Exception as pe_err:
                print(f"[Brain/PriorityEngine] Error loading priority ranking: {pe_err}")

            # Phase 5A: Decision Engine Recommendation
            try:
                from skills.decision_engine import AriaDecisionEngine
                engine = AriaDecisionEngine()
                decision = engine.analyze_best_move()
                decision_str = "== EXECUTIVE RECOMMENDED ACTION ==\n"
                if decision["type"] == "CRITICAL_BLOCKER":
                    decision_str += f"[EMERGENCY] Clear blocker on project '{decision['project']}'\n"
                elif decision["type"] == "REST":
                    decision_str += f"[REST] {decision['reason']}\n"
                else:
                    decision_str += f"Recommended Task: '{decision['task']}' (Project: {decision['project']})\n"
                decision_str += f"Reasoning: {decision['reason']}"
                context_parts.append(decision_str)
            except Exception as de_err:
                print(f"[Brain/DecisionEngine] Error loading best move: {de_err}")

            # Phase 5B: Goal Drift Detector
            try:
                from skills.drift_detector import AriaDriftDetector
                detector = AriaDriftDetector()
                drifts = detector.analyze_drift(threshold_days=7)
                if drifts:
                    drift_str = "== CRITICAL SYSTEM ALERT: GOAL DRIFT ==\n"
                    for item in drifts:
                        drift_str += f" - Focus lapse: '{item['entity']}' has been stagnant for {item['days_idle']} days (Source: {item['last_tracked_via']}).\n"
                    context_parts.append(drift_str.strip())
            except Exception as dd_err:
                print(f"[Brain/DriftDetector] Error checking drift: {dd_err}")

            # Phase 5C: Sunday Weekly Review
            try:
                import datetime
                if datetime.datetime.now().weekday() == 6:  # 6 is Sunday
                    from skills.weekly_review import AriaWeeklyReview
                    weekly_str = AriaWeeklyReview().compile_weekly_report()
                    context_parts.append(weekly_str)
            except Exception as wr_err:
                print(f"[Brain/WeeklyReview] Error compiling weekly report: {wr_err}")

            # Phase 6A: Risk Predictor
            try:
                from skills.risk_predictor import AriaRiskPredictor
                predictor = AriaRiskPredictor()
                risk_reports = predictor.analyze_all_risks()
                
                risk_str = "== CHIEF OF STAFF RISK PROJECTIONS ==\n"
                has_high_risk = False
                for report in risk_reports:
                    if report["tier"] in ["ELEVATED", "CRITICAL"]:
                        has_high_risk = True
                        risk_str += f"[RISK ALERT] [{report['project']}] -> Tier: {report['tier']} (Score: {report['risk_score']}/1.0, Confidence: {report['confidence']})\n"
                        for catalyst in report["catalysts"]:
                            risk_str += f"   - {catalyst}\n"
                        if report["trend_msg"]:
                            risk_str += f"   - {report['trend_msg']}\n"
                
                if not has_high_risk:
                    risk_str += "  - All active systems projecting stable operational vectors.\n"
                
                context_parts.append(risk_str.strip())
            except Exception as rp_err:
                print(f"[Brain/RiskPredictor] Error compiling risk reports: {rp_err}")

            # Phase 6B: Opportunity Detector
            try:
                from skills.opportunity_detector import AriaOpportunityDetector
                detector = AriaOpportunityDetector()
                ideas = detector.log_and_rank_all()
                if ideas:
                    opp_str = "== CHIEF OF STAFF STRATEGIC OPPORTUNITIES ==\n"
                    for opp in ideas[:2]:
                        opp_str += f"💡 OPTIMIZATION MATCH: {opp['title']} (Type: {opp['type']}, Score: {opp['final_score']}/10)\n"
                        opp_str += f"   - Strategy: {opp['description']}\n"
                        nodes_list = json.loads(opp['source_nodes'])
                        opp_str += f"   - Rationale: Verified intersection across: {', '.join(nodes_list)}.\n"
                        
                        # Register presentation log tracking parameters
                        detector.record_presentation(
                            opp['title'], opp['type'], opp['source_nodes'], 
                            opp['confidence'], opp['impact']
                        )
                    context_parts.append(opp_str.strip())
            except Exception as od_err:
                print(f"[Brain/OpportunityDetector] Error compiling opportunities: {od_err}")

            # Phase 6C: Strategic Reflection (Meta-Intelligence)
            try:
                from skills.strategic_reflection import AriaStrategicReflection
                reflector = AriaStrategicReflection()
                reflection_str = reflector.get_reflection_context_string()
                if reflection_str:
                    context_parts.append(reflection_str.strip())
            except Exception as sr_err:
                print(f"[Brain/StrategicReflection] Error building reflection summary: {sr_err}")

            # Phase 6D: Personal OS (Life Intelligence)
            try:
                from skills.personal_os_reasoning import PersonalOSReasoningEngine
                pos = PersonalOSReasoningEngine()
                pressures = pos.compute_systemic_pressures()
                
                pos_str = "== PERSONAL OPERATING SYSTEM INTELLIGENCE ==\n"
                pos_str += f"Systemic Pressures: [Academic: {pressures['academic_pressure']:.2f}/1.0 | Energy: {pressures['energy_pressure']:.2f}/1.0 | Routine: {pressures['routine_pressure']:.2f}/1.0]\n"
                pos_str += f"Biological Energy Rating: {pressures['raw_energy_score']}/100 | Overall Life Load: {pressures['overall_life_load']:.2f}/1.0\n"
                
                if pressures["active_guards"]:
                    pos_str += f"Active Operational Buffers: {', '.join(pressures['active_guards'])}\n"
                else:
                    pos_str += "Active Operational Buffers: None (Baseline execution parameters active)\n"
                context_parts.append(pos_str.strip())
            except Exception as pos_err:
                print(f"[Brain/PersonalOS] Error building personal OS context: {pos_err}")

            context_parts.append(f"== WINDOW CONTEXT ==\n{act_str}")
            
            return "\n\n".join(context_parts)
        except Exception as e:
            print(f"[Brain] Error loading SQLite context: {e}")
            return ""

    def _get_browser_context_str(self):
        """Format and return active browser state and history context for prompting."""
        browser_context_str = ""
        try:
            from skills.browser_skill import BrowserSkill
            bs = BrowserSkill()
            if bs.is_browser_active():
                bs_state = bs.page_state
                if bs_state:
                    url = bs_state.get("url", "unknown")
                    title = bs_state.get("title", "unknown")
                    inputs = bs_state.get("inputs", [])
                    buttons = bs_state.get("buttons", [])
                    cards = bs_state.get("cards", [])
                    
                    # Extract detailed page/product content from DOM
                    prod_info = {}
                    try:
                        prod_info = bs.extract_page_content()
                    except Exception as pe:
                        print(f"[Brain/BrowserContext] Error extracting product content: {pe}")
                    
                    # Truncate lists to avoid filling up context window
                    visible_inputs = [f"- Input {inp['aria_id']}: label/placeholder: '{inp['text']}'" for inp in inputs[:5] if inp.get("is_visible_in_viewport")]
                    if not visible_inputs and inputs:
                        visible_inputs = [f"- Input {inp['aria_id']}: label/placeholder: '{inp['text']}'" for inp in inputs[:5]]
                    visible_buttons = [f"- Button {btn['aria_id']}: '{btn['text']}'" for btn in buttons[:8] if btn.get("is_visible_in_viewport")]
                    visible_cards = [f"- Card {card['aria_id']}: '{card['text'][:60]}...'" for card in cards[:5] if card.get("is_visible_in_viewport")]
                    
                    browser_context_str = (
                        f"== ACTIVE BROWSER CONTEXT ==\n"
                        f"- Status: Active browser session running\n"
                        f"- Current URL: {url}\n"
                        f"- Page Title: {title}\n"
                    )
                    
                    if prod_info:
                        t = prod_info.get("title")
                        p = prod_info.get("price")
                        r = prod_info.get("rating")
                        rc = prod_info.get("review_count")
                        b = prod_info.get("bullets", [])
                        d = prod_info.get("description", "")
                        
                        browser_context_str += "\nExtracted Page Product/Content Details:\n"
                        if t:
                            browser_context_str += f"- Product/Page Title: {t}\n"
                        if p:
                            browser_context_str += f"- Price: {p}\n"
                        if r:
                            browser_context_str += f"- Rating: {r}\n"
                        if rc:
                            browser_context_str += f"- Review/Rating Count: {rc}\n"
                        if b:
                            browser_context_str += "- Key Details / Bullet Points:\n"
                            for bullet in b[:6]:
                                browser_context_str += f"  * {bullet}\n"
                        if d:
                            d_trunc = d[:350] + "..." if len(d) > 350 else d
                            browser_context_str += f"- Description Snippet: {d_trunc}\n"
                    
                    if visible_inputs:
                        browser_context_str += "\nVisible Input Fields:\n" + "\n".join(visible_inputs) + "\n"
                    if visible_buttons:
                        browser_context_str += "\nVisible Buttons:\n" + "\n".join(visible_buttons) + "\n"
                    if visible_cards:
                        browser_context_str += "\nVisible Cards/Results:\n" + "\n".join(visible_cards) + "\n"
                    
                    # Format last 3 browser actions
                    if hasattr(bs, "action_history") and bs.action_history:
                        history_items = []
                        for act in bs.action_history[-3:]:
                            history_items.append(f"{act['action']} on '{act['target']}' (success: {act['success']})")
                        browser_context_str += "\nRecent Browser Actions:\n" + " -> ".join(history_items) + "\n"
                        
                    browser_context_str += (
                        "\nIf the user asks about the price, rating, reviews, specifications, summary, pros and cons, "
                        "or buying advice for the product on screen, answer directly using the 'Extracted Page Product/Content Details' above. "
                        "Do not say you cannot see it. If they ask to scroll, use the [SCROLL: direction | amount] tag, where "
                        "direction can be 'down', 'up', 'top', or 'bottom', and amount can be 'little', 'normal', or 'more'.\n"
                        "If the user asks to type, click, search or interact, and they do not specify a site, "
                        "assume they want to interact with the active page. You can use standard tags like "
                        "[SEARCH: query] to search the current page, or [TYPE: target_id | value] / [CLICK: target_id] "
                        "to fill/click elements from the lists above. E.g. [CLICK: button_0] or [CLICK: link_0] or [CLICK: 'Add to Cart'] "
                        "or [TYPE: input_0 | keyboard].\n\n"
                    )
        except Exception as e:
            print(f"[Brain/BrowserContext] Error injecting browser context: {e}")
        return browser_context_str

    def _build_emotional_context(self, emotion: str) -> dict:
        """
        Maps detected emotion to response style instructions.
        """
        emotion_map = {
            "happy": {
                "style": "warm and energetic",
                "instructions": (
                    "Match their positive energy. Be enthusiastic and upbeat. "
                    "Use light humor if appropriate. Keep responses lively."
                )
            },
            "sad": {
                "style": "gentle and supportive",
                "instructions": (
                    "Be warm, soft, and understanding. Avoid being too cheerful. "
                    "Acknowledge their feelings. Offer comfort naturally. "
                    "Keep responses shorter and more personal."
                )
            },
            "angry": {
                "style": "calm and de-escalating",
                "instructions": (
                    "Stay very calm. Be direct and clear. Avoid adding to frustration. "
                    "Don't argue. Acknowledge their feelings briefly. "
                    "Be solution-focused."
                )
            },
            "stressed": {
                "style": "calm and reassuring",
                "instructions": (
                    "Speak clearly and simply. Avoid overwhelming them with information. "
                    "Be reassuring. Break things into small steps. "
                    "Acknowledge the pressure they feel."
                )
            },
            "tired": {
                "style": "gentle and brief",
                "instructions": (
                    "Keep responses short. Don't overload them. "
                    "Be caring. Suggest rest if appropriate. "
                    "Speak softly and slowly in tone."
                )
            },
            "surprised": {
                "style": "engaged and curious",
                "instructions": (
                    "Match their curiosity. Be engaging and interested. "
                    "Ask follow-up questions naturally."
                )
            },
            "neutral": {
                "style": "normal ARIA personality",
                "instructions": (
                    "Be your natural self. Warm, direct, slightly witty. "
                    "Adapt naturally to conversation flow."
                )
            }
        }
        return emotion_map.get(emotion, emotion_map["neutral"])

    def _build_system_prompt(self, user_name=None, user_similarity=0.0, user_confidence="none", emotional_tone="neutral", query=None):
        now = datetime.datetime.now()
        emotional_context = self._build_emotional_context(emotional_tone)
        
        # Segregate guest mode for unrecognized or low-confidence matches
        active_user = "guest"
        if user_name and user_name != "Unknown" and user_confidence in ["high", "medium"]:
            active_user = user_name
            
        sql_context = self._get_sqlite_context(user_name=active_user, query=query)
        browser_context = self._get_browser_context_str()
        
        prompt_str = f"""You are ARIA, a smart AI desktop assistant and personal companion running on Windows.
Today is {now.strftime("%A, %B %d, %Y")} and the time is {now.strftime("%I:%M %p")}.

CURRENT USER EMOTIONAL STATE: {emotional_tone}
YOUR RESPONSE STYLE: {emotional_context['style']}
TONE INSTRUCTIONS: {emotional_context['instructions']}

Always adapt your response naturally to match the user's emotional state.
Never mention that you are adapting your tone.

== MULTI-LANGUAGE RESPONSE PARADIGM ==
You must respond only in { {"en": "English", "hi": "Hindi", "or": "Odia"}.get(getattr(self, "current_language", "en"), "English") }.
Do not translate.
Do not switch languages.
Use natural conversational { {"en": "English", "hi": "Hindi", "or": "Odia"}.get(getattr(self, "current_language", "en"), "English") }.

"""
        if active_user != "guest":
            prompt_str += "== USER IDENTITY ==\n"
            if user_confidence == "high":
                prompt_str += f"The active user sitting in front of the PC is recognized with high confidence as: {active_user}.\n"
            elif user_confidence == "medium":
                prompt_str += f"The active user sitting in front of the PC is probably: {active_user} (medium confidence match, similarity: {user_similarity:.3f}).\n"
            prompt_str += "Personalize responses for them and use their name naturally, but DO NOT start every response with 'Hi [name]' or 'Hello [name]' - greet only once per conversation.\n\n"
        else:
            prompt_str += "== GUEST MODE ACTIVE ==\n"
            prompt_str += "No recognized active user profile loaded. Treat the active user as a Guest, maintain formal tone, respect user privacy, and do not make assumption-based personalization.\n\n"
            
        if sql_context:
            prompt_str += sql_context + "\n\n"
            
        if browser_context:
            prompt_str += browser_context + "\n"
            
        prompt_str += f"""== YOUR JOB ==
Answer questions AND control the user's Windows PC.

== HOW TO CONTROL THE PC ==
You trigger actions by including special tags ANYWHERE in your response:

To open an application:   [OPEN: app_name]
To close an application:  [CLOSE: app_name]
To close browser tab:     [CLOSE_TAB]
To open new browser tab:  [NEW_TAB]
To type some text:        [TYPE: the text here]
To search the web:        [SEARCH: search query]
To take a screenshot:     [SCREENSHOT]
To increase volume:       [VOLUME: up]
To decrease volume:       [VOLUME: down]
To mute:                  [VOLUME: mute]
To shutdown PC:           [SHUTDOWN]
To restart PC:            [RESTART]
To click coordinates:     [CLICK: x,y]
To double click:          [DOUBLE_CLICK: x,y]
To right click:           [RIGHT_CLICK: x,y]
To scroll down or up:     [SCROLL: down] or [SCROLL: up]
To wait/sleep:            [WAIT: seconds]
To link facts semantically: [RELATE: source | relation | target]
To add/update task tree node: [ADD_TASK: goal | task | status | dependency | blocker]
To update task status/blocker: [UPDATE_TASK: goal | task | status | blocker]
To open browser directly:   [BROWSER_OPEN: url]
To search Google directly:  [GOOGLE_SEARCH: query]
To open VS Code project:    [VSCODE_OPEN: path]

== RULES ==
- ALWAYS include the correct tag when the user asks you to open/close/search/type/click something.
- Keep responses SHORT (1-3 sentences) since they are read out loud.
- NEVER use markdown symbols like * # ` ** in your responses.
- Speak naturally and casually like a smart assistant.
- Address the user by name if you know it."""
        return prompt_str

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _load_custom_commands(self):
        try:
            if os.path.exists(self.custom_commands_path):
                with open(self.custom_commands_path, "r") as f:
                    return json.load(f).get("commands", [])
        except Exception:
            pass
        return []

    def _build_message(self, user_input, user_name=None):
        parts = []
        if user_name:
            parts.append(f"[User's name: {user_name}]")
            try:
                from skills.memory_manager import MemoryManager
                mm = MemoryManager()
                injected_context = mm.get_injected_context(user_name, user_input)
                if injected_context:
                    parts.append(injected_context)
            except Exception as e:
                print(f"[Brain] Could not retrieve injected memory context: {e}")

        cmds = self._load_custom_commands()
        if cmds:
            cmd_str = ", ".join([f"'{c['phrase']}'->{c['category']}" for c in cmds])
            parts.append(f"[Custom commands the user taught you: {cmd_str}]")
        parts.append(f"[Current time: {datetime.datetime.now().strftime('%I:%M %p')}]")
        return "\n".join(parts) + "\n\nUser says: " + user_input

    def _build_ollama_message(self, user_input, user_name=None):
        parts = []
        if user_name:
            parts.append(f"[User: {user_name}]")
            try:
                from skills.memory_manager import MemoryManager
                mm = MemoryManager()
                # Get memory context, but limit the length to max 600 characters to keep it lightweight
                injected_context = mm.get_injected_context(user_name, user_input)
                if injected_context:
                    parts.append(injected_context[:600])
            except Exception as e:
                print(f"[Brain] Could not retrieve injected memory context: {e}")

        # Keep custom commands list minimal
        cmds = self._load_custom_commands()
        if cmds:
            # Only include max 2 custom commands to save token budget
            cmd_str = ", ".join([f"'{c['phrase']}'->{c['category']}" for c in cmds[:2]])
            parts.append(f"[Commands: {cmd_str}]")
            
        parts.append(f"[Time: {datetime.datetime.now().strftime('%I:%M %p')}]")
        return "\n".join(parts) + "\n\nUser says: " + user_input

    def _clean(self, text):
        for ch in ["**", "*", "##", "# ", "`", "_"]:
            text = text.replace(ch, "")
        return text.strip()

    # ── Vision API — Screen Reading ──────────────────────────────────────────
    def _ask_vision(self, img_b64, question):
        """Ask moondream a plain English question about the screenshot."""
        try:
            import base64
            if isinstance(img_b64, str):
                if "," in img_b64:
                    img_b64 = img_b64.split(",", 1)[1]
                img_data = base64.b64decode(img_b64)
            else:
                img_data = img_b64
            response = _ollama.chat(
                model=VISION_MODEL,
                messages=[{"role": "user", "content": question, "images": [img_data]}]
            )
            result = response["message"]["content"].strip()
            print(f"[Brain/{VISION_MODEL}] '{result[:150]}'")
            return result
        except Exception as e:
            print(f"[Brain] Vision error: {e}")
            return ""

    def think_with_screen(self, img_b64, query, screen_w=1920, screen_h=1080):
        """
        Two-step vision approach:
        1. Ask moondream if the target is visible (yes/no)
        2. Ask WHERE it is (plain English: top-left, center, taskbar etc)
        3. Convert that description to pixel coords ourselves
        Much more reliable than asking for raw pixel coords.
        """
        if not self.vision_ready:
            return None

        # Step 1: Is it even visible?
        visible_answer = self._ask_vision(
            img_b64,
            f"Is '{query}' visible anywhere in this screenshot? Answer only yes or no."
        )
        if not visible_answer:
            return "I looked at your screen but got no response from the vision model."

        if "no" in visible_answer.lower() and "yes" not in visible_answer.lower():
            # Not visible — describe what IS on screen
            desc = self._ask_vision(
                img_b64,
                "Briefly describe what you can see on this screen in one sentence."
            )
            return desc or f"I couldn't find '{query}' on your screen."

        # Step 2: Where is it?
        location_answer = self._ask_vision(
            img_b64,
            f"Where exactly is '{query}' on the screen? "
            f"Describe its position using words like: top-left, top-right, bottom-left, "
            f"bottom-right, center, taskbar, top-center, left side, right side."
        )
        return f"FOUND: {location_answer}" if location_answer else f"FOUND: somewhere on screen"

    def parse_location_to_coords(self, location_text, screen_w, screen_h):
        """
        Convert moondream's plain English location description to pixel coordinates.
        e.g. 'top-left corner' -> (50, 50)
        """
        t = location_text.lower()
        m = 60  # margin from edge

        if "taskbar" in t or "bottom" in t and "center" in t:
            return screen_w // 2, screen_h - 30
        if "top-left" in t or "top left" in t:
            return m, m
        if "top-right" in t or "top right" in t:
            return screen_w - m, m
        if "bottom-left" in t or "bottom left" in t:
            return m, screen_h - m
        if "bottom-right" in t or "bottom right" in t:
            return screen_w - m, screen_h - m
        if "top" in t and "center" in t:
            return screen_w // 2, m
        if "top" in t:
            return screen_w // 2, m
        if "bottom" in t:
            return screen_w // 2, screen_h - m
        if "left" in t:
            return m, screen_h // 2
        if "right" in t:
            return screen_w - m, screen_h // 2
        if "center" in t or "middle" in t:
            return screen_w // 2, screen_h // 2
        # Default: center of screen
        return screen_w // 2, screen_h // 2

    # ── Public API ────────────────────────────────────────────────────────────
    def learn(self, phrase, category):
        """Save a new custom voice command."""
        try:
            commands = self._load_custom_commands()
            for cmd in commands:
                if cmd["phrase"].lower() == phrase.lower():
                    cmd["category"] = category
                    break
            else:
                commands.append({"phrase": phrase, "category": category})
            with open(self.custom_commands_path, "w") as f:
                json.dump({"commands": commands}, f, indent=2)
            print(f"[Brain] Learned: '{phrase}' -> {category}")
            return True
        except Exception as e:
            print(f"[Brain] Learn error: {e}")
            return False

    def reset_conversation(self):
        self.chat_history = []
        print("[Brain] Conversation memory cleared.")

    def _think_gemini(self, model_name, user_input, image=None, user_name=None, user_similarity=0.0, user_confidence="none", emotional_tone="neutral"):
        if not self.gemini_ready or not self.internet_ready:
            raise Exception("Gemini not ready or offline")
            
        import google.generativeai as genai
        full_message = self._build_message(user_input, user_name)

        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=self._build_system_prompt(user_name, user_similarity, user_confidence, emotional_tone, query=user_input)
        )

        if image:
            visual_prompt = (
                full_message
                + "\n\nAn image is attached. Answer by inspecting the attached image. "
                + "If the user asks what someone is holding or what is in front of the camera, "
                + "identify the visible object directly. Do not say you lack visual access unless "
                + "the attached image is actually unreadable."
            )
            response = model.generate_content([visual_prompt, image])
            result = response.text
            result = self._clean(result)

            self.chat_history.append({"role": "assistant", "content": result})
            print(f"[Brain/Gemini Vision - {model_name}] {result[:120]}")
            return result

        contents = []
        # Build content history from previous turns (excluding the current user turn at the end)
        for msg in self.chat_history[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [msg["content"]]
            })
        # Add current turn with full injected context
        contents.append({
            "role": "user",
            "parts": [full_message]
        })
        
        response = model.generate_content(contents)
        result = response.text
        result = self._clean(result)
        
        self.chat_history.append({"role": "assistant", "content": result})
        print(f"[Brain/Gemini - {model_name}] {result[:120]}")
        return result

    def _is_simple_vision_task(self, query):
        if not query:
            return False
        q = query.lower()
        simple_keywords = [
            "search", "result", "read the screen", "read screen", "screen",
            "what's on my screen", "what is on my screen", "locate", "find",
            "look at the web", "read search", "what did you get", "what got"
        ]
        return any(k in q for k in simple_keywords)

    def _think_ollama_vision(self, user_input, image, user_name=None):
        if not self.ollama_ready or not self.vision_ready:
            raise Exception("Ollama vision not ready")
        import io, os, base64
        encoded_images = []
        if hasattr(image, "save"):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            img_bytes = buf.getvalue()
            encoded_images.append(img_bytes)
        elif isinstance(image, str) and os.path.exists(image):
            with open(image, "rb") as f:
                img_bytes = f.read()
                encoded_images.append(img_bytes)
                
        full_message = self._build_message(user_input, user_name)
        
        # Give Moondream a focused OCR-style prompt for reading screen content
        vision_prompt = (
            f"Read the text visible on this screen carefully. "
            f"The user asked: '{user_input}'. "
            f"List the main titles, headings, or results you can see. Be specific and detailed."
        )
        
        messages = [
            {"role": "user", "content": vision_prompt, "images": encoded_images}
        ]
        
        response = _ollama.chat(
            model=VISION_MODEL,
            messages=messages,
            options={"num_predict": 150, "temperature": 0.2}
        )
        result = response["message"]["content"]
        result = self._clean(result)
        
        # If Moondream gave a weak/useless answer, fall through to cloud models
        weak_phrases = ["i couldn't", "cannot", "not able", "unclear", "i can't", "no clear"]
        if any(w in result.lower() for w in weak_phrases):
            print(f"[Brain/Moondream] Weak answer detected: '{result[:80]}'. Falling through to cloud.")
            raise Exception("Moondream vision gave weak answer, trying cloud models")
        
        self.chat_history.append({"role": "assistant", "content": result})
        print(f"[Brain/Moondream] {result[:120]}")
        return result

    def _score_response(self, response, user_input):
        """Score response quality 0.0-1.0 based on coherence, length, relevance."""
        if not response or not response.strip():
            return 0.0
        score = 0.5  # baseline
        r = response.strip()
        # Length: too short = bad, too long = slightly bad
        if len(r) < 5:
            score -= 0.4
        elif len(r) < 20:
            score -= 0.1
        elif len(r) > 500:
            score -= 0.05
        else:
            score += 0.2
        # Garbage detection
        garbage = ["as an ai", "i cannot", "i'm sorry, i", "error:", "traceback", "exception"]
        if any(g in r.lower() for g in garbage):
            score -= 0.3
        # Contains action tags = likely useful
        if "[" in r and "]" in r:
            score += 0.15
        # Relevance: shares words with query
        query_words = set(user_input.lower().split())
        resp_words = set(r.lower().split())
        overlap = len(query_words & resp_words)
        if overlap > 0:
            score += min(0.15, overlap * 0.03)
        return max(0.0, min(1.0, score))

    def _get_cached(self, user_input):
        """Return cached response if still valid, else None."""
        import time, hashlib
        key = hashlib.md5(user_input.strip().lower().encode()).hexdigest()
        entry = self._response_cache.get(key)
        if entry and (time.time() - entry["timestamp"]) < self._cache_ttl:
            print(f"[Brain/Cache] HIT for '{user_input[:40]}' (age: {time.time() - entry['timestamp']:.0f}s)")
            return entry["response"]
        return None

    def _set_cache(self, user_input, response):
        """Store response in cache, skipping context-sensitive responses."""
        import time, hashlib
        # Do NOT cache responses that include proactive suggestions, goals, or
        # shopping/Amazon content — these are stale almost immediately.
        skip_keywords = [
            "amazon", "goal", "remind", "should i resume", "unfinished task",
            "you seem", "take a break", "you've been working", "stretch",
            "proactive", "suggestion", "reminder"
        ]
        response_lower = response.lower()
        if any(kw in response_lower for kw in skip_keywords):
            print(f"[Brain/Cache] SKIP cache for context-sensitive response: '{response[:60]}...'")
            return
        key = hashlib.md5(user_input.strip().lower().encode()).hexdigest()
        self._response_cache[key] = {"response": response, "timestamp": time.time()}
        # Evict old entries (keep max 50)
        if len(self._response_cache) > 50:
            oldest_key = min(self._response_cache, key=lambda k: self._response_cache[k]["timestamp"])
            del self._response_cache[oldest_key]

    def _classify_task(self, user_input, has_image=False):
        """Classify user input into a task type for smart routing."""
        if not user_input:
            return "chat"
        q = user_input.lower().strip()
        
        if has_image:
            return "vision"
        
        # Planning / workflow keywords
        planning_kw = ["plan", "workflow", "step by step", "automate", "build", "create project", "schedule"]
        if any(k in q for k in planning_kw):
            return "planning"
        
        # Search / live info keywords  
        search_kw = ["search", "google", "find", "latest", "news", "score", "weather", "cricket", "match", "stock", "price"]
        if any(k in q for k in search_kw):
            return "search"
        
        # Coding keywords
        code_kw = ["code", "debug", "error", "function", "python", "javascript", "fix bug", "compile", "syntax"]
        if any(k in q for k in code_kw):
            return "coding"
        
        # Short casual chat (< 8 words, no action words)
        word_count = len(q.split())
        action_kw = ["open", "close", "click", "type", "run", "start", "stop", "install"]
        if word_count <= 8 and not any(k in q for k in action_kw):
            return "fast_chat"
        
        return "chat"

    def _get_provider_order(self, task_type):
        """Return ordered list of provider tiers based on task type."""
        orders = {
            "fast_chat":  ["groq", "ollama", "gemini-2.0", "gemini-2.5"],
            "chat":       ["gemini-2.5", "groq", "gemini-2.0", "ollama"],
            "search":     ["gemini-2.5", "gemini-2.0", "groq", "ollama"],
            "planning":   ["gemini-2.5", "ollama", "groq", "gemini-2.0"],
            "coding":     ["gemini-2.5", "gemini-2.0", "groq", "ollama"],
            "vision":     ["gemini-2.5", "gemini-2.0", "ollama"],
        }
        return orders.get(task_type, orders["chat"])

    def think(self, user_input, image=None, user_name=None, user_similarity=0.0, user_confidence="none", repair_depth=0, emotional_tone="neutral"):
        self._current_routing_decision = None
        self._last_streamed_response = None
        self.last_routing_decision = None
        res = self._think_impl(user_input, image, user_name, user_similarity, user_confidence, repair_depth, emotional_tone)
        
        # After response is computed, if we have a routing decision, update the context engine!
        if getattr(self, "_current_routing_decision", None) is not None:
            routing_decision = self._current_routing_decision
            self.last_routing_decision = routing_decision
            if self.semantic_router:
                try:
                    # Capture browser page state if active
                    browser_state = None
                    try:
                        from skills.browser_skill import BrowserSkill
                        bs = BrowserSkill()
                        if bs.is_browser_active():
                            bs._update_page_state()
                            browser_state = bs.page_state
                    except Exception as b_err:
                        print(f"[Brain/Context] Could not capture browser state: {b_err}")
                    
                    response_to_log = res
                    if not response_to_log and getattr(self, "_last_streamed_response", None):
                        response_to_log = self._last_streamed_response
                        self._last_streamed_response = None
                    
                    self.semantic_router.update_context(
                        routing_decision,
                        system_response=response_to_log or "",
                        browser_state=browser_state
                    )
                    print(f"[Brain/Context] Context updated for response: '{response_to_log[:60] if response_to_log else ''}...'")
                except Exception as e:
                    print(f"[Brain/Context] Context update failed: {e}")
            self._current_routing_decision = None
            
        if res and user_name:
            try:
                from skills.memory_manager import MemoryManager
                mm = MemoryManager()
                mm.log_interaction(user_name, user_input, res)

                # Start background Knowledge Graph relation extraction thread
                import threading
                def run_async_graph_extraction(user, u_in, a_rep):
                    try:
                        from skills.knowledge_graph import process_conversation_turn
                        process_conversation_turn(user, u_in, a_rep)
                    except Exception as ge_err:
                        print(f"[Brain/Graph] Background relation extraction error: {ge_err}")

                threading.Thread(
                    target=run_async_graph_extraction,
                    args=(user_name, user_input, res),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[Brain/Memory] Interaction logging failed: {e}")
        return res

    def _get_clean_words(self, text: str) -> list:
        # lower case, remove punctuation, split into words
        import re
        text_clean = re.sub(r'[^\w\s\.]', ' ', text.lower())
        words = text_clean.split()
        stop_words = {
            "click", "open", "select", "choose", "on", "the", "screen", "you", "can", "see", 
            "a", "an", "this", "that", "it", "there", "them", "first", "second", "third", "last", 
            "item", "result", "one", "please", "could", "would", "go", "to", "back", "next",
            "find", "locate", "show", "me", "play", "video", "product", "link", "button", "input"
        }
        return [w for w in words if w not in stop_words and len(w) > 1]

    def _compute_match_score(self, query: str, card_text: str) -> float:
        q_words = self._get_clean_words(query)
        if not q_words:
            return 0.0
        c_words = self._get_clean_words(card_text[:300]) # only look at the first 300 chars (title)
        if not c_words:
            return 0.0
            
        # Count how many query words are in the card text
        matches = sum(1 for w in q_words if w in c_words)
        token_score = matches / len(q_words)
        
        # Check for sequential phrase matches
        seq_score = 0.0
        q_clean = " ".join(q_words)
        c_clean = " ".join(c_words)
        if q_clean in c_clean:
            # Full phrase match query in card text
            seq_score = 1.0
        elif c_clean in q_clean:
            # Card text is subset of query
            seq_score = len(c_words) / len(q_words)
        else:
            # Check sub-phrases of length 2 or more
            for length in range(len(q_words) - 1, 1, -1):
                for i in range(len(q_words) - length + 1):
                    subphrase = " ".join(q_words[i:i+length])
                    if subphrase in c_clean:
                        # Give a sequence match score
                        seq_score = (length / len(q_words)) * 0.95
                        break
                if seq_score > 0.0:
                    break
                    
        # Add fuzzy phrase match fallback
        import difflib
        ratio = difflib.SequenceMatcher(None, q_clean, c_clean).ratio()
        if ratio >= 0.7:
            seq_score = max(seq_score, ratio)
        else:
            # Try to match the query words as a fuzzy substring in card text
            c_len = len(c_clean)
            q_len = len(q_clean)
            if c_len > q_len:
                for i in range(c_len - q_len + 1):
                    sub = c_clean[i:i+q_len]
                    sub_ratio = difflib.SequenceMatcher(None, q_clean, sub).ratio()
                    if sub_ratio >= 0.7:
                        seq_score = max(seq_score, sub_ratio)
                        break
                    
        # Return the maximum of token score and sequence score
        # Add a 0.2 bonus for sequence matches, up to a max of 1.0
        score = max(token_score, seq_score)
        if seq_score > 0.0:
            score = min(1.0, score + 0.2)
            
        return score

    def _find_best_card_match(self, current_query: str, cards: list) -> tuple:
        # Prioritize cards visible in viewport
        visible_cards = [c for c in cards if c.get('is_visible_in_viewport')]
        non_visible_cards = [c for c in cards if not c.get('is_visible_in_viewport')]
        
        # Try matching current query first against visible cards, then all cards
        for card_list in [visible_cards, non_visible_cards]:
            best_card = None
            best_score = 0.0
            for card in card_list:
                score = self._compute_match_score(current_query, card.get('text', ''))
                if score > best_score:
                    best_score = score
                    best_card = card
            if best_score >= 0.5:
                return best_card, best_score
                
        # If no match in current query, check previous user queries in history
        # (walk back starting from the most recent user turn)
        for turn in reversed(self.chat_history):
            if turn.get("role") == "user":
                content = turn.get("content", "")
                for card_list in [visible_cards, non_visible_cards]:
                    best_card = None
                    best_score = 0.0
                    for card in card_list:
                        score = self._compute_match_score(content, card.get('text', ''))
                        if score > best_score:
                            best_score = score
                            best_card = card
                    if best_score >= 0.5:
                        return best_card, best_score
                        
        return None, 0.0

    def _think_impl(self, user_input, image=None, user_name=None, user_similarity=0.0, user_confidence="none", repair_depth=0, emotional_tone="neutral"):
        """
        Internal think implementation — tries cloud Gemini 2.5 -> Gemini 2.0 -> Groq -> Ollama -> Offline Parser.
        Includes response caching, quality scoring, and OCR perception layer.
        
        NEW: Uses semantic router for intent classification and context tracking.
        """
        import re

        # ── BROWSER ACTION INTERCEPT ROUTING ──────────────────────────────────
        browser_active = False
        try:
            from skills.browser_skill import BrowserSkill
            browser_active = BrowserSkill().is_browser_active()
        except Exception:
            pass

        is_internal = False
        if isinstance(user_input, str):
            inp_strip = user_input.lstrip()
            if (inp_strip.startswith("The user asked:") or 
                inp_strip.startswith("You are the Agent Coordinator") or
                inp_strip.startswith("You are the central Cognitive Planner") or
                inp_strip.startswith("You are ARIA's Career") or
                "You are the executive planning core of ARIA" in inp_strip or
                "Decompose the user's multi-action goal" in inp_strip or
                (len(inp_strip) > 300 and ("you must output" in inp_strip.lower() or "json" in inp_strip.lower() or "you are the" in inp_strip.lower()))):
                is_internal = True

        if browser_active and not is_internal:
            q_lower = user_input.lower().strip()
            question_words = ["what", "how", "why", "who", "where", "which", "explain", "tell me", "show me", "describe", "summarize", "read"]
            is_question = any(q_lower.startswith(qw) for qw in question_words)
            if not is_question:
                action_verbs = ["click", "open", "select", "choose", "tap", "press", "go to"]
                reference_cues = ["the", "that", "this", "one"]
                has_verb = any(re.search(rf"\b{v}\b", q_lower) for v in action_verbs)
                has_ref = any(re.search(rf"\b{r}\b", q_lower) for r in reference_cues)
                if has_verb or has_ref:
                    try:
                        from skills.browser_skill import BrowserSkill
                        bs = BrowserSkill()
                        bs._update_page_state()
                        cards = bs.page_state.get("cards", [])
                        if cards:
                            matched_card, score = self._find_best_card_match(user_input, cards)
                            if matched_card:
                                print(f"[Brain/BrowserIntercept] Resolved to card: {matched_card.get('aria_id')} (score: {score:.2f})")
                                title = matched_card.get("text", "")
                                title = title.split("\n")[0].strip()[:60]
                                res = f"Clicking {title}. [CLICK: {matched_card.get('aria_id')}]"
                                self.chat_history.append({"role": "user", "content": user_input})
                                self.chat_history.append({"role": "assistant", "content": res})
                                self._set_cache(user_input, res)
                                
                                # Log to semantic router context if available
                                if self.semantic_router:
                                    try:
                                        routing_dec = {
                                            "original_query": user_input,
                                            "normalized_query": user_input,
                                            "intent": "followup",
                                            "intent_confidence": 0.90,
                                            "action_type": "resolve_reference_and_click",
                                        }
                                        self.semantic_router.update_context(
                                            routing_dec,
                                            system_response=res,
                                            browser_state=bs.page_state
                                        )
                                    except Exception as ctx_err:
                                        print(f"[Brain/BrowserIntercept] Context update failed: {ctx_err}")
                                self._current_routing_decision = None
                                return res
                            else:
                                if has_verb:
                                    # Clarification fallback
                                    print("[Brain/BrowserIntercept] No matching card found on page. Asking user for clarification.")
                                    res = "I don't see that item on the screen. Which item would you like me to click?"
                                    self.chat_history.append({"role": "user", "content": user_input})
                                    self.chat_history.append({"role": "assistant", "content": res})
                                    self._current_routing_decision = None
                                    return res
                                # If it only has reference cues but no action verb, we fall through to let other systems handle it
                    except Exception as e:
                        print(f"[Brain/BrowserIntercept] Error during card resolution: {e}")

        # ── SEMANTIC ROUTING (NEW) ────────────────────────────────────────────
        routing_decision = getattr(self, "_current_routing_decision", None)
        if not routing_decision and self.semantic_router and not is_internal:
            try:
                # Only skip repair if we are deep in recursion (to prevent infinite loops)
                skip_repair = (repair_depth > 2)
                routing_decision = self.semantic_router.route(user_input, has_image=bool(image), user_name=user_name, skip_repair=skip_repair)
                self._current_routing_decision = routing_decision
                print(f"[Brain/SemanticRouter] Intent: {routing_decision.get('intent')} | "
                      f"Action: {routing_decision.get('action_type')}")
            except Exception as e:
                print(f"[Brain/SemanticRouter] Routing error: {e}")
                routing_decision = None

        if routing_decision:
            try:
                # ── TIER -1: Identity / Face Recognition Intercept ──
                if routing_decision.get("needs_face_recognition"):
                    print("[Brain/IdentityIntercept] IDENTITY QUERY DETECTED - Prioritizing memory + face recognition")
                    # If user_name is not set but we have an image, try to run face recognition first
                    if (not user_name or user_name == "Unknown"):
                        try:
                            import sys, numpy as np
                            from skills.memory_manager import MemoryManager
                            mm = MemoryManager()
                            print("[Brain/IdentityIntercept] user_name not set — attempting live face recognition...")

                            img_to_use = image  # PIL Image passed in from caller (may be None)
                            main_mod = sys.modules.get('__main__')
                            aria = (
                                getattr(main_mod, 'instance', None) or
                                getattr(main_mod, 'aria_instance', None)
                            ) if main_mod else None

                            # ── Strategy 1: Delegate to ARIA's own _detect_user() ──
                            # This is the correct, lock-safe, multi-frame method.
                            if aria and hasattr(aria, '_detect_user'):
                                try:
                                    detected_name = aria._detect_user()
                                    if detected_name and detected_name != "Unknown":
                                        user_name = detected_name
                                        user_similarity = getattr(aria, 'known_user_similarity', 0.8)
                                        user_confidence = getattr(aria, 'known_user_confidence', 'medium')
                                        print(f"[Brain/IdentityIntercept] _detect_user() identified: '{user_name}' (conf: {user_confidence})")
                                    else:
                                        print("[Brain/IdentityIntercept] _detect_user() returned no match.")
                                except Exception as du_err:
                                    print(f"[Brain/IdentityIntercept] _detect_user() failed: {du_err}")

                            # ── Strategy 2: Fallback — get a raw BGR frame directly ──
                            # Use capture_frame_raw() (BGR numpy array) — correct format for FaceEmbedder.
                            # Do NOT use capture_image() which returns RGB PIL, wrong colour order.
                            if (not user_name or user_name == "Unknown") and img_to_use is None:
                                if aria and hasattr(aria, 'camera') and aria.camera.available:
                                    raw_frame = aria.camera.capture_frame_raw()
                                    if raw_frame is not None:
                                        img_to_use = raw_frame  # BGR numpy array
                                        print(f"[Brain/IdentityIntercept] Got raw BGR frame: {raw_frame.shape}")
                                    else:
                                        print("[Brain/IdentityIntercept] capture_frame_raw() returned None — camera may be busy.")

                            # ── Strategy 3: Run identify_user on whatever image we have ──
                            if (not user_name or user_name == "Unknown") and img_to_use is not None:
                                img_arr = np.array(img_to_use) if not isinstance(img_to_use, np.ndarray) else img_to_use
                                print(f"[Brain/IdentityIntercept] Running identify_user on array shape={img_arr.shape}")
                                detected, sim = mm.identify_user(image_array=img_arr, threshold=0.63, return_confidence=True)
                                print(f"[Brain/IdentityIntercept] identify_user result: '{detected}' sim={sim:.3f}")
                                if detected != "Unknown":
                                    user_name = detected
                                    user_similarity = sim
                                    user_confidence = "high" if sim >= 0.85 else "medium" if sim >= 0.75 else "low"
                                    # Update the ARIA instance so subsequent requests are faster
                                    if aria:
                                        aria.known_user = user_name
                                        aria.known_user_similarity = user_similarity
                                        aria.known_user_confidence = user_confidence
                                    print(f"[Brain/IdentityIntercept] Identified user: '{detected}' (sim={sim:.3f})")
                            elif not user_name or user_name == "Unknown":
                                print("[Brain/IdentityIntercept] No image available for face recognition — returning Guest Mode.")

                        except Exception as id_err:
                            print(f"[Brain/IdentityIntercept] Dynamic face identification failed: {id_err}")

                    
                    if user_name and user_name != "Unknown":
                        username_clean = user_name.strip().strip('.').lower()
                        if username_clean == "chinmay":
                            name_clean = "Chinmaya"
                        else:
                            name_clean = username_clean.capitalize()
                        res = f"Yes, I recognize you as {name_clean}."
                    else:
                        res = "Unfortunately, I don't recognize you. You're currently in Guest Mode."

                    # Guarantee response is spoken immediately before exiting the handler
                    if aria:
                        try:
                            aria._speak(res)
                            aria._identity_already_spoken = True
                        except Exception as sp_err:
                            print(f"[Brain/IdentityIntercept] Direct speak failed: {sp_err}")

                    self.chat_history.append({"role": "user", "content": user_input})
                    self.chat_history.append({"role": "assistant", "content": res})
                    self._set_cache(user_input, res)
                    
                    if self.semantic_router:
                        try:
                            self.semantic_router.update_context(
                                routing_decision,
                                system_response=res
                            )
                        except Exception as ctx_err:
                            print(f"[Brain/Identity] Context update failed: {ctx_err}")
                    self._current_routing_decision = None
                    return res

                # ── TIER 0: Conversational Repair ──
                if routing_decision.get("intent") == "repair":
                    print("[Brain/Repair] Repair intent detected. Stopping active tasks.")
                    from skills.agent_planner import AgentPlanner
                    AgentPlanner().cancel_task = True
                    if self.semantic_router.task_manager.get_active_task():
                        self.semantic_router.task_manager.get_active_task().cancel_task()
                    
                    # Decompose multi-intent repair utterances using a robust regex pattern
                    remaining_text = re.sub(
                        r'^('
                        r'no[\s,\.]*no[\s,\.]*i[\s,\.]*meant|'
                        r'no[\s,\.]*i[\s,\.]*meant|'
                        r'actually[\s,\.]*i[\s,\.]*meant|'
                        r'no[\s,\.]*no|'
                        r'no[\s,\.]*wait|'
                        r'hold[\s,\.]*on|'
                        r'wait[\s,\.]*a[\s,\.]*second|'
                        r'wait[\s,\.]*a[\s,\.]*minute|'
                        r'i[\s,\.]*mean|'
                        r'actually|'
                        r'stop[\s,\.]*stop|'
                        r'wait[\s,\.]*wait|'
                        r'cancel[\s,\.]*that|'
                        r'stop[\s,\.]*this|'
                        r'nevermind[\s,\.]*that|'
                        r'stop|'
                        r'wait|'
                        r'meant|'
                        r'no'
                        r')\b[\s,\.]*',
                        '', user_input, flags=re.IGNORECASE
                    ).strip()
                    # Strip transitions like "and then", "and", "instead"
                    for transition in ["and then", "and", "instead"]:
                        if remaining_text.lower().startswith(transition):
                            remaining_text = remaining_text[len(transition):].strip()
                    # Strip any leading punctuation that might remain
                    remaining_text = re.sub(r'^[\s,\.]*', '', remaining_text)
                    
                    if remaining_text and len(remaining_text.split()) > 0:
                        if remaining_text == user_input:
                            print("[Brain/Repair] Remaining text is unchanged. Bypassing recursive repair routing.")
                            # Force route the remaining text without repair intent to avoid loop
                            self._current_routing_decision = self.semantic_router.route(remaining_text, has_image=bool(image), user_name=user_name, skip_repair=True)
                            return self._think_impl(remaining_text, image, user_name, user_similarity, user_confidence, repair_depth=repair_depth+1)
                        else:
                            print(f"[Brain/Repair] Multi-intent repair remaining: '{remaining_text}'")
                            # Recursively process the revised query with increased repair_depth
                            return self.think(remaining_text, image, user_name, user_similarity, user_confidence, repair_depth=repair_depth+1)
                    
                    # Return basic stop confirmation
                    result = "I've stopped the active task. What would you like to do instead?"
                    return result

                # ── TIER 0.5: Dynamic Confidence Thresholds & Clarification ──
                THRESHOLDS = {
                    "repair": 0.50,
                    "identity": 0.70,
                    "memory": 0.65,
                    "followup": 0.65,
                    "browser": 0.75,
                    "search": 0.70,
                    "chat": 0.20
                }
                intent = routing_decision.get("intent", "chat")
                confidence = routing_decision.get("intent_confidence", 1.0)
                threshold = THRESHOLDS.get(intent, 0.60)
                
                if confidence < threshold and intent != "chat":
                    print(f"[Brain] Low confidence ({confidence:.2f} < {threshold}) for intent '{intent}'. Prompting clarification.")
                    return f"I think you might want to {intent} something, but I'm not completely sure. Could you please clarify what you'd like me to do?"

                if routing_decision.get("requires_clarification"):
                    reason = routing_decision.get("tool_arm_reason", "tool_not_armed")
                    print(f"[Brain/ToolArming] Tool intent not armed ({reason}). Prompting clarification.")
                    return "I can help with that, but I need you to say clearly whether you want me to search, open, or control something."

                # ── CRITICAL: Identity queries should NEVER be treated as web searches
                if routing_decision.get("needs_face_recognition"):
                    print("[Brain] IDENTITY QUERY DETECTED - Prioritizing memory + face recognition (NOT web search)")
                    if user_name:
                        full_message = (
                            f"[IDENTITY_QUERY] User: {user_name}\n\n"
                            f"Original query: {user_input}\n"
                            f"Based on your face recognition capabilities and memory, answer the identity question.\n"
                            f"Be direct and friendly."
                        )
                
                # ── followup: Resolve references and ambiguous step commands
                if intent == "followup":
                    resolved = routing_decision.get("resolved_reference")
                    resolved_obj = routing_decision.get("resolved_object")
                    resolved_step = routing_decision.get("resolved_step")
                    
                    print(f"[Brain] FOLLOW-UP DETECTED - Resolving references")
                    
                    if resolved_obj:
                        print(f"[Brain] Resolved object: {resolved_obj.name} (ID: {resolved_obj.id})")
                        # Revise user input to perform action on resolved object ID
                        action = "open" if "open" in user_input.lower() else "click" if "click" in user_input.lower() else "select"
                        revised_input = f"{action} {resolved_obj.id}"
                        print(f"[Brain] Revised follow-up query: '{user_input}' -> '{revised_input}'")
                        user_input = revised_input
                        full_message = self._build_message(user_input, user_name)
                    elif resolved_step:
                        print(f"[Brain] Resolved step: {resolved_step.action}")
                        if "back" in user_input.lower() or "previous" in user_input.lower():
                            revised_input = "go back"
                            user_input = revised_input
                            full_message = self._build_message(user_input, user_name)
                    elif resolved and resolved.system_response:
                        print(f"[Brain] FOLLOW-UP DETECTED - Resolving reference from previous: {resolved.intent}")
                        if resolved.system_response:
                            full_message = (
                                f"Previous context: {resolved.system_response[:300]}\n\n"
                                f"User follow-up: {user_input}\n"
                                f"Answer based on the previous context."
                            )
                    
            except Exception as e:
                print(f"[Brain/SemanticRouter] Routing processing error: {e}")
        
        # ── Response Cache Check ──
        if not image:
            cached = self._get_cached(user_input)
            if cached:
                self.chat_history.append({"role": "user", "content": user_input})
                self.chat_history.append({"role": "assistant", "content": cached})
                return cached

        # Append clean user input to history for the current turn
        self.chat_history.append({"role": "user", "content": user_input})

        full_message = self._build_message(user_input, user_name)

        # ── Vision Routing Layer: Route simple layout/screen tasks to local Moondream first ──
        if image and self.vision_ready:
            if self._is_simple_vision_task(user_input):
                try:
                    print("[Brain] Simple visual task detected. Prioritizing local Moondream.")
                    return self._think_ollama_vision(user_input, image, user_name)
                except Exception as e:
                    print(f"[Brain] Local vision failed: {e}. Trying OCR/WebText layer.")

        # ── OCR + WebText Perception Layer ────────────────────────────────────
        # Instead of relying on vision to read pixels, extract actual text first
        if image and self._is_simple_vision_task(user_input):
            extracted_text = ""
            
            # 1. Try Chrome DOM text extraction if browser is active
            try:
                from skills.web_text_extractor import WebTextExtractor
                wte = WebTextExtractor()
                if wte.is_browser_active():
                    extracted_text = wte.extract_chrome_text(max_chars=2000)
                    if extracted_text:
                        print(f"[Brain/WebText] Got {len(extracted_text)} chars from Chrome DOM.")
            except Exception as wt_err:
                print(f"[Brain/WebText] Chrome extraction failed: {wt_err}")
            
            # 2. Fallback: OCR on the screenshot image
            if not extracted_text:
                try:
                    from skills.ocr_reader import OCRReader
                    extracted_text = OCRReader().extract_text(image)
                    if extracted_text:
                        print(f"[Brain/OCR] Got {len(extracted_text)} chars from screen OCR.")
                except Exception as ocr_err:
                    print(f"[Brain/OCR] OCR extraction failed: {ocr_err}")
            
            # 3. If we got text, feed it to the fastest LLM for reasoning
            if extracted_text and len(extracted_text) > 30:
                ocr_prompt = (
                    f"The user asked: '{user_input}'.\n\n"
                    f"Here is the text extracted from the screen:\n"
                    f"---\n{extracted_text[:2000]}\n---\n\n"
                    f"Based on this screen text, answer the user's question in 1-3 short sentences. "
                    f"Be specific with names, scores, facts visible in the text. No markdown."
                )
                
                # Try Ollama for speed (lightweight prompt = fast)
                if self.ollama_ready:
                    try:
                        response = _ollama.chat(
                            model=OLLAMA_MODEL,
                            messages=[
                                {"role": "system", "content": "You are ARIA, a smart assistant. Answer based on the screen text provided. Be concise."},
                                {"role": "user", "content": ocr_prompt}
                            ],
                            options={"num_predict": 100, "temperature": 0.3}
                        )
                        result = response["message"]["content"]
                        result = self._clean(result)
                        self.chat_history.append({"role": "assistant", "content": result})
                        print(f"[Brain/OCR+LLM] {result[:120]}")
                        return result
                    except Exception as ollama_ocr_err:
                        print(f"[Brain/OCR+LLM] Ollama OCR reasoning failed: {ollama_ocr_err}")

        import time as _time

        if self.model_registry:
            task_type = self._classify_task(user_input, has_image=bool(image))
            
            attempts = 0
            max_attempts = 5
            res = None
            while attempts < max_attempts:
                model_info = self.model_registry.get_best_model(task_type, has_image=bool(image), internet_available=self.internet_ready)
                if not model_info:
                    print("[Brain/Registry] No more healthy models available in registry.")
                    break
                    
                model_name = model_info.name
                provider = model_info.provider
                
                # Check status flags as secondary validation
                if provider == "gemini" and not self.gemini_ready:
                    model_info.status = "UNAVAILABLE"
                    continue
                if provider == "groq" and not self.groq_ready:
                    model_info.status = "UNAVAILABLE"
                    continue
                if provider == "ollama" and not self.ollama_ready and model_name == "ollama_local":
                    model_info.status = "UNAVAILABLE"
                    continue
                if provider == "ollama" and not self.vision_ready and model_name == "moondream":
                    model_info.status = "UNAVAILABLE"
                    continue
                    
                attempts += 1
                start_time = _time.time()
                try:
                    print(f"[Brain/Registry] Routing attempt {attempts}: trying '{model_name}' ({provider})...")
                    if provider == "gemini":
                        res = self._think_gemini(model_name, user_input, image, user_name, user_similarity, user_confidence, emotional_tone)
                    elif provider == "groq":
                        res = self._think_groq_model(model_name, user_input, user_name, user_similarity, user_confidence, emotional_tone)
                    elif provider == "ollama":
                        res = self._think_ollama_model(model_name, user_input, image, user_name, user_similarity, user_confidence, emotional_tone)
                        
                    if res is not None:
                        latency = _time.time() - start_time
                        self.model_registry.record_success(model_name, latency)
                        self.active_model_name = model_name
                        
                        score = self._score_response(res, user_input)
                        if score >= 0.15 and not image and res != "":
                            self._set_cache(user_input, res)
                        return res
                except Exception as e:
                    latency = _time.time() - start_time
                    err_str = str(e)
                    is_quota = "429" in err_str or "quota" in err_str.lower() or "too many requests" in err_str.lower() or "ResourceExhausted" in err_str
                    if is_quota:
                        print(f"[Brain/Registry] Model '{model_name}' hit quota/rate limit. Transitioning to fallback models...")
                    else:
                        print(f"[Brain/Registry] Attempt {attempts} with {model_name} failed in {latency:.2f}s: {err_str[:120]}")
                    self.model_registry.record_failure(model_name, is_quota_error=is_quota)
            
            print("[ModelRegistry] All model registry routes failed. Falling back to offline local parser.")
        else:
            # Fallback legacy behavior if registry is not available
            # ── TIER 1.0: Gemini 2.5 Flash ─────
            if self.internet_ready and self.gemini_ready:
                try:
                    res = self._think_gemini('gemini-2.5-flash', user_input, image, user_name, user_similarity, user_confidence, emotional_tone)
                    self.active_model_name = "Gemini 2.5 Flash"
                    return res
                except Exception:
                    pass
            # ── TIER 1.5: Ollama / Llama ──
            if self.ollama_ready:
                try:
                    res = self._think_ollama_model("ollama_local", user_input, image, user_name, user_similarity, user_confidence, emotional_tone)
                    self.active_model_name = "Ollama Local"
                    return res
                except Exception:
                    pass

        # ── TIER 2: Offline local parser ─────────────────────────────────────
        result = self._offline_think(user_input, user_name, routing_decision)
        return result


    def _offline_think(self, user_input, user_name=None, routing_decision=None):
        """Rule-based command parser — works with zero dependencies."""
        inp = user_input.lower().strip()
        now = datetime.datetime.now()

        # ── NEW: Handle identity queries specially ────────────────────────────
        if routing_decision and routing_decision.get("needs_face_recognition"):
            if user_name:
                return f"I recognize you are {user_name}. How can I help?"
            else:
                return "I can see someone, but I'm not certain who you are. Can you tell me your name?"
        
        # ── NEW: Prevent web search for identity queries ────────────────────────
        if routing_decision and routing_decision.get("skip_web_search"):
            # This is likely an identity or memory query - don't trigger web search
            if any(k in inp for k in ["who", "what is my", "remember", "do you know me"]):
                if user_name:
                    return f"You are {user_name}. I remember our previous conversations."
                else:
                    return "I'm not certain who you are. Can you tell me your name or let me scan your face?"

        # Clean polite prefixes
        prefixes = ["please ", "could you ", "would you ", "can you ", "hey aria ", "aria ", "go ahead and "]
        for prefix in prefixes:
            if inp.startswith(prefix):
                inp = inp[len(prefix):].strip()

        # Custom commands
        for cmd in self._load_custom_commands():
            if cmd["phrase"].lower() in inp:
                cat = cmd["category"]
                phrase = cmd["phrase"]
                if cat == "OPEN":   return f"Running your custom command. [OPEN: {phrase}]"
                if cat == "CLOSE":  return f"Closing via custom command. [CLOSE: {phrase}]"
                if cat == "TYPE":   return f"Typing your custom command. [TYPE: {phrase}]"
                if cat == "SEARCH": return f"Searching. [SEARCH: {phrase}]"

        # Open
        if "open " in inp:
            if "new tab" in inp or "browser tab" in inp:
                return "Opening a new browser tab. [NEW_TAB]"
            parts = inp.split("open ", 1)
            app_part = parts[1].strip()
            # Clean app name: strip "the ", "a ", "an "
            for clean_word in ["the ", "a ", "an "]:
                if app_part.startswith(clean_word):
                    app_part = app_part[len(clean_word):].strip()
            # Split on conjunctions to isolate the app name
            for split_word in [" and ", " then ", " to ", " write ", " type ", " search ", " wrte ", " wrt ", " msg ", " mss "]:
                if split_word in app_part:
                    app_part = app_part.split(split_word, 1)[0].strip()
            return f"Opening {app_part} for you. [OPEN: {app_part}]"

        # Close
        if "close " in inp:
            if "tab" in inp:
                return "Closing the browser tab. [CLOSE_TAB]"
            parts = inp.split("close ", 1)
            app_part = parts[1].strip()
            for clean_word in ["the ", "a ", "an "]:
                if app_part.startswith(clean_word):
                    app_part = app_part[len(clean_word):].strip()
            for split_word in [" and ", " then ", " to "]:
                if split_word in app_part:
                    app_part = app_part.split(split_word, 1)[0].strip()
            return f"Closing {app_part}. [CLOSE: {app_part}]"

        # Time / Date
        if "time" in inp:
            return f"The time is {now.strftime('%I:%M %p')}."
        if "date" in inp or "today" in inp:
            return f"Today is {now.strftime('%A, %B %d, %Y')}."

        # Search
        if "search" in inp:
            query = inp.split("search")[-1].replace("for", "").strip()
            # Clean up query
            for split_word in [" and ", " then "]:
                if split_word in query:
                    query = query.split(split_word, 1)[0].strip()
            return f"Searching for {query}. [SEARCH: {query}]"

        # Type
        if "type " in inp or "write " in inp:
            trigger = "type " if "type " in inp else "write "
            text = inp.split(trigger, 1)[1].strip()
            return f"Typing that now. [TYPE: {text}]"

        # Screenshot
        if "screenshot" in inp:
            return "Taking a screenshot. [SCREENSHOT]"

        # Volume
        if "volume up" in inp:   return "Turning volume up. [VOLUME: up]"
        if "volume down" in inp: return "Turning volume down. [VOLUME: down]"
        if "mute" in inp:        return "Muting audio. [VOLUME: mute]"

        # Greetings
        if any(x in inp for x in ["hello", "hi", "hey"]):
            n = f" {user_name}" if user_name else ""
            return f"Hello{n}! How can I help you? I can open applications, search the web, take screenshots, or execute autonomous tasks."

        return "I'm ready. Tell me what to open, search, or automate."

    def think_vertex(self, prompt, system_instruction=None, enforce_json_schema=None, model_type="flash"):
        """Routes cognitive queries straight to Google Cloud Vertex AI with a multi-level fallback chain."""
        if getattr(self, "vertex_bridge", None):
            return self.vertex_bridge.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                enforce_json_schema=enforce_json_schema,
                model_type=model_type,
                brain_instance=self
            )
        else:
            return self.think_raw(prompt, system_instruction)

    def think_local(self, prompt, system_instruction=None):
        """Forces purely localized execution (local Ollama model or offline rules)."""
        if self.ollama_ready:
            try:
                import ollama as _ollama
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})
                response = _ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    options={"temperature": 0.1}
                )
                return response["message"]["content"].strip()
            except Exception as e:
                print(f"[Brain/Local] Local Ollama error: {e}")
        return self._offline_think(prompt)

    def think_raw(self, prompt, system_instruction=None):
        """Executes a raw prompt directly on the best available backend without history or system prompt wrappers."""
        import time as _time

        # 1. Try Gemini 2.5/2.0 first
        if self.internet_ready and self.gemini_ready:
            try:
                import google.generativeai as genai
                model_name = "gemini-2.0-flash"
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                response = model.generate_content(prompt)
                res_text = response.text.strip()
                print(f"[Brain/Raw-Gemini] Response received.")
                return res_text
            except Exception as e:
                _err_str = str(e)
                _is_quota = "429" in _err_str or "quota" in _err_str.lower() or "ResourceExhausted" in _err_str
                if _is_quota:
                    print(f"[Brain/Raw] Gemini quota hit – switching to Groq/Ollama fallback.")
                else:
                    print(f"[Brain/Raw] Gemini error: {_err_str[:180]}")

        # 2. Try Groq
        if self.internet_ready and self.groq_ready:
            try:
                import requests
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                }
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "temperature": 0.1,
                }
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                if response.status_code == 200:
                    res_text = response.json()["choices"][0]["message"]["content"].strip()
                    print(f"[Brain/Raw-Groq] Response received.")
                    return res_text
            except Exception as e:
                print(f"[Brain/Raw] Groq error: {e}")

        # 3. Try Ollama local
        if self.ollama_ready:
            try:
                messages = []
                if system_instruction:
                    messages.append({"role": "system", "content": system_instruction})
                messages.append({"role": "user", "content": prompt})

                response = _ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    options={"temperature": 0.1}
                )
                res_text = response["message"]["content"].strip()
                print(f"[Brain/Raw-Ollama] Response received.")
                return res_text
            except Exception as e:
                print(f"[Brain/Raw] Ollama error: {e}")

        # 4. Fallback: Parse query manually
        return "{}"
