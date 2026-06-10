import sqlite3
import json
import time
import os
import threading
from datetime import datetime
from typing import Optional, List, Dict, Tuple

DB_PATH = "aria_knowledge.db"

# Existing smart graph DB path for backward compatibility
LEGACY_DB_PATH = "aria_memory.db"


class AriaSmartGraph:
    """Manages the Layer 3 Knowledge Graph database logic with confidence, tracking, and decay."""
    
    def __init__(self, db_path=LEGACY_DB_PATH):
        self.db_path = db_path

    def get_or_create_node(self, node_type, name, initial_confidence=1.0, importance=0.5):
        """Creates a node if it does not exist, enforcing UNIQUE constraints."""
        node_type = node_type.strip().title()
        name = name.strip()
        now = int(time.time())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO knowledge_graph_nodes (type, name, created_at, confidence, importance)
                VALUES (?, ?, ?, ?, ?)
            """, (node_type, name, now, initial_confidence, importance))
            conn.commit()
            
            cursor.execute("SELECT id FROM knowledge_graph_nodes WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print(f"[AriaSmartGraph] Error in get_or_create_node: {e}")
            return None
        finally:
            conn.close()

    def learn_relationship(self, source_node, relation, target_node, source_type="Conversation", initial_conf=0.6):
        """
        Inserts a new connection or strengthens an existing one.
        source_node: tuple (type, name) or string name
        target_node: tuple (type, name) or string name
        """
        s_type, s_name = source_node if isinstance(source_node, tuple) else ("Concept", source_node)
        t_type, t_name = target_node if isinstance(target_node, tuple) else ("Concept", target_node)
        relation = relation.strip().lower()
        now = int(time.time())

        s_importance = 1.0 if s_name.lower() in ["chinmay", "chinmaya", "aria", "aria app"] else 0.5
        t_importance = 1.0 if t_name.lower() in ["chinmay", "chinmaya", "aria", "aria app"] else 0.5

        source_id = self.get_or_create_node(s_type, s_name, importance=s_importance)
        target_id = self.get_or_create_node(t_type, t_name, importance=t_importance)

        if not source_id or not target_id:
            print(f"[AriaSmartGraph] Error: Failed to resolve node IDs for {s_name} or {t_name}")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT confidence FROM knowledge_graph_edges
                WHERE source_id = ? AND relation = ? AND target_id = ?
            """, (source_id, relation, target_id))
            row = cursor.fetchone()

            if row:
                curr_conf = row[0]
                new_conf = min(0.99, curr_conf + (1.0 - curr_conf) * 0.4)
                cursor.execute("""
                    UPDATE knowledge_graph_edges
                    SET confidence = ?, last_seen = ?, source = ?
                    WHERE source_id = ? AND relation = ? AND target_id = ?
                """, (new_conf, now, source_type, source_id, relation, target_id))
                print(f"[AriaSmartGraph] Reinforced relationship: ({s_name}) -[{relation}]-> ({t_name}) (Confidence: {new_conf:.2f})")
            else:
                cursor.execute("""
                    INSERT INTO knowledge_graph_edges (source_id, relation, target_id, confidence, last_seen, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (source_id, relation, target_id, initial_conf, now, source_type))
                print(f"[AriaSmartGraph] Learned new relationship: ({s_name}) -[{relation}]-> ({t_name}) (Confidence: {initial_conf:.2f})")
            conn.commit()
        except Exception as e:
            print(f"[AriaSmartGraph] Error in learn_relationship: {e}")
        finally:
            conn.close()

    def query_subgraph(self, username="chinmay", min_confidence=0.5):
        """Retrieves 1-hop and 2-hop relationships connected to the user."""
        username = username.strip()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        relations = []
        try:
            cursor.execute("""
                SELECT n1.name, n1.type, e.relation, n2.name, n2.type, e.confidence
                FROM knowledge_graph_edges e
                JOIN knowledge_graph_nodes n1 ON e.source_id = n1.id
                JOIN knowledge_graph_nodes n2 ON e.target_id = n2.id
                WHERE (n1.name = ? OR n2.name = ?) AND e.confidence >= ?
                ORDER BY e.confidence DESC, e.last_seen DESC LIMIT 30
            """, (username, username, min_confidence))
            direct = cursor.fetchall()
            relations.extend(direct)
            
            cursor.execute("""
                SELECT n1.name, n1.type, e.relation, n2.name, n2.type, e.confidence
                FROM knowledge_graph_edges e
                JOIN knowledge_graph_nodes n1 ON e.source_id = n1.id
                JOIN knowledge_graph_nodes n2 ON e.target_id = n2.id
                WHERE n1.id IN (
                    SELECT target_id FROM knowledge_graph_edges 
                    WHERE source_id = (SELECT id FROM knowledge_graph_nodes WHERE name = ?)
                ) AND e.confidence >= ?
                ORDER BY e.confidence DESC, e.last_seen DESC LIMIT 30
            """, (username, min_confidence))
            indirect = cursor.fetchall()
            relations.extend(indirect)
            
            seen = set()
            deduped = []
            for r in relations:
                key = (r[0], r[2], r[3])
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)
            return deduped
        except Exception as e:
            print(f"[AriaSmartGraph] Subgraph query error: {e}")
            return []
        finally:
            conn.close()

    def apply_memory_decay(self, decay_rate=0.02, threshold_days=30):
        """Decays relationship confidence for items not seen recently."""
        now = int(time.time())
        threshold_seconds = threshold_days * 86400
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE knowledge_graph_edges
                SET confidence = MAX(0.1, confidence - ?)
                WHERE (? - last_seen) > ?
            """, (decay_rate, now, threshold_seconds))
            conn.commit()
            print("[AriaSmartGraph] Memory decay pass completed.")
        except Exception as e:
            print(f"[AriaSmartGraph] Memory decay error: {e}")
        finally:
            conn.close()


