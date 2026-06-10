import os
import json
import sqlite3
import time
from typing import Dict, Any, List

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
from skills.document_loader import AriaDocumentLoader
from skills.embedding_engine import AriaEmbeddingEngine
from skills.vector_store import AriaVectorStore

class AriaKnowledgeSearchAgent(BaseAgent):
    def __init__(self, aria_instance=None, vault_dir: str = "data/knowledge_vault"):
        super().__init__("KnowledgeSearchAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        self.vault_dir = vault_dir
        
        self.loader = AriaDocumentLoader(vault_dir)
        self.encoder = AriaEmbeddingEngine()
        self.vector_store = AriaVectorStore(vault_dir)
        
        # Load index on startup
        self.vector_store.load()
        # Perform initial incremental index refresh
        self.rebuild_knowledge_index()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def rebuild_knowledge_index(self) -> bool:
        """Scans the vault folder recursively, incrementally reindexing modified/new files."""
        if not os.path.exists(self.vault_dir):
            os.makedirs(self.vault_dir)
            
        found_files = {}
        changed = False
        
        # 1. Scan directory
        for root, _, files in os.walk(self.vault_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in [".pdf", ".docx", ".md", ".txt"]:
                    continue
                file_path = os.path.join(root, file)
                found_files[file] = file_path

        # 2. Check for deleted files
        registry_keys = list(self.vector_store.registry.keys())
        for file in registry_keys:
            if file not in found_files:
                print(f"[KnowledgeSearchAgent] File deleted on disk: {file}. Removing from index.")
                # We construct mock path to remove chunks by basename
                self.vector_store.remove_document(os.path.join(self.vault_dir, file))
                changed = True

        # 3. Check for new or modified files
        for file, file_path in found_files.items():
            current_hash = self.vector_store.get_file_hash(file_path)
            current_mtime = os.path.getmtime(file_path)
            
            cached = self.vector_store.registry.get(file)
            is_changed = False
            
            if not cached:
                print(f"[KnowledgeSearchAgent] New file found: {file}. Indexing.")
                is_changed = True
            elif cached.get("file_hash") != current_hash or cached.get("last_modified") != current_mtime:
                print(f"[KnowledgeSearchAgent] File modified: {file}. Re-indexing.")
                is_changed = True
                
            if is_changed:
                text = self.loader.extract_text(file_path)
                if len(text.strip()) > 20:
                    chunks = self.loader.chunk_text(text, file_path)
                    chunk_texts = [c["text"] for c in chunks]
                    embeddings = self.encoder.get_embeddings(chunk_texts)
                    
                    if chunks and embeddings and len(chunks) == len(embeddings):
                        self.vector_store.add_document_chunks(file_path, chunks, embeddings)
                        self.vector_store.registry[file] = {
                            "file_hash": current_hash,
                            "last_modified": current_mtime
                        }
                        changed = True
                    else:
                        print(f"[KnowledgeSearchAgent] Skipping empty/failed chunking for {file}")
                else:
                    # File is empty/too small, ensure it is removed
                    self.vector_store.remove_document(file_path)
                    changed = True

        # 4. Save and rebuild index if anything changed
        if changed:
            self.vector_store.update_index_from_chunks()
            self.vector_store.save()
            print("[KnowledgeSearchAgent] Incremental re-indexing completed successfully.")
            return True
            
        return False

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Processing semantic RAG workflow...")

        action = payload.get("action", "")
        # Check task description for rebuild trigger
        if "rebuild" in task_description.lower() or "refresh" in task_description.lower() or action == "rebuild":
            self.log_state_shift("RUNNING", "Rebuilding knowledge vault index...")
            rebuilt = self.rebuild_knowledge_index()
            status = "REBUILT" if rebuilt else "UNCHANGED"
            self.log_state_shift("IDLE", f"Knowledge vault index: {status}.")
            return json.dumps({"status": "SUCCESS", "action": status})

        query = payload.get("query", "")
        if not query:
            query = payload.get("target", "")
        if not query:
            query = task_description

        # --- retrieval hierarchy order ---
        contexts = []

        # 1. Knowledge Vault (top-4 chunks)
        query_embedding = self.encoder.get_embedding(query)
        vault_chunks = []
        if query_embedding:
            vault_chunks = self.vector_store.search(query_embedding, k=4)
            for c in vault_chunks:
                contexts.append(f"Source notes [{c['source']}] (Topic: {c['topic']}): {c['text']}")

        # 2. Project Memory (aria_projects.json & Knowledge Graph)
        project_details = self._retrieve_project_context(query)
        if project_details:
            contexts.append(f"Project Memory:\n{project_details}")

        # 3. Career Database (career_opportunities in aria_memory.db)
        career_details = self._retrieve_career_context(query)
        if career_details:
            contexts.append(f"Career Postings Database:\n{career_details}")

        # 4. Knowledge Graph (aria_knowledge.db)
        kg_details = self._retrieve_kg_context(query)
        if kg_details:
            contexts.append(f"Knowledge Graph Profile:\n{kg_details}")

        # 5. User Preferences (aria_memory.db preferences table)
        pref_details = self._retrieve_user_preferences(query)
        if pref_details:
            contexts.append(f"User Profile Preferences:\n{pref_details}")

        # Generate Synthesis Briefing via Gemini
        self.log_state_shift("RUNNING", "Synthesizing answer with retrieved context...")
        final_briefing = self._generate_synthesis_briefing(query, contexts)

        # Publish result to blackboard
        bb_key = f"search_result_{task_id}"
        self.blackboard.publish(
            topic="knowledge",
            key=bb_key,
            value={"query": query, "briefing": final_briefing, "contexts": vault_chunks},
            source=self.agent_name,
            ttl_hours=24
        )

        self.log_state_shift("IDLE", "RAG query response synthesized and saved to blackboard.")
        return json.dumps({"status": "SUCCESS", "answer": final_briefing})

    def _retrieve_project_context(self, query: str) -> str:
        """Searches projects inside aria_projects.json and the Knowledge Graph."""
        projects_info = []
        query_lower = query.lower()
        
        # 1. Search aria_projects.json
        projects_file = "aria_projects.json"
        if os.path.exists(projects_file):
            try:
                with open(projects_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    active_projects = data.get("active_projects", {})
                    for p_name, p_data in active_projects.items():
                        # Simple keyword overlap match
                        p_desc = p_data.get("last_session_summary", "")
                        p_focus = p_data.get("current_focus", "")
                        p_tools = ", ".join(p_data.get("associated_tools", []))
                        
                        if (query_lower in p_name.lower() or 
                            query_lower in p_desc.lower() or 
                            query_lower in p_focus.lower() or 
                            query_lower in p_tools.lower()):
                            
                            projects_info.append(
                                f"- Project: {p_name} | Status: {p_data.get('status')} | "
                                f"Tools: {p_tools} | Focus: {p_focus} | Summary: {p_desc}"
                            )
            except Exception as e:
                print(f"[KnowledgeSearchAgent] Project JSON search error: {e}")

        # 2. Search Knowledge Graph projects
        try:
            from skills.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph()
            # Split query into words to find relevant topics
            words = [w.strip("?,.!-").lower() for w in query.split() if len(w.strip("?,.!-")) > 3]
            for w in words[:2]:
                kg_proj = kg.find_relevant_projects(w)
                for p in kg_proj:
                    p_name = p.get("name", "")
                    p_reasons = ", ".join(p.get("reasons", []))
                    projects_info.append(f"- Project: {p_name} (KG match: {p_reasons})")
        except Exception:
            pass

        return "\n".join(list(set(projects_info))) if projects_info else ""

    def _retrieve_career_context(self, query: str) -> str:
        """Queries career_opportunities in aria_memory.db matching keyword query."""
        db_path = "aria_memory.db"
        results = []
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                # Simple keyword search on role, company, or notes
                like_query = f"%{query}%"
                cursor.execute("""
                    SELECT company, role, match_score, status, notes 
                    FROM career_opportunities 
                    WHERE role LIKE ? OR company LIKE ? OR notes LIKE ?
                    LIMIT 3
                """, (like_query, like_query, like_query))
                
                for r in cursor.fetchall():
                    results.append(
                        f"- Listing: {r['role']} at {r['company']} (Status: {r['status']}, "
                        f"Match Score: {r['match_score']}%, Notes: {r['notes']})"
                    )
                conn.close()
            except Exception as e:
                print(f"[KnowledgeSearchAgent] Career DB query error: {e}")
        return "\n".join(results) if results else ""

    def _retrieve_kg_context(self, query: str) -> str:
        """Retrieves profile facts lexically relevant to the query from the Knowledge Graph."""
        try:
            from skills.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph()
            return kg.retrieve_relevant_profile(query)
        except Exception:
            return ""

    def _retrieve_user_preferences(self, query: str) -> str:
        """Gathers user preferences matching keywords in the query."""
        results = []
        try:
            from skills.memory_manager import MemoryManager
            prefs = MemoryManager().get_preferences("chinmay")
            query_lower = query.lower()
            
            for key, val in prefs.items():
                if query_lower in key.lower() or query_lower in str(val).lower():
                    results.append(f"- {key}: {val}")
        except Exception:
            pass
        return "\n".join(results) if results else ""

    def _generate_synthesis_briefing(self, query: str, contexts: List[str]) -> str:
        context_block = "\n\n".join(contexts)
        
        prompt = f"""
        You are ARIA's advanced academic search and retrieval core brain layer. 
        Chinmaya has asked a question. Answer it by synthesizing the semantically matched context blocks below.
        If the topic relates to competitive programming, placement data, or computer science terms, prioritize technical clarity.
        Provide a clean layout-focused answer. Highlight specific file names, project titles, and match metrics if visible.
        
        == USER COMMAND ==
        {query}
        
        == SEMANTICALLY RETRIEVED RELEVANT MATERIAL ==
        {context_block if context_block else "No document or memory context found."}
        """
        
        aria = self.aria_inst
        if aria and getattr(aria, "brain", None):
            try:
                return aria.brain.think(prompt)
            except Exception as e:
                return f"Brain model synthesis layer error: {e}"
        return "Brain model is currently offline. Cannot synthesize RAG query."
