import os
import json
import hashlib
from typing import Dict, Any, List

from skills.base_agent import BaseAgent
from skills.blackboard import AriaBlackboard
from skills.code_parser import AriaCodeASTParser
from skills.code_vector_store import AriaCodeVectorStore
from skills.embedding_engine import AriaEmbeddingEngine

class AriaCodeSearchAgent(BaseAgent):
    def __init__(self, aria_instance=None, data_dir: str = "data"):
        super().__init__("CodeSearchAgent", aria_instance)
        self.blackboard = AriaBlackboard()
        self.data_dir = data_dir
        self.store = AriaCodeVectorStore(data_dir)
        self.encoder = AriaEmbeddingEngine()
        
        # Load store on startup
        self.store.load_store()

    @property
    def aria_inst(self):
        if self.aria is None:
            try:
                from skills.agent_orchestrator import AriaMultiAgentOrchestrator
                self.aria = AriaMultiAgentOrchestrator().aria
            except Exception:
                pass
        return self.aria

    def get_file_hash(self, file_path: str) -> str:
        """Computes MD5 hash of file content."""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                buf = f.read(65536)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = f.read(65536)
            return hasher.hexdigest()
        except Exception as e:
            print(f"[CodeSearchAgent] Hash error for {file_path}: {e}")
            return ""

    def sync_codebase_index(self, force_rebuild: bool = False) -> bool:
        """Indexes or incrementally reindexes workspace python codebase."""
        self.log_state_shift("RUNNING", "Scanning codebase for AST parsing...")
        parser = AriaCodeASTParser(root_dir=".")
        
        found_files = {}
        exclude_dirs = parser.exclude_dirs
        
        # Walk files recursively
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, ".").replace("\\", "/")
                    found_files[rel_path] = full_path

        changed = False
        
        # Force rebuild or clean deleted files
        if force_rebuild:
            print("[CodeSearchAgent] Forced rebuild requested. Clearing registry and chunks.")
            self.store.registry = {}
            self.store.chunk_store = []
            self.store.symbol_index = {}
            changed = True
        else:
            # Check for deleted files
            registry_keys = list(self.store.registry.keys())
            for file in registry_keys:
                if file not in found_files:
                    print(f"[CodeSearchAgent] File deleted: {file}. Removing nodes.")
                    self.store.remove_file_nodes(file)
                    del self.store.registry[file]
                    changed = True

        # Check for new or modified files
        for rel_path, full_path in found_files.items():
            current_hash = self.get_file_hash(full_path)
            current_mtime = os.path.getmtime(full_path)
            
            cached = self.store.registry.get(rel_path)
            is_changed = force_rebuild or (not cached) or (cached.get("file_hash") != current_hash) or (cached.get("last_modified") != current_mtime)
            
            if is_changed:
                print(f"[CodeSearchAgent] File changed or new: {rel_path}. Processing AST.")
                # Parse single file
                file_nodes = parser._parse_file_ast(full_path)
                
                # Remove old file nodes if they exist
                self.store.remove_file_nodes(rel_path)
                
                if file_nodes:
                    embeddable_nodes = [n for n in file_nodes if n["type"] != "FILE_DEPS"]
                    if embeddable_nodes:
                        texts = [n["text"] for n in embeddable_nodes]
                        embeddings = self.encoder.get_embeddings(texts)
                        if len(embeddable_nodes) == len(embeddings):
                            non_embeddable_nodes = [n for n in file_nodes if n["type"] == "FILE_DEPS"]
                            self.store.add_nodes(embeddable_nodes, embeddings)
                            # add non-embeddable directly
                            self.store.chunk_store.extend(non_embeddable_nodes)
                            
                            self.store.registry[rel_path] = {
                                "file_hash": current_hash,
                                "last_modified": current_mtime
                            }
                            changed = True
                        else:
                            print(f"[CodeSearchAgent] Skipping nodes in {rel_path} due to embedding mismatch.")
                    else:
                        # Only dependency nodes or empty
                        non_embeddable_nodes = [n for n in file_nodes if n["type"] == "FILE_DEPS"]
                        self.store.chunk_store.extend(non_embeddable_nodes)
                        self.store.registry[rel_path] = {
                            "file_hash": current_hash,
                            "last_modified": current_mtime
                        }
                        changed = True

        if changed:
            self.store.rebuild_faiss_index()
            self.store.serialize_store()
            self.log_state_shift("IDLE", "AST Vector space indexing sync successful.")
            return True
            
        self.log_state_shift("IDLE", "AST Vector space up-to-date. No changes indexed.")
        return False

    def run(self, task_id: str, task_description: str, payload: Dict[str, Any], campaign_id: str = None) -> str:
        self.log_state_shift("RUNNING", "Processing codebase query...")
        
        action = payload.get("action", "")
        # Trigger rebuild
        if "rebuild" in task_description.lower() or "refresh" in task_description.lower() or action in ("rebuild", "incremental_rebuild"):
            force = (action == "rebuild") or ("force" in task_description.lower())
            rebuilt = self.sync_codebase_index(force_rebuild=force)
            status = "REBUILT" if rebuilt else "UNCHANGED"
            return json.dumps({"status": "SUCCESS", "action": status})
            
        query = payload.get("query", "")
        if not query:
            query = task_description

        # Ensure index is loaded
        if not self.store.chunk_store:
            self.store.load_store()
            if not self.store.chunk_store:
                self.sync_codebase_index(force_rebuild=False)

        # 1. Check symbol index for exact match
        symbol_file = self.store.lookup_symbol(query.strip())
        exact_chunks = []
        if symbol_file:
            print(f"[CodeSearchAgent] Exact symbol match found: '{query.strip()}' in {symbol_file}")
            exact_chunks = [c for c in self.store.chunk_store if c.get("file") == symbol_file and (c.get("name") == query.strip() or f"{c.get('class')}.{c.get('name')}" == query.strip())]

        # 2. Query FAISS index for semantic matches
        matches = []
        query_embedding = self.encoder.get_embedding(query)
        if query_embedding:
            matches = self.store.search_code(query_embedding, k=3)

        # Combine results, prioritize exact chunks
        combined_chunks = exact_chunks + [m for m in matches if m not in exact_chunks]
        
        # Build context prompt
        contexts = []
        for c in combined_chunks[:3]:
            doc = c.get("docstring", "None")
            contexts.append(
                f"File: {c['file']} (Type: {c['type']}, Name: {c['name']}, Class: {c.get('class') or 'None'}, Lines: {c['start_line']}-{c['end_line']})\n"
                f"Docstring: {doc}\n"
                f"Source Snippet:\n{c['source']}"
            )

        context_str = "\n\n---\n\n".join(contexts) if contexts else "No codebase match found."

        # Fetch dependency context if dependency or import queried
        file_deps_contexts = []
        if "dependency" in query.lower() or "import" in query.lower() or "use" in query.lower():
            for c in self.store.chunk_store:
                if c.get("type") == "FILE_DEPS":
                    file_deps_contexts.append(f"File {c['file']} imports: {c['text'].split('Imports: ')[-1]}")

        dep_str = "\n".join(file_deps_contexts[:10]) if file_deps_contexts else ""

        # Try to enrich query with dependency graph context
        arch_details = ""
        try:
            from skills.dependency_graph import AriaDependencyGraphEngine
            dep_engine = AriaDependencyGraphEngine()
            dep_engine.build_system_architecture_map()
            
            # Extract possible module names from the query
            words = [w.strip("?,.!-").lower() for w in query.split() if len(w.strip("?,.!-")) > 3]
            matched_mods = []
            for w in words:
                for mod in dep_engine.graph:
                    if w == mod.lower() and mod not in matched_mods:
                        matched_mods.append(mod)
                        
            if matched_mods:
                lines = []
                for mod in matched_mods:
                    impact = dep_engine.trace_ripple_impact(mod)
                    if impact:
                        lines.append(f"- Modifying '{mod}' has direct ripple impact on: {', '.join(impact)}")
                if lines:
                    arch_details = "\n== CODEBASE DEPENDENCY IMPACT RADIUS ==\n" + "\n".join(lines)
        except Exception as e:
            print(f"[CodeSearchAgent] Error adding dependency context: {e}")

        dep_part = f"== FILE IMPORT DEPENDENCIES ==\n{dep_str}" if dep_str else ""
        prompt = f"""
        You are ARIA's advanced codebase intelligence and system search architect core. 
        Your goal is to answer developer questions about ARIA's internal system design, registrations, file structures, and code logic.
        Answer the developer's question using the semantically matched AST node blocks and imports below.
        Always cite the exact file name (relative path), class/function name, docstring, and line ranges.
        Provide a clean layout-focused technical answer.
        
        == USER QUESTION ==
        {query}
        
        == SEMANTICALLY MATCHED CODE CONTEXT ==
        {context_str}
        
        {dep_part}
        {arch_details}
        """

        # Synthesis via Gemini
        self.log_state_shift("RUNNING", "Synthesizing codebase explanation...")
        aria = self.aria_inst
        briefing = ""
        if aria and getattr(aria, "brain", None):
            try:
                briefing = aria.brain.think(prompt)
            except Exception as e:
                briefing = f"Brain model synthesis error: {e}"
        else:
            briefing = "Brain model is currently offline. Cannot synthesize RAG query."

        # Publish RAG result to Blackboard
        bb_key = f"codesearch_result_{task_id}"
        self.blackboard.publish(
            topic="system",
            key=bb_key,
            value={"query": query, "briefing": briefing, "contexts": combined_chunks},
            source=self.agent_name,
            ttl_hours=24
        )

        self.log_state_shift("IDLE", "Codebase search explanation synthesized.")
        return json.dumps({"status": "SUCCESS", "answer": briefing})
