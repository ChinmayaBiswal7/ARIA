"""
skills/proactive_scheduler_commands.py — Extracted Scheduler and Proactive checks logic for ARIA
==============================================================================================
Encapsulates executor queue workers, background scheduler loops, and periodic checks.
Does not import main.py directly.
"""
import time
import datetime
import psutil
import os
import json
from skills.event_bus import EventBus

try:
    from gui import set_state, set_text
except ImportError:
    def set_state(s): pass
    def set_text(t): pass


def run_background_scheduler(aria):
    """Proactive background scheduler that checks battery levels, break suggestions, and database reminders."""
    last_battery_check_time = 0
    last_break_check_time = time.time()
    last_memory_maintenance_time = time.time()
    last_career_check_time = time.time()
    last_learning_update_time = 0
    
    print("[ARIA Scheduler] Proactive Background Loop successfully running.")
    
    while aria.running:
        try:
            now = time.time()
            
            # 1. Reminders check (every 15 seconds)
            try:
                with aria.memory_skill._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, task, due_at, due_date FROM reminders WHERE status = 'pending'")
                    pending = cursor.fetchall()
                    
                    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                    current_time = datetime.datetime.now().strftime("%H:%M")
                    
                    for rid, task, due_time, due_date in pending:
                        trigger_reminder = False
                        # Match date
                        if due_date and due_date <= current_date:
                            if not due_time or due_time <= current_time:
                                trigger_reminder = True
                        
                        if trigger_reminder:
                            # Mark as notified/done
                            cursor.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (rid,))
                            conn.commit()
                            
                            # Evaluate Priority Triage
                            action = aria.attention_manager.evaluate_event("reminder", {"task": task})
                            EventBus().publish("SCHEDULER_ALERT", {"task": task, "type": "reminder", "action": action})
                            
                            if action == "execute":
                                set_state("SPEAKING")
                                aria.safe_speak(f"Proactive alert. You have a reminder: '{task}'.")
                                set_state("IDLE")
                            else:
                                # Batch notification silently
                                try:
                                    from dashboard import CognitionState
                                    CognitionState.pending_notifications = aria.attention_manager.pending_notifications[:]
                                except Exception:
                                    pass
            except Exception as re_err:
                print(f"[ARIA Scheduler] Reminders check error: {re_err}")
            
            # Evaluate Cognitive Load and execute adaptive regulation (every 15s)
            try:
                aria.cognitive_load_manager.regulate_cognition(aria)
                # Update load status to dashboard API
                load_metrics = aria.cognitive_load_manager.get_load_metrics()
                from dashboard import CognitionState
                CognitionState.cognitive_load_score = load_metrics["load_score"]
                CognitionState.cognitive_load_status = load_metrics["status"]
            except Exception as ce:
                print(f"[ARIA Scheduler] Load evaluation error: {ce}")

            # Sleep / Idle Consolidation Cycle (after 60s of agent inactivity)
            if not aria.idle_consolidation_done and (now - aria.last_agent_activity > 60):
                try:
                    # Ensure no task is actively running
                    if aria.attention_manager.focus_priority == 0:
                        print("[ARIA Scheduler] INITIATING OFFLINE MEMORY CONSOLIDATION CYCLE...")
                        set_state("SPEAKING")
                        aria._speak("Subsystems entering idle. Initiating memory consolidation cycle.")
                        set_state("IDLE")
                        
                        # Perform memory GC and compact database indexes
                        aria.memory_skill.compress_memories()
                        
                        # Clean/vacuum sqlite database indexes
                        with aria.memory_skill._get_connection() as conn:
                            conn.execute("VACUUM")
                            
                        aria.idle_consolidation_done = True
                        set_state("SPEAKING")
                        aria._speak("Offline consolidation complete. Subsystems optimized.")
                        set_state("IDLE")
                except Exception as s_err:
                    print(f"[ARIA Scheduler] Idle consolidation error: {s_err}")

            # 2. Battery check (every 5 minutes)
            if now - last_battery_check_time > 300:
                last_battery_check_time = now
                try:
                    battery = psutil.sensors_battery()
                    if battery:
                        percent = battery.percent
                        power_plugged = battery.power_plugged
                        if percent < 20 and not power_plugged:
                            # Low Battery is Priority 4: Interrupt task immediately
                            action = aria.attention_manager.evaluate_event("low_battery", {"percent": percent})
                            EventBus().publish("SYSTEM_ALERT", {"type": "low_battery", "percent": percent, "action": action})
                            
                            if action == "execute":
                                # Interrupt running task
                                has_task = getattr(aria, "attention_manager", None) and aria.attention_manager.focus_priority > 0
                                if has_task:
                                    aria.paused_by_interrupt = True
                                    print("[AttentionManager] INTERRUPTING ACTIVE WORKFLOW FOR CRITICAL BATTERY ALERT.")
                                    
                                set_state("SPEAKING")
                                aria.safe_speak(f"System alert. Battery level is low at {percent} percent. Please connect a charger.")
                                set_state("IDLE")
                                
                                if has_task:
                                    aria.paused_by_interrupt = False
                            else:
                                # Batch notification silently
                                try:
                                    from dashboard import CognitionState
                                    CognitionState.pending_notifications = aria.attention_manager.pending_notifications[:]
                                except Exception:
                                    pass
                except Exception as bat_err:
                    print(f"[ARIA Scheduler] Battery telemetry error: {bat_err}")
            
            # 3. Stretch break check (every 45 minutes)
            if now - last_break_check_time > 2700:
                last_break_check_time = now
                action = aria.attention_manager.evaluate_event("break_suggestion", {})
                EventBus().publish("SYSTEM_ALERT", {"type": "break_suggestion", "action": action})
                
                if action == "execute":
                    set_state("SPEAKING")
                    aria.safe_speak("System alert. You have been working continuously. I suggest taking a short break to stretch.")
                    set_state("IDLE")
                else:
                    # Batch notification silently
                    try:
                        from dashboard import CognitionState
                        CognitionState.pending_notifications = aria.attention_manager.pending_notifications[:]
                    except Exception:
                        pass

            # 3.5. Background User Perception (run every 60 seconds)
            if now - getattr(aria, "last_background_perception_time", 0.0) > 60.0:
                try:
                    aria._run_background_perception()
                except Exception as perc_err:
                    print(f"[ARIA Scheduler] Background user perception error: {perc_err}")

            # 4. Proactive Cognition — soft suggestion check (respects cooldown)
            try:
                suggestion = None
                if hasattr(aria, "proactive_queue") and aria.proactive_queue is not None and not aria.proactive_queue.empty():
                    try:
                        suggestion = aria.proactive_queue.get_nowait()
                        aria.proactive_queue.task_done()
                        print(f"[Proactive] Retrieved suggestion from queue: {suggestion}")
                    except Exception:
                        pass
                
                if not suggestion:
                    if not getattr(aria, "startup_greeting_done", False) or (now - aria.start_time < 120):
                        suggestion = None
                    else:
                        suggestion = aria.proactive_cognition.run_background_check(aria)
                if suggestion:
                    action = aria.attention_manager.evaluate_event("proactive_suggestion", {"text": suggestion})
                    EventBus().publish("PROACTIVE_SUGGESTION", {"text": suggestion, "action": action})
                    
                    if action == "execute":
                        set_state("SPEAKING")
                        aria.deliver_proactive(suggestion)
                        set_state("IDLE")
                        aria.last_proactive_suggestion_time = time.time()
                    else:
                        try:
                            from dashboard import CognitionState
                            CognitionState.pending_notifications = aria.attention_manager.pending_notifications[:]
                        except Exception:
                            pass
            except Exception as pro_err:
                print(f"[ARIA Scheduler] Proactive cognition error: {pro_err}")

            # 5. Idle Reflection — trigger background reflection when agent is idle
            try:
                if aria.attention_manager.focus_priority == 0 and (now - aria.last_agent_activity > 120):
                    username = aria.known_user or "chinmaya"
                    recent_episodes = aria.episodic_memory.get_recent(username=username, n=5)
                    if recent_episodes and len(recent_episodes) > 0:
                        aria.reflection_engine.reflect_asynchronously(
                            username=username,
                            recent_episodes=recent_episodes,
                            recent_task_results=[]
                        )
                        aria.last_agent_activity = now  # Prevent re-triggering continuously
            except Exception as ref_err:
                print(f"[ARIA Scheduler] Idle reflection error: {ref_err}")

            # 5.5. Memory maintenance decay & compression pass (every 24 hours)
            if now - last_memory_maintenance_time > 86400:
                last_memory_maintenance_time = now
                print("[MemoryMaintenance] Running daily decay and compression pass...")
                try:
                    username = aria.known_user or "chinmaya"
                    aria.episodic_memory.decay_pass(username)
                    print("[MemoryMaintenance] Decay pass complete.")
                    aria.episodic_memory.compress_old_episodes(username)
                    print("[MemoryMaintenance] Compression pass complete.")
                except Exception as e:
                    print(f"[MemoryMaintenance] Error during maintenance: {repr(e)}")

            # 5.6. Career/DSA daily checks (every 24 hours)
            if now - last_career_check_time > 86400:
                last_career_check_time = now
                try:
                    from skills.career_agent import CareerAgent
                    CareerAgent().check_daily_metrics(aria)
                except Exception as ce_err:
                    print(f"[CareerScheduler] Error running daily career/DSA checks: {ce_err}")

            # 5.7. Learning Core daily update + decay (every 24 hours)
            if now - last_learning_update_time > 86400:
                last_learning_update_time = now
                try:
                    run_daily_learning_update(aria)
                except Exception as l_err:
                    print(f"[LearningScheduler] Error running daily learning update: {l_err}")

            # 6. Dashboard Telemetry — push relationship & proactive status
            try:
                from dashboard import CognitionState
                username = aria.known_user or "chinmaya"
                
                # Relationship soft labels
                labels = aria.reflection_engine.get_relationship_labels(username)
                CognitionState.familiarity_label = labels.get("familiarity", "Acquaintance")
                CognitionState.interaction_depth_label = labels.get("interaction_depth", "Surface-level")
                
                # Proactive cooldown status
                CognitionState.proactive_status = aria.proactive_cognition.get_cooldown_status()
                CognitionState.cooldown_multiplier = aria.proactive_cognition.cooldown_multiplier
                
                # Push presence state to dashboard
                CognitionState.presence_state = getattr(aria, "presence_state", "USER_LEFT")

                # Quarantine count from candidate updates table
                q_count = 0
                try:
                    with aria.reflection_engine._get_conn() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM candidate_semantic_updates WHERE status = 'quarantined'")
                        row = cursor.fetchone()
                        if row:
                            q_count = row[0]
                except Exception:
                    pass
                CognitionState.quarantine_count = q_count
            except Exception:
                pass
                
        except Exception as loop_err:
            print(f"[ARIA Scheduler] Scheduler thread error: {loop_err}")
            
        time.sleep(15)


