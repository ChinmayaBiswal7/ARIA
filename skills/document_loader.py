import os
import re
import hashlib

class AriaDocumentLoader:
    def __init__(self, vault_dir: str = "data/knowledge_vault"):
        self.vault_dir = vault_dir

    def extract_text(self, file_path: str) -> str:
        """Reads raw text content from PDF, DOCX, MD, and TXT files."""
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        try:
            if ext in [".txt", ".md"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            elif ext == ".pdf":
                import pypdf
                reader = pypdf.PdfReader(file_path)
                text = "".join([page.extract_text() or "" for page in reader.pages])
            elif ext == ".docx":
                import docx
                doc = docx.Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            print(f"[DocumentLoader] Error reading {file_path}: {e}")
        return text

    def chunk_text(self, text: str, file_path: str) -> list:
        """Splits document text into paragraph-aware chunks (500-800 characters) with overlap."""
        paragraphs = re.split(r'\n\s*\n', text)
        
        chunks = []
        current_chunk = ""
        chunk_idx = 0
        
        # Basic file info
        basename = os.path.basename(file_path)
        file_type = os.path.splitext(file_path)[1].lstrip('.').lower()
        
        # Topic extraction from parent directory relative to vault_dir
        rel_dir = os.path.relpath(os.path.dirname(file_path), self.vault_dir)
        if rel_dir != "." and rel_dir != "":
            topic = rel_dir.replace("\\", "/").split("/")[0].lower()
        else:
            # Fallback to file name prefix or general
            topic = basename.split("_")[0].split("-")[0].lower()
            if not topic:
                topic = "general"

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
                
            # If paragraph itself exceeds 800 chars, split it with 100 char overlap
            if len(para) > 800:
                if current_chunk:
                    chunks.append(self._create_chunk_dict(current_chunk, file_path, file_type, topic, chunk_idx))
                    chunk_idx += 1
                    current_chunk = ""
                
                start = 0
                while start < len(para):
                    end = start + 700
                    sub_para = para[start:end].strip()
                    if len(sub_para) > 40:
                        chunks.append(self._create_chunk_dict(sub_para, file_path, file_type, topic, chunk_idx))
                        chunk_idx += 1
                    start += 600  # 100 character overlap
                continue
                
            # Accumulate paragraphs to fit the 500-800 character range
            if len(current_chunk) + len(para) + 1 <= 800:
                if current_chunk:
                    current_chunk += "\n" + para
                else:
                    current_chunk = para
            else:
                # Flush the current chunk
                if current_chunk:
                    chunks.append(self._create_chunk_dict(current_chunk, file_path, file_type, topic, chunk_idx))
                    chunk_idx += 1
                    
                    # Carry over overlap
                    overlap_len = min(100, len(current_chunk))
                    overlap_text = current_chunk[-overlap_len:]
                    current_chunk = overlap_text + "\n" + para
                else:
                    current_chunk = para

        # Flush final chunk
        if current_chunk:
            chunks.append(self._create_chunk_dict(current_chunk, file_path, file_type, topic, chunk_idx))
            
        return chunks

    def _create_chunk_dict(self, text: str, file_path: str, file_type: str, topic: str, index: int) -> dict:
        """Constructs a chunk descriptor with MD5 hash as ID."""
        basename = os.path.basename(file_path)
        raw_id = f"{file_path}_{index}_{text}"
        chunk_id = hashlib.md5(raw_id.encode('utf-8')).hexdigest()
        return {
            "chunk_id": chunk_id,
            "source": basename,
            "file_type": file_type,
            "topic": topic,
            "chunk_index": index,
            "text": text
        }
