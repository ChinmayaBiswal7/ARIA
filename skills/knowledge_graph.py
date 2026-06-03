import os
import sys
import time
import json
import sqlite3

DB_PATH = "aria_memory.db"

class AriaSmartGraph:
    """Manages the Layer 3 Knowledge Graph database logic with confidence, tracking, and decay."""
    
    def __init__(self, db_path=DB_PATH):
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
        # Parse inputs
        s_type, s_name = source_node if isinstance(source_node, tuple) else ("Concept", source_node)
        t_type, t_name = target_node if isinstance(target_node, tuple) else ("Concept", target_node)
        relation = relation.strip().lower()
        now = int(time.time())

        # Enforce importance defaults
        s_importance = 1.0 if s_name.lower() in ["chinmay", "chinmaya", "aria", "aria app"] else 0.5
        t_importance = 1.0 if t_name.lower() in ["chinmay", "chinmaya", "aria", "aria app"] else 0.5

        # Get or create node IDs
        source_id = self.get_or_create_node(s_type, s_name, importance=s_importance)
        target_id = self.get_or_create_node(t_type, t_name, importance=t_importance)

        if not source_id or not target_id:
            print(f"[AriaSmartGraph] Error: Failed to resolve node IDs for {s_name} or {t_name}")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Check if connection already exists
            cursor.execute("""
                SELECT confidence FROM knowledge_graph_edges
                WHERE source_id = ? AND relation = ? AND target_id = ?
            """, (source_id, relation, target_id))
            row = cursor.fetchone()

            if row:
                # Reinforce connection confidence asymptotically towards 1.0
                curr_conf = row[0]
                new_conf = min(0.99, curr_conf + (1.0 - curr_conf) * 0.4)
                cursor.execute("""
                    UPDATE knowledge_graph_edges
                    SET confidence = ?, last_seen = ?, source = ?
                    WHERE source_id = ? AND relation = ? AND target_id = ?
                """, (new_conf, now, source_type, source_id, relation, target_id))
                print(f"[AriaSmartGraph] Reinforced relationship: ({s_name}) -[{relation}]-> ({t_name}) (Confidence: {new_conf:.2f})")
            else:
                # Insert new relationship with initial confidence (defaults to 0.6)
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
            # 1. Fetch 1-hop relations
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
            
            # 2. Fetch 2-hop relations (where source is a target of the user's direct connections)
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
            
            # Deduplicate while preserving order
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
            # We decay confidence by decay_rate. If confidence drops below 0.25, we could prune or keep at minimum 0.1
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
    structural_triggers = ["friend", "works", "using", "project", "goal", "build", "member", "study", "git", "dependency", "develop"]
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
