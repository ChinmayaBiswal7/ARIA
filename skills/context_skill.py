import ctypes
from ctypes import wintypes
import socket
import subprocess
import time

# ctypes structure for Windows system power monitoring
class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ('ACLineStatus', wintypes.BYTE),
        ('BatteryFlag', wintypes.BYTE),
        ('BatteryLifePercent', wintypes.BYTE),
        ('Reserved1', wintypes.BYTE),
        ('BatteryLifeTime', wintypes.DWORD),
        ('BatteryFullLifeTime', wintypes.DWORD),
    ]

class ContextSkill:
    """Detects active desktop context (battery percentage, wifi connectivity, foreground app)."""

    def get_battery_percent(self):
        """Retrieve battery percentage using Windows kernel32."""
        status = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            percent = status.BatteryLifePercent
            if percent == 255:  # Windows returns 255 for unknown/desktop no battery
                return None
            return percent
        return None

    def get_charging_status(self):
        """Check if laptop is plugged in."""
        status = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            # ACLineStatus: 1 = online (charging), 0 = offline (discharging)
            return status.ACLineStatus == 1
        return False

    def get_active_window(self):
        """Get the title of the currently focused desktop window."""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return "Desktop"
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return "Desktop"
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def get_wifi_status(self):
        """Check if connected to the internet."""
        try:
            socket.setdefaulttimeout(1.5)
            # Try to connect to DNS server
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
            return "Connected"
        except Exception:
            return "Disconnected"

    def get_context_summary(self):
        """Return a formatted text summary of PC state."""
        battery = self.get_battery_percent()
        charging = self.get_charging_status()
        active = self.get_active_window()
        wifi = self.get_wifi_status()

        battery_txt = f"{battery}%" if battery is not None else "Desktop (No Battery)"
        if charging and battery is not None:
            battery_txt += " (Charging)"
            
        return (
            f"Active Window: {active}\n"
            f"Power Level: {battery_txt}\n"
            f"Network: {wifi}"
        )

    def get_active_window_info(self):
        """
        Get info about the currently focused desktop window.
        Returns a tuple: (pid, process_name, window_title)
        """
        try:
            import win32gui
            import win32process
            import win32api
            import win32con
            import os
            
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return 0, "Idle", "Desktop"
                
            # Get window title
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                title = "Desktop"
            else:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                
            # Get PID
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            
            # Get process name
            try:
                handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
                path = win32process.GetModuleFileNameEx(handle, 0)
                process_name = os.path.basename(path)
            except Exception:
                process_name = "unknown"
                
            return pid, process_name, title
        except Exception as e:
            print(f"[ContextSkill] Error getting window info: {e}")
            # Fallback using standard ctypes title retrieval
            title = self.get_active_window()
            return 0, "unknown", title


class WindowEvent:
    def __init__(self, pid: int, app_name: str, window_title: str, source: str = "DesktopPerceptionService", accessibility_tree: dict = None):
        self.event_type = "WINDOW_FOCUS_CHANGED"
        self.pid = pid
        self.app_name = app_name.upper().strip()
        self.window_title = window_title
        self.source = source
        self.timestamp = time.time()
        self.accessibility_tree = accessibility_tree or {}

    def to_json(self) -> str:
        import json
        return json.dumps(self.__dict__)


from collections import OrderedDict

class AriaDesktopPerceptionService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AriaDesktopPerceptionService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, aria_instance=None, db_path: str = "aria_orchestrator.db"):
        if self._initialized:
            return
        self.aria = aria_instance
        self.db_path = db_path
        
        # Debouncing and Signature Caches
        self.last_pid = -1
        self.last_app = "IDLE"
        self.last_title = ""
        self.last_shift_timestamp = time.time()
        
        # Fixed LRU Cache Constraints
        self.MAX_CACHE_ENTRIES = 100
        self.accessibility_cache = OrderedDict()
        self._initialized = True

    def process_window_focus_event(self, event: WindowEvent) -> bool:
        """Processes foreground switches with strict window debouncing and cache limits."""
        now = time.time()
        duration_seconds = int(now - self.last_shift_timestamp)

        # ── REFINEMENT 1: DEBOUNCING MECHANISM ──────────────────────────────
        # Ignore sudden changes under 2.0 seconds unless you switched to a completely different process
        if event.pid == self.last_pid and event.window_title == self.last_title:
            return False
            
        if event.pid == self.last_pid and (now - self.last_shift_timestamp) < 2.0:
            # Title fluctuated too fast (e.g., VS Code loading or unsaved asterisks), skip update
            return False

        # ── LOG FOCUS TELEMETRY ─────────────────────────────────────────────
        # Only commit if app switch duration is >= 30 seconds to prevent DB write bloat
        if duration_seconds >= 30 and self.last_app != "IDLE":
            self._archive_focus_duration(self.last_app, self.last_title, self.last_pid, duration_seconds)

        # ── REFINEMENT 2: SIZE-LIMITED LEAST-RECENTLY-USED CACHE ────────────
        if event.accessibility_tree:
            cache_key = f"{event.pid}_{event.app_name}"
            # Pop and move item to ensure correct LRU sequence orders
            if cache_key in self.accessibility_cache:
                self.accessibility_cache.pop(cache_key)
            elif len(self.accessibility_cache) >= self.MAX_CACHE_ENTRIES:
                self.accessibility_cache.popitem(last=False) # Evict oldest entry
            
            self.accessibility_cache[cache_key] = {
                "tree": event.accessibility_tree,
                "cached_at": now
            }

        # Update core runtime state bounds
        self.last_pid = event.pid
        self.last_app = event.app_name
        self.last_title = event.window_title
        self.last_shift_timestamp = now

        print(f"[PerceptionService] Focus Block Context: {self.last_app} (PID: {self.last_pid})")

        # Share the fresh context vector onto the Blackboard for other skills to consume
        if self.aria and hasattr(self.aria, "broker") and self.aria.broker:
            self.aria.broker.share_data(
                key="active_desktop_context",
                source=event.source,
                payload={
                    "pid": self.last_pid,
                    "app_name": self.last_app,
                    "window_title": self.last_title,
                    "timestamp": now
                }
            )
        return True

    def get_cached_accessibility_tree(self, pid: int, app_name: str) -> dict:
        """Exposes the active cache interface to external apps or the Executive Brain."""
        cache_key = f"{pid}_{app_name.upper().strip()}"
        if cache_key in self.accessibility_cache:
            return self.accessibility_cache[cache_key]["tree"]
        return {}

    def _archive_focus_duration(self, app: str, title: str, pid: int, duration: int):
        """Archives your raw workspace focus hours directly into the timeline database."""
        import sqlite3
        import os
        
        # Ensure target directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vision_event_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    timestamp INTEGER, 
                    event_description TEXT, 
                    sequence_duration_seconds INTEGER
                )
            """)
            conn.execute("""
                INSERT INTO vision_event_timeline (timestamp, event_description, sequence_duration_seconds)
                VALUES (?, ?, ?)
            """, (int(time.time()), f"Focused on app: {app} (PID: {pid}) - Title: {title}", duration))
            conn.commit()
            conn.close()
            print(f"[PerceptionService] Flushed focus session to DB: {app} for {duration}s")
        except Exception as e:
            print(f"[PerceptionService] DB Write failed: {e}")


