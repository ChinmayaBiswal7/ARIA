import json
import time
from typing import Dict, Any, List

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
from skills.knowledge_search_agent import AriaKnowledgeSearchAgent
from skills.code_search_agent import AriaCodeSearchAgent
from skills.dependency_graph import AriaDependencyGraphEngine

class AriaResearchAgent(BaseAgent):
    def __init__(self, aria_instance=None):
        super().__init__("ResearchAgent", aria_instance)
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
        self.log_state_shift("RUNNING", "Initializing multi-source research retrieval...")

        query = payload.get("query", "")
        if not query:
            query = payload.get("target", "")
        if not query:
            query = task_description

        # Instantiation of direct retrieval layers
        aria_ctx = self.aria_inst
        knowledge_agent = AriaKnowledgeSearchAgent(aria_instance=aria_ctx)
        code_agent = AriaCodeSearchAgent(aria_instance=aria_ctx)
        dep_engine = AriaDependencyGraphEngine()

        knowledge_chunks = []
        knowledge_sources = []
        code_chunks = []
        code_sources = []
        dep_chunks = []
        dep_sources = []

        # 1. Harvest Context from Knowledge RAG directly
        query_embedding = knowledge_agent.encoder.get_embedding(query)
        if query_embedding:
            vault_chunks = knowledge_agent.vector_store.search(query_embedding, k=4)
            for c in vault_chunks:
                knowledge_chunks.append(c["text"])
                knowledge_sources.append(c["source"])

        proj = knowledge_agent._retrieve_project_context(query)
        if proj:
            knowledge_chunks.append(proj)
            knowledge_sources.append("aria_projects.json")

        career = knowledge_agent._retrieve_career_context(query)
        if career:
            knowledge_chunks.append(career)
            knowledge_sources.append("aria_memory.db/career_opportunities")

        kg = knowledge_agent._retrieve_kg_context(query)
        if kg:
            knowledge_chunks.append(kg)
            knowledge_sources.append("aria_knowledge.db")

        pref = knowledge_agent._retrieve_user_preferences(query)
        if pref:
            knowledge_chunks.append(pref)
            knowledge_sources.append("aria_memory.db/preferences")

        # 2. Harvest Context from Code RAG directly
        symbol_file = code_agent.store.lookup_symbol(query.strip())
        exact_chunks = []
        exact_match_bonus = 0.0
        
        # If direct lookup failed, try looking up individual words
        matched_symbol = query.strip()
        if not symbol_file:
            words = [w.strip("?,.!-()_") for w in query.split()]
            for w in words:
                if len(w) > 2:
                    sf = code_agent.store.lookup_symbol(w)
                    if sf:
                        symbol_file = sf
                        matched_symbol = w
                        break

        if symbol_file:
            print(f"[ResearchAgent] Found exact symbol match: '{matched_symbol}' in {symbol_file}")
            # Filter chunks in the matched file that are relevant to the query words or the matched symbol
            for c in code_agent.store.chunk_store:
                if c.get("file") == symbol_file:
                    name_lower = c.get("name", "").lower()
                    class_lower = (c.get("class") or "").lower()
                    
                    # Direct equality matches
                    is_match = (
                        c.get("name") == matched_symbol or 
                        f"{c.get('class')}.{c.get('name')}" == matched_symbol
                    )
                    
                    # Or substring/word-level match
                    if not is_match:
                        q_words = [w.strip("?,.!-()_").lower() for w in query.split()]
                        for qw in q_words:
                            if len(qw) > 3:
                                qw_norm = qw.replace("_", "")
                                if (qw in name_lower or qw_norm in name_lower or 
                                    name_lower in qw or name_lower in qw_norm or
                                    qw in class_lower or qw_norm in class_lower):
                                    is_match = True
                                    break
                    
                    if is_match:
                        exact_chunks.append(c)
            
            if exact_chunks:
                exact_match_bonus = 0.10

        code_query_embedding = code_agent.encoder.get_embedding(query)
        code_matches = []
        if code_query_embedding:
            code_matches = code_agent.store.search_code(code_query_embedding, k=3)

        combined_code_chunks = exact_chunks + [m for m in code_matches if m not in exact_chunks]
        for c in combined_code_chunks[:3]:
            doc = c.get("docstring", "None")
            code_chunks.append(
                f"File: {c['file']} (Type: {c['type']}, Name: {c['name']}, Class: {c.get('class') or 'None'}, Lines: {c['start_line']}-{c['end_line']})\n"
                f"Docstring: {doc}\n"
                f"Source:\n{c['source']}"
            )
            code_sources.append(c["file"])

        # 3. Harvest Context from Dependency Graph Engine
        dep_engine.build_system_architecture_map()
        words = [w.strip("?,.!-").lower() for w in query.split()]
        for w in words:
            for m in dep_engine.graph:
                if w == m.lower():
                    impact = dep_engine.trace_ripple_impact(m)
                    if impact:
                        dep_sources.append("data/dependency_graph.json")
                        dep_chunks.append(f"Module '{m}' dependencies impact: {', '.join(impact)}")
                    # Check call paths
                    for w2 in words:
                        if w2 != w:
                            for m2 in dep_engine.graph:
                                if w2 == m2.lower():
                                    path = dep_engine.compile_call_path(m, m2)
                                    if path:
                                        dep_sources.append("data/dependency_graph.json")
                                        dep_chunks.append(f"Call path from '{m}' to '{m2}': {' -> '.join(path)}")

        # Include general stats if no explicit module match is hit
        if not dep_sources:
            stats = dep_engine.get_graph_stats()
            dep_sources.append("data/dependency_graph.json")
            dep_chunks.append(f"Codebase stats: Modules={stats['modules']}, Edges={stats['edges']}, Cycles={stats['cycles']}")

        # 4. Deterministic Confidence Scoring
        base = 0.30
        knowledge_count = len(set(knowledge_sources))
        code_count = len(set(code_sources))
        dep_count = len(set(dep_sources))

        knowledge_hits = min(knowledge_count * 0.10, 0.30)
        code_hits = min(code_count * 0.10, 0.20)
        dependency_hits = min(dep_count * 0.05, 0.10)

        confidence = min(
            base +
            knowledge_hits +
            code_hits +
            dependency_hits +
            exact_match_bonus,
            1.0
        )
        # Round to 2 decimal places
        confidence = round(confidence, 2)

        # 5. Build prompt and run synthesis via Vertex Pro
        self.log_state_shift("RUNNING", "Synthesizing research briefing via Vertex AI...")

        sources = sorted(list(set(knowledge_sources + code_sources + dep_sources)))
        retrieved_context_preview = knowledge_chunks + code_chunks + dep_chunks

        # Format context for Vertex AI
        context_str = "\n\n".join(retrieved_context_preview)

        prompt = f"""
        You are ARIA's master Cloud Research Specialist powered by Vertex AI.
        Synthesize a highly comprehensive, executive-level technical briefing report for Chinmaya regarding the query: '{query}'.
        
        Cross-reference and analyze all retrieved context below:
        
        {context_str}
        
        Provide a beautifully organized, layout-focused answer strategy block. Highlight critical takeaways clearly.
        Cite sources used in your analysis.
        """

        model_used = "gemini-2.5-pro"
        report_text = ""
        
        # Invoke think_vertex
        if aria_ctx and hasattr(aria_ctx, "brain"):
            try:
                report_text = aria_ctx.brain.think_vertex(
                    prompt=prompt,
                    model_type="pro"
                )
            except Exception as e:
                report_text = f"Synthesis failure: {e}"
        else:
            report_text = "Cognitive context layer unavailable for cloud routing."

        # Structured report payload conforming to target schema
        report_payload = {
            "query": query,
            "report": report_text,
            "confidence": confidence,
            "sources": sources,
            "knowledge_sources": sorted(list(set(knowledge_sources))),
            "code_sources": sorted(list(set(code_sources))),
            "dependency_sources": sorted(list(set(dep_sources))),
            "retrieved_context_preview": retrieved_context_preview,
            "generated_at": int(time.time()),
            "model_used": model_used
        }

        # 6. Publish to Blackboard under 'research' topic
        self.blackboard.publish(
            topic="research",
            key=f"research_report_{task_id}",
            value=report_payload,
            source=self.agent_name,
            ttl_hours=24
        )

        self.log_state_shift("IDLE", "Research briefing synthesized and cached successfully.")
        return json.dumps({"status": "SUCCESS", "report": report_text, "metadata": report_payload})
