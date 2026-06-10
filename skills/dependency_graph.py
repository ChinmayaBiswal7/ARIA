import os
import ast
import json
import hashlib
from typing import Dict, Any, List, Set

class AriaDependencyGraphEngine:
    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self.exclude_dirs = ["aria_env", ".git", "__pycache__", "test_data", "failed_face_frames", ".firebase", ".pytest_cache", "chroma_db", "face_memory"]
        self.db_path = "data/dependency_graph.json"
        
        # Adjacency list: Map module -> Set of modules it imports (outgoing dependencies)
        self.graph: Dict[str, Set[str]] = {}
        # Reverse adjacency list: Map module -> Set of modules that import it (incoming dependencies)
        self.reverse_graph: Dict[str, Set[str]] = {}
        # Registry to track file hashes and last modified dates
        self.registry: Dict[str, Dict[str, Any]] = {}
        
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)

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
            print(f"[DependencyEngine] Hash error for {file_path}: {e}")
            return ""

    def load_store(self) -> bool:
        """Loads persistent dependency details from disk."""
        if not os.path.exists(self.db_path):
            return False
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.registry = data.get("registry", {})
                
                imports_data = data.get("imports", {})
                if isinstance(imports_data, list):
                    self.graph = {}
                    for item in imports_data:
                        if isinstance(item, dict) and "module" in item and "imports" in item:
                            self.graph[item["module"]] = set(item["imports"])
                elif isinstance(imports_data, dict):
                    self.graph = {k: set(v) for k, v in imports_data.items()}
                else:
                    graph_data = data.get("graph", {})
                    self.graph = {k: set(v) for k, v in graph_data.items()}
                
                imported_by_data = data.get("imported_by", {})
                if isinstance(imported_by_data, list):
                    self.reverse_graph = {}
                    for item in imported_by_data:
                        if isinstance(item, dict) and "module" in item and "imported_by" in item:
                            self.reverse_graph[item["module"]] = set(item["imported_by"])
                elif isinstance(imported_by_data, dict):
                    self.reverse_graph = {k: set(v) for k, v in imported_by_data.items()}
                else:
                    rev_graph_data = data.get("reverse_graph", {})
                    self.reverse_graph = {k: set(v) for k, v in rev_graph_data.items()}
            print(f"[DependencyEngine] Dependency store loaded with {len(self.graph)} modules.")
            return True
        except Exception as e:
            print(f"[DependencyEngine] Load error: {e}")
            return False

    def serialize_store(self) -> bool:
        """Saves current state to JSON."""
        try:
            imports_list = []
            imported_by_list = []
            for k in sorted(self.graph.keys()):
                imports_list.append({
                    "module": k,
                    "imports": sorted(list(self.graph[k]))
                })
                imported_by_list.append({
                    "module": k,
                    "imported_by": sorted(list(self.reverse_graph.get(k, [])))
                })

            data = {
                "registry": self.registry,
                "graph": {k: sorted(list(v)) for k, v in self.graph.items()},
                "reverse_graph": {k: sorted(list(v)) for k, v in self.reverse_graph.items()},
                "imports": imports_list,
                "imported_by": imported_by_list
            }
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[DependencyEngine] Saved dependency store with {len(self.graph)} modules.")
            return True
        except Exception as e:
            print(f"[DependencyEngine] Serialize error: {e}")
            return False

    def build_system_architecture_map(self, force_rebuild: bool = False) -> bool:
        """Scans codebase incrementally to map out imports and construct dependency graphs."""
        # Clean graphs if full rebuild requested
        if force_rebuild:
            self.graph.clear()
            self.reverse_graph.clear()
            self.registry.clear()

        # Try to load existing data
        if not force_rebuild and not self.graph:
            self.load_store()

        found_modules = {}
        # Walk directories recursively
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.root_dir).replace("\\", "/")
                    module_name = os.path.splitext(file)[0]
                    found_modules[module_name] = (full_path, rel_path)

        # Set default empty sets for all found modules
        for mod in found_modules:
            if mod not in self.graph:
                self.graph[mod] = set()
            if mod not in self.reverse_graph:
                self.reverse_graph[mod] = set()

        changed = False

        # Clean registry for deleted files
        registry_keys = list(self.registry.keys())
        for mod in registry_keys:
            if mod not in found_modules:
                print(f"[DependencyEngine] Module deleted: {mod}. Removing dependencies.")
                if mod in self.graph:
                    del self.graph[mod]
                if mod in self.reverse_graph:
                    del self.reverse_graph[mod]
                del self.registry[mod]
                changed = True

        # Scan new or modified files
        for mod, (full_path, rel_path) in found_modules.items():
            current_hash = self.get_file_hash(full_path)
            current_mtime = os.path.getmtime(full_path)
            
            cached = self.registry.get(mod)
            is_changed = force_rebuild or (not cached) or (cached.get("file_hash") != current_hash) or (cached.get("last_modified") != current_mtime)

            if is_changed:
                print(f"[DependencyEngine] File changed or new: {mod} ({rel_path}). Parsing imports.")
                # Clear previous outgoing deps
                self.graph[mod] = set()
                
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        tree = ast.parse(f.read(), filename=full_path)
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                base_mod = alias.name.split(".")[-1]
                                if base_mod in found_modules and base_mod != mod:
                                    self.graph[mod].add(base_mod)
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            base_mod = node.module.split(".")[-1]
                            if base_mod in found_modules and base_mod != mod:
                                self.graph[mod].add(base_mod)
                            # Also check if actual imported symbols are modules in the codebase
                            for alias in node.names:
                                base_alias = alias.name.split(".")[-1]
                                if base_alias in found_modules and base_alias != mod:
                                    self.graph[mod].add(base_alias)
                except Exception as e:
                    print(f"[DependencyEngine] Error parsing imports for {mod}: {e}")
                
                self.registry[mod] = {
                    "file_hash": current_hash,
                    "last_modified": current_mtime,
                    "rel_path": rel_path
                }
                changed = True

        # Re-build the reverse graph (imported_by) based on the updated graph
        if changed:
            # Reinitialize reverse graph
            self.reverse_graph = {mod: set() for mod in self.graph}
            for source_mod, dependencies in self.graph.items():
                for target_mod in dependencies:
                    if target_mod in self.reverse_graph:
                        self.reverse_graph[target_mod].add(source_mod)
            
            self.serialize_store()
            return True

        return False

    def trace_ripple_impact(self, target_module: str) -> List[str]:
        """Identifies which modules directly depend on target_module."""
        target_clean = target_module.split(".")[-1]
        if target_clean not in self.reverse_graph:
            return []
        return sorted(list(self.reverse_graph[target_clean]))

    def compile_call_path(self, start_module: str, target_module: str, visited=None) -> List[str]:
        """Calculates a directional import/call path between two components."""
        start_clean = start_module.split(".")[-1]
        target_clean = target_module.split(".")[-1]
        
        if visited is None:
            visited = set()
        
        if start_clean == target_clean:
            return [start_clean]
            
        visited.add(start_clean)
        if start_clean in self.graph:
            for neighbor in self.graph[start_clean]:
                if neighbor not in visited:
                    path = self.compile_call_path(neighbor, target_clean, visited)
                    if path:
                        return [start_clean] + path
        return []

    def find_circular_dependencies(self) -> List[List[str]]:
        """Identifies unique circular dependency loops in the graph."""
        visited = set()
        rec_stack = []
        cycles = []

        def dfs(node):
            if node in rec_stack:
                idx = rec_stack.index(node)
                cycle_path = rec_stack[idx:] + [node]
                # Normalize loop: rotate cycle path so it always starts with the lexicographically smallest module name
                sub_cycle = cycle_path[:-1]
                min_idx = sub_cycle.index(min(sub_cycle))
                rotated = sub_cycle[min_idx:] + sub_cycle[:min_idx] + [sub_cycle[min_idx]]
                if rotated not in cycles:
                    cycles.append(rotated)
                return
            
            if node in visited:
                return
                
            visited.add(node)
            rec_stack.append(node)
            if node in self.graph:
                for neighbor in self.graph[node]:
                    dfs(neighbor)
            rec_stack.pop()

        for module in self.graph:
            dfs(module)
            
        return cycles

    def get_graph_stats(self) -> Dict[str, Any]:
        """Returns metadata statistics about codebase architecture graph."""
        modules = len(self.graph)
        edges = sum(len(deps) for deps in self.graph.values())
        cycles = self.find_circular_dependencies()
        
        # Sorted by length of reverse graph values (incoming dependency count)
        depended_on_sorted = sorted(
            [(k, len(v)) for k, v in self.reverse_graph.items()],
            key=lambda x: x[1],
            reverse=True
        )
        most_depended_on = [item[0] for item in depended_on_sorted if item[1] > 0]
        
        return {
            "modules": modules,
            "edges": edges,
            "cycles": len(cycles),
            "most_depended_on": most_depended_on[:10]
        }
