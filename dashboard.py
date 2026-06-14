import os
import psutil
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from skills.event_bus import EventBus
from skills.runtime_capabilities import CAPABILITIES
try:
    from skills.subsystem_health import HEALTH as _SUBSYSTEM_HEALTH
except Exception:
    _SUBSYSTEM_HEALTH = None

from skills.health_skill import HealthSkill
health_skill_instance = HealthSkill()

class CognitionState:
    # Active execution stats
    active_goal = "No active task"
    active_subtask = "Idle"
    confidence = 1.0
    model_in_use = "Gemini 2.5 Flash"
    memory_hits = []
    active_window = "Desktop"
    last_actions = []  # List of dicts: {"time": "12:01:00", "action": "[CLICK: 200,300]", "status": "success", "confidence": 0.95}
    reflection_results = ""
    mode = "safe"  # safe, auto, dev
    screenshot = ""  # Base64 string
    # World State Modeling
    world_state = {
        "active_project": "AI Assistant (ARIA)",
        "browser_tabs": "Dashboard, Workspace",
        "current_workflow": "None",
        "agent_status": "Idle"
    }
    # Tool health metrics
    tool_health = {
        "stuck_rate": "0%",
        "recovery_rate": "100%",
        "memory_latency": "0.01s",
        "vision_latency": "0.00s",
        "success_rate": "100%"
    }
    # Attention & Notification triage logs
    pending_notifications = []
    # Cognitive Load metrics
    cognitive_load_score = 0.1
    cognitive_load_status = "NORMAL"
    # Predictive forecasts
    predictive_forecasts = {}
    # Sandbox simulation results
    sandbox_simulation = {}
    # Calibration scale factor
    calibration_factor = 1.0
    # Causal attribution failure results
    causal_blame = {}
    # Dynamic runtime profile (AUTONOMOUS, CONSERVATIVE, MINIMAL, EXPLORATION)
    runtime_profile = "AUTONOMOUS"
    # Relationship Vector Soft Labels (from ReflectionEngine)
    familiarity_label = "Acquaintance"
    interaction_depth_label = "Surface-level"
    # Proactive Cognition Status (from ProactiveCognition)
    proactive_status = {
        "on_cooldown": False,
        "remaining_seconds": 0,
        "remaining_label": "Ready",
        "last_suggestion": "None"
    }
    cooldown_multiplier = 1.0
    quarantine_count = 0
    # Cognitive Governance Telemetry
    simulated_anomalies_quarantined = 0
    drift_delta_score = 0.0
    emotional_volatility = {"trust_volatile": False, "comfort_volatile": False}
    cognitive_version = {"personality": "personality_v0", "profile": "profile_v0"}
    runtime_capabilities = CAPABILITIES.snapshot()
    degradation_mode = CAPABILITIES.degradation_mode
    capability_health = CAPABILITIES.health_snapshot()
    presence_state = "USER_LEFT"
    # Live subsystem health (populated by HEALTH singleton in skills/subsystem_health.py)
    subsystem_health: dict = {}
    profile_insights: dict = {}

    # Dynamic Live Dashboard (Sprint V4)
    ambient_active_tab = "AMBIENT"  # AMBIENT, SPORTS, NEWS, WEATHER, STOCKS, SEARCH, PEOPLE, PRODUCTS, VIDEOS
    ambient_context_entity = ""     # e.g., "MATCH_RCB_GT", "PROD_MK345", "PERSON_VIRAT_KOHLI"
    ambient_widget_data = {}        # Chameleon contract JSON
    ambient_last_updated = 0        # Unix timestamp

app = FastAPI(title="ARIA Control Center")

# ── Static File Mounts & PWA Helpers ─────────────────────────────────────────
remote_dist_path = os.path.join(os.path.dirname(__file__), "remote", "dist")
if os.path.exists(remote_dist_path):
    # Mount the /assets sub-folder from the built React app
    assets_dir = os.path.join(remote_dist_path, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="remote_assets")

public_path = os.path.join(os.path.dirname(__file__), "public")
if os.path.exists(public_path):
    app.mount("/public", StaticFiles(directory=public_path), name="public")

@app.get("/login.html")
def serve_login():
    if os.path.exists(remote_dist_path):
        idx = os.path.join(remote_dist_path, "index.html")
        if os.path.exists(idx):
            return FileResponse(idx)
    p_idx = os.path.join(public_path, "index.html")
    if os.path.exists(p_idx):
        return FileResponse(p_idx)
    c_path = os.path.join(os.path.dirname(__file__), "controller.html")
    if os.path.exists(c_path):
        return FileResponse(c_path)
    return HTMLResponse("<h2>No remote interface files found on server</h2>", status_code=404)

@app.get("/controller.html")
def serve_controller():
    c_path = os.path.join(os.path.dirname(__file__), "controller.html")
    if os.path.exists(c_path):
        return FileResponse(c_path)
    p_idx = os.path.join(public_path, "index.html")
    if os.path.exists(p_idx):
        return FileResponse(p_idx)
    return HTMLResponse("<h2>No controller interface files found on server</h2>", status_code=404)

@app.get("/dashboard.html")
def serve_dashboard_html():
    p_dash = os.path.join(public_path, "dashboard.html")
    if os.path.exists(p_dash):
        return FileResponse(p_dash)
    return serve_dashboard()

# ── ARIA Design Lab (Engineering Studio) Backend State & APIs ─────────────────
import json
import re

