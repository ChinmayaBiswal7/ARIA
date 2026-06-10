class RobotController:
    """
    Future-ready abstract interface for Phase W Robotics Layer integration.
    Keeps ARIA's core brain and multi-agent coordinator decoupled from physical hardware concerns
    until Raspberry Pi / ESP32 hardware is introduced.
    """
    def move_forward(self, distance: float):
        pass

    def turn_left(self, angle: float):
        pass

    def speak(self, text: str):
        pass

    def get_camera_frame(self):
        return None
