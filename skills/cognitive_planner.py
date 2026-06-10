"""
skills/cognitive_planner.py — Deprecated Cognitive Planner Facade
==================================================================
This module has been deprecated in favor of skills/learning_skill.py.
It is kept for backwards compatibility.
"""

import json
import re
import os
import sqlite3
import datetime
from skills.active_context import ActiveContext

class AriaCognitivePlanner:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AriaCognitivePlanner, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    def fetch_notes(self, target):
        import warnings
        warnings.warn("AriaCognitivePlanner is deprecated. Use AriaLearningSkill instead.", DeprecationWarning)
        print("[Planner] DEPRECATED: Delegating fetch_notes to AriaLearningSkill")
        from skills.learning_skill import AriaLearningSkill
        return AriaLearningSkill().fetch_notes(target)

    def orchestrate_goal(self, aria, goal_text):
        import warnings
        warnings.warn("AriaCognitivePlanner is deprecated. Use AriaLearningSkill instead.", DeprecationWarning)
        print("[Planner] DEPRECATED: Delegating orchestrate_goal to AriaLearningSkill")
        from skills.learning_skill import AriaLearningSkill
        
        # Instantiate learning skill and temporarily forward fetch_notes 
        # to self.fetch_notes to respect any mocks/patches on this instance.
        skill = AriaLearningSkill()
        original_fetch = skill.fetch_notes
        skill.fetch_notes = self.fetch_notes
        try:
            return skill.orchestrate_study_goal(aria, goal_text)
        finally:
            skill.fetch_notes = original_fetch

def handle_cognitive_planning_cmd(aria, inp, user_input):
    planner = AriaCognitivePlanner()
    clean_goal = user_input.lower().replace("help me study for", "").replace("help me prepare for", "").replace("study plan for", "").replace("plan the goal", "").replace("orchestrate task", "").strip()
    res = planner.orchestrate_goal(aria, clean_goal)
    return res
