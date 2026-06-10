import json
from typing import Dict, Any, List
from skills.base_agent import BaseAgent
from skills.dependency_graph import AriaDependencyGraphEngine
from skills.blackboard import AriaBlackboard

class AriaArchitectureAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("ArchitectureAgent", aria_instance)
        self.engine = AriaDependencyGraphEngine(root_dir=".")
        self.blackboard = AriaBlackboard()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Generating system dependency architecture maps...")
        
        # Incremental sync first
        self.engine.build_system_architecture_map(force_rebuild=False)
        
        action = payload.get("action", "").lower()
        query = payload.get("query", "") or task_description
        query_lower = query.lower()
        
        # Decide search parameters based on payload or query parsing
        target_mod = payload.get("target", "").strip()
        source_mod = payload.get("source", "").strip()
        
        # Autodetect action if not specified
        if not action:
            if "circle" in query_lower or "cycle" in query_lower or "circular" in query_lower:
                action = "detect_cycles"
            elif "stat" in query_lower or "summary" in query_lower or "metric" in query_lower:
                action = "stats"
            elif "path" in query_lower or "flow" in query_lower or "route" in query_lower:
                action = "trace_path"
            else:
                action = "trace_impact"

        # Auto-extract module names from query if not specified in payload
        if action == "trace_path":
            words = [w.strip("?,.!-").lower() for w in query.split()]
            # Try to map word to a known module name using from/to context
            for i, w in enumerate(words):
                for m in self.engine.graph:
                    if w == m.lower():
                        if i > 0 and words[i-1] == "from":
                            source_mod = m
                        elif i > 0 and words[i-1] == "to":
                            target_mod = m
            
            # Fallback based on order of occurrence if still missing
            if not source_mod or not target_mod:
                mentioned_mods = []
                for w in words:
                    for m in self.engine.graph:
                        if w == m.lower():
                            if m not in mentioned_mods:
                                mentioned_mods.append(m)
                            break
                if len(mentioned_mods) >= 2:
                    if not source_mod:
                        source_mod = mentioned_mods[0]
                    if not target_mod:
                        target_mod = mentioned_mods[1] if mentioned_mods[1] != source_mod else mentioned_mods[0]
                elif len(mentioned_mods) == 1:
                    if not target_mod:
                        target_mod = mentioned_mods[0]
        else:
            if not target_mod:
                words = [w.strip("?,.!-").lower() for w in query.split()]
                for w in words:
                    for m in self.engine.graph:
                        if w == m.lower():
                            target_mod = m
                            break
                    if target_mod:
                        break

        report_data = {}
        answer_text = ""

        if action == "stats":
            stats = self.engine.get_graph_stats()
            report_data = {"stats": stats}
            cycle_desc = f"{stats['cycles']} cycles detected" if stats['cycles'] > 0 else "0 circular dependencies"
            answer_text = (
                f"System Architecture Stats:\n"
                f"- Modules indexed: {stats['modules']}\n"
                f"- Adjacency edges: {stats['edges']}\n"
                f"- Integrity: {cycle_desc}\n"
                f"- Most depended on modules: {', '.join(stats['most_depended_on'])}"
            )
        elif action == "detect_cycles":
            cycles = self.engine.find_circular_dependencies()
            report_data = {"cycles": cycles}
            if cycles:
                cycle_strs = [" -> ".join(c) for c in cycles]
                answer_text = f"Circular dependencies found: {'; '.join(cycle_strs)}."
            else:
                answer_text = "Integrity check passed. No circular dependencies detected in the codebase."
        elif action == "trace_path":
            if not source_mod or not target_mod:
                answer_text = "To trace an execution call path, please specify both source and target modules."
            else:
                path = self.engine.compile_call_path(source_mod, target_mod)
                report_data = {"source": source_mod, "target": target_mod, "path": path}
                if path:
                    answer_text = f"Call path mapped: {' -> '.join(path)}."
                else:
                    answer_text = f"No direct import call path found from '{source_mod}' to '{target_mod}'."
        else: # trace_impact
            if not target_mod:
                stats = self.engine.get_graph_stats()
                report_data = {"stats": stats}
                answer_text = (
                    f"Please specify a target module. Here are the system stats:\n"
                    f"Total modules: {stats['modules']}, Edges: {stats['edges']}, Circular loops: {stats['cycles']}."
                )
            else:
                impact = self.engine.trace_ripple_impact(target_mod)
                report_data = {"target": target_mod, "impact_radius": impact}
                if impact:
                    answer_text = f"Ripple impact analysis: modifying '{target_mod}.py' directly affects these modules: {', '.join(impact)}."
                else:
                    answer_text = f"Ripple impact analysis: modifying '{target_mod}.py' has a ripple impact radius of 0 modules."

        # Synthesis via Gemini
        self.log_state_shift("RUNNING", "Synthesizing architectural briefing...")
        prompt = f"""
        You are ARIA's advanced codebase architect agent. Answer this developer query about ARIA's system dependencies.
        Analyze and present the mapped structural data report below in a clear layout-focused format.
        Cite file dependencies and import relations.
        
        == DEVELOPER QUERY ==
        {query}
        
        == STRUCTURAL MAP REPORT ==
        {answer_text}
        """
        
        aria = self.aria_inst
        briefing = ""
        if aria and getattr(aria, "brain", None):
            try:
                briefing = aria.brain.think(prompt)
            except Exception as e:
                briefing = f"Brain model synthesis error: {e}. Raw report:\n{answer_text}"
        else:
            briefing = answer_text

        # Publish architectural report to Blackboard
        self.blackboard.publish(
            topic="system",
            key=f"architecture_report_{task_id}",
            value={"query": query, "briefing": briefing, "data": report_data},
            source=self.agent_name,
            ttl_hours=2
        )

        self.log_state_shift("IDLE", "Architecture analysis completed successfully.")
        return json.dumps({"status": "SUCCESS", "answer": briefing, "data": report_data})
