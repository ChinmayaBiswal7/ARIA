import unittest
import time
import os
import sys
import sqlite3

# Ensure root folder is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from skills.episodic_memory import EpisodicMemory, DB_PATH

class TestEpisodicMemory(unittest.TestCase):
    def setUp(self):
        self.mem = EpisodicMemory()
        self.username = "test_user_memory"
        
        # Clean up existing test records
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM episodic_events WHERE username = ?", (self.username,))
            conn.commit()

    def tearDown(self):
        # Clean up test records
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM episodic_events WHERE username = ?", (self.username,))
            conn.commit()

    def test_record_and_decay(self):
        # Record a temporary episode that is older than 1 day
        eid1 = self.mem.record(
            username=self.username,
            event_text="Temporary event to be deleted",
            retention_tier="temporary",
            importance=0.1,
            emotional_weight=0.1
        )
        
        # Record a weekly episode that is older than 7 days
        eid2 = self.mem.record(
            username=self.username,
            event_text="Weekly event to be archived",
            retention_tier="weekly",
            importance=0.2,
            emotional_weight=0.1
        )
        
        # Record a permanent episode that will be retained
        eid3 = self.mem.record(
            username=self.username,
            event_text="Permanent important event",
            retention_tier="permanent",
            importance=0.9,
            emotional_weight=0.8
        )
        
        # Manually alter timestamps to simulate time lapse
        now = time.time()
        one_day_ago = now - 90000        # > 24 hours
        eight_days_ago = now - 700000    # > 7 days
        
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE episodic_events SET timestamp = ? WHERE id = ?", (one_day_ago, eid1))
            conn.execute("UPDATE episodic_events SET timestamp = ? WHERE id = ?", (eight_days_ago, eid2))
            conn.commit()
            
        # Run decay pass
        stats = self.mem.decay_pass(self.username, now=now)
        
        # Check database to see if correct actions were taken
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM episodic_events WHERE username = ?", (self.username,)).fetchall()
            
        row_map = {r["id"]: r for r in rows}
        
        # eid1 (temporary) should be deleted
        self.assertNotIn(eid1, row_map)
        
        # eid2 (weekly) should be archived
        self.assertIn(eid2, row_map)
        self.assertEqual(row_map[eid2]["archived"], 1)
        self.assertTrue(row_map[eid2]["archive_summary"].startswith("[weekly-archived]"))
        
        # eid3 (permanent) should be retained and active
        self.assertIn(eid3, row_map)
        self.assertEqual(row_map[eid3]["archived"], 0)

    def test_compress_old_episodes(self):
        # We need more than 10 archived episodes to trigger compression
        ids = []
        for i in range(12):
            eid = self.mem.record(
                username=self.username,
                event_text=f"Event {i} that is archived",
                retention_tier="permanent",
                importance=0.2,
                emotional_weight=0.1
            )
            ids.append(eid)
            
        # Mark them as archived
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE episodic_events SET archived = 1 WHERE username = ?", (self.username,))
            conn.commit()
            
        # Run compression
        self.mem.compress_old_episodes(self.username)
        
        # Verify that they were deleted and replaced by a consolidated block
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM episodic_events WHERE username = ?", (self.username,)).fetchall()
            
        # The 12 original archived items should be deleted
        for eid in ids:
            self.assertNotIn(eid, [r["id"] for r in rows])
            
        # There should be exactly 1 consolidated permanent item left
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["archived"], 0)
        self.assertTrue(rows[0]["event_text"].startswith("Aggregated faded memory:"))

if __name__ == "__main__":
    unittest.main()