class KnowledgeGraph:
    """
    SQLite-backed personal knowledge graph.
    Stores nodes, edges, and facts about Chinmaya's life.
    Supports status checks ('confirmed' vs 'unconfirmed') and source priorities.
    """
    _instance = None
    _lock = threading.Lock()

    # Source Priority Ratings
    SOURCE_PRIORITIES = {
        "voice": 100,
        "manual": 90,
        "git_scan": 70,
        "calendar": 60,
        "conversation": 50,
        "window_monitor": 30,
    }

    def __new__(cls, db_path=DB_PATH):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(KnowledgeGraph, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path=DB_PATH):
        if self._initialized:
            return
        self.db_path = db_path
        self._db_lock = threading.Lock()
        self._init_db()
        self._initialized = True
        print("[KnowledgeGraph] Initialized SQLite knowledge graph.")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    properties TEXT DEFAULT '{}',
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'unconfirmed',
                    source TEXT DEFAULT 'manual',
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    updated_at REAL DEFAULT (strftime('%s', 'now')),
                    UNIQUE(name, node_type)
                );

                CREATE TABLE IF NOT EXISTS kg_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_node_id INTEGER NOT NULL,
                    to_node_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    properties TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'unconfirmed',
                    source TEXT DEFAULT 'manual',
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    FOREIGN KEY(from_node_id) REFERENCES kg_nodes(id),
                    FOREIGN KEY(to_node_id) REFERENCES kg_nodes(id),
                    UNIQUE(from_node_id, to_node_id, relation)
                );

                CREATE TABLE IF NOT EXISTS kg_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'unconfirmed',
                    source TEXT DEFAULT 'manual',
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    UNIQUE(subject, predicate, object)
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_type ON kg_nodes(node_type);
                CREATE INDEX IF NOT EXISTS idx_edges_from ON kg_edges(from_node_id);
                CREATE INDEX IF NOT EXISTS idx_edges_to ON kg_edges(to_node_id);
            """)

    def _should_update(self, existing_source: str, new_source: str) -> bool:
        """Evaluate source priority matrix to handle write precedence."""
        existing_prio = self.SOURCE_PRIORITIES.get(existing_source or "", 0)
        new_prio = self.SOURCE_PRIORITIES.get(new_source or "", 0)
        return new_prio >= existing_prio

    # ── Node Operations ──────────────────────────────

    def add_node(self, name, node_type, properties=None, confidence=1.0, source="manual", status="unconfirmed"):
        name = name.strip()
        node_type = node_type.strip().lower()
        props_dict = properties or {}
        
        with self._db_lock:
            existing = self.get_node(name, node_type)
            if existing:
                # Resolve source priorities
                if self._should_update(existing.get('source'), source):
                    # Merge properties
                    try:
                        exist_props = json.loads(existing.get('properties', '{}'))
                    except Exception:
                        exist_props = {}
                    exist_props.update(props_dict)
                    
                    merged_props = json.dumps(exist_props)
                    new_conf = max(existing.get('confidence', 0.0), confidence)
                    new_status = 'confirmed' if (status == 'confirmed' or existing.get('status') == 'confirmed') else 'unconfirmed'
                    
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_nodes 
                            SET properties=?, confidence=?, status=?, source=?, updated_at=strftime('%s', 'now')
                            WHERE id=?
                        """, (merged_props, new_conf, new_status, source, existing['id']))
                else:
                    # Higher priority exists. Only reinforce confidence.
                    new_conf = max(existing.get('confidence', 0.0), confidence)
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_nodes SET confidence=? WHERE id=?
                        """, (new_conf, existing['id']))
            else:
                # Insert new node
                props_str = json.dumps(props_dict)
                with self._get_conn() as conn:
                    conn.execute("""
                        INSERT INTO kg_nodes (name, node_type, properties, confidence, status, source)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (name, node_type, props_str, confidence, status, source))
                    
        return self.get_node(name, node_type)

    def get_node(self, name, node_type):
        name = name.strip()
        node_type = node_type.strip().lower()
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM kg_nodes WHERE name=? AND node_type=?
            """, (name, node_type)).fetchone()
            return dict(row) if row else None

    def get_nodes_by_type(self, node_type):
        node_type = node_type.strip().lower()
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM kg_nodes WHERE node_type=? ORDER BY confidence DESC, updated_at DESC
            """, (node_type,)).fetchall()
            return [dict(r) for r in rows]

    # ── Edge Operations ──────────────────────────────

    def add_edge(self, from_name, from_type, to_name, to_type, relation, weight=1.0, properties=None, source="manual", status="unconfirmed"):
        from_node = self.add_node(from_name, from_type, source=source, status=status)
        to_node = self.add_node(to_name, to_type, source=source, status=status)
        if not from_node or not to_node:
            return False
            
        relation = relation.strip().lower()
        props_dict = properties or {}
        
        with self._db_lock:
            # Check existing edge
            with self._get_conn() as conn:
                existing = conn.execute("""
                    SELECT * FROM kg_edges WHERE from_node_id=? AND to_node_id=? AND relation=?
                """, (from_node['id'], to_node['id'], relation)).fetchone()
                
            if existing:
                existing = dict(existing)
                if self._should_update(existing.get('source'), source):
                    try:
                        exist_props = json.loads(existing.get('properties', '{}'))
                    except Exception:
                        exist_props = {}
                    exist_props.update(props_dict)
                    
                    merged_props = json.dumps(exist_props)
                    new_weight = max(existing.get('weight', 0.0), weight)
                    new_status = 'confirmed' if (status == 'confirmed' or existing.get('status') == 'confirmed') else 'unconfirmed'
                    
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_edges SET weight=?, properties=?, status=?, source=? WHERE id=?
                        """, (new_weight, merged_props, new_status, source, existing['id']))
                else:
                    new_weight = max(existing.get('weight', 0.0), weight)
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_edges SET weight=? WHERE id=?
                        """, (new_weight, existing['id']))
            else:
                props_str = json.dumps(props_dict)
                with self._get_conn() as conn:
                    conn.execute("""
                        INSERT INTO kg_edges (from_node_id, to_node_id, relation, weight, properties, status, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (from_node['id'], to_node['id'], relation, weight, props_str, status, source))
        return True

    def get_edges(self, name, node_type, direction="both"):
        node = self.get_node(name, node_type)
        if not node:
            return []
        nid = node['id']
        with self._get_conn() as conn:
            if direction == "out":
                rows = conn.execute("""
                    SELECT e.*, n2.name as to_name, n2.node_type as to_type
                    FROM kg_edges e
                    JOIN kg_nodes n2 ON e.to_node_id = n2.id
                    WHERE e.from_node_id=?
                """, (nid,)).fetchall()
            elif direction == "in":
                rows = conn.execute("""
                    SELECT e.*, n1.name as from_name, n1.node_type as from_type
                    FROM kg_edges e
                    JOIN kg_nodes n1 ON e.from_node_id = n1.id
                    WHERE e.to_node_id=?
                """, (nid,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT e.*, n1.name as from_name, n1.node_type as from_type, n2.name as to_name, n2.node_type as to_type
                    FROM kg_edges e
                    JOIN kg_nodes n1 ON e.from_node_id = n1.id
                    JOIN kg_nodes n2 ON e.to_node_id = n2.id
                    WHERE e.from_node_id=? OR e.to_node_id=?
                """, (nid, nid)).fetchall()
            return [dict(r) for r in rows]

    # ── Fact Operations ──────────────────────────────

    def add_fact(self, subject, predicate, obj, confidence=1.0, source="manual", status="unconfirmed"):
        subject = subject.strip()
        predicate = predicate.strip().lower()
        obj = obj.strip()
        
        with self._db_lock:
            with self._get_conn() as conn:
                existing = conn.execute("""
                    SELECT * FROM kg_facts WHERE subject=? AND predicate=? AND object=?
                """, (subject, predicate, obj)).fetchone()
                
            if existing:
                existing = dict(existing)
                if self._should_update(existing.get('source'), source):
                    new_conf = max(existing.get('confidence', 0.0), confidence)
                    new_status = 'confirmed' if (status == 'confirmed' or existing.get('status') == 'confirmed') else 'unconfirmed'
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_facts SET confidence=?, status=?, source=? WHERE id=?
                        """, (new_conf, new_status, source, existing['id']))
                else:
                    new_conf = max(existing.get('confidence', 0.0), confidence)
                    with self._get_conn() as conn:
                        conn.execute("""
                            UPDATE kg_facts SET confidence=? WHERE id=?
                        """, (new_conf, existing['id']))
            else:
                with self._get_conn() as conn:
                    conn.execute("""
                        INSERT INTO kg_facts (subject, predicate, object, confidence, status, source)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (subject, predicate, obj, confidence, status, source))

    def get_facts(self, subject=None, predicate=None):
        query = "SELECT * FROM kg_facts WHERE 1=1"
        params = []
        if subject:
            query += " AND subject=?"
            params.append(subject)
        if predicate:
            query += " AND predicate=?"
            params.append(predicate)
        query += " ORDER BY confidence DESC"
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ── Context Retrieval & Querying ─────────────────

    def query_profile_summary(self) -> str:
        """Returns a human-readable summary of everything ARIA knows about Chinmaya."""
        lines = []

        projects = self.get_nodes_by_type("project")
        if projects:
            names = [p['name'] for p in projects]
            lines.append(f"Projects: {', '.join(names)}")

        skills = self.get_nodes_by_type("skill")
        if skills:
            top = sorted(skills, key=lambda x: x.get('confidence', 0.0), reverse=True)[:10]
            names = [f"{s['name']} ({s['status']})" for s in top]
            lines.append(f"Skills: {', '.join(names)}")

        subjects = self.get_nodes_by_type("subject")
        if subjects:
            names = [s['name'] for s in subjects]
            lines.append(f"Studying: {', '.join(names)}")

        applications = self.get_nodes_by_type("application")
        if applications:
            names = [a['name'] for a in applications]
            lines.append(f"Applied to: {', '.join(names)}")

        goals = self.get_nodes_by_type("goal")
        if goals:
            names = [g['name'] for g in goals]
            lines.append(f"Goals: {', '.join(names)}")

        facts = self.get_facts(subject="chinmaya")
        for f in facts[:5]:
            lines.append(f"{f['predicate'].replace('_', ' ').title()}: {f['object']}")

        return "\n".join(lines) if lines else "No profile data yet."

    def retrieve_relevant_profile(self, query: str) -> str:
        """
        Retrieves a subset of the profile that is lexically relevant to the query.
        Falls back to a general brief summary if no direct matches occur.
        """
        if not query:
            return ""

        words = [w.strip("?,.!-").lower() for w in query.split() if len(w.strip("?,.!-")) > 3]
        if not words:
            return ""

        matched_nodes = []
        matched_facts = []

        with self._get_conn() as conn:
            # Query nodes matching keywords ordered by priority
            node_placeholders = ",".join(["?"] * len(words))
            node_rows = conn.execute(f"""
                SELECT * FROM kg_nodes 
                WHERE name IN ({node_placeholders}) 
                   OR properties LIKE '%' || ? || '%'
                ORDER BY 
                  CASE source
                    WHEN 'voice' THEN 100
                    WHEN 'manual' THEN 90
                    WHEN 'git_scan' THEN 70
                    WHEN 'calendar' THEN 60
                    WHEN 'conversation' THEN 50
                    WHEN 'window_monitor' THEN 30
                    ELSE 0
                  END DESC,
                  confidence DESC,
                  updated_at DESC
                LIMIT 15
            """, (*words, query.lower())).fetchall()
            matched_nodes = [dict(r) for r in node_rows]

            # Query facts matching keywords ordered by priority
            fact_conditions = []
            fact_params = []
            for w in words:
                fact_conditions.append("(subject LIKE '%' || ? || '%' OR predicate LIKE '%' || ? || '%' OR object LIKE '%' || ? || '%')")
                fact_params.extend([w, w, w])
            fact_placeholders = " OR ".join(fact_conditions)
            
            fact_rows = conn.execute(f"""
                SELECT * FROM kg_facts 
                WHERE {fact_placeholders}
                ORDER BY 
                  CASE source
                    WHEN 'voice' THEN 100
                    WHEN 'manual' THEN 90
                    WHEN 'git_scan' THEN 70
                    WHEN 'calendar' THEN 60
                    WHEN 'conversation' THEN 50
                    WHEN 'window_monitor' THEN 30
                    ELSE 0
                  END DESC,
                  confidence DESC,
                  created_at DESC
                LIMIT 15
            """, fact_params).fetchall()
            matched_facts = [dict(r) for r in fact_rows]

        # Format retrieved content
        lines = []
        if matched_nodes:
            lines.append("== RELEVANT PROFILE NODES ==")
            for n in matched_nodes:
                props = json.loads(n.get('properties', '{}'))
                desc = f" ({props.get('description')})" if props.get('description') else ""
                lines.append(f"- {n['name']} ({n['node_type']}, {n['status']}){desc}")

        if matched_facts:
            lines.append("== RELEVANT RELATIONSHIPS ==")
            for f in matched_facts:
                lines.append(f"- {f['subject']} --({f['predicate']})--> {f['object']} (status: {f['status']})")

        # If nothing matches, return a brief overview
        if not lines:
            summary = self.query_profile_summary()
            if summary != "No profile data yet.":
                lines.append("== GENERAL PROFILE BRIEFING ==")
                # Limit summary output to first 5 lines to preserve context window budget
                lines.extend(summary.split("\n")[:5])

        return "\n".join(lines) if lines else ""

    def find_relevant_projects(self, topic: str) -> List[Dict]:
        """
        Find projects relevant to a given topic/skill.
        Returns a ranked list of dicts with match score and plain-text reasons.
        """
        topic_lower = topic.lower()
        projects = self.get_nodes_by_type("project")
        scored = []
        
        for p in projects:
            score = 0.0
            reasons = []
            try:
                props = json.loads(p.get('properties', '{}'))
            except Exception:
                props = {}

            # Match in project name
            if topic_lower in p['name'].lower():
                score += 3.0
                reasons.append(f"Project name matches '{topic}'")

            # Match in description
            desc = props.get('description', '').lower()
            if topic_lower in desc:
                score += 1.5
                reasons.append(f"Description matches keyword '{topic}'")

            # Match in tags
            tags = props.get('tags', [])
            if any(topic_lower in t.lower() for t in tags):
                score += 2.0
                matched_tags = [t for t in tags if topic_lower in t.lower()]
                reasons.append(f"Project tags match skill: {', '.join(matched_tags)}")

            # Check language/skill connections
            edges = self.get_edges(p['name'], 'project', 'out')
            for e in edges:
                to_name = e.get('to_name', '').lower()
                if topic_lower in to_name:
                    score += 1.5
                    reasons.append(f"Project is connected to skill: '{e.get('to_name')}'")

            if score > 0.0:
                scored.append({
                    "name": p['name'],
                    "node_type": p['node_type'],
                    "score": score,
                    "reasons": reasons,
                    "properties": props
                })

        # Rank by score desc
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored


