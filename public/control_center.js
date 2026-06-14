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
                        riskColor = "text-red-500 bg-red-650/10 border-red-655/20 font-extrabold animate-pulse";
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
                                    <span class="text-gray-500">Type:</span> <span class="text-violet-355 font-semibold font-mono">${item.patch_type}</span>
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
                                    <div class="bg-red-955/20 border border-red-900/10 p-1.5 rounded text-red-300 overflow-x-auto max-h-[60px]">
                                        <div class="text-[8px] text-red-500 font-bold border-b border-red-900/20 pb-0.5 mb-0.5">- ORIGINAL</div>
                                        <pre class="leading-tight">${origEscaped}</pre>
                                    </div>` : ''}
                                    ${propEscaped ? `
                                    <div class="bg-emerald-955/20 border border-emerald-900/10 p-1.5 rounded text-emerald-300 overflow-x-auto max-h-[80px]">
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
