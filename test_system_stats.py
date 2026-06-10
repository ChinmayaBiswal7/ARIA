import unittest
from unittest.mock import MagicMock, patch

from skills.memory_commands import get_system_stats, handle_personal_notes_pc_status
from skills.command_router import handle_memory

class TestSystemStats(unittest.TestCase):
    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    @patch('psutil.sensors_battery')
    def test_get_system_stats_with_battery(self, mock_battery, mock_disk, mock_ram, mock_cpu):
        # Setup mocks
        mock_cpu.return_value = 34.0
        
        mock_ram_obj = MagicMock()
        mock_ram_obj.percent = 61.0
        mock_ram_obj.used = 9.8 * (1024 ** 3)
        mock_ram_obj.total = 16.0 * (1024 ** 3)
        mock_ram.return_value = mock_ram_obj
        
        mock_disk_obj = MagicMock()
        mock_disk_obj.percent = 45.0
        mock_disk_obj.free = 234.5 * (1024 ** 3)
        mock_disk.return_value = mock_disk_obj
        
        mock_battery_obj = MagicMock()
        mock_battery_obj.percent = 87.0
        mock_battery_obj.power_plugged = True
        mock_battery.return_value = mock_battery_obj
        
        # Execute
        stats = get_system_stats()
        
        # Verify
        expected = (
            "CPU usage is 34.0%. RAM usage is 61.0%, that's 9.8 of 16.0 gigabytes used. "
            "Disk usage is 45.0%, 234.5 gigabytes free. Battery is at 87% and charging."
        )
        self.assertEqual(stats, expected)

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    @patch('psutil.sensors_battery')
    def test_get_system_stats_no_battery(self, mock_battery, mock_disk, mock_ram, mock_cpu):
        # Setup mocks
        mock_cpu.return_value = 12.5
        
        mock_ram_obj = MagicMock()
        mock_ram_obj.percent = 40.0
        mock_ram_obj.used = 8.0 * (1024 ** 3)
        mock_ram_obj.total = 20.0 * (1024 ** 3)
        mock_ram.return_value = mock_ram_obj
        
        mock_disk_obj = MagicMock()
        mock_disk_obj.percent = 30.0
        mock_disk_obj.free = 500.0 * (1024 ** 3)
        mock_disk.return_value = mock_disk_obj
        
        mock_battery.return_value = None
        
        # Execute
        stats = get_system_stats()
        
        # Verify
        expected = (
            "CPU usage is 12.5%. RAM usage is 40.0%, that's 8.0 of 20.0 gigabytes used. "
            "Disk usage is 30.0%, 500.0 gigabytes free."
        )
        self.assertEqual(stats, expected.strip())

    @patch('psutil.cpu_percent')
    def test_get_system_stats_error_handling(self, mock_cpu):
        mock_cpu.side_effect = Exception("System error")
        stats = get_system_stats()
        self.assertEqual(stats, "Sorry, I could not retrieve system stats.")

    @patch('skills.memory_commands.get_system_stats')
    def test_handle_personal_notes_pc_status_routing(self, mock_get_stats):
        mock_get_stats.return_value = "Mocked system stats output."
        
        aria = MagicMock()
        
        # Test routing cases
        test_queries = [
            "cpu usage",
            "ram status",
            "system stats",
            "memory usage",
            "disk usage",
            "how much ram is being used",
            "what is my cpu percent"
        ]
        
        for query in test_queries:
            aria._speak.reset_mock()
            aria.normalizer_val = query
            res = handle_personal_notes_pc_status(aria, query.lower(), query)
            self.assertEqual(res, "read_system_stats")
            aria._speak.assert_called_once_with("Mocked system stats output.")

    @patch('skills.memory_commands.get_system_stats')
    def test_command_router_integration(self, mock_get_stats):
        mock_get_stats.return_value = "Mocked stats."
        aria = MagicMock()
        
        test_queries = [
            "cpu usage",
            "ram status",
            "system stats",
            "how much ram is being used"
        ]
        
        for query in test_queries:
            aria._speak.reset_mock()
            aria.normalizer_val = query
            res = handle_memory(aria, query.lower(), query)
            self.assertTrue(res["handled"])
            self.assertEqual(res["action"], "memory")
            self.assertEqual(res["response"], "read_system_stats")

if __name__ == "__main__":
    unittest.main()
