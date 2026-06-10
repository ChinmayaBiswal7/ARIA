import threading

class ActiveContext:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.current_goal = None
        self.active_project = None
        self.active_window = None
        self.active_file = None
        self.last_error = None
        self.last_plan = None
        self.last_task = None
        self.focus_mode = None
        self._initialized = True

    def reset(self):
        self.current_goal = None
        self.active_project = None
        self.active_window = None
        self.active_file = None
        self.last_error = None
        self.last_plan = None
        self.last_task = None
        self.focus_mode = None
