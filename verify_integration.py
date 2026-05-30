from brain import Brain

def test_brain():
    print("Testing Brain Integration...")
    try:
        brain = Brain() # Should load local model
        
        test_inputs = [
            "Open Notepad",
            "Please type hello world for me",
            "Who are you?",
            "open unigrm wrte mss",
            "could you please open chrome to search for news"
        ]
        
        for text in test_inputs:
            print(f"\nUser Input: {text}")
            response = brain.think(text)
            print(f"Brain Response: {response}")
            
        print("\nVerification Successful.")
    except Exception as e:
        print(f"\nVerification Failed: {e}")

if __name__ == "__main__":
    test_brain()
