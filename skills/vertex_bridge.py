import os
import json
import traceback
from typing import Dict, Any, Optional

# Lazy imports/detection of Vertex AI
_VERTEX_AVAILABLE = False
try:
    import google.auth
    from google.cloud import aiplatform
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig
    _VERTEX_AVAILABLE = True
except ImportError:
    vertexai = None
    GenerativeModel = None
    GenerationConfig = None

class AriaVertexBridge:
    def __init__(self, project_id: Optional[str] = None, location: str = "us-central1"):
        self.project_id = project_id
        self.location = location
        self.initialized = False
        
        # Default model mappings
        self.flash_model_name = "gemini-2.5-flash"
        self.pro_model_name = "gemini-2.5-pro"
        
        self._resolve_credentials()
        self._init_vertex()

    def _resolve_credentials(self):
        """Resolves Google Cloud credentials using priority order."""
        # 1. Env Var GOOGLE_APPLICATION_CREDENTIALS
        env_cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if env_cred and os.path.exists(env_cred):
            print(f"[VertexBridge] Using credentials from GOOGLE_APPLICATION_CREDENTIALS env var: {env_cred}")
            return
            
        # 2. Local workspace file serviceAccountKey.json
        local_key = "serviceAccountKey.json"
        if os.path.exists(local_key):
            abs_key_path = os.path.abspath(local_key)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_key_path
            print(f"[VertexBridge] Found workspace key. Set GOOGLE_APPLICATION_CREDENTIALS to: {abs_key_path}")
            return
            
        # 3. Default ADC
        print("[VertexBridge] GOOGLE_APPLICATION_CREDENTIALS not explicitly defined. Relying on default ADC.")

    def _init_vertex(self):
        """Initializes connection to Vertex AI endpoint."""
        if not _VERTEX_AVAILABLE:
            print("[VertexBridge] google-cloud-aiplatform libraries not installed. Bypassing initialization.")
            return

        try:
            # If project_id not provided, try to extract from serviceAccountKey.json
            if not self.project_id:
                local_key = "serviceAccountKey.json"
                if os.path.exists(local_key):
                    try:
                        with open(local_key, "r") as f:
                            key_data = json.load(f)
                            self.project_id = key_data.get("project_id")
                    except Exception:
                        pass
                
                # Fallback to GCP_PROJECT_ID environment variable
                if not self.project_id:
                    self.project_id = os.getenv("GCP_PROJECT_ID")

            if not self.project_id:
                # Try to auto-discover project ID using google auth helper
                try:
                    credentials, project = google.auth.default()
                    self.project_id = project or "aria-cloud-core"
                except Exception:
                    self.project_id = "aria-cloud-core"

            vertexai.init(project=self.project_id, location=self.location)
            self.initialized = True
            print(f"[VertexBridge] Vertex AI initialized successfully. Project: {self.project_id}, Region: {self.location}")
        except Exception as e:
            print(f"[VertexBridge] Vertex AI initialization failed: {e}")

    def generate(self, prompt: str, system_instruction: Optional[str] = None, 
                 enforce_json_schema: Optional[Dict[str, Any]] = None, model_type: str = "flash", 
                 brain_instance: Optional[Any] = None) -> str:
        """
        Routes the prompt to Vertex AI with schema and fallback constraints.
        Fallback chain: Vertex AI -> Ollama -> Local rule-based parser.
        """
        # Build fallback list depending on model_type
        tiers = []
        if model_type == "pro":
            tiers = ["vertex_pro", "vertex_flash", "ollama", "local_rules"]
        else:
            tiers = ["vertex_flash", "vertex_pro", "ollama", "local_rules"]

        for tier in tiers:
            try:
                if tier == "vertex_flash":
                    if self.initialized:
                        print(f"[VertexBridge] Dispatching prompt to Vertex AI ({self.flash_model_name})...")
                        return self._call_vertex(self.flash_model_name, prompt, system_instruction, enforce_json_schema)
                elif tier == "vertex_pro":
                    if self.initialized:
                        print(f"[VertexBridge] Dispatching prompt to Vertex AI ({self.pro_model_name})...")
                        return self._call_vertex(self.pro_model_name, prompt, system_instruction, enforce_json_schema)
                elif tier == "ollama":
                    if brain_instance and getattr(brain_instance, "ollama_ready", False):
                        print("[VertexBridge] Falling back to local Ollama...")
                        # Run via Ollama
                        return self._call_ollama(prompt, system_instruction, brain_instance)
                elif tier == "local_rules":
                    print("[VertexBridge] Falling back to offline rule-based parser...")
                    return self._call_local_rules(prompt, brain_instance)
            except Exception as e:
                print(f"[VertexBridge] Tier {tier} failed: {e}")
                
        # Ultimate fallback
        return "I'm ready. Tell me what to open, search, or automate."

    def _call_vertex(self, model_name: str, prompt: str, system_instruction: Optional[str], 
                     enforce_json_schema: Optional[Dict[str, Any]]) -> str:
        """Helper to invoke GenerativeModel under Vertex AI."""
        if not GenerativeModel:
            raise RuntimeError("Vertex GenerativeModel class not imported.")
            
        model = GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction
        )
        
        config = None
        if enforce_json_schema:
            config = GenerationConfig(
                response_mime_type="application/json",
                response_schema=enforce_json_schema
            )
            
        response = model.generate_content(prompt, generation_config=config)
        return response.text.strip()

    def _call_ollama(self, prompt: str, system_instruction: Optional[str], brain_instance: Any) -> str:
        """Invokes local Ollama client."""
        # Use brain_instance's existing Ollama setup if possible
        import ollama as _ollama
        from brain import OLLAMA_MODEL
        
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

    def _call_local_rules(self, prompt: str, brain_instance: Any) -> str:
        """Calls the offline rule parser."""
        if brain_instance and hasattr(brain_instance, "_offline_think"):
            return brain_instance._offline_think(prompt)
        return "Vertex service offline. Operating on localized fallback processing protocols."
