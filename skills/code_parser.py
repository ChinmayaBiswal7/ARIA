import os
import ast
import json
from typing import List, Dict, Any

class AriaCodeASTParser:
    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self.exclude_dirs = ["aria_env", ".git", "__pycache__", "test_data", "failed_face_frames", ".firebase", ".pytest_cache", "chroma_db", "face_memory"]

    def extract_codebase_nodes(self) -> List[Dict[str, Any]]:
        """Scans workspace folders and uses ast compilers to extract clean logic entities."""
        discovered_nodes = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    discovered_nodes.extend(self._parse_file_ast(file_path))
        return discovered_nodes

    def _parse_file_ast(self, file_path: str) -> List[Dict[str, Any]]:
        nodes_list = []
        rel_path = os.path.relpath(file_path, self.root_dir).replace("\\", "/")
        
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source_code = f.read()
            
            tree = ast.parse(source_code, filename=file_path)
            lines = source_code.splitlines()
        except Exception as e:
            print(f"[ASTParser] Skipped unparsable file {rel_path}: {e}")
            return []

        file_imports = []

        for node in tree.body:
            # Handle attributes start_line & end_line safely
            start_line = getattr(node, "lineno", 1)
            end_line = getattr(node, "end_lineno", len(lines))
            raw_snippet = "\n".join(lines[start_line - 1:end_line])

            if isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node) or "None"
                meta_text = (
                    f"File: {rel_path}\n"
                    f"Type: CLASS\n"
                    f"Name: {node.name}\n"
                    f"Lines: {start_line}-{end_line}\n"
                    f"Docstring: {docstring}\n\n"
                    f"{raw_snippet}"
                )
                nodes_list.append({
                    "file": rel_path,
                    "type": "CLASS",
                    "name": node.name,
                    "class": None,
                    "start_line": start_line,
                    "end_line": end_line,
                    "docstring": docstring,
                    "text": meta_text,
                    "source": raw_snippet
                })

                # Extract methods inside class
                for sub_node in node.body:
                    if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sub_start = getattr(sub_node, "lineno", start_line)
                        sub_end = getattr(sub_node, "end_lineno", end_line)
                        sub_snippet = "\n".join(lines[sub_start - 1:sub_end])
                        sub_doc = ast.get_docstring(sub_node) or "None"
                        m_type = "METHOD"
                        
                        meta_text_method = (
                            f"File: {rel_path}\n"
                            f"Type: METHOD\n"
                            f"Class: {node.name}\n"
                            f"Name: {sub_node.name}\n"
                            f"Lines: {sub_start}-{sub_end}\n"
                            f"Docstring: {sub_doc}\n\n"
                            f"{sub_snippet}"
                        )
                        nodes_list.append({
                            "file": rel_path,
                            "type": m_type,
                            "name": sub_node.name,
                            "class": node.name,
                            "start_line": sub_start,
                            "end_line": sub_end,
                            "docstring": sub_doc,
                            "text": meta_text_method,
                            "source": sub_snippet
                        })

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node) or "None"
                b_type = "ASYNC_FUNCTION" if isinstance(node, ast.AsyncFunctionDef) else "FUNCTION"
                meta_text = (
                    f"File: {rel_path}\n"
                    f"Type: {b_type}\n"
                    f"Name: {node.name}\n"
                    f"Lines: {start_line}-{end_line}\n"
                    f"Docstring: {docstring}\n\n"
                    f"{raw_snippet}"
                )
                nodes_list.append({
                    "file": rel_path,
                    "type": b_type,
                    "name": node.name,
                    "class": None,
                    "start_line": start_line,
                    "end_line": end_line,
                    "docstring": docstring,
                    "text": meta_text,
                    "source": raw_snippet
                })

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    file_imports.append(alias.name)
                    meta_text = (
                        f"File: {rel_path}\n"
                        f"Type: IMPORT\n"
                        f"Name: {alias.name}\n"
                        f"AsName: {alias.asname or ''}\n"
                        f"Lines: {start_line}-{end_line}\n"
                    )
                    nodes_list.append({
                        "file": rel_path,
                        "type": "IMPORT",
                        "name": alias.name,
                        "class": None,
                        "start_line": start_line,
                        "end_line": end_line,
                        "docstring": "None",
                        "text": meta_text,
                        "source": raw_snippet
                    })

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full_name = f"{module}.{alias.name}" if module else alias.name
                    file_imports.append(full_name)
                    meta_text = (
                        f"File: {rel_path}\n"
                        f"Type: IMPORT\n"
                        f"Module: {module}\n"
                        f"Name: {alias.name}\n"
                        f"AsName: {alias.asname or ''}\n"
                        f"Lines: {start_line}-{end_line}\n"
                    )
                    nodes_list.append({
                        "file": rel_path,
                        "type": "IMPORT",
                        "name": alias.name,
                        "class": None,
                        "start_line": start_line,
                        "end_line": end_line,
                        "docstring": "None",
                        "text": meta_text,
                        "source": raw_snippet
                    })

        if file_imports:
            nodes_list.append({
                "file": rel_path,
                "type": "FILE_DEPS",
                "name": rel_path,
                "class": None,
                "start_line": 1,
                "end_line": len(lines) or 1,
                "docstring": "None",
                "text": f"File: {rel_path}\nImports: {', '.join(file_imports)}",
                "source": json.dumps({"source_file": rel_path, "imports": file_imports})
            })

        return nodes_list
