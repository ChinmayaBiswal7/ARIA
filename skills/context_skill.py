import ctypes
from ctypes import wintypes
import socket
import subprocess

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