class DesignState:
    active_project = "Mark 42"
    project_type = "suit"
    active_theme = ""
    current_version = "v1"
    
    # Active design state (copy of current version's components)
    components = {
        "torso": {"type": "capsule", "radius": 0.5, "length": 1.2, "color": "#dd2222", "pos_x": 0.0, "pos_y": 0.5, "pos_z": 0.0, "rot_y": 0.0},
        "head": {"type": "sphere", "radius": 0.28, "color": "#ffe600", "pos_x": 0.0, "pos_y": 0.8, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
        "left_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": -0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
        "right_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": 0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
        "left_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": -0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
        "right_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": 0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
        "arc_reactor": {"type": "sphere", "radius": 0.12, "color": "#00f0ff", "pos_x": 0.0, "pos_y": 0.2, "pos_z": 0.45, "rot_y": 0.0, "parent": "torso"}
    }
    
    # Design Memory / context to resolve "it"
    design_memory = {
        "last_referenced_component": "torso",
        "description": "glowing chest reactor armor suit"
    }

    # Simulation statuses
    simulations = {
        "airflow": False,
        "weight_distribution": False,
        "stability": False,
        "heat_map": False
    }

    # AI sketch/concept alternatives generated
    ai_concepts = []
    
    version_history = [
        {
            "version": "v1",
            "timestamp": "13:30:00",
            "description": "Initial design concept: Ironman Mark 42 suit with capsule limbs and central arc reactor.",
            "components": {
                "torso": {"type": "capsule", "radius": 0.5, "length": 1.2, "color": "#dd2222", "pos_x": 0.0, "pos_y": 0.5, "pos_z": 0.0, "rot_y": 0.0},
                "head": {"type": "sphere", "radius": 0.28, "color": "#ffe600", "pos_x": 0.0, "pos_y": 0.8, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
                "left_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": -0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
                "right_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": 0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
                "left_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": -0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
                "right_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": 0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
                "arc_reactor": {"type": "sphere", "radius": 0.12, "color": "#00f0ff", "pos_x": 0.0, "pos_y": 0.2, "pos_z": 0.45, "rot_y": 0.0, "parent": "torso"}
            }
        }
    ]

def get_ai_concepts(project_type: str, theme: str = "") -> list:
    t = project_type.lower()
    th = theme.lower().strip()
    
    if "suit" in t or "armor" in t or "ironman" in t or "iron man" in t:
        th_label = f" {theme.title()}" if theme else " Nano"
        th_desc = f" infused with {theme} shielding" if theme else ""
        return [
            {"id": "opt_a", "label": f"Option A:{th_label} Titanium Composite", "description": f"Gold titanium alloy reinforced with micro-grid weave{th_desc}. +15% armor.", "drag": 0.0, "power": 98, "preview_type": "mesh_update", "body_color": "#ffd700" if "stealth" not in th else "#222222", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_b", "label": f"Option B:{th_label} Stealth Plating", "description": f"Matte carbon plating with active cloaking grid{th_desc}. -10% thermal signature.", "drag": 0.0, "power": 85, "preview_type": "mesh_update", "body_color": "#151515", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_c", "label": f"Option C:{th_label} Arc Overcharge", "description": f"Enlarged chest reactor core{th_desc}. Boosts repulsor beam output by 25%.", "drag": 0.0, "power": 120, "preview_type": "mesh_update", "body_color": "#dd2222" if "stealth" not in th else "#4b0082", "spoiler_size": 1.0, "headlights_thickness": 1.0}
        ]
    elif "drone" in t or "copter" in t:
        th_label = f" {theme.title()}" if theme else " Hexa"
        th_desc = f" optimized for {theme}" if theme else ""
        return [
            {"id": "opt_a", "label": f"Option A:{th_label} Carbon Frame", "description": f"Vibration-damped carbon composite chassis{th_desc}. Max hover time: 55m.", "drag": 1.2, "power": 90, "preview_type": "mesh_update", "body_color": "#2c3e50" if "stealth" not in th else "#1c1c1c", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_b", "label": f"Option B:{th_label} Heavy Lift", "description": f"Enlarged rotor blades and high torque brushless motors{th_desc}. +3kg payload.", "drag": 2.5, "power": 120, "preview_type": "mesh_update", "body_color": "#e67e22", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_c", "label": f"Option C:{th_label} FPV High Agility", "description": f"Ultra-lightweight aerodynamic shroud{th_desc}. Max speed: 120 km/h.", "drag": 0.8, "power": 110, "preview_type": "mesh_update", "body_color": "#00f0ff", "spoiler_size": 1.0, "headlights_thickness": 1.0}
        ]
    elif "house" in t or "building" in t or "home" in t or "mansion" in t:
        return [
            {"id": "opt_a", "label": "Option A: Cantilever Glasshouse", "description": "Overhanging glass wings with panoramic sea-facing solar panels.", "drag": 0.0, "power": 100, "preview_type": "mesh_update", "body_color": "#f8fafc", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_b", "label": "Option B: Cyber Punk Bunker", "description": "Concrete structural shell, neon channel grooves, ballistic security windows.", "drag": 0.0, "power": 85, "preview_type": "mesh_update", "body_color": "#334155", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_c", "label": "Option C: Biophilic Green Roof", "description": "Laminated timber framing, living vegetation canopy, integrated rainwater cistern.", "drag": 0.0, "power": 60, "preview_type": "mesh_update", "body_color": "#e2e8f0", "spoiler_size": 1.0, "headlights_thickness": 1.0}
        ]
    elif "room" in t or "office" in t:
        return [
            {"id": "opt_a", "label": "Option A: Holographic Workspace", "description": "Integrated wall display grids, central projection floor, neon styling.", "drag": 0.0, "power": 100, "preview_type": "mesh_update", "body_color": "#0f172a", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_b", "label": "Option B: Minimalist Studio", "description": "Natural oak wood panels, dynamic dimmable lights, ergonomic active chair.", "drag": 0.0, "power": 50, "preview_type": "mesh_update", "body_color": "#fafaf9", "spoiler_size": 1.0, "headlights_thickness": 1.0},
            {"id": "opt_c", "label": "Option C: Industrial Lab", "description": "Exposed pipe ducts, steel counter workbenches, component bins.", "drag": 0.0, "power": 120, "preview_type": "mesh_update", "body_color": "#475569", "spoiler_size": 1.0, "headlights_thickness": 1.0}
        ]
    else: # Car
        return [
            {"id": "opt_a", "label": "Option A: Aggressive Shark Nose", "description": "Thinner headlights, shark-fin side scoops, 4% drag reduction.", "drag": 0.28, "power": 800, "preview_type": "mesh_update", "body_color": "#ff007f", "spoiler_size": 1.4, "headlights_thickness": 0.4},
            {"id": "opt_b", "label": "Option B: McLaren Longtail", "description": "Elongated rear spoiler, low drag, high speed stability.", "drag": 0.29, "power": 800, "preview_type": "mesh_update", "body_color": "#ff8a00", "spoiler_size": 1.8, "headlights_thickness": 0.8},
            {"id": "opt_c", "label": "Option C: Stealth Hybrid", "description": "Closed air intakes, active aerodynamics, matte carbon styling.", "drag": 0.30, "power": 850, "preview_type": "mesh_update", "body_color": "#333333", "spoiler_size": 1.0, "headlights_thickness": 0.6}
        ]

def init_project_components(project_name: str, project_type: str = "car"):
    t = project_type.lower()
    if "suit" in t or "armor" in t or "ironman" in t or "iron man" in t:
        return {
            "torso": {"type": "capsule", "radius": 0.5, "length": 1.2, "color": "#dd2222", "pos_x": 0.0, "pos_y": 0.5, "pos_z": 0.0, "rot_y": 0.0},
            "head": {"type": "sphere", "radius": 0.28, "color": "#ffe600", "pos_x": 0.0, "pos_y": 0.8, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
            "left_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": -0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
            "right_arm": {"type": "cylinder", "radius": 0.15, "length": 0.9, "color": "#dd2222", "pos_x": 0.7, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
            "left_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": -0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
            "right_leg": {"type": "cylinder", "radius": 0.2, "length": 1.1, "color": "#dd2222", "pos_x": 0.35, "pos_y": -1.1, "pos_z": 0.0, "rot_y": 0.0, "parent": "torso"},
            "arc_reactor": {"type": "sphere", "radius": 0.12, "color": "#00f0ff", "pos_x": 0.0, "pos_y": 0.2, "pos_z": 0.45, "rot_y": 0.0, "parent": "torso"}
        }
    elif "drone" in t or "copter" in t:
        return {
            "core": {"type": "cylinder", "radius": 0.6, "length": 0.15, "color": "#222233", "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0},
            "arm_fl": {"type": "cylinder", "radius": 0.05, "length": 0.8, "color": "#555555", "pos_x": -0.5, "pos_y": 0.0, "pos_z": 0.5, "rot_y": 0.78, "parent": "core"},
            "arm_fr": {"type": "cylinder", "radius": 0.05, "length": 0.8, "color": "#555555", "pos_x": 0.5, "pos_y": 0.0, "pos_z": 0.5, "rot_y": -0.78, "parent": "core"},
            "arm_bl": {"type": "cylinder", "radius": 0.05, "length": 0.8, "color": "#555555", "pos_x": -0.5, "pos_y": 0.0, "pos_z": -0.5, "rot_y": -0.78, "parent": "core"},
            "arm_br": {"type": "cylinder", "radius": 0.05, "length": 0.8, "color": "#555555", "pos_x": 0.5, "pos_y": 0.0, "pos_z": -0.5, "rot_y": 0.78, "parent": "core"},
            "rotor_fl": {"type": "cylinder", "radius": 0.35, "length": 0.02, "color": "#00f0ff", "pos_x": -0.35, "pos_y": 0.08, "pos_z": 0.35, "rot_y": 0.0, "parent": "arm_fl"},
            "rotor_fr": {"type": "cylinder", "radius": 0.35, "length": 0.02, "color": "#00f0ff", "pos_x": 0.35, "pos_y": 0.08, "pos_z": 0.35, "rot_y": 0.0, "parent": "arm_fr"},
            "rotor_bl": {"type": "cylinder", "radius": 0.35, "length": 0.02, "color": "#00f0ff", "pos_x": -0.35, "pos_y": 0.08, "pos_z": -0.35, "rot_y": 0.0, "parent": "arm_bl"},
            "rotor_br": {"type": "cylinder", "radius": 0.35, "length": 0.02, "color": "#00f0ff", "pos_x": 0.35, "pos_y": 0.08, "pos_z": -0.35, "rot_y": 0.0, "parent": "arm_br"}
        }
    elif "house" in t or "building" in t or "home" in t or "mansion" in t:
        return {
            "foundation": {"type": "box", "length": 4.0, "width": 4.0, "height": 2.2, "color": "#e2e8f0", "pos_x": 0.0, "pos_y": 0.6, "pos_z": 0.0, "rot_y": 0.0},
            "roof": {"type": "cone", "radius": 3.0, "length": 1.2, "color": "#dd2222", "pos_x": 0.0, "pos_y": 1.5, "pos_z": 0.0, "rot_y": 0.78, "parent": "foundation"},
            "door": {"type": "box", "length": 0.1, "width": 0.7, "height": 1.4, "color": "#ff6c00", "pos_x": 0.0, "pos_y": -0.3, "pos_z": 2.0, "rot_y": 0.0, "parent": "foundation"},
            "window_l": {"type": "box", "length": 0.1, "width": 0.6, "height": 0.6, "color": "#00f0ff", "pos_x": -1.2, "pos_y": 0.3, "pos_z": 2.0, "rot_y": 0.0, "parent": "foundation"},
            "window_r": {"type": "box", "length": 0.1, "width": 0.6, "height": 0.6, "color": "#00f0ff", "pos_x": 1.2, "pos_y": 0.3, "pos_z": 2.0, "rot_y": 0.0, "parent": "foundation"}
        }
    elif "room" in t or "office" in t:
        return {
            "floor": {"type": "box", "length": 4.0, "width": 4.0, "height": 0.05, "color": "#333344", "pos_x": 0.0, "pos_y": -0.4, "pos_z": 0.0, "rot_y": 0.0},
            "back_wall": {"type": "box", "length": 4.0, "width": 0.05, "height": 2.0, "color": "#555566", "pos_x": 0.0, "pos_y": 1.0, "pos_z": -2.0, "rot_y": 0.0, "parent": "floor"},
            "desk": {"type": "box", "length": 1.6, "width": 0.8, "height": 0.75, "color": "#ff6c00", "pos_x": 0.0, "pos_y": 0.4, "pos_z": -0.8, "rot_y": 0.0, "parent": "floor"},
            "chair": {"type": "box", "length": 0.5, "width": 0.5, "height": 0.9, "color": "#ff007f", "pos_x": 0.0, "pos_y": 0.3, "pos_z": 0.0, "rot_y": 0.0, "parent": "floor"},
            "monitor": {"type": "box", "length": 0.8, "width": 0.1, "height": 0.45, "color": "#111111", "pos_x": 0.0, "pos_y": 0.5, "pos_z": 0.0, "rot_y": 0.0, "parent": "desk"}
        }
    else: # Default: Car
        return {
            "body": {"type": "box", "length": 4.5, "width": 2.0, "height": 1.1, "color": "#ff007f", "aerodynamics": 0.32, "spoiler_size": 1.0, "headlights_thickness": 1.0, "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0},
            "engine": {"type": "box", "horsepower": 800, "hybrid": True, "torque": 750, "turbo": True, "pos_x": 0.0, "pos_y": 0.1, "pos_z": -0.8, "rot_y": 0.0},
            "wheels": {"type": "wheels", "radius": 0.45, "width": 0.3, "color": "#333333", "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0, "rot_y": 0.0},
            "spoiler": {"type": "spoiler", "size": 1.0, "color": "#00f0ff", "pos_x": 0.0, "pos_y": 0.5, "pos_z": -1.8, "rot_y": 0.0},
            "chassis": {"type": "box", "wheelbase": 2.8, "ride_height": 0.12, "pos_x": 0.0, "pos_y": -0.1, "pos_z": 0.0, "rot_y": 0.0}
        }

def match_component_name(name: str) -> str:
    n = name.lower().strip()
    p_type = getattr(DesignState, "project_type", "car").lower()
    if "body" in n or "aerodynamics" in n:
        if p_type == "suit": return "torso"
        if p_type == "drone": return "core"
        if p_type == "house": return "foundation"
        if p_type == "room": return "floor"
        return "body"
    if "engine" in n or "motor" in n or "power" in n: return "engine"
    if "wheel" in n or "tire" in n: return "wheels"
    if "spoiler" in n or "wing" in n: return "spoiler"
    if "chassis" in n or "wheelbase" in n or "height" in n: return "chassis"
    # Dynamic key matching
    for k in DesignState.components.keys():
        if n in k or k in n:
            return k
    return n

def create_new_version(description: str):
    v_num = len(DesignState.version_history) + 1
    v_name = f"v{v_num}"
    DesignState.current_version = v_name
    DesignState.version_history.append({
        "version": v_name,
        "timestamp": "13:45:00",
        "description": description,
        "components": json.loads(json.dumps(DesignState.components))
    })

def parse_design_command(text: str) -> dict:
    text_clean = text.lower().strip()
    
    # Clean up common voice dictation typos
    text_clean = text_clean.replace("get pack", "jet pack")
    text_clean = text_clean.replace("getpack", "jet pack")
    text_clean = text_clean.replace("lauch", "launch")
    
    # 0. Immersive HUD Mode controls
    if any(phrase in text_clean for phrase in ["hide hud", "hide interface", "immersive mode", "full screen", "clear workspace"]):
        return {
            "status": "success",
            "message": "Immersive mode activated. Hiding HUD panels.",
            "action": "TOGGLE_IMMERSIVE",
            "immersive": True
        }
    if any(phrase in text_clean for phrase in ["show hud", "show interface", "restore hud", "show controls", "hud online"]):
        return {
            "status": "success",
            "message": "HUD panels online. Interface restored.",
            "action": "TOGGLE_IMMERSIVE",
            "immersive": False
        }
        
    ref_comp = DesignState.design_memory["last_referenced_component"]
    
    # 1. Create project
    m = re.search(r"create (?:a )?(stealth|heavy|tactical|cyber|minimalist)?\s*(car|suit|drone|house|room)?\s*project(?:\s+called)?\s+([a-zA-Z0-9_\s\-]+)", text_clean)
    if not m:
        m = re.search(r"create (?:a )?(stealth|heavy|tactical|cyber|minimalist)?\s*(car|suit|drone|house|room)?\s*(?:project|design)\s+([a-zA-Z0-9_\s\-]+)", text_clean)
    if m:
        theme = m.group(1) or ""
        proj_type = m.group(2) or "car"
        name = m.group(3).strip().title()
        
        if not m.group(2):
            n_lower = name.lower()
            if "suit" in n_lower or "armor" in n_lower or "ironman" in n_lower or "iron man" in n_lower:
                proj_type = "suit"
            elif "drone" in n_lower or "copter" in n_lower:
                proj_type = "drone"
            elif "house" in n_lower or "home" in n_lower or "mansion" in n_lower:
                proj_type = "house"
            elif "room" in n_lower or "office" in n_lower:
                proj_type = "room"
            else:
                proj_type = "car"
                
        DesignState.active_project = name
        DesignState.project_type = proj_type
        DesignState.active_theme = theme
        DesignState.current_version = "v1"
        DesignState.components = init_project_components(name, proj_type)
        
        # Apply theme colors
        primary_comp = "body"
        for k in ["body", "torso", "core", "foundation", "floor"]:
            if k in DesignState.components:
                primary_comp = k
                break
                
        if theme == "stealth":
            DesignState.components[primary_comp]["color"] = "#151515"
        elif theme == "heavy":
            DesignState.components[primary_comp]["color"] = "#e67e22"
        elif theme == "tactical":
            DesignState.components[primary_comp]["color"] = "#2c3e50"
        elif theme == "cyber":
            DesignState.components[primary_comp]["color"] = "#00f0ff"
        elif theme == "minimalist":
            DesignState.components[primary_comp]["color"] = "#f8fafc"
            
        DesignState.ai_concepts = get_ai_concepts(proj_type, theme)
        
        DesignState.version_history = [{
            "version": "v1",
            "timestamp": "13:30:00",
            "description": f"Initial project '{name}' initialized as a {theme.upper() + ' ' if theme else ''}{proj_type.upper()} design.",
            "components": json.loads(json.dumps(DesignState.components))
        }]
        return {
            "status": "success",
            "message": f"Project '{name}' has been created as a {theme.upper() + ' ' if theme else ''}{proj_type.upper()} type. Dynamic mesh workspace loaded.",
            "action": "CREATE_PROJECT"
        }

    # 2. Simulation toggles
    if "airflow" in text_clean:
        DesignState.simulations["airflow"] = not DesignState.simulations["airflow"]
        status_str = "activated" if DesignState.simulations["airflow"] else "deactivated"
        return {
            "status": "success",
            "message": f"Airflow wind-tunnel simulation is now {status_str}.",
            "action": "SIMULATION_TOGGLE",
            "simulation": "airflow",
            "state": DesignState.simulations["airflow"]
        }
    if "weight" in text_clean or "center of mass" in text_clean:
        DesignState.simulations["weight_distribution"] = not DesignState.simulations["weight_distribution"]
        status_str = "activated" if DesignState.simulations["weight_distribution"] else "deactivated"
        return {
            "status": "success",
            "message": f"Weight distribution sensor overlay is now {status_str}.",
            "action": "SIMULATION_TOGGLE",
            "simulation": "weight_distribution",
            "state": DesignState.simulations["weight_distribution"]
        }
    if "stability" in text_clean:
        DesignState.simulations["stability"] = not DesignState.simulations["stability"]
        status_str = "activated" if DesignState.simulations["stability"] else "deactivated"
        return {
            "status": "success",
            "message": f"FEA stress and stability analysis is now {status_str}.",
            "action": "SIMULATION_TOGGLE",
            "simulation": "stability",
            "state": DesignState.simulations["stability"]
        }
    if "heat map" in text_clean or "thermal" in text_clean:
        DesignState.simulations["heat_map"] = not DesignState.simulations["heat_map"]
        status_str = "activated" if DesignState.simulations["heat_map"] else "deactivated"
        return {
            "status": "success",
            "message": f"Thermal distribution imaging is now {status_str}.",
            "action": "SIMULATION_TOGGLE",
            "simulation": "heat_map",
            "state": DesignState.simulations["heat_map"]
        }

    # 3. Apply concept
    m = re.search(r"apply (?:option|concept) ([a-c])", text_clean)
    if not m:
        m = re.search(r"use (?:option|concept) ([a-c])", text_clean)
    if not m:
        m = re.search(r"select (?:option|concept) ([a-c])", text_clean)
    if m:
        opt = m.group(1).lower()
        idx = ord(opt) - ord('a')
        concepts = get_ai_concepts(getattr(DesignState, "project_type", "car"), getattr(DesignState, "active_theme", ""))
        concept = concepts[idx]
        
        primary = "body"
        for k in ["body", "torso", "core", "foundation", "floor"]:
            if k in DesignState.components:
                primary = k
                break
        
        DesignState.components[primary]["color"] = concept["body_color"]
        if "aerodynamics" in DesignState.components[primary]:
            DesignState.components[primary]["aerodynamics"] = concept["drag"]
        if "spoiler" in DesignState.components:
            DesignState.components["spoiler"]["size"] = concept["spoiler_size"]
            
        create_new_version(f"Applied AI Concept {opt.upper()}: {concept['label']}")
        return {
            "status": "success",
            "message": f"Merged Option {opt.upper()} configuration: {concept['description']}",
            "action": "APPLY_CONCEPT"
        }

    # 4. Version Switcher
    m = re.search(r"compare version (v[1-9]) and (v[1-9])", text_clean)
    if not m:
        m = re.search(r"compare (v[1-9]) and (v[1-9])", text_clean)
    if m:
        vA = m.group(1).lower()
        vB = m.group(2).lower()
        verA = next((v for v in DesignState.version_history if v["version"] == vA), None)
        verB = next((v for v in DesignState.version_history if v["version"] == vB), None)
        if verA and verB:
            diffs = []
            for comp, attrs in verA["components"].items():
                for attr, val in attrs.items():
                    valB = verB["components"][comp].get(attr)
                    if val != valB:
                        diffs.append(f"{comp.title()} {attr.replace('_',' ')} changed from {val} to {valB}")
            diff_text = "; ".join(diffs) if diffs else "No differences detected."
            return {
                "status": "success",
                "message": f"Comparison complete. Differences: {diff_text}",
                "action": "COMPARE_VERSIONS",
                "diff": diffs
            }
        return {"status": "error", "message": "One or both versions do not exist."}

    m = re.search(r"revert to (v[1-9])", text_clean)
    if not m:
        m = re.search(r"load version (v[1-9])", text_clean)
    if m:
        v_num = m.group(1).lower()
        ver = next((v for v in DesignState.version_history if v["version"] == v_num), None)
        if ver:
            DesignState.components = json.loads(json.dumps(ver["components"]))
            DesignState.current_version = v_num
            return {
                "status": "success",
                "message": f"Loaded version {v_num.upper()} parameters into canvas.",
                "action": "LOAD_VERSION"
            }

    # 4.5 Add component: "add [component] [type] to [parent]" or "add [component] to [parent]"
    add_match = re.search(r"(?:add|insert)\s+([a-zA-Z0-9_\s]+?)(?:\s+of\s+type\s+([a-zA-Z]+))?(?:\s+to\s+([a-zA-Z0-9_]+))?$", text_clean)
    if add_match:
        comp_raw = add_match.group(1).strip()
        comp_name = comp_raw.replace(' ', '_')
        comp_type = "box"
        parent_name = None
        
        if add_match.group(2):
            comp_type = add_match.group(2).strip().lower()
        else:
            if "arm" in comp_name or "leg" in comp_name or "pillar" in comp_name or "cannon" in comp_name or "rotor" in comp_name:
                comp_type = "cylinder"
            elif "reactor" in comp_name or "core" in comp_name or "globe" in comp_name or "head" in comp_name or "sphere" in comp_name:
                comp_type = "sphere"
            elif "roof" in comp_name or "cone" in comp_name:
                comp_type = "cone"
            elif "wing" in comp_name or "spoiler" in comp_name:
                comp_type = "spoiler"
            elif "wheel" in comp_name or "tire" in comp_name:
                comp_type = "wheels"

        if add_match.group(3):
            parent_raw = add_match.group(3).strip()
            parent_name = match_component_name(parent_raw)
            if parent_name not in DesignState.components:
                parent_name = None
        else:
            # Auto-parent to primary component if parent is omitted in voice command
            p_type = getattr(DesignState, "project_type", "car").lower()
            if p_type == "suit":
                parent_name = "torso" if "torso" in DesignState.components else None
            elif p_type == "drone":
                parent_name = "core" if "core" in DesignState.components else None
            elif p_type == "house":
                parent_name = "foundation" if "foundation" in DesignState.components else None
            elif p_type == "room":
                parent_name = "floor" if "floor" in DesignState.components else None
            else:
                parent_name = "body" if "body" in DesignState.components else None

        if comp_name not in DesignState.components:
            # Smart coordinate offsets & dimensions defaults based on name
            px, py, pz = 0.0, 0.4 if parent_name else 0.8, 0.0
            col = "#00f0ff" # Default cyan glow
            length_val = 1.0
            width_val = 1.0
            radius_val = 0.4
            
            p_type = getattr(DesignState, "project_type", "car").lower()
            
            # Identify smart characteristics
            if "jet" in comp_name or "pack" in comp_name or "booster" in comp_name or "thruster" in comp_name:
                comp_type = "box"
                col = "#dd2222" # Match suit red armor color
                px, py, pz = 0.0, 0.1, -0.55 # Behind back relative to torso
                length_val = 0.4 # thickness
                width_val = 0.8 # width
                radius_val = 0.7 # height (reused as radius/height)
            elif "launcher" in comp_name or "cannon" in comp_name or "weapon" in comp_name:
                comp_type = "cylinder"
                col = "#ffe600" # Gold accent color
                px, py, pz = 0.35, 0.6, 0.15 # Shoulder mount placement
                length_val = 0.7
                radius_val = 0.08
            elif "reactor" in comp_name:
                comp_type = "sphere"
                col = "#00f0ff" # Blue cyan core glow
                px, py, pz = 0.0, 0.2, 0.45 # Chest mount placement
                radius_val = 0.12
            elif "shield" in comp_name:
                comp_type = "box"
                col = "#dd2222" # Shield color
                # Auto-attach to left arm if present on suit
                if p_type == "suit" and "left_arm" in DesignState.components:
                    parent_name = "left_arm"
                    px, py, pz = -0.1, 0.0, 0.2
                else:
                    px, py, pz = -0.5, 0.0, 0.2
                length_val = 0.1
                width_val = 0.6
                radius_val = 0.6
            elif "wing" in comp_name:
                comp_type = "spoiler"
                col = "#00f0ff"
                px, py, pz = 0.0, 0.5, -1.8
            else:
                # Fallback to standard sizes based on geometry type
                if comp_type == "cylinder":
                    length_val = 0.8
                    width_val = 0.2
                    radius_val = 0.15
                elif comp_type == "sphere":
                    radius_val = 0.4
                elif comp_type == "cone":
                    length_val = 0.8
                    radius_val = 0.4
                else: # box
                    length_val = 1.0
                    width_val = 1.0
                    radius_val = 0.4 # height
                    
            DesignState.components[comp_name] = {
                "type": comp_type,
                "length": length_val,
                "width": width_val,
                "radius": radius_val,
                "color": col,
                "pos_x": px,
                "pos_y": py,
                "pos_z": pz,
                "rot_y": 0.0,
                "parent": parent_name
            }
            DesignState.design_memory["last_referenced_component"] = comp_name
            msg = f"Assembled and added new {comp_raw} module (type: {comp_type})"
            if parent_name:
                msg += f" attached to {parent_name}"
            msg += " to workspace."
            create_new_version(f"Added component {comp_name} ({comp_type})")
            return {
                "status": "success",
                "message": msg,
                "action": "ADD_COMPONENT",
                "component": comp_name
            }

    # 4.6 Remove component: "remove [component]" or "delete [component]"
    rm_match = re.search(r"(?:remove|delete|de-assemble)\s+([a-zA-Z0-9_]+)", text_clean)
    if rm_match:
        comp_name = match_component_name(rm_match.group(1).strip())
        if comp_name in DesignState.components:
            # Symmetrically remove any children referencing it
            to_remove = [comp_name]
            for k, v in list(DesignState.components.items()):
                if v.get("parent") == comp_name:
                    to_remove.append(k)
            
            for k in to_remove:
                if k in DesignState.components:
                    del DesignState.components[k]
                    
            create_new_version(f"Removed component: {comp_name}")
            return {
                "status": "success",
                "message": f"De-assembled and removed the {comp_name} module (and its sub-assemblies).",
                "action": "REMOVE_COMPONENT",
                "component": comp_name
            }

    # 5. Modifiers
    color_map = {
        "red": "#ff0000", "blue": "#0022ff", "green": "#00ff22", "cyan": "#00f0ff",
        "orange": "#ff6c00", "yellow": "#ffe600", "purple": "#8f00ff", "pink": "#ff00c8",
        "white": "#ffffff", "black": "#151515", "dark gray": "#333333", "gold": "#ffd700"
    }
    found_color = None
    for name, code in color_map.items():
        if name in text_clean:
            found_color = code
            break
    hex_match = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", text_clean)
    if hex_match:
        found_color = hex_match.group(0)

    if found_color:
        target = ref_comp
        for k in DesignState.components.keys():
            if k in text_clean:
                target = k
                break
        if "wheel" in text_clean: target = "wheels"
        elif "spoiler" in text_clean: target = "spoiler"
        elif "body" in text_clean: target = match_component_name("body")
        elif "chassis" in text_clean: target = "chassis"

        if target in DesignState.components:
            DesignState.components[target]["color"] = found_color
            create_new_version(f"Modified {target} color to {found_color}")
            return {
                "status": "success",
                "message": f"Modified {target} surface color to {found_color}.",
                "action": "UPDATE_COMPONENT",
                "component": target
            }

    # Generic dimension scaling: scale component by X% or make component larger/smaller
    scale_match = re.search(r"(?:scale|make)\s+([a-zA-Z0-9_\s]*)\s*(?:by\s+)?([0-9]+)%", text_clean)
    if not scale_match:
        scale_match = re.search(r"make\s+([a-zA-Z0-9_\s]*)\s+(larger|smaller|bigger|thinner|narrower|longer)", text_clean)
    if scale_match:
        comp_name = scale_match.group(1).strip()
        comp_name = ref_comp if not comp_name else match_component_name(comp_name)
        if comp_name in DesignState.components:
            comp = DesignState.components[comp_name]
            pct = 0.20
            has_pct = False
            try:
                if scale_match.group(2).isdigit():
                    pct = float(scale_match.group(2)) / 100.0
                    has_pct = True
            except:
                pass
            if not has_pct:
                keyword = scale_match.group(2)
                if keyword in ["larger", "bigger", "longer"]:
                    pct = 0.25
                elif keyword in ["smaller", "thinner", "narrower"]:
                    pct = -0.25
            for dim in ["length", "width", "height", "radius", "size"]:
                if dim in comp:
                    comp[dim] = max(0.05, comp[dim] * (1 + pct))
            DesignState.design_memory["last_referenced_component"] = comp_name
            create_new_version(f"Scaled {comp_name} by {pct*100}%")
            return {
                "status": "success",
                "message": f"Rescaled {comp_name} dimensions by {pct*100:+.0f}%.",
                "action": "UPDATE_COMPONENT",
                "component": comp_name
            }

    # Translation: move component dir X cm
    move_match = re.search(r"move\s+([a-zA-Z0-9_\s]+)\s+(back|forward|up|down|left|right)\s*([0-9]+)\s*(cm|m|degrees)?", text_clean)
    if not move_match:
        move_match = re.search(r"move\s+()(back|forward|up|down|left|right)\s*([0-9]+)\s*(cm|m|degrees)?", text_clean)
    if move_match:
        comp_name = move_match.group(1).strip()
        direction = move_match.group(2)
        amount = float(move_match.group(3))
        unit = move_match.group(4) or "cm"
        comp_name = ref_comp if not comp_name else match_component_name(comp_name)
        
        if comp_name in DesignState.components:
            val = amount / 100.0 if unit == "cm" else amount
            if direction == "back": DesignState.components[comp_name]["pos_z"] -= val
            elif direction == "forward": DesignState.components[comp_name]["pos_z"] += val
            elif direction == "left": DesignState.components[comp_name]["pos_x"] -= val
            elif direction == "right": DesignState.components[comp_name]["pos_x"] += val
            elif direction == "up": DesignState.components[comp_name]["pos_y"] += val
            elif direction == "down": DesignState.components[comp_name]["pos_y"] -= val
            DesignState.design_memory["last_referenced_component"] = comp_name
            create_new_version(f"Moved {comp_name} {direction} by {amount}{unit}")
            return {
                "status": "success",
                "message": f"Translated {comp_name} mesh {direction} by {amount} {unit}.",
                "action": "UPDATE_COMPONENT",
                "component": comp_name
            }

    # Rotation: rotate component X degrees
    rot_match = re.search(r"rotate\s+([a-zA-Z0-9_\s]*)\s*(?:by\s+)?([0-9\-]+)\s*(?:deg|degrees)?", text_clean)
    if rot_match:
        comp_name = rot_match.group(1).strip()
        degrees = float(rot_match.group(2))
        comp_name = ref_comp if not comp_name else match_component_name(comp_name)
        if comp_name in DesignState.components:
            import math
            rad = math.radians(degrees)
            DesignState.components[comp_name]["rot_y"] += rad
            create_new_version(f"Rotated {comp_name} by {degrees} degrees")
            return {
                "status": "success",
                "message": f"Rotated {comp_name} alignment by {degrees}°.",
                "action": "UPDATE_COMPONENT",
                "component": comp_name
            }

    # Spoiler size
    if "spoiler" in text_clean and "spoiler" in DesignState.components:
        if "increase" in text_clean or "larger" in text_clean or "bigger" in text_clean:
            DesignState.components["spoiler"]["size"] += 0.25
            if "body" in DesignState.components and "aerodynamics" in DesignState.components["body"]:
                DesignState.components["body"]["aerodynamics"] = max(0.24, DesignState.components["body"]["aerodynamics"] - 0.02)
            create_new_version("Increased rear spoiler wing profile")
            return {
                "status": "success", "message": "Scaled spoiler wing surface. Downforce ratio optimized.",
                "action": "UPDATE_COMPONENT", "component": "spoiler"
            }
        elif "decrease" in text_clean or "smaller" in text_clean:
            DesignState.components["spoiler"]["size"] = max(0.4, DesignState.components["spoiler"]["size"] - 0.25)
            if "body" in DesignState.components and "aerodynamics" in DesignState.components["body"]:
                DesignState.components["body"]["aerodynamics"] = min(0.38, DesignState.components["body"]["aerodynamics"] + 0.01)
            create_new_version("Decreased rear spoiler wing profile")
            return {
                "status": "success", "message": "Reduced spoiler wing profile.",
                "action": "UPDATE_COMPONENT", "component": "spoiler"
            }

    # Headlights
    if "headlight" in text_clean and "body" in DesignState.components:
        if "thinner" in text_clean or "narrow" in text_clean or "slim" in text_clean:
            DesignState.components["body"]["headlights_thickness"] = max(0.15, DesignState.components["body"]["headlights_thickness"] - 0.2)
            if "aerodynamics" in DesignState.components["body"]:
                DesignState.components["body"]["aerodynamics"] = max(0.25, DesignState.components["body"]["aerodynamics"] - 0.01)
            create_new_version("Headlight bezel profile reduced")
            return {
                "status": "success", "message": "Laser headlights thickness slimmed. Coefficient of drag minimized.",
                "action": "UPDATE_COMPONENT", "component": "body"
            }

    # Wheelbase
    if "wheelbase" in text_clean and "chassis" in DesignState.components:
        if "increase" in text_clean or "longer" in text_clean or "extend" in text_clean:
            DesignState.components["chassis"]["wheelbase"] += 0.25
            create_new_version("Extended chassis wheelbase")
            return {
                "status": "success", "message": "Extended vehicle wheelbase by 25cm for high speed stability.",
                "action": "UPDATE_COMPONENT", "component": "chassis"
            }

    # Wheels scale
    if "wheel" in text_clean and "wheels" in DesignState.components:
        scale_m = re.search(r"(?:scale|increase|decrease)\s+(?:wheels|wheel)\s*(?:by\s+)?([0-9]+)%", text_clean)
        if scale_m:
            pct = float(scale_m.group(1)) / 100.0
            if "decrease" in text_clean:
                DesignState.components["wheels"]["radius"] = max(0.2, DesignState.components["wheels"]["radius"] * (1 - pct))
            else:
                DesignState.components["wheels"]["radius"] = min(0.8, DesignState.components["wheels"]["radius"] * (1 + pct))
            create_new_version(f"Scaled wheels by {scale_m.group(1)}%")
            return {
                "status": "success", "message": f"Rescaled wheels by {scale_m.group(1)}%.",
                "action": "UPDATE_COMPONENT", "component": "wheels"
            }

    # Engine Power / Arc Reactor calibration
    if "engine" in text_clean or "power" in text_clean or "horsepower" in text_clean or "hp" in text_clean or "reactor" in text_clean:
        hp_match = re.search(r"([0-9]+)\s*(?:hp|horsepower|%)", text_clean)
        if hp_match:
            val = int(hp_match.group(1))
            if "arc_reactor" in DesignState.components:
                DesignState.components["arc_reactor"]["radius"] = min(0.35, max(0.05, 0.12 * (val / 100.0)))
                create_new_version(f"Calibrated arc reactor power to {val}%")
                return {
                    "status": "success", "message": f"Arc Reactor output calibrated to {val}%. Resonance core stabilized.",
                    "action": "UPDATE_COMPONENT", "component": "arc_reactor"
                }
            elif "engine" in DesignState.components:
                DesignState.components["engine"]["horsepower"] = val
                DesignState.components["engine"]["torque"] = int(val * 0.95)
                create_new_version(f"Upgraded horsepower target to {val} HP")
                return {
                    "status": "success", "message": f"Engine module mapped to V8 configuration outputting {val} HP.",
                    "action": "UPDATE_COMPONENT", "component": "engine"
                }

    # Fallback to general AI sketch merge if it is a design sentence
    if len(text_clean.split()) >= 3:
        create_new_version(f"Merged iteration: {text}")
        return {
            "status": "success",
            "message": f"Design iteration processed: '{text}'. Core component constraints updated.",
            "action": "INTELLIGENT_MERGE"
        }

    return {
        "status": "error",
        "message": "Engineering prompt not recognized. Try 'move engine back 20cm', 'change body color to cyan', or 'airflow simulation'."
    }

class DesignCommandRequest(BaseModel):
    command: str

@app.get("/design_lab.html")
def serve_design_lab_html():
    p_lab = os.path.join(public_path, "design_lab.html")
    if os.path.exists(p_lab):
        return FileResponse(p_lab)
    return HTMLResponse("<h2>Design Lab HTML not found</h2>", status_code=404)

@app.get("/api/design/project")
def get_design_project():
    p_type = getattr(DesignState, "project_type", "car")
    p_theme = getattr(DesignState, "active_theme", "")
    return {
        "project_name": DesignState.active_project,
        "project_type": p_type,
        "active_theme": p_theme,
        "current_version": DesignState.current_version,
        "components": DesignState.components,
        "simulations": DesignState.simulations,
        "ai_concepts": get_ai_concepts(p_type, p_theme),
        "version_history": [
            {
                "version": v["version"],
                "timestamp": v["timestamp"],
                "description": v["description"]
            }
            for v in DesignState.version_history
        ]
    }

@app.post("/api/design/command")
def post_design_command(data: DesignCommandRequest):
    try:
        res = parse_design_command(data.command)
        p_type = getattr(DesignState, "project_type", "car")
        p_theme = getattr(DesignState, "active_theme", "")
        res["project"] = {
            "project_name": DesignState.active_project,
            "project_type": p_type,
            "active_theme": p_theme,
            "current_version": DesignState.current_version,
            "components": DesignState.components,
            "simulations": DesignState.simulations,
            "ai_concepts": get_ai_concepts(p_type, p_theme),
            "version_history": [
                {
                    "version": v["version"],
                    "timestamp": v["timestamp"],
                    "description": v["description"]
                }
                for v in DesignState.version_history
            ]
        }
        return res
    except Exception as e:
        return {"status": "error", "message": f"Design engine exception: {str(e)}"}

@app.post("/api/camera/release")
def release_backend_camera():
    import sys
    aria_instance = getattr(sys.modules.get('__main__'), 'instance', None)
    if aria_instance:
        aria_instance.airtouch_mode = True
        if aria_instance.camera:
            aria_instance.camera.release()
            return {"status": "success", "message": "Camera released successfully"}
    return {"status": "warning", "message": "ARIA instance not found, camera may not be released"}

@app.post("/api/camera/acquire")
def acquire_backend_camera():
    import sys
    aria_instance = getattr(sys.modules.get('__main__'), 'instance', None)
    if aria_instance:
        aria_instance.airtouch_mode = False
        if aria_instance.camera:
            aria_instance.camera.reacquire()
            return {"status": "success", "message": "Camera reacquired successfully"}
    return {"status": "warning", "message": "ARIA instance not found, camera may not be reacquired"}

@app.get("/manifest.json")
def get_manifest():
    for base in [remote_dist_path, os.path.join(os.path.dirname(__file__), "remote", "public"), public_path]:
        path = os.path.join(base, "manifest.json")
        if os.path.exists(path):
            return FileResponse(path)
    return Response(status_code=404)

@app.get("/sw.js")
def get_sw():
    for base in [remote_dist_path, os.path.join(os.path.dirname(__file__), "remote", "public"), public_path]:
        path = os.path.join(base, "sw.js")
        if os.path.exists(path):
            return FileResponse(path, media_type="application/javascript")
    return Response(status_code=404)

@app.get("/favicon.svg")
def get_favicon():
    for base in [remote_dist_path, os.path.join(os.path.dirname(__file__), "remote", "public"), public_path]:
        path = os.path.join(base, "favicon.svg")
        if os.path.exists(path):
            return FileResponse(path, media_type="image/svg+xml")
    return Response(status_code=404)

@app.get("/icon-192.png")
def get_icon192():
    for base in [remote_dist_path, os.path.join(os.path.dirname(__file__), "remote", "public"), public_path]:
        path = os.path.join(base, "icon-192.png")
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)

@app.get("/icon-512.png")
def get_icon512():
    for base in [remote_dist_path, os.path.join(os.path.dirname(__file__), "remote", "public"), public_path]:
        path = os.path.join(base, "icon-512.png")
        if os.path.exists(path):
            return FileResponse(path, media_type="image/png")
    return Response(status_code=404)

class ModeUpdate(BaseModel):
    mode: str

@app.get("/api/fitness/latest")
def get_fitness_latest():
    try:
        return health_skill_instance.get_latest_metrics() or {}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/fitness/history")
def get_fitness_history():
    try:
        return health_skill_instance.get_recent_history(days=7) or []
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/failures")
def get_failures():
    import sqlite3
    db_path = "aria_memory.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT failure_type, COUNT(*) as count FROM failure_analytics GROUP BY failure_type")
        data = [{"type": row[0], "count": row[1]} for row in cursor.fetchall()]
        conn.close()
        return data
    except Exception:
        return []

@app.get("/api/events")
def get_events():
    return EventBus().get_history()

@app.get("/api/state")
def get_state():
    # Fetch real-time system resource stats
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    
    return {
        "active_goal": CognitionState.active_goal,
        "active_subtask": CognitionState.active_subtask,
        "confidence": CognitionState.confidence,
        "model_in_use": CognitionState.model_in_use,
        "memory_hits": CognitionState.memory_hits,
        "active_window": CognitionState.active_window,
        "last_actions": CognitionState.last_actions,
        "reflection_results": CognitionState.reflection_results,
        "mode": CognitionState.mode,
        "cpu_usage": cpu,
        "ram_usage": ram,
        "screenshot_available": bool(CognitionState.screenshot),
        "world_state": CognitionState.world_state,
        "tool_health": CognitionState.tool_health,
        "pending_notifications": CognitionState.pending_notifications,
        "cognitive_load_score": CognitionState.cognitive_load_score,
        "cognitive_load_status": CognitionState.cognitive_load_status,
        "predictive_forecasts": CognitionState.predictive_forecasts,
        "sandbox_simulation": CognitionState.sandbox_simulation,
        "calibration_factor": CognitionState.calibration_factor,
        "causal_blame": CognitionState.causal_blame,
        "runtime_profile": CognitionState.runtime_profile,
        "familiarity_label": CognitionState.familiarity_label,
        "interaction_depth_label": CognitionState.interaction_depth_label,
        "proactive_status": CognitionState.proactive_status,
        "cooldown_multiplier": CognitionState.cooldown_multiplier,
        "quarantine_count": CognitionState.quarantine_count,
        "simulated_anomalies_quarantined": CognitionState.simulated_anomalies_quarantined,
        "drift_delta_score": CognitionState.drift_delta_score,
        "emotional_volatility": CognitionState.emotional_volatility,
        "cognitive_version": CognitionState.cognitive_version,
        "runtime_capabilities": CAPABILITIES.snapshot(),
        "capability_health": CAPABILITIES.health_snapshot(),
        "recovery_policies": CAPABILITIES.recovery_policies(),
        "degradation_mode": CAPABILITIES.degradation_mode,
        "capability_context": CAPABILITIES.cognition_context(),
        "presence_state": CognitionState.presence_state,
        "ambient_active_tab": CognitionState.ambient_active_tab,
        "ambient_context_entity": CognitionState.ambient_context_entity,
        "ambient_widget_data": CognitionState.ambient_widget_data,
        "ambient_last_updated": CognitionState.ambient_last_updated,
        "subsystem_health": _SUBSYSTEM_HEALTH.get_all() if _SUBSYSTEM_HEALTH else {},
    }

@app.get("/api/relationship")
def get_relationship():
    """Returns relationship vector and proactive cognition status for dashboard."""
    return {
        "familiarity": CognitionState.familiarity_label,
        "interaction_depth": CognitionState.interaction_depth_label,
        "proactive_status": CognitionState.proactive_status
    }

@app.get("/api/cognitive_governance")
def get_cognitive_governance():
    """Returns cognitive governance telemetry for dashboard."""
    return {
        "simulated_anomalies_quarantined": CognitionState.simulated_anomalies_quarantined,
        "drift_delta_score": CognitionState.drift_delta_score,
        "emotional_volatility": CognitionState.emotional_volatility,
        "cognitive_version": CognitionState.cognitive_version,
        "quarantine_count": CognitionState.quarantine_count,
        "cooldown_multiplier": CognitionState.cooldown_multiplier,
        "runtime_capabilities": CAPABILITIES.snapshot(),
        "capability_health": CAPABILITIES.health_snapshot(),
        "recovery_policies": CAPABILITIES.recovery_policies(),
        "degradation_mode": CAPABILITIES.degradation_mode,
        "capability_context": CAPABILITIES.cognition_context(),
    }

@app.post("/api/mode")
def set_mode(data: ModeUpdate):
    if data.mode.lower() in ["safe", "auto", "dev"]:
        CognitionState.mode = data.mode.lower()
        return {"status": "success", "mode": CognitionState.mode}
    return {"status": "error", "message": "Invalid mode"}

class RegionTriggerUpdate(BaseModel):
    region: str

@app.post("/api/v1/dashboard/trigger-news")
def trigger_news(data: RegionTriggerUpdate):
    region = data.region or "Global"
    import sys
    import threading
    main_mod = sys.modules.get('__main__')
    aria = getattr(main_mod, 'instance', None)
    if aria:
        def search_bg():
            query = f"latest news in {region}"
            print(f"[DashboardAPI] Background news search for: {query}")
            try:
                # 1. Fetch news using ARIA search_and_read
                raw_text = aria.search_and_read(query)
                if not raw_text or raw_text.startswith("Could not fetch"):
                    print(f"[DashboardAPI] Web search returned empty result for {region}")
                    return
                # Limit size to prevent LLM quota/token overflow
                if len(raw_text) > 5000:
                    raw_text = raw_text[:5000] + "\n...[truncated]"
                
                # 2. Build prompt requesting a NEWS_WIDGET
                prompt = (
                    f"The user clicked region: '{region}' on the map.\n\n"
                    f"Here is search data from the web:\n---\n{raw_text}\n---\n\n"
                    f"IMPORTANT: Return ONLY a compact JSON object — no prose, no markdown. Keep all string values SHORT.\n"
                    f"Create a response with both a concise voice summary (1 sentence max) AND a compact JSON widget payload with view_type: NEWS_WIDGET.\n"
                    f"You must return ONLY a valid JSON object (enclosed in ```json ... ```) with this structure:\n"
                    f'{{\n'
                    f'  "voice_summary": "Latest news headlines for {region}.",\n'
                    f'  "widget_payload": {{\n'
                    f'    "view_type": "NEWS_WIDGET",\n'
                    f'    "payload": {{\n'
                    f'      "articles": [\n'
                    f'        {{ "headline": "headline text", "summary": "1 sentence summary", "source": "Source Name", "url": "URL link", "image_url": "", "category": "World", "sentiment": "positive|negative|neutral" }}\n'
                    f'      ]\n'
                    f'    }}\n'
                    f'  }}\n'
                    f'}}\n'
                )
                
                # 3. Call LLM think
                answer = aria.brain.think(prompt, user_name=aria.known_user)
                
                # 4. Parse JSON
                import json
                import re
                clean_ans = answer.strip()
                if "```" in clean_ans:
                    m = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_ans, re.DOTALL | re.IGNORECASE)
                    if m:
                        clean_ans = m.group(1).strip()
                # Strip leading "json\n" etc.
                if clean_ans.lower().startswith("json\n"):
                    clean_ans = clean_ans[5:].strip()
                elif clean_ans.lower().startswith("json "):
                    clean_ans = clean_ans[5:].strip()
                f_b = clean_ans.find("{")
                l_b = clean_ans.rfind("}")
                if f_b != -1 and l_b != -1:
                    clean_ans = clean_ans[f_b:l_b+1]
                
                parsed = json.loads(clean_ans)
                widget_payload = parsed.get("widget_payload", {})
                view_type = widget_payload.get("view_type", "NEWS_WIDGET")
                payload_data = widget_payload.get("payload", {})
                
                from skills.ambient_dashboard_controller import AmbientDashboardController
                controller = AmbientDashboardController()
                controller.push_widget_payload(view_type, payload_data)
                print(f"[DashboardAPI] Background news search success for {region}")
            except Exception as err:
                print(f"[DashboardAPI] Background news search failed: {err}")
                
        threading.Thread(target=search_bg, daemon=True).start()
        return {"status": "success", "message": f"Triggered background search for {region}"}
    return {"status": "error", "message": "ARIA instance not found"}

class TabUpdate(BaseModel):
    tab: str
    entity_id: Optional[str] = ""

class WidgetDataUpdate(BaseModel):
    view_type: str
    refresh_interval_seconds: int = 30
    payload: dict

@app.post("/api/v1/viewport/set-tab")
def set_tab(data: TabUpdate):
    import time
    CognitionState.ambient_active_tab = data.tab
    CognitionState.ambient_context_entity = data.entity_id or ""
    CognitionState.ambient_last_updated = int(time.time())
    return {"status": "success", "tab": CognitionState.ambient_active_tab, "entity_id": CognitionState.ambient_context_entity}

@app.post("/api/v1/viewport/widget-data")
def set_widget_data(data: WidgetDataUpdate):
    import time
    CognitionState.ambient_widget_data = {
        "view_type": data.view_type,
        "refresh_interval_seconds": data.refresh_interval_seconds,
        "payload": data.payload
    }
    # Map view_type to tab
    tab_map = {
        "SPORTS_WIDGET": "SPORTS",
        "NEWS_WIDGET": "NEWS",
        "WEATHER_WIDGET": "WEATHER",
        "STOCK_WIDGET": "STOCKS",
        "SEARCH_WIDGET": "SEARCH",
        "PERSON_WIDGET": "PEOPLE",
        "PRODUCT_WIDGET": "PRODUCTS",
        "VIDEO_WIDGET": "VIDEOS",
        "AMBIENT_WIDGET": "AMBIENT"
    }
    CognitionState.ambient_active_tab = tab_map.get(data.view_type, "AMBIENT")
    # Set entity_id context based on view_type if present in payload
    if data.view_type == "SPORTS_WIDGET":
        CognitionState.ambient_context_entity = f"MATCH_{data.payload.get('match_title', '').replace(' ', '_')}"
    elif data.view_type == "PERSON_WIDGET":
        CognitionState.ambient_context_entity = f"PERSON_{data.payload.get('name', '').replace(' ', '_')}"
    elif data.view_type == "PRODUCT_WIDGET":
        CognitionState.ambient_context_entity = f"PROD_{data.payload.get('name', '').replace(' ', '_')}"
    elif data.view_type == "WEATHER_WIDGET":
        CognitionState.ambient_context_entity = data.payload.get("location", "")
    
    CognitionState.ambient_last_updated = int(time.time())
    return {
        "status": "success", 
        "view_type": data.view_type, 
        "tab": CognitionState.ambient_active_tab, 
        "entity_id": CognitionState.ambient_context_entity
    }

@app.get("/api/v1/viewport/active-state")
def get_viewport_active_state():
    return {
        "ambient_active_tab": CognitionState.ambient_active_tab,
        "ambient_context_entity": CognitionState.ambient_context_entity,
        "ambient_widget_data": CognitionState.ambient_widget_data,
        "ambient_last_updated": CognitionState.ambient_last_updated
    }

@app.get("/api/ambient/data")
def get_ambient_data():
    return get_viewport_active_state()

@app.get("/api/orchestration/campaigns")
def get_campaigns():
    import sqlite3
    db_path = "aria_orchestrator.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM campaigns ORDER BY created_at DESC")
        data = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return data
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/orchestration/campaign/{campaign_id}/tasks")
def get_campaign_tasks(campaign_id: str):
    import sqlite3
    db_path = "aria_orchestrator.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agent_tasks WHERE campaign_id = ? ORDER BY created_at ASC", (campaign_id,))
        tasks = [dict(row) for row in cursor.fetchall()]
        
        for t in tasks:
            cursor.execute("SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ?", (t["id"],))
            t["depends_on"] = [r[0] for r in cursor.fetchall()]
            
            cursor.execute("SELECT result_payload, confidence FROM agent_results WHERE task_id = ?", (t["id"],))
            res_row = cursor.fetchone()
            if res_row:
                t["result"] = res_row[0]
                t["confidence"] = res_row[1]
            else:
                t["result"] = None
                t["confidence"] = None
        conn.close()
        return tasks
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/orchestration/campaign/{campaign_id}/artifacts")
def get_campaign_artifacts(campaign_id: str):
    import sqlite3
    db_path = "aria_orchestrator.db"
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM campaign_artifacts WHERE campaign_id = ? ORDER BY id ASC", (campaign_id,))
        artifacts = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return artifacts
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/orchestration/blackboard")
def get_blackboard(topic: str = None):
    from skills.blackboard import AriaBlackboard
    bb = AriaBlackboard()
    return bb.get_all(topic=topic)

@app.get("/api/profile/insights")
def get_profile_insights():
    """Returns the Continuous Learning Engine profile insights snapshot."""
    return CognitionState.profile_insights

@app.get("/api/health")
def get_subsystem_health():
    """Returns live runtime health states for all ARIA subsystems."""
    if _SUBSYSTEM_HEALTH is None:
        return {"error": "SubsystemHealthMonitor not available"}
    all_states = _SUBSYSTEM_HEALTH.get_all()
    failed = _SUBSYSTEM_HEALTH.get_failed()
    degraded = _SUBSYSTEM_HEALTH.get_degraded()
    return {
        "subsystems": all_states,
        "summary": {
            "all_healthy": _SUBSYSTEM_HEALTH.all_healthy(),
            "failed_count": len(failed),
            "degraded_count": len(degraded),
            "failed": failed,
            "degraded": degraded,
        },
        "degradation_text": _SUBSYSTEM_HEALTH.degradation_summary(),
    }

@app.get("/api/health/{subsystem}")
def get_subsystem_health_single(subsystem: str):
    """Returns live health state for a single named ARIA subsystem."""
    if _SUBSYSTEM_HEALTH is None:
        return {"error": "SubsystemHealthMonitor not available"}
    state = _SUBSYSTEM_HEALTH.get_state(subsystem)
    return state.as_dict()

@app.get("/api/screenshot")
def get_screenshot():
    if not CognitionState.screenshot:
        return Response(status_code=404)
    import base64
    try:
        img_bytes = base64.b64decode(CognitionState.screenshot)
        return Response(content=img_bytes, media_type="image/png")
    except Exception:
        return Response(status_code=500)

from typing import Optional

class OpportunityCreate(BaseModel):
    company: str
    role: str
    location: Optional[str] = None
    apply_link: Optional[str] = None
    deadline: Optional[str] = None
    source_type: Optional[str] = "MANUAL"

class StatusUpdate(BaseModel):
    status: str

class MatchRequest(BaseModel):
    description: str

@app.get("/api/career/opportunities")
def api_get_opportunities():
    from skills.career_agent import CareerAgent
    try:
        return CareerAgent().get_opportunities()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/career/opportunities")
def api_create_opportunity(opp: OpportunityCreate):
    from skills.career_agent import CareerAgent
    try:
        opp_id = CareerAgent().add_opportunity(
            company=opp.company,
            role=opp.role,
            location=opp.location,
            apply_link=opp.apply_link,
            deadline=opp.deadline,
            source_type=opp.source_type
        )
        return {"status": "success", "id": opp_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/career/opportunities/{opp_id}/status")
def api_update_opportunity_status(opp_id: int, status_data: StatusUpdate):
    from skills.career_agent import CareerAgent
    try:
        success = CareerAgent().update_opportunity(opp_id, {"status": status_data.status})
        return {"status": "success" if success else "error"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/career/stats")
def api_get_career_stats():
    from skills.career_agent import CareerAgent
    try:
        agent = CareerAgent()
        github_user = "chinmaya"
        codeforces_user = "chinmaya"
        with agent._get_connection() as conn:
            row = conn.execute("SELECT value FROM user_preferences WHERE key = 'github_username'").fetchone()
            if row: github_user = row['value']
            row = conn.execute("SELECT value FROM user_preferences WHERE key = 'codeforces_username'").fetchone()
            if row: codeforces_user = row['value']
        
        cf = agent.get_codeforces_stats(codeforces_user)
        gh = agent.get_github_stats(github_user)
        
        return {
            "codeforces": cf,
            "github": gh
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/career/match")
def api_match_resume(req: MatchRequest):
    from skills.career_agent import CareerAgent
    try:
        return CareerAgent().match_resume_to_job(req.description)
    except Exception as e:
        return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    p_cc = os.path.join(public_path, "control_center.html")
    if os.path.exists(p_cc):
        return FileResponse(p_cc)
    return HTMLResponse("<h2>No control center template found on server</h2>", status_code=404)