def process_conversation_turn(username, user_msg, assist_reply):
    """
    Background worker that runs a fact extraction prompt on the dialogue turn
    and updates the SQLite knowledge graph.
    """
    # 1. Filtration check: avoid running extraction on obvious trivial small talk
    trivial_words = {"hello", "hi", "how are you", "what is", "search for", "bye", "good morning", "thank you", "thanks"}
    clean_msg = user_msg.strip().lower()
    if clean_msg in trivial_words or len(clean_msg) < 8:
        return

    # Check if there are structural cues in the sentence
    structural_triggers = ["friend", "works", "using", "project", "goal", "build", "member", "study", "git", "dependency", "develop", "organize", "planning", "event", "next month"]
    has_trigger = any(t in clean_msg for t in structural_triggers)
    if not has_trigger:
        # If no explicit trigger, skip to prevent junk extraction
        return

    print(f"[AriaSmartGraph] Structural triggers matched in conversation turn. Initiating extraction...")

    # 2. Extract facts via Brain Raw Model
    from brain import Brain
    brain = Brain()
    
    prompt = f"""
    You are ARIA's memory extraction engine. Analyze this conversation turn and extract key structural facts about people, projects, goals, technologies, or events.
    Output ONLY raw comma-separated lines for each fact found using this exact format:
    Source_Type | Source_Name | Relation | Target_Type | Target_Name

    Example conversation:
    User: Rahul is my friend and he works at Google.
    Assistant: I will remember that.
    Example output:
    Person | Chinmay | friend | Person | Rahul
    Person | Rahul | works_at | Company | Google

    Current Conversation Turn:
    User: {user_msg}
    ARIA: {assist_reply}

    Strict Rules:
    1. If no new structural relationship facts are found, output nothing.
    2. Output ONLY the lines matching the format. Do not add explanations or surrounding text.
    """

    try:
        raw_output = brain.think_raw(prompt)
        if not raw_output or not raw_output.strip():
            return
        
        # 3. Filter and save relationships
        graph = AriaSmartGraph()
        lines = raw_output.strip().split("\n")
        
        for line in lines:
            if "|" not in line:
                continue
            
            parts = [item.strip() for item in line.split("|")]
            if len(parts) == 5:
                s_type, s_name, relation, t_type, t_name = parts
                
                # Junk filtration filters
                invalid_tokens = {"weather", "something", "stuff", "it", "that", "today", "yesterday", "tomorrow", "now"}
                if s_name.lower() in invalid_tokens or t_name.lower() in invalid_tokens:
                    continue
                
                # Check for self-reference normalization
                if s_name.lower() in ["i", "me", "my", "user", "owner"]:
                    s_name = username
                    s_type = "Person"
                if t_name.lower() in ["i", "me", "my", "user", "owner"]:
                    t_name = username
                    t_type = "Person"
                
                # Save to advanced graph
                graph.learn_relationship(
                    (s_type, s_name),
                    relation,
                    (t_type, t_name),
                    source_type="Conversation Log"
                )
    except Exception as ex:
        print(f"[AriaSmartGraph] Process turn error: {ex}")

