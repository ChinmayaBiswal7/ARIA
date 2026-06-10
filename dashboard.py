import os
import psutil
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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
    return serve_dashboard()

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
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ARIA Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Space+Mono&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Outfit', 'sans-serif'],
                        mono: ['Space Mono', 'monospace'],
                    }
                }
            }
        }
    </script>
    <style>
        body {
            background-color: #050508;
            font-family: 'Outfit', sans-serif;
        }
        .glass {
            background: rgba(13, 13, 23, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        .glow-blue {
            box-shadow: 0 0 25px rgba(59, 130, 246, 0.2);
        }
        .glow-purple {
            box-shadow: 0 0 25px rgba(168, 85, 247, 0.2);
        }
        .status-pulse {
            animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; filter: brightness(1.2); }
            50% { opacity: .5; filter: brightness(0.8); }
        }
    </style>
</head>
<body class="text-gray-100 min-h-screen flex flex-col">

    <!-- Header -->
    <header class="glass glow-blue border-b border-blue-500/20 px-8 py-4 flex justify-between items-center z-10">
        <div class="flex items-center gap-3">
            <div class="w-3 h-3 rounded-full bg-cyan-400 status-pulse shadow-[0_0_10px_#22d3ee]"></div>
            <h1 class="text-2xl font-extrabold tracking-wider bg-gradient-to-r from-cyan-400 via-blue-500 to-purple-600 bg-clip-text text-transparent">
                ARIA CONTROL CENTER
            </h1>
        </div>
        <div class="flex items-center gap-4">
            <span class="text-xs text-gray-400 font-mono">MODE SELECTOR:</span>
            <div class="flex rounded-lg overflow-hidden border border-white/10 p-0.5 bg-black/40">
                <button onclick="setMode('safe')" id="btn-safe" class="px-3 py-1 text-xs font-semibold rounded-md transition-all">SAFE</button>
                <button onclick="setMode('auto')" id="btn-auto" class="px-3 py-1 text-xs font-semibold rounded-md transition-all">AUTO</button>
                <button onclick="setMode('dev')" id="btn-dev" class="px-3 py-1 text-xs font-semibold rounded-md transition-all">DEV</button>
            </div>
            <div class="px-3 py-1 rounded bg-blue-500/10 border border-blue-500/20 text-xs text-blue-400 font-mono" id="model-badge">
                OLLAMA / QWEN2.5
            </div>
            <div class="px-3 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400 font-mono" id="profile-badge">
                EXECUTIVE: AUTONOMOUS
            </div>
        </div>
    </header>

    <!-- Main Grid -->
    <main class="flex-grow p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-[1800px] mx-auto w-full">
        
        <!-- Left Column: Visuals & Systems -->
        <section class="lg:col-span-4 flex flex-col gap-6">
            <!-- Screen Grounding Capture -->
            <div class="glass p-5 rounded-2xl glow-blue flex flex-col gap-3">
                <div class="flex justify-between items-center">
                    <h2 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Live Grounding Screen</h2>
                    <span class="text-xs text-gray-500 font-mono" id="active-win-lbl">Desktop</span>
                </div>
                <div class="w-full aspect-[16/10] bg-black/40 rounded-lg overflow-hidden border border-white/5 relative flex items-center justify-center">
                    <img id="screenshot-img" src="" alt="Live Desktop View" class="w-full h-full object-contain hidden" />
                    <div id="no-screenshot-lbl" class="text-xs text-gray-500 font-mono flex flex-col items-center gap-2">
                        <svg class="animate-pulse w-8 h-8 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                        </svg>
                        Awaiting vision frame...
                    </div>
                </div>
            </div>

            <!-- Failure Analytics -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-red-400 uppercase font-mono">Failure Analytics</h2>
                <div id="failure-analytics-list" class="flex flex-col gap-2 text-xs font-mono">
                    <div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No stability events recorded.</div>
                </div>
            </div>

            <!-- Recent Diagnostics (Blackboard) -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-rose-500 uppercase font-mono">Recent Diagnostics</h2>
                <div id="recent-diagnostics-list" class="flex flex-col gap-2 text-xs font-mono overflow-y-auto max-h-[220px] pr-1">
                    <div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No active system failures.</div>
                </div>
            </div>

            <!-- Recent Root Causes (Blackboard) -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-fuchsia-500 uppercase font-mono">Recent Root Causes</h2>
                <div id="recent-rootcauses-list" class="flex flex-col gap-2 text-xs font-mono overflow-y-auto max-h-[220px] pr-1">
                    <div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No root causes diagnosed.</div>
                </div>
            </div>

            <!-- Recent Patch Plans (Blackboard) -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Recent Patch Plans</h2>
                <div id="recent-patchplans-list" class="flex flex-col gap-2 text-xs font-mono overflow-y-auto max-h-[220px] pr-1">
                    <div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No patch plans proposed.</div>
                </div>
            </div>

            <!-- Recent Patches (Blackboard) -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-violet-400 uppercase font-mono">Recent Patches</h2>
                <div id="recent-patches-list" class="flex flex-col gap-2 text-xs font-mono overflow-y-auto max-h-[220px] pr-1">
                    <div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No patches generated.</div>
                </div>
            </div>

            <!-- World State & Health Modeling -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-4">
                <h2 class="text-sm font-semibold tracking-wider text-emerald-400 uppercase font-mono">World State & Tool Health</h2>
                <div class="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div class="p-2 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">ACTIVE PROJECT</span>
                        <div id="ws-project" class="text-emerald-400 font-semibold truncate">ARIA</div>
                    </div>
                    <div class="p-2 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">BROWSER TABS</span>
                        <div id="ws-tabs" class="text-emerald-400 font-semibold truncate">Dashboard</div>
                    </div>
                    <div class="p-2 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">WORKFLOW</span>
                        <div id="ws-workflow" class="text-emerald-400 font-semibold truncate">Idle</div>
                    </div>
                    <div class="p-2 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">AGENT STATUS</span>
                        <div id="ws-status" class="text-emerald-400 font-semibold truncate">Idle</div>
                    </div>
                </div>
                
                <div class="border-t border-white/5 pt-3 flex flex-col gap-2 text-xs font-mono">
                    <div class="flex justify-between">
                        <span class="text-gray-400">Success Rate:</span>
                        <span id="health-success" class="text-emerald-400 font-bold">100%</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Memory Latency:</span>
                        <span id="health-mem-lat" class="text-cyan-400">0.01s</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Vision Latency:</span>
                        <span id="health-vis-lat" class="text-purple-400">0.00s</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Stuck Rate:</span>
                        <span id="health-stuck" class="text-amber-400">0%</span>
                    </div>
                </div>
            </div>

            <!-- Passive Notification Intelligence Triage -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-amber-400 uppercase font-mono">Attention & Triage Box</h2>
                <div id="triage-notifications-list" class="flex flex-col gap-2 overflow-y-auto max-h-[150px] text-[10px] font-mono text-gray-400 pr-1">
                    <div class="italic text-gray-500 text-center">Triage box empty. Silent notifications are batched here during tasks.</div>
                </div>
            </div>

            <!-- Event Bus Cognition Stream -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Cognition Event Stream</h2>
                <div id="event-ticker-list" class="flex flex-col gap-2 overflow-y-auto max-h-[180px] text-[10px] font-mono text-gray-400 pr-1">
                    <div class="italic text-gray-500">Awaiting bus events...</div>
                </div>
            </div>

            <!-- Stats -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-4">
                <h2 class="text-sm font-semibold tracking-wider text-purple-400 uppercase font-mono">System Telemetry</h2>
                <div class="flex flex-col gap-3">
                    <div>
                        <div class="flex justify-between text-xs font-mono text-gray-400 mb-1">
                            <span>COGNITIVE LOAD</span>
                            <span id="load-val" class="text-emerald-400 font-bold">NORMAL (0.10)</span>
                        </div>
                        <div class="w-full bg-white/5 h-2 rounded-full overflow-hidden">
                            <div id="load-bar" class="bg-gradient-to-r from-emerald-500 via-yellow-400 to-red-500 h-full transition-all duration-500" style="width: 10%"></div>
                        </div>
                    </div>
                    <div>
                        <div class="flex justify-between text-xs font-mono text-gray-400 mb-1">
                            <span>CPU USAGE</span>
                            <span id="cpu-val">0%</span>
                        </div>
                        <div class="w-full bg-white/5 h-2 rounded-full overflow-hidden">
                            <div id="cpu-bar" class="bg-gradient-to-r from-blue-500 to-cyan-400 h-full transition-all duration-500" style="width: 0%"></div>
                        </div>
                    </div>
                    <div>
                        <div class="flex justify-between text-xs font-mono text-gray-400 mb-1">
                            <span>RAM ALLOCATION</span>
                            <span id="ram-val">0%</span>
                        </div>
                        <div class="w-full bg-white/5 h-2 rounded-full overflow-hidden">
                            <div id="ram-bar" class="bg-gradient-to-r from-purple-500 to-pink-500 h-full transition-all duration-500" style="width: 0%"></div>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Middle Column: Cognition Monitor -->
        <section class="lg:col-span-5 flex flex-col gap-6">
            <!-- Active Goal -->
            <div class="glass p-6 rounded-2xl glow-purple flex flex-col gap-4">
                <div>
                    <span class="text-[10px] font-bold tracking-widest text-purple-400 uppercase font-mono">Current Goal</span>
                    <h2 class="text-xl font-bold tracking-tight text-white mt-1" id="goal-lbl">No active goal</h2>
                </div>
                
                <div class="border-t border-white/5 pt-4">
                    <span class="text-[10px] font-bold tracking-widest text-cyan-400 uppercase font-mono">Active Subtask / State</span>
                    <p class="text-sm font-semibold text-gray-300 mt-1 font-mono" id="subtask-lbl">Idle</p>
                </div>

                <div class="border-t border-white/5 pt-4">
                    <span class="text-[10px] font-bold tracking-widest text-amber-400 uppercase font-mono">Anticipatory Runtime Forecast</span>
                    <p class="text-xs text-gray-400 mt-1 font-mono" id="forecast-lbl">No forecasts available (awaiting query...)</p>
                </div>

                <div class="border-t border-white/5 pt-4">
                    <span class="text-[10px] font-bold tracking-widest text-emerald-400 uppercase font-mono">Deliberative Sandbox Simulation</span>
                    <p class="text-xs text-gray-400 mt-1 font-mono" id="sandbox-lbl">No simulations active (idle...)</p>
                </div>

                <div class="flex gap-4 border-t border-white/5 pt-4">
                    <div>
                        <span class="text-[10px] font-bold tracking-widest text-gray-500 uppercase font-mono">Confidence</span>
                        <div class="text-lg font-bold text-white font-mono" id="conf-lbl">1.00</div>
                    </div>
                    <div class="flex-grow">
                        <span class="text-[10px] font-bold tracking-widest text-gray-500 uppercase font-mono">Self-Reflection Result</span>
                        <p class="text-xs text-gray-400 mt-1 italic" id="reflection-lbl">No reflection logged.</p>
                    </div>
                </div>

                <div class="border-t border-white/5 pt-4">
                    <span class="text-[10px] font-bold tracking-widest text-red-400 uppercase font-mono">Causal Blame Diagnosis</span>
                    <p class="text-xs text-gray-400 mt-1 font-mono text-gray-500" id="causal-lbl">No failures logged (system healthy)</p>
                </div>
            </div>

            <!-- Memory Hits -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3 max-h-[200px] overflow-hidden">
                <h2 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Cognitive Memory Hits</h2>
                <div id="memory-list" class="flex flex-col gap-2 overflow-y-auto max-h-[130px] pr-2 text-xs font-mono text-gray-400">
                    <div class="p-3 rounded bg-white/5 border border-white/5 italic text-gray-500">No active memory references queried in this step.</div>
                </div>
            </div>

            <!-- Career & Coding Tracker -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-4">
                <div class="flex justify-between items-center border-b border-white/5 pb-2">
                    <h2 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Career & DSA Tracker</h2>
                    <div class="flex gap-2">
                        <button onclick="openMatchModal()" class="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 text-[10px] border border-purple-500/30 hover:bg-purple-500/30 transition-all font-mono">MATCH RESUME</button>
                        <button onclick="openAddJobModal()" class="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 text-[10px] border border-cyan-500/30 hover:bg-cyan-500/30 transition-all font-mono">+ ADD JOB</button>
                    </div>
                </div>

                <!-- Stats Widgets -->
                <div class="grid grid-cols-2 gap-2 text-[10px] font-mono text-gray-400">
                    <div class="p-2 rounded bg-white/5 border border-white/5 flex flex-col gap-1">
                        <span class="text-gray-500 text-[8px]">GITHUB STREAK</span>
                        <div id="gh-streak" class="text-emerald-400 font-bold text-xs truncate">Loading...</div>
                        <div id="gh-weekly" class="text-[8px] text-gray-500 truncate">commits last 7d</div>
                    </div>
                    <div class="p-2 rounded bg-white/5 border border-white/5 flex flex-col gap-1">
                        <span class="text-gray-500 text-[8px]">CODEFORCES</span>
                        <div id="cf-rating" class="text-purple-400 font-bold text-xs truncate">Loading...</div>
                        <div id="cf-rank" class="text-[8px] text-gray-500 truncate font-mono">rank info</div>
                    </div>
                </div>

                <!-- Opportunities List -->
                <div class="overflow-x-auto max-h-[180px]">
                    <table class="w-full text-[11px] font-mono text-left">
                        <thead>
                            <tr class="text-gray-500 border-b border-white/5">
                                <th class="pb-1.5 font-semibold">Company</th>
                                <th class="pb-1.5 font-semibold">Role</th>
                                <th class="pb-1.5 font-semibold">Status</th>
                                <th class="pb-1.5 font-semibold">Score</th>
                                <th class="pb-1.5 font-semibold text-right">Action</th>
                            </tr>
                        </thead>
                        <tbody id="career-opportunities-list">
                            <tr>
                                <td colspan="5" class="py-3 text-center text-gray-500 italic">No job tracking entries.</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Right Column: Action Replay Timeline + Cognitive Companion Panels -->
        <section class="lg:col-span-3 flex flex-col gap-6">

            <!-- Relationship Vector Panel -->
            <div class="glass p-5 rounded-2xl glow-purple flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-pink-400 uppercase font-mono">Relationship Vector</h2>
                <div class="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div class="p-2.5 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">FAMILIARITY</span>
                        <div id="rel-familiarity" class="text-pink-400 font-semibold">Acquaintance</div>
                    </div>
                    <div class="p-2.5 rounded bg-white/5 border border-white/5">
                        <span class="text-gray-500 text-[10px]">INTERACTION DEPTH</span>
                        <div id="rel-depth" class="text-purple-400 font-semibold">Surface-level</div>
                    </div>
                </div>
                <div class="flex justify-between items-center text-xs font-mono border-t border-white/5 pt-2">
                    <span class="text-gray-400">Quarantine Count:</span>
                    <span id="quarantine-count" class="text-pink-400 font-bold">0</span>
                </div>
            </div>

            <!-- Cognitive Governance Panel -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-amber-400 uppercase font-mono">Cognitive Governance</h2>
                <div class="flex flex-col gap-2 text-xs font-mono">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Sim Quarantine:</span>
                        <span id="gov-sim-quarantine" class="text-amber-300 font-bold">0</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Drift Delta:</span>
                        <span id="gov-drift-delta" class="text-cyan-300 font-bold">0.0000</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Volatility:</span>
                        <span id="gov-volatility" class="text-emerald-300 font-semibold">Stable</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Versions:</span>
                        <span id="gov-version" class="text-gray-300 truncate max-w-[170px]">personality_v0 / profile_v0</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Runtime:</span>
                        <span id="gov-runtime" class="text-blue-300 font-semibold">SAFE_MODE</span>
                    </div>
                    <div class="text-[10px] text-gray-500 leading-snug" id="gov-capability-health">
                        Capability health pending...
                    </div>
                </div>
            </div>

            <!-- Proactive Cognition Status Panel -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-3">
                <h2 class="text-sm font-semibold tracking-wider text-teal-400 uppercase font-mono">Proactive Cognition</h2>
                <div class="flex flex-col gap-2 text-xs font-mono">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Cooldown:</span>
                        <span id="proactive-cooldown" class="text-teal-400 font-bold">Ready</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Backoff Multiplier:</span>
                        <span id="proactive-multiplier" class="text-teal-300 font-semibold">1.0x</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Last Suggestion:</span>
                        <span id="proactive-last" class="text-gray-300 truncate max-w-[180px]" title="">None</span>
                    </div>
                </div>
            </div>

            <!-- Action Replay Timeline -->
            <div class="glass p-5 rounded-2xl flex flex-col gap-4 min-h-[400px]">
                <h2 class="text-sm font-semibold tracking-wider text-purple-400 uppercase font-mono">Action Replay Timeline</h2>
                <div id="timeline-container" class="flex-grow overflow-y-auto flex flex-col gap-4 pr-2 max-h-[600px] text-xs font-mono">
                    <div class="flex gap-3 text-gray-500 italic p-4 text-center justify-center">
                        Timeline empty. Run tasks to populate events.
                    </div>
                </div>
            </div>
        </section>

    </main>

    <!-- Footer -->
    <footer class="mt-auto py-4 px-8 border-t border-white/5 flex justify-between text-xs text-gray-500 font-mono">
        <span>ARIA Local-First Cognitive Desktop Environment</span>
        <span>Observability Layer v1.0.0</span>
    </footer>

    <script>
        async function fetchState() {
            try {
                const res = await fetch("/api/state");
                const state = await res.json();
                
                // Update UI Texts
                document.getElementById("goal-lbl").innerText = state.active_goal || "No active goal";
                document.getElementById("subtask-lbl").innerText = state.active_subtask || "Idle";
                document.getElementById("conf-lbl").innerText = Number(state.confidence).toFixed(2);
                document.getElementById("model-badge").innerText = state.model_in_use.toUpperCase();
                document.getElementById("active-win-lbl").innerText = state.active_window || "Desktop";
                document.getElementById("reflection-lbl").innerText = state.reflection_results || "No reflection logged.";
                
                // Update World State UI
                if (state.world_state) {
                    document.getElementById("ws-project").innerText = state.world_state.active_project || "None";
                    document.getElementById("ws-tabs").innerText = state.world_state.browser_tabs || "None";
                    document.getElementById("ws-workflow").innerText = state.world_state.current_workflow || "None";
                    document.getElementById("ws-status").innerText = state.world_state.agent_status || "None";
                }
                if (state.tool_health) {
                    document.getElementById("health-success").innerText = state.tool_health.success_rate || "100%";
                    document.getElementById("health-mem-lat").innerText = state.tool_health.memory_latency || "0.01s";
                    document.getElementById("health-vis-lat").innerText = state.tool_health.vision_latency || "0.00s";
                    document.getElementById("health-stuck").innerText = state.tool_health.stuck_rate || "0%";
                }

                // Update Cognitive Load UI
                if (state.cognitive_load_status) {
                    const lVal = document.getElementById("load-val");
                    const scorePct = Math.min(state.cognitive_load_score * 100, 100);
                    lVal.innerText = `${state.cognitive_load_status} (${Number(state.cognitive_load_score).toFixed(2)})`;
                    
                    // Style color dynamically
                    if (state.cognitive_load_status === "OVERLOADED") {
                        lVal.className = "text-red-400 font-bold";
                    } else if (state.cognitive_load_status === "STRESSED") {
                        lVal.className = "text-yellow-400 font-bold";
                    } else {
                        lVal.className = "text-emerald-400 font-bold";
                    }
                    document.getElementById("load-bar").style.width = scorePct + "%";
                }

                // Update CPU / RAM Bars
                document.getElementById("cpu-val").innerText = state.cpu_usage + "%";
                document.getElementById("cpu-bar").style.width = state.cpu_usage + "%";
                document.getElementById("ram-val").innerText = state.ram_usage + "%";
                document.getElementById("ram-bar").style.width = state.ram_usage + "%";
                
                // Update Mode Buttons active styles
                updateModeButtons(state.mode);
                
                // Update Memory Hits List
                const memList = document.getElementById("memory-list");
                if (state.memory_hits && state.memory_hits.length > 0) {
                    memList.innerHTML = state.memory_hits.map(hit => `
                        <div class="p-2.5 rounded bg-black/40 border border-white/5 text-gray-300">
                            ${hit}
                        </div>
                    `).join("");
                } else {
                    memList.innerHTML = `<div class="p-3 rounded bg-white/5 border border-white/5 italic text-gray-500">No active memory references queried in this step.</div>`;
                }

                // Update Failure Analytics List
                try {
                    const failRes = await fetch("/api/failures");
                    const fails = await failRes.json();
                    const failList = document.getElementById("failure-analytics-list");
                    if (fails && fails.length > 0) {
                        failList.innerHTML = fails.map(f => `
                            <div class="flex justify-between items-center p-2 rounded bg-red-500/5 border border-red-500/10 text-red-400">
                                <span>${f.type}</span>
                                <span class="px-2 py-0.5 rounded bg-red-500/20 text-[10px] font-bold">${f.count}</span>
                            </div>
                        `).join("");
                    } else {
                        failList.innerHTML = `<div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No stability events recorded.</div>`;
                    }
                } catch(e) {
                    console.error("Failures fetch error:", e);
                }

                // Update Recent Diagnostics List (Blackboard)
                try {
                    const diagRes = await fetch("/api/orchestration/blackboard?topic=system");
                    const diags = await diagRes.json();
                    const diagList = document.getElementById("recent-diagnostics-list");
                    
                    let items = [];
                    if (diags && diags.system) {
                        // Gather keys starting with failure_
                        items = Object.keys(diags.system)
                            .filter(k => k.startsWith("failure_"))
                            .map(k => diags.system[k].value);
                    }
                    
                    // Sort items by timestamp descending
                    items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
                    
                    if (items.length > 0) {
                        diagList.innerHTML = items.map(item => {
                            let sevColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
                            if (item.severity === "HIGH") {
                                sevColor = "text-red-400 bg-red-500/10 border-red-500/20";
                            } else if (item.severity === "MEDIUM") {
                                sevColor = "text-amber-400 bg-amber-500/10 border-amber-500/20";
                            }
                            
                            const filename = item.failed_file ? item.failed_file.split(/[\\/]/).pop() : "unknown.py";
                            const dateStr = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString() : "";
                            
                            return `
                                <div class="p-2.5 rounded bg-black/40 border border-white/5 flex flex-col gap-1.5">
                                    <div class="flex justify-between items-center">
                                        <span class="font-bold text-gray-200 truncate max-w-[150px]" title="${item.failed_file}">${filename}</span>
                                        <span class="px-1.5 py-0.5 rounded border text-[9px] font-bold ${sevColor}">${item.severity}</span>
                                    </div>
                                    <div class="text-[10px] text-gray-400 flex flex-col gap-0.5">
                                        <div><span class="text-gray-500">Error:</span> <span class="text-rose-300 font-semibold">${item.error_type}</span></div>
                                        <div><span class="text-gray-500">Line:</span> ${item.failed_line} | <span class="text-gray-500">Func:</span> ${item.failed_function}</div>
                                        <div class="truncate text-gray-500" title="${item.error_message}">${item.error_message}</div>
                                        <div class="text-[9px] text-gray-600 flex justify-between mt-1 border-t border-white/5 pt-1">
                                            <span>${item.campaign_id}</span>
                                            <span>${dateStr}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join("");
                    } else {
                        diagList.innerHTML = `<div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No active system failures.</div>`;
                    }
                } catch(e) {
                    console.error("Diagnostics fetch error:", e);
                }

                // Update Recent Root Causes List (Blackboard)
                try {
                    const diagRes = await fetch("/api/orchestration/blackboard?topic=system");
                    const diags = await diagRes.json();
                    const rcList = document.getElementById("recent-rootcauses-list");
                    
                    let items = [];
                    if (diags && diags.system) {
                        // Gather keys starting with rootcause_
                        items = Object.keys(diags.system)
                            .filter(k => k.startsWith("rootcause_"))
                            .map(k => diags.system[k].value);
                    }
                    
                    // Sort items by timestamp descending
                    items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
                    
                    if (items.length > 0) {
                        rcList.innerHTML = items.map(item => {
                            let sevColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
                            const confPct = Math.round(item.confidence * 100);
                            if (confPct >= 85) {
                                sevColor = "text-red-400 bg-red-500/10 border-red-500/20";
                            } else if (confPct >= 65) {
                                sevColor = "text-amber-400 bg-amber-500/10 border-amber-500/20";
                            }
                            
                            const filename = item.failed_file ? item.failed_file.split(/[\\/]/).pop() : "unknown.py";
                            const dateStr = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString() : "";
                            const evidenceList = (item.evidence || []).map(e => `<li class="list-disc ml-3.5 mt-0.5 leading-snug">• ${e}</li>`).join("");
                            
                            return `
                                <div class="p-2.5 rounded bg-black/40 border border-white/5 flex flex-col gap-1.5">
                                    <div class="flex justify-between items-center">
                                        <span class="font-bold text-gray-200 truncate max-w-[150px]" title="${item.failed_file}">${filename}</span>
                                        <span class="px-1.5 py-0.5 rounded border text-[9px] font-bold ${sevColor}">Conf: ${confPct}%</span>
                                    </div>
                                    <div class="text-[10px] text-gray-400 flex flex-col gap-1">
                                        <div><span class="text-gray-500">Category:</span> <span class="text-fuchsia-300 font-semibold font-mono">${item.fix_category}</span></div>
                                        <div class="text-gray-300"><span class="text-gray-500">Cause:</span> ${item.root_cause}</div>
                                        <div class="text-emerald-350 bg-emerald-950/20 border border-emerald-800/10 p-1.5 rounded mt-1 font-sans text-[9px] leading-snug">
                                            <span class="font-bold uppercase tracking-wider text-emerald-400">Strategy:</span> ${item.recommended_strategy}
                                        </div>
                                        ${evidenceList ? `
                                        <div class="mt-1 border-t border-white/5 pt-1 text-[9px] text-gray-500">
                                            <span class="font-semibold text-gray-400">Evidence:</span>
                                            <ul class="flex flex-col gap-0.5 mt-0.5 pl-1 leading-snug">
                                                ${evidenceList}
                                            </ul>
                                        </div>
                                        ` : ''}
                                        <div class="text-[9px] text-gray-600 flex justify-between mt-1 border-t border-white/5 pt-1">
                                            <span>${item.campaign_id}</span>
                                            <span>${dateStr}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join("");
                    } else {
                        rcList.innerHTML = `<div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No root causes diagnosed.</div>`;
                    }
                } catch(e) {
                    console.error("Root causes fetch error:", e);
                }

                // Update Recent Patch Plans List (Blackboard)
                try {
                    const diagRes = await fetch("/api/orchestration/blackboard?topic=system");
                    const diags = await diagRes.json();
                    const planList = document.getElementById("recent-patchplans-list");
                    
                    let items = [];
                    if (diags && diags.system) {
                        items = Object.keys(diags.system)
                            .filter(k => k.startsWith("patchplan_"))
                            .map(k => diags.system[k].value);
                    }
                    
                    items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
                    
                    if (items.length > 0) {
                        planList.innerHTML = items.map(item => {
                            const filename = item.failed_file ? item.failed_file.split(/[\\/]/).pop() : "unknown.py";
                            const dateStr = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString() : "";
                            let typeColor = "text-cyan-400 bg-cyan-500/10 border-cyan-500/20";
                            if (item.edit_type === "INSERT") {
                                typeColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
                            } else if (item.edit_type === "DELETE") {
                                typeColor = "text-rose-400 bg-rose-500/10 border-rose-500/20";
                            }
                            
                            return `
                                <div class="p-2.5 rounded bg-black/40 border border-white/5 flex flex-col gap-1.5">
                                    <div class="flex justify-between items-center">
                                        <span class="font-bold text-gray-200 truncate max-w-[150px]" title="${item.failed_file}">${filename}</span>
                                        <span class="px-1.5 py-0.5 rounded border text-[9px] font-bold ${typeColor}">${item.edit_type}</span>
                                    </div>
                                    <div class="text-[10px] text-gray-400 flex flex-col gap-1">
                                        <div>
                                            <span class="text-gray-500">Scope:</span> <span class="text-amber-400 font-mono font-bold">${item.estimated_scope || "LINE"}</span>
                                            | <span class="text-gray-500">Target Func:</span> <span class="text-cyan-300 font-mono">${item.target_function}</span>
                                        </div>
                                        <div><span class="text-gray-500">Location:</span> <span class="text-gray-350">${item.target_location}</span></div>
                                        <div class="text-gray-300"><span class="text-gray-500">Goal:</span> ${item.goal}</div>
                                        <div class="text-[9px] text-gray-600 flex justify-between mt-1 border-t border-white/5 pt-1">
                                            <span>${item.campaign_id}</span>
                                            <span>${dateStr}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join("");
                    } else {
                        planList.innerHTML = `<div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No patch plans proposed.</div>`;
                    }
                } catch(e) {
                    console.error("Patch plans fetch error:", e);
                }

                // Update Recent Patches List (Blackboard)
                try {
                    const diagRes = await fetch("/api/orchestration/blackboard?topic=system");
                    const diags = await diagRes.json();
                    const patchList = document.getElementById("recent-patches-list");
                    
                    let items = [];
                    if (diags && diags.system) {
                        items = Object.keys(diags.system)
                            .filter(k => k.startsWith("patch_"))
                            .map(k => diags.system[k].value);
                    }
                    
                    items.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
                    
                    if (items.length > 0) {
                        patchList.innerHTML = items.map(item => {
                            const filename = item.target_file ? item.target_file.split(/[\\/]/).pop() : "unknown.py";
                            const dateStr = item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString() : "";
                            
                            let riskColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
                            if (item.risk_level === "CRITICAL") {
                                riskColor = "text-red-500 bg-red-600/10 border-red-650/20 font-extrabold animate-pulse";
                            } else if (item.risk_level === "HIGH") {
                                riskColor = "text-red-400 bg-red-500/10 border-red-500/20";
                            } else if (item.risk_level === "MEDIUM") {
                                riskColor = "text-amber-400 bg-amber-500/10 border-amber-500/20";
                            }
                            
                            const confPct = Math.round(item.confidence * 100);
                            const rcConf = item.confidence_source ? Math.round(item.confidence_source.root_cause * 100) : 0;
                            const staticConf = item.confidence_source ? Math.round(item.confidence_source.static_checks * 100) : 0;
                            const llmConf = item.confidence_source ? Math.round(item.confidence_source.llm_patch * 100) : 0;
                            
                            const linesStr = (item.affected_lines || []).join(", ");
                            
                            // Escape HTML in code snippets to avoid rendering issues
                            const escapeHtml = (str) => (str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                            const origEscaped = escapeHtml(item.original_snippet);
                            const propEscaped = escapeHtml(item.proposed_snippet);
                            
                            return `
                                <div class="p-2.5 rounded bg-black/40 border border-white/5 flex flex-col gap-1.5">
                                    <div class="flex justify-between items-center">
                                        <span class="font-bold text-gray-200 truncate max-w-[140px]" title="${item.target_file}">${filename}</span>
                                        <span class="px-1.5 py-0.5 rounded border text-[9px] font-bold ${riskColor}">${item.risk_level} RISK</span>
                                    </div>
                                    <div class="text-[10px] text-gray-400 flex flex-col gap-1">
                                        <div>
                                            <span class="text-gray-500">Type:</span> <span class="text-violet-350 font-semibold font-mono">${item.patch_type}</span>
                                            ${linesStr ? ` | <span class="text-gray-500">Lines:</span> <span class="text-gray-300 font-mono">${linesStr}</span>` : ''}
                                        </div>
                                        <div class="text-gray-300"><span class="text-gray-500">Rationale:</span> ${item.rationale || "None"}</div>
                                        
                                        <!-- Confidence breakdown -->
                                        <div class="bg-white/5 p-1.5 rounded mt-1 border border-white/5 flex flex-col gap-1 text-[9px]">
                                            <div class="flex justify-between text-gray-300 font-bold border-b border-white/5 pb-0.5">
                                                <span>Combined Confidence:</span>
                                                <span class="text-violet-400">${confPct}%</span>
                                            </div>
                                            <div class="grid grid-cols-3 gap-1 text-center text-gray-500 text-[8px] font-mono">
                                                <div>
                                                    <div class="text-gray-400 font-bold">${rcConf}%</div>
                                                    <div>Root Cause</div>
                                                </div>
                                                <div>
                                                    <div class="text-gray-400 font-bold">${staticConf}%</div>
                                                    <div>Static</div>
                                                </div>
                                                <div>
                                                    <div class="text-gray-400 font-bold">${llmConf}%</div>
                                                    <div>LLM Patch</div>
                                                </div>
                                            </div>
                                        </div>
                                        
                                        <!-- Diff Snippets Preview -->
                                        <div class="mt-1 flex flex-col gap-1 text-[9px] font-mono">
                                            ${origEscaped ? `
                                            <div class="bg-red-950/20 border border-red-900/10 p-1.5 rounded text-red-300 overflow-x-auto max-h-[60px]">
                                                <div class="text-[8px] text-red-500 font-bold border-b border-red-900/20 pb-0.5 mb-0.5">- ORIGINAL</div>
                                                <pre class="leading-tight">${origEscaped}</pre>
                                            </div>` : ''}
                                            ${propEscaped ? `
                                            <div class="bg-emerald-950/20 border border-emerald-900/10 p-1.5 rounded text-emerald-300 overflow-x-auto max-h-[80px]">
                                                <div class="text-[8px] text-emerald-500 font-bold border-b border-emerald-900/20 pb-0.5 mb-0.5">+ PROPOSED</div>
                                                <pre class="leading-tight">${propEscaped}</pre>
                                            </div>` : ''}
                                        </div>

                                        <div class="text-[9px] text-gray-600 flex justify-between mt-1 border-t border-white/5 pt-1">
                                            <span>${item.campaign_id}</span>
                                            <span>${dateStr}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join("");
                    } else {
                        patchList.innerHTML = `<div class="p-2 rounded bg-white/5 border border-white/5 italic text-gray-500">No patches generated.</div>`;
                    }
                } catch(e) {
                    console.error("Patches fetch error:", e);
                }

                // Update Attention Triage Ticker
                if (state.pending_notifications) {
                    const triList = document.getElementById("triage-notifications-list");
                    if (state.pending_notifications.length > 0) {
                        triList.innerHTML = state.pending_notifications.map(n => `
                            <div class="p-1.5 rounded bg-amber-500/5 border border-amber-500/10 flex justify-between items-center text-amber-300">
                                <span class="truncate">[${n.type.toUpperCase()}] ${JSON.stringify(n.data)}</span>
                                <span class="text-[8px] text-gray-500 flex-shrink-0">${n.time}</span>
                            </div>
                        `).reverse().join("");
                    } else {
                        triList.innerHTML = `<div class="italic text-gray-500 text-center">Triage box empty. Silent notifications are batched here during tasks.</div>`;
                    }
                }

                // Update Event Bus ticker
                try {
                    const eventRes = await fetch("/api/events");
                    const evs = await eventRes.json();
                    const evList = document.getElementById("event-ticker-list");
                    if (evs && evs.length > 0) {
                        evList.innerHTML = evs.map(ev => {
                            let badgeColor = "bg-blue-500/20 text-blue-400";
                            if (ev.type.includes("FAILED")) badgeColor = "bg-red-500/20 text-red-400";
                            if (ev.type.includes("COMPLETED")) badgeColor = "bg-emerald-500/20 text-emerald-400";
                            if (ev.type.includes("EXECUTED")) badgeColor = "bg-purple-500/20 text-purple-400";
                            if (ev.type.includes("VERIFIED")) badgeColor = "bg-cyan-500/20 text-cyan-400";
                            
                            return `
                                <div class="p-1.5 rounded bg-white/5 border border-white/5 flex gap-2 items-center justify-between">
                                    <div class="flex items-center gap-1.5 truncate">
                                        <span class="px-1 py-0.5 rounded text-[8px] font-bold ${badgeColor}">${ev.type}</span>
                                        <span class="text-gray-300 truncate">${JSON.stringify(ev.data)}</span>
                                    </div>
                                    <span class="text-gray-600 text-[8px] flex-shrink-0">${ev.time}</span>
                                </div>
                            `;
                        }).reverse().join("");
                    } else {
                        evList.innerHTML = `<div class="italic text-gray-500 text-center">Awaiting bus events...</div>`;
                    }
                } catch(e) {
                    console.error("Events fetch error:", e);
                }

                // Update Timeline Logs
                const timeline = document.getElementById("timeline-container");
                if (state.last_actions && state.last_actions.length > 0) {
                    timeline.innerHTML = state.last_actions.map(act => `
                        <div class="flex gap-3 border-l-2 border-purple-500/30 pl-3 relative py-1">
                            <div class="w-2.5 h-2.5 rounded-full bg-purple-500 absolute -left-[6px] top-2 shadow-[0_0_8px_#a855f7]"></div>
                            <div class="flex-grow">
                                <div class="flex justify-between items-center text-[10px] text-gray-500 mb-0.5">
                                    <span>${act.time}</span>
                                    <span class="text-purple-400">conf: ${Number(act.confidence).toFixed(2)}</span>
                                </div>
                                <div class="text-xs text-gray-200 font-semibold">${act.action}</div>
                                <div class="text-[10px] text-emerald-400 mt-0.5">Status: ${act.status}</div>
                            </div>
                        </div>
                    `).join("");
                } else {
                    timeline.innerHTML = `<div class="flex gap-3 text-gray-500 italic p-4 text-center justify-center">Timeline empty. Run tasks to populate events.</div>`;
                }

                // Update Relationship Vector Panel
                if (state.familiarity_label) {
                    document.getElementById("rel-familiarity").innerText = state.familiarity_label;
                }
                if (state.interaction_depth_label) {
                    document.getElementById("rel-depth").innerText = state.interaction_depth_label;
                }

                // Update Proactive Cognition Panel
                if (state.proactive_status) {
                    const cdEl = document.getElementById("proactive-cooldown");
                    const lastEl = document.getElementById("proactive-last");
                    if (state.proactive_status.on_cooldown) {
                        cdEl.innerText = state.proactive_status.remaining_label;
                        cdEl.className = "text-amber-400 font-bold";
                    } else {
                        cdEl.innerText = "Ready";
                        cdEl.className = "text-teal-400 font-bold";
                    }
                    lastEl.innerText = state.proactive_status.last_suggestion || "None";
                    lastEl.title = state.proactive_status.last_suggestion || "";
                }
                
                if (state.cooldown_multiplier !== undefined) {
                    document.getElementById("proactive-multiplier").innerText = state.cooldown_multiplier.toFixed(1) + "x";
                }
                if (state.quarantine_count !== undefined) {
                    document.getElementById("quarantine-count").innerText = state.quarantine_count;
                }

                // Update Cognitive Governance Panel
                if (state.simulated_anomalies_quarantined !== undefined) {
                    document.getElementById("gov-sim-quarantine").innerText = state.simulated_anomalies_quarantined;
                }
                if (state.drift_delta_score !== undefined) {
                    document.getElementById("gov-drift-delta").innerText = Number(state.drift_delta_score).toFixed(4);
                }
                if (state.emotional_volatility) {
                    const alerts = state.emotional_volatility.alerts || [];
                    const volatile = state.emotional_volatility.trust_volatile ||
                        state.emotional_volatility.comfort_volatile ||
                        state.emotional_volatility.trust_spike_detected ||
                        state.emotional_volatility.comfort_collapse_detected;
                    const volEl = document.getElementById("gov-volatility");
                    volEl.innerText = volatile ? alerts.map(a => a.type).join(", ") || "Alert" : "Stable";
                    volEl.className = volatile ? "text-red-400 font-bold" : "text-emerald-300 font-semibold";
                }
                if (state.cognitive_version !== undefined) {
                    const version = state.cognitive_version;
                    document.getElementById("gov-version").innerText = typeof version === "object"
                        ? `${version.personality || "personality_v0"} / ${version.profile || "profile_v0"}`
                        : `profile_v${version}`;
                }
                if (state.degradation_mode !== undefined) {
                    document.getElementById("gov-runtime").innerText = state.degradation_mode;
                    document.getElementById("gov-runtime").title = state.capability_context || "";
                }
                if (state.capability_health !== undefined) {
                    const healthRows = Object.values(state.capability_health).map(h =>
                        `${h.name}: ${h.status} (${Number(h.confidence).toFixed(2)})`
                    );
                    document.getElementById("gov-capability-health").innerText = healthRows.join(" | ");
                }

                // Update Screenshot Frame
                const img = document.getElementById("screenshot-img");
                const noImgLbl = document.getElementById("no-screenshot-lbl");
                if (state.screenshot_available) {
                    // Update image source by appending cache buster to trigger re-render
                    img.src = "/api/screenshot?t=" + new Date().getTime();
                    img.classList.remove("hidden");
                    noImgLbl.classList.add("hidden");
                } else {
                    img.classList.add("hidden");
                    noImgLbl.classList.remove("hidden");
                }
                
                // Fetch career stats and opportunities
                await fetchCareerData();
                
            } catch(e) {
                console.error("Dashboard fetch error:", e);
            }
        }

        async function setMode(mode) {
            try {
                await fetch("/api/mode", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ mode: mode })
                });
                fetchState();
            } catch(e) {
                console.error("Mode update error:", e);
            }
        }

        function updateModeButtons(activeMode) {
            ["safe", "auto", "dev"].forEach(m => {
                const btn = document.getElementById("btn-" + m);
                if (activeMode === m) {
                    btn.className = "px-3 py-1 text-xs font-semibold rounded-md transition-all bg-blue-500 text-white shadow-[0_0_10px_rgba(59,130,246,0.5)]";
                } else {
                    btn.className = "px-3 py-1 text-xs font-semibold rounded-md transition-all text-gray-400 hover:text-white hover:bg-white/5";
                }
            });
        }

        // Career functions
        async function fetchCareerData() {
            try {
                // 1. Fetch coding/dsa stats
                const statsRes = await fetch("/api/career/stats");
                const stats = await statsRes.json();
                
                
                if (stats.github && !stats.github.error) {
                    document.getElementById("gh-streak").innerText = stats.github.streak + " Days";
                    document.getElementById("gh-weekly").innerText = stats.github.weekly_commits + " commits last 7d";
                } else {
                    document.getElementById("gh-streak").innerText = "0 Days";
                    document.getElementById("gh-weekly").innerText = stats.github?.error || "API failed";
                }
                
                if (stats.codeforces && !stats.codeforces.error) {
                    document.getElementById("cf-rating").innerText = stats.codeforces.rating + " Rating";
                    document.getElementById("cf-rank").innerText = `${stats.codeforces.rank} (max ${stats.codeforces.max_rating})`;
                } else {
                    document.getElementById("cf-rating").innerText = "Unrated";
                    document.getElementById("cf-rank").innerText = stats.codeforces?.error || "API failed";
                }
                
                // 2. Fetch opportunities list
                const oppsRes = await fetch("/api/career/opportunities");
                const opps = await oppsRes.json();
                const oppsList = document.getElementById("career-opportunities-list");
                
                if (opps && opps.length > 0) {
                    oppsList.innerHTML = opps.map(o => {
                        const scoreText = o.match_score !== null ? `${Math.round(o.match_score)}%` : "N/A";
                        const linkHtml = o.apply_link ? `<a href="${o.apply_link}" target="_blank" class="text-cyan-400 hover:underline">Apply</a>` : "N/A";
                        
                        return `
                            <tr class="border-b border-white/5 hover:bg-white/5 transition-colors">
                                <td class="py-2 text-white font-semibold">${o.company}</td>
                                <td class="py-2 text-gray-300">${o.role}</td>
                                <td class="py-2">
                                    <select onchange="updateJobStatus(${o.id}, this.value)" class="bg-black/50 border border-white/10 rounded px-1 text-[10px] text-gray-300 focus:outline-none">
                                        <option value="bookmarked" ${o.status === 'bookmarked' ? 'selected' : ''}>Bookmarked</option>
                                        <option value="applied" ${o.status === 'applied' ? 'selected' : ''}>Applied</option>
                                        <option value="interviewing" ${o.status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                                        <option value="rejected" ${o.status === 'rejected' ? 'selected' : ''}>Rejected</option>
                                        <option value="offered" ${o.status === 'offered' ? 'selected' : ''}>Offered</option>
                                    </select>
                                </td>
                                <td class="py-2 text-purple-400 font-bold">${scoreText}</td>
                                <td class="py-2 text-right">${linkHtml}</td>
                            </tr>
                        `;
                    }).join("");
                } else {
                    oppsList.innerHTML = `<tr><td colspan="5" class="py-3 text-center text-gray-500 italic">No job tracking entries.</td></tr>`;
                }
            } catch (e) {
                console.error("Error fetching career data:", e);
            }
        }
        
        async function updateJobStatus(oppId, newStatus) {
            try {
                await fetch(`/api/career/opportunities/${oppId}/status`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status: newStatus })
                });
                fetchCareerData();
            } catch (e) {
                console.error("Error updating job status:", e);
            }
        }
        
        function openAddJobModal() {
            document.getElementById("add-job-modal").classList.remove("hidden");
        }
        
        function closeAddJobModal() {
            document.getElementById("add-job-modal").classList.add("hidden");
            document.getElementById("job-company").value = "";
            document.getElementById("job-role").value = "";
            document.getElementById("job-location").value = "";
            document.getElementById("job-link").value = "";
            document.getElementById("job-deadline").value = "";
        }
        
        async function submitJob() {
            const company = document.getElementById("job-company").value.trim();
            const role = document.getElementById("job-role").value.trim();
            if (!company || !role) {
                alert("Company and Role are required.");
                return;
            }
            const location = document.getElementById("job-location").value;
            const link = document.getElementById("job-link").value;
            const deadline = document.getElementById("job-deadline").value;
            
            try {
                await fetch("/api/career/opportunities", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        company: company,
                        role: role,
                        location: location,
                        apply_link: link,
                        deadline: deadline
                    })
                });
                closeAddJobModal();
                fetchCareerData();
            } catch (e) {
                console.error("Error submitting job:", e);
            }
        }
        
        function openMatchModal() {
            document.getElementById("match-modal").classList.remove("hidden");
        }
        
        function closeMatchModal() {
            document.getElementById("match-modal").classList.add("hidden");
            document.getElementById("match-description").value = "";
            document.getElementById("match-results-box").classList.add("hidden");
        }
        
        async function runMatch() {
            const desc = document.getElementById("match-description").value.trim();
            if (!desc) {
                alert("Please enter a job description.");
                return;
            }
            
            document.getElementById("match-loading").classList.remove("hidden");
            document.getElementById("btn-run-match").disabled = true;
            document.getElementById("match-results-box").classList.add("hidden");
            
            try {
                const res = await fetch("/api/career/match", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ description: desc })
                });
                const data = await res.json();
                
                document.getElementById("match-result-score").innerText = (data.match_score || 0) + "%";
                document.getElementById("match-result-matching").innerText = (data.matching_skills || []).join(", ") || "None";
                document.getElementById("match-result-gaps").innerText = (data.gaps || []).join(", ") || "None";
                document.getElementById("match-result-recs").innerText = (data.recommendations || []).join(", ") || "None";
                
                document.getElementById("match-results-box").classList.remove("hidden");
            } catch (e) {
                console.error("Error running match:", e);
                alert("Match evaluation failed.");
            } finally {
                document.getElementById("match-loading").classList.add("hidden");
                document.getElementById("btn-run-match").disabled = false;
            }
        }

        // Poll API every 2 seconds
        setInterval(fetchState, 2000);
        window.onload = fetchState;
    </script>

    <!-- Add Job Modal -->
    <div id="add-job-modal" class="hidden fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
        <div class="glass max-w-md w-full p-6 rounded-2xl flex flex-col gap-4 border border-cyan-500/20">
            <h3 class="text-sm font-semibold tracking-wider text-cyan-400 uppercase font-mono">Bookmark Job Opportunity</h3>
            <div class="flex flex-col gap-3 text-xs">
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Company Name</label>
                    <input type="text" id="job-company" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-cyan-500" placeholder="e.g. Google">
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Role Title</label>
                    <input type="text" id="job-role" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-cyan-500" placeholder="e.g. Software Engineer Intern">
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Location</label>
                    <input type="text" id="job-location" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-cyan-500" placeholder="e.g. Mountain View, CA">
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Apply Link URL</label>
                    <input type="text" id="job-link" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-cyan-500" placeholder="https://careers.google.com/...">
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Deadline (YYYY-MM-DD)</label>
                    <input type="text" id="job-deadline" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-cyan-500" placeholder="e.g. 2026-10-31">
                </div>
            </div>
            <div class="flex justify-end gap-2 text-xs font-mono mt-2">
                <button onclick="closeAddJobModal()" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-gray-300">Cancel</button>
                <button onclick="submitJob()" class="px-3 py-1.5 rounded bg-cyan-500 text-black font-semibold">Save</button>
            </div>
        </div>
    </div>

    <!-- Match Resume Modal -->
    <div id="match-modal" class="hidden fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
        <div class="glass max-w-lg w-full p-6 rounded-2xl flex flex-col gap-4 border border-purple-500/20">
            <h3 class="text-sm font-semibold tracking-wider text-purple-400 uppercase font-mono">LLM Resume Matcher</h3>
            <div class="flex flex-col gap-3 text-xs">
                <div class="flex flex-col gap-1">
                    <label class="text-gray-400">Target Job Description</label>
                    <textarea id="match-description" rows="6" class="p-2 rounded bg-white/5 border border-white/10 text-white focus:outline-none focus:border-purple-500 resize-none" placeholder="Paste the job description or requirements here..."></textarea>
                </div>
                <div id="match-results-box" class="hidden p-3 rounded bg-white/5 border border-white/5 flex flex-col gap-2 font-mono">
                    <div class="flex justify-between font-bold">
                        <span>MATCH SCORE:</span>
                        <span id="match-result-score" class="text-purple-400">0%</span>
                    </div>
                    <div class="text-[10px]">
                        <span class="text-emerald-400 font-semibold">MATCHING:</span>
                        <div id="match-result-matching" class="text-gray-300 mt-0.5 font-sans"></div>
                    </div>
                    <div class="text-[10px] mt-1">
                        <span class="text-red-400 font-semibold">GAPS:</span>
                        <div id="match-result-gaps" class="text-gray-300 mt-0.5 font-sans"></div>
                    </div>
                    <div class="text-[10px] mt-1">
                        <span class="text-amber-400 font-semibold">RECOMMENDATIONS:</span>
                        <div id="match-result-recs" class="text-gray-300 mt-0.5 font-sans"></div>
                    </div>
                </div>
            </div>
            <div class="flex justify-between items-center text-xs font-mono mt-2">
                <span id="match-loading" class="hidden text-purple-300 animate-pulse">Deliberating...</span>
                <div class="flex justify-end gap-2 ml-auto">
                    <button onclick="closeMatchModal()" class="px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 text-gray-300">Close</button>
                    <button id="btn-run-match" onclick="runMatch()" class="px-3 py-1.5 rounded bg-purple-500 text-white font-semibold">Run Match</button>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)