def run_proactive_checks(aria):
    """Periodically check battery status and system session time for proactive announcements."""
    now = time.time()
    
    # 1. Battery status check: run every 5 minutes (300 seconds)
    if now - aria.last_battery_check > 300:
        aria.last_battery_check = now
        try:
            batt = aria.context_skill.get_battery_percent()
            charging = aria.context_skill.get_charging_status()
            if batt is not None and batt < 20 and not charging:
                aria.safe_speak(f"Excuse me. Your laptop battery is low at {batt} percent. Please connect your charger.")
        except Exception as e:
            print(f"[Proactive] Battery check error: {e}")
            
    # 2. Continuous work duration check: check every hour (3600 seconds)
    if now - aria.last_break_check > 3600:
        aria.last_break_check = now
        elapsed_hours = int((now - aria.start_time) / 3600)
        if elapsed_hours >= 1:
            aria.safe_speak(f"Hi. You have been working for {elapsed_hours} hour. Remember to take a quick break.")

    if now - aria.last_activity_log > 300:
        aria.last_activity_log = now
        try:
            active = aria.context_skill.get_active_window()
            battery = aria.context_skill.get_battery_percent()
            wifi = aria.context_skill.get_wifi_status()
            aria.memory_skill.log_activity(active, battery, wifi)
        except Exception as e:
            print(f"[Proactive] Activity log error: {e}")

    if now - aria.last_reminder_check > 30:
        aria.last_reminder_check = now
        try:
            due = aria.memory_skill.get_due_reminders()
            for reminder_id, task in due:
                aria.safe_speak(f"Reminder: {task}")
                aria.memory_skill.complete_reminder(reminder_id)
        except Exception as e:
            print(f"[Proactive] Reminder check error: {e}")


