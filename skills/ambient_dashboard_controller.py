# skills/ambient_dashboard_controller.py
import os
import time
import sqlite3
from typing import Dict, Any, Optional

class AmbientDashboardController:
    """
    Orchestrates dynamic widget layout compilation (Chameleon View contracts)
    and SQLite context persistence for the ARIA Observability Center.
    """

    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aria_orchestrator.db")
        self._init_db()

    def _init_db(self):
        """Creates the active session tracking table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_dashboard_session (
                    key TEXT PRIMARY KEY,
                    tab TEXT,
                    entity_id TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        except Exception as e:
            print(f"[AmbientController] Database initialization error: {e}")
        finally:
            conn.close()

    def set_tab(self, tab: str, entity_id: Optional[str] = None):
        """
        Updates the active dashboard tab and entity context in SQLite and CognitionState.
        Sends a non-blocking POST fallback call.
        """
        print(f"[AmbientDashboard] set_tab({tab}, entity_id={entity_id})")
        # 1. Update SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO active_dashboard_session (key, tab, entity_id, last_updated)
                VALUES ('active_tab', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET 
                tab=excluded.tab,
                entity_id=excluded.entity_id,
                last_updated=CURRENT_TIMESTAMP
            """, (tab, entity_id or ""))
            conn.commit()
        except Exception as e:
            print(f"[AmbientController] Error saving session to SQLite: {e}")
        finally:
            conn.close()

        # 2. Update CognitionState in-process
        try:
            from dashboard import CognitionState
            CognitionState.ambient_active_tab = tab
            CognitionState.ambient_context_entity = entity_id or ""
            CognitionState.ambient_last_updated = int(time.time())
        except ImportError:
            pass

        # 3. Non-blocking HTTP POST fallback
        import requests
        import threading
        
        def push_tab_post():
            try:
                res = requests.post("http://127.0.0.1:8000/api/v1/viewport/set-tab", json={
                    "tab": tab,
                    "entity_id": entity_id or ""
                }, timeout=1)
                print(f"[AmbientDashboard/HTTP] POST /api/v1/viewport/set-tab status: {res.status_code}")
            except Exception as http_err:
                print(f"[AmbientDashboard/HTTP] POST /api/v1/viewport/set-tab failed: {http_err}")
                
        threading.Thread(target=push_tab_post, daemon=True).start()

    def push_widget_payload(self, view_type: str, payload: Dict[str, Any], refresh_seconds: int = 30):
        """
        Updates CognitionState with a dynamic Chameleon contract.
        Infers the dashboard tab and updates SQLite.
        """
        # Normalize view_type (e.g. NEWSWIDGET -> NEWS_WIDGET)
        if isinstance(view_type, str):
            view_type = view_type.upper().strip()
            # If it's a known widget without underscore, normalize it
            known_widgets_no_underscore = {
                "SPORTSWIDGET": "SPORTS_WIDGET",
                "NEWSWIDGET": "NEWS_WIDGET",
                "WEATHERWIDGET": "WEATHER_WIDGET",
                "STOCKWIDGET": "STOCK_WIDGET",
                "STOCKS_WIDGET": "STOCK_WIDGET",
                "STOCKSWIDGET": "STOCK_WIDGET",
                "SEARCHWIDGET": "SEARCH_WIDGET",
                "PERSONWIDGET": "PERSON_WIDGET",
                "PRODUCTWIDGET": "PRODUCT_WIDGET",
                "VIDEOWIDGET": "VIDEO_WIDGET",
                "AMBIENTWIDGET": "AMBIENT_WIDGET"
            }
            if view_type in known_widgets_no_underscore:
                view_type = known_widgets_no_underscore[view_type]

        print(f"[AmbientDashboard] push_widget_payload({view_type})")
        tab_map = {
            "SPORTS_WIDGET": "SPORTS",
            "NEWS_WIDGET": "NEWS",
            "WEATHER_WIDGET": "WEATHER",
            "STOCK_WIDGET": "STOCKS",
            "SEARCH_WIDGET": "SEARCH",
            "PERSON_WIDGET": "PEOPLE",
            "PRODUCT_WIDGET": "PRODUCTS",
            "VIDEO_WIDGET": "VIDEOS",
            "AMBIENT_WIDGET": "AMBIENT"
        }
        tab = tab_map.get(view_type, "AMBIENT")
        entity_id = None
        
        # Infer entity context from payload
        if view_type == "SPORTS_WIDGET" and isinstance(payload, dict):
            entity_id = f"MATCH_{payload.get('match_title', '').replace(' ', '_')}"
        elif view_type == "PERSON_WIDGET" and isinstance(payload, dict):
            entity_id = f"PERSON_{payload.get('name', '').replace(' ', '_')}"
        elif view_type == "PRODUCT_WIDGET" and isinstance(payload, dict):
            entity_id = f"PROD_{payload.get('name', '').replace(' ', '_')}"
        elif view_type == "WEATHER_WIDGET" and isinstance(payload, dict):
            entity_id = payload.get("location", "")

        # Write tab/session context
        self.set_tab(tab, entity_id)

        # Compile Chameleon data packet
        widget_data = {
            "view_type": view_type,
            "refresh_interval_seconds": refresh_seconds,
            "payload": payload
        }

        # Update CognitionState in-process
        try:
            from dashboard import CognitionState
            CognitionState.ambient_widget_data = widget_data
            CognitionState.ambient_last_updated = int(time.time())
        except ImportError:
            pass

        # Non-blocking HTTP POST fallback
        import requests
        import threading
        
        def push_widget_post():
            try:
                res = requests.post("http://127.0.0.1:8000/api/v1/viewport/widget-data", json=widget_data, timeout=1)
                print(f"[AmbientDashboard/HTTP] POST /api/v1/viewport/widget-data status: {res.status_code}")
            except Exception as http_err:
                print(f"[AmbientDashboard/HTTP] POST /api/v1/viewport/widget-data failed: {http_err}")
                
        threading.Thread(target=push_widget_post, daemon=True).start()

        # Bring the ARIA Dashboard browser window to the front
        def focus_dashboard_window():
            try:
                import sys
                import os
                # Detect test suite runs using sys.argv / environment
                is_testing = False
                if os.environ.get('TESTING') == 'True':
                    is_testing = True
                else:
                    for arg in sys.argv:
                        if 'pytest' in arg or 'unittest' in arg or 'test_' in arg:
                            is_testing = True
                            break
                if is_testing:
                    print("[AmbientDashboard] Focus dashboard bypassed (testing detected).")
                    return
                
                print("[AmbientDashboard] Attempting dashboard focus...")
                if os.name == 'nt':
                    from skills.desktop_control_skill import AriaDesktopControlSkill
                    ds = AriaDesktopControlSkill()
                    success, msg = ds.focus_window("ARIA Dashboard")
                    if success:
                        print(f"[AmbientDashboard] Focused dashboard window: {msg}")
                        return
                    else:
                        print(f"[AmbientDashboard] Dashboard focus failed: {msg}")
                
                print("[AmbientDashboard] Dashboard window not found or OS not NT. Opening browser...")
                import webbrowser
                webbrowser.open("http://127.0.0.1:8000/public/dashboard.html")
                print(f"[AmbientDashboard] Re-opened dashboard URL in browser.")
            except Exception as focus_err:
                print(f"[AmbientDashboard] Focus dashboard window failed: {focus_err}")

        threading.Thread(target=focus_dashboard_window, daemon=True).start()

    def resolve_context(self, user_query: str) -> str:
        """
        Reads the last active session from SQLite.
        If a vague query is detected, appends the active tab context.
        """
        query_lower = (user_query or "").lower().strip()
        
        # Connect to SQLite to read active session
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT tab, entity_id FROM active_dashboard_session WHERE key = 'active_tab'")
            row = cursor.fetchone()
            if not row:
                return user_query
            tab, entity_id = row[0], row[1]
        except Exception as e:
            print(f"[AmbientController] SQLite active tab query failed: {e}")
            return user_query
        finally:
            conn.close()
            
        if not tab or tab == "AMBIENT":
            return user_query
            
        # High-signal vague keywords mapping to active dashboard screens
        vague_sports = ["who is winning", "who is batting", "who is bowling", "what is the score", "wickets", "overs", "runs", "match scorecard", "scorecard", "highlights", "cricket", "who won"]
        vague_weather = ["weather", "forecast", "temp", "temperature", "rain", "humidity", "wind", "how is it"]
        vague_news = ["news", "headlines", "articles", "read more", "show headlines", "what is it about"]
        vague_stocks = ["price", "trend", "share", "value", "stock", "chart"]
        vague_person = ["bio", "age", "stats", "images", "photos", "about him", "about her", "career", "records", "who is he", "who is she"]
        vague_product = ["price", "reviews", "features", "specs", "buy now", "amazon", "buy link", "how much"]
        
        if tab == "SPORTS" and entity_id and any(w in query_lower for w in vague_sports):
            clean_entity = entity_id.replace("MATCH_", "").replace("_", " ")
            return f"{user_query} (Context: active cricket match {clean_entity})"
        elif tab == "WEATHER" and entity_id and any(w in query_lower for w in vague_weather):
            return f"{user_query} (Context: weather in {entity_id})"
        elif tab == "PEOPLE" and entity_id and any(w in query_lower for w in vague_person):
            clean_entity = entity_id.replace("PERSON_", "").replace("_", " ")
            return f"{user_query} (Context: person {clean_entity})"
        elif tab == "PRODUCTS" and entity_id and any(w in query_lower for w in vague_product):
            clean_entity = entity_id.replace("PROD_", "").replace("_", " ")
            return f"{user_query} (Context: product {clean_entity})"
            
        return user_query
