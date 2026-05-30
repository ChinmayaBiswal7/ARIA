import torch
import json
import os
import sys
from generative_model import MiniGPT

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'

def generate_interactive():
    meta_path = "generative_meta.json"
    weights_path = "generative_brain.pth"

    if not os.path.exists(meta_path) or not os.path.exists(weights_path):
        print("Error: Model has not been trained yet. Please run: python train_generative_brain.py")
        sys.exit(1)

    # Load metadata
    with open(meta_path, "r") as f:
        meta = json.load(f)

    chars = meta["chars"]
    vocab_size = meta["vocab_size"]
    n_embd = meta["n_embd"]
    n_head = meta["n_head"]
    n_layer = meta["n_layer"]
    block_size = meta["block_size"]

    # Mappings
    stoi = {ch: i for i, ch in enumerate(chars)}
    itos = {i: ch for i, ch in enumerate(chars)}
    encode = lambda s: [stoi[c] for c in s if c in stoi]
    decode = lambda l: ''.join([itos[i] for i in l])

    # Reconstruct model
    model = MiniGPT(
        vocab_size=vocab_size, 
        n_embd=n_embd, 
        n_head=n_head, 
        n_layer=n_layer, 
        block_size=block_size
    ).to(DEVICE)

    # Load weights
    model.load_state_dict(torch.load(weights_path, map_location=DEVICE))
    model.eval()
    print("Model loaded successfully!")
    print("==================================================")
    print("   MiniGPT Generative Text Completer")
    print("   Type 'exit' to quit.")
    print("==================================================")

    while True:
        try:
            prompt = input("\nEnter starting text prompt: ")
            if not prompt or prompt.lower() == 'exit':
                break

            # Encode prompt
            encoded = encode(prompt)
            if not encoded:
                # Fallback to newline if no valid characters
                encoded = [0]
                
            context = torch.tensor([encoded], dtype=torch.long, device=DEVICE)
            
            # Ask how many tokens to generate
            length_input = input("Number of characters to generate (default 200): ")
            try:
                max_tokens = int(length_input) if length_input.strip() else 200
            except ValueError:
                max_tokens = 200

            print("\nGenerating text...")
            generated = model.generate(context, max_new_tokens=max_tokens, temperature=0.8, top_k=10)[0].tolist()
            
            print("\n--- Result ---")
            print(decode(generated))
            print("--------------")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error during generation: {e}")

if __name__ == "__main__":
    generate_interactive()