def executor_queue_worker(aria):
    """Worker thread that processes the task execution queue."""
    print("[ARIA Queue] Executor queue worker running.")
    while aria.running:
        try:
            task_item = aria.executor_queue.get_next_task()
            if not task_item:
                time.sleep(1.0)
                continue

            if task_item.cancelled:
                print(f"[ARIA Queue] Skipping enqueued task '{task_item.goal}' because it was cancelled.")
                aria.executor_queue.finish_active_task()
                continue

            # Execute active task
            print(f"[ARIA Queue] Executing queued task: '{task_item.goal}'")
            aria.run_autonomous_agent(task_item.goal, task_item=task_item)
            aria.executor_queue.finish_active_task()
        except Exception as e:
            print(f"[ARIA Queue] Error executing queued task: {e}")
            time.sleep(1.0)


def run_daily_learning_update(aria):
    """
    Triggers the Continuous Learning Engine updates:
    1. Pulls KnowledgeGraph summary (GitHub details, voice details, etc.)
    2. Pulls Codeforces stats
    3. Pulls career opportunities outcomes
    4. Pulls ARIA usage patterns
    5. Fuses signals and runs daily decay
    6. Syncs profile snapshot to Firestore
    """
    print("[LearningCore] Starting daily user profile learning update...")
    try:
        from skills.learning_core import AriaLearningCore
        from skills.knowledge_graph import KnowledgeGraph
        from skills.career_agent import CareerAgent
        from skills.firebase_sync import sync_profile_to_firestore
        from dashboard import CognitionState
        
        lc = AriaLearningCore()
        kg = KnowledgeGraph()
        ca = CareerAgent()
        
        # 1. GitHub signal ingestion (reads from KG nodes)
        lc.ingest_github_signal(aria, kg)
        
        # 2. Codeforces signal ingestion
        username = "chinmaya"
        try:
            # Query preferences if stored
            with ca._get_connection() as conn:
                row = conn.execute("SELECT value FROM user_preferences WHERE key = 'codeforces_username'").fetchone()
                if row:
                    username = row['value']
        except Exception:
            pass
        cf_stats = ca.get_codeforces_stats(username)
        lc.ingest_codeforces_signal(aria, cf_stats)
        
        # 3. Career signal ingestion
        # Query career outcomes updated in the last 24h
        now = time.time()
        one_day_ago = now - 86400
        try:
            with ca._get_connection() as conn:
                rows = conn.execute("""
                    SELECT role, status FROM career_opportunities 
                    WHERE updated_at >= ?
                """, (one_day_ago,)).fetchall()
                for r in rows:
                    role = r["role"]
                    status = r["status"]
                    # Map status/outcome
                    outcome = None
                    if status in ["interview", "interviewing"]:
                        outcome = "INTERVIEW"
                    elif status in ["offered", "offer"]:
                        outcome = "OFFER"
                    elif status in ["rejected"]:
                        outcome = "REJECTED"
                    elif status in ["ghosted"]:
                        outcome = "GHOSTED"
                        
                    if outcome:
                        # Map role to role_type
                        role_lower = role.lower()
                        role_type = "swe"
                        if "backend" in role_lower:
                            role_type = "backend"
                        elif "frontend" in role_lower:
                            role_type = "frontend"
                        elif "ml" in role_lower or "ai" in role_lower or "machine learning" in role_lower:
                            role_type = "ml"
                        lc.ingest_career_signal(aria, role_type, outcome)
        except Exception as e:
            print(f"[LearningCore] Career signal ingest failed: {e}")
            
        # 4. Usage signal ingestion (from episodic memory logs in the last 24h)
        try:
            em = aria.episodic_memory
            recent_episodes = em.get_recent(username="chinmaya", n=50)
            topics = []
            for ep in recent_episodes:
                # Extract words/topics from user message
                text = ep.get("event_text", "")
                for kw in ["python", "kotlin", "java", "javascript", "typescript", "c++", "rust", "go", "backend", "frontend", "ml", "ai", "competitive programming", "dsa", "sql"]:
                    if kw in text.lower():
                        topics.append(kw)
            if topics:
                lc.ingest_usage_signal(topics)
        except Exception as e:
            print(f"[LearningCore] Usage signal ingest failed: {e}")

        # 5. Run decay
        lc.run_daily_decay()
        
        # 6. Retrieve snapshot and update dashboard state
        snapshot = lc.get_profile_snapshot()
        foci = lc.get_current_focus()
        snapshot["current_focus"] = foci
        
        # Push to FastAPI state
        CognitionState.profile_insights = snapshot
        
        # 7. Sync to Firestore
        sync_profile_to_firestore(snapshot)
        print("[LearningCore] Daily user profile learning update completed successfully.")
        
    except Exception as ex:
        print(f"[LearningCore] Error in run_daily_learning_update: {ex}")
