import sys
import os

# Ensure project path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.vector_memory import VectorMemory
from skills.scene_memory import SceneMemory

def test_scene_learning_and_recognition():
    print("--- Testing SceneMemory ---")
    vm = VectorMemory()
    sm = SceneMemory(vm)

    # 1. Test bedroom scene signature
    bedroom_objects = ["bed", "monitor", "keyboard", "chair", "laptop"]
    success, msg = sm.learn_scene("Chinmay's bedroom", bedroom_objects)
    print(f"Learn bedroom scene: success={success}, msg='{msg}'")
    assert success, "Should successfully learn the bedroom scene"

    # 2. Test kitchen scene signature
    kitchen_objects = ["refrigerator", "stove", "sink", "microwave", "dining table"]
    success, msg = sm.learn_scene("Kitchen", kitchen_objects)
    print(f"Learn kitchen scene: success={success}, msg='{msg}'")
    assert success, "Should successfully learn the kitchen scene"

    # 3. Test recognition of bedroom (with slightly different objects list)
    current_obs_bedroom = ["bed", "keyboard", "monitor", "person"]
    room_name, sim, desc = sm.recognize_scene(current_obs_bedroom)
    print(f"Recognize bedroom query: room_name='{room_name}', sim={sim:.3f}, desc='{desc}'")
    assert room_name == "chinmay's bedroom", "Should match chinmay's bedroom"
    assert "working at your computer" in desc or "resting or winding" in desc, "Should match pattern"

    # 4. Test recognition of kitchen
    current_obs_kitchen = ["stove", "sink", "refrigerator", "plate"]
    room_name, sim, desc = sm.recognize_scene(current_obs_kitchen)
    print(f"Recognize kitchen query: room_name='{room_name}', sim={sim:.3f}, desc='{desc}'")
    assert room_name == "kitchen", "Should match kitchen"
    assert "cooking or preparing food" in desc, "Should match cooking pattern"

    # 5. Test activity patterns directly
    print("\n--- Testing Activity Inference Engine ---")
    assert "working" in sm._check_activity_patterns(["monitor", "keyboard"]), "monitor + keyboard -> working"
    assert "cooking" in sm._check_activity_patterns(["stove", "sink"]), "stove + sink -> cooking"
    assert "resting" in sm._check_activity_patterns(["bed"]), "bed -> resting"
    assert "go out" in sm._check_activity_patterns(["backpack", "shoes"]), "backpack + shoes -> going out"
    print("Activity inference engine passed all checks.")

if __name__ == "__main__":
    try:
        test_scene_learning_and_recognition()
        print("\nAll SceneMemory integration tests passed successfully!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nSceneMemory integration test failed: {e}")
