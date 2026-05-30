from brain import Brain

def test_generalization():
    print("Testing Generalization...")
    b = Brain()
    
    # 1. Test a known command
    known = "open notepad"
    print(f"\nScanning '{known}'...")
    print(b.think(known))
    
    # 2. Test a command with a known keyword ("open") but an UNKNOWN app name
    # "blazeblast" is definitely not in the training data
    unknown_app = "open blazeblast"
    print(f"\nScanning '{unknown_app}'...")
    print(b.think(unknown_app))

    # 3. Test a new keyword if we teach it?
    # We can't easily test training here without modifying the file, 
    # but we can verify if the keyword is enough.
    
    start_cmd = "start blazeblast" # "start" should be in data
    print(f"\nScanning '{start_cmd}'...")
    print(b.think(start_cmd))

if __name__ == "__main__":
    test_generalization()
