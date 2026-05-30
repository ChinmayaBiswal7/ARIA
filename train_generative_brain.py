import torch
import torch.optim as optim
import json
import os
import urllib.request
from generative_model import MiniGPT

# Hyperparameters for training on CPU / light laptop
BATCH_SIZE = 32
BLOCK_SIZE = 64      # Context length
MAX_ITERS = 1500     # Training steps
EVAL_INTERVAL = 300
LEARNING_RATE = 1e-3
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
N_EMBD = 128
N_HEAD = 4
N_LAYER = 3
DROPOUT = 0.1

def get_or_download_data():
    data_file = "training_text.txt"
    if not os.path.exists(data_file):
        print("Downloading a light dataset (Tiny Shakespeare, ~100KB split)...")
        # Download small subset to make training super fast
        url = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                full_text = response.read().decode('utf-8')
                # Take first 150,000 characters for laptop speed
                light_text = full_text[:150000]
                with open(data_file, "w", encoding="utf-8") as f:
                    f.write(light_text)
            print(f"Data saved to {data_file} ({len(light_text)} characters).")
        except Exception as e:
            print(f"Failed downloading online dataset. Creating fallback dataset locally: {e}")
            # Local fallback dialogue data
            fallback = "Hello ARIA. Hello! How can I help you?\n" * 1000 + "What is your name? My name is ARIA.\n" * 1000
            with open(data_file, "w", encoding="utf-8") as f:
                f.write(fallback)
    
    with open(data_file, "r", encoding="utf-8") as f:
        text = f.read()
    return text

def train():
    print(f"Using device: {DEVICE}")
    text = get_or_download_data()

    # Characters vocabulary
    chars = sorted(list(set(text)))
    vocab_size = len(chars)
    print(f"Vocab size: {vocab_size} unique characters.")

    # Mappings
    stoi = {ch: i for i, ch in enumerate(chars)}
    itos = {i: ch for i, ch in enumerate(chars)}
    encode = lambda s: [stoi[c] for c in s if c in stoi]
    decode = lambda l: ''.join([itos[i] for i in l])

    # Train/Val splits
    data = torch.tensor(encode(text), dtype=torch.long)
    n = int(0.9 * len(data))
    train_data = data[:n]
    val_data = data[n:]

    # Data batching function
    def get_batch(split):
        data_split = train_data if split == 'train' else val_data
        ix = torch.randint(len(data_split) - BLOCK_SIZE, (BATCH_SIZE,))
        x = torch.stack([data_split[i:i+BLOCK_SIZE] for i in ix])
        y = torch.stack([data_split[i+1:i+BLOCK_SIZE+1] for i in ix])
        x, y = x.to(DEVICE), y.to(DEVICE)
        return x, y

    # Estimate loss
    @torch.no_grad()
    def estimate_loss(model):
        out = {}
        model.eval()
        for split in ['train', 'val']:
            losses = torch.zeros(10)
            for k in range(10):
                X, Y = get_batch(split)
                _, loss = model(X, Y)
                losses[k] = loss.item()
            out[split] = losses.mean()
        model.train()
        return out

    # Initialize model
    model = MiniGPT(
        vocab_size=vocab_size, 
        n_embd=N_EMBD, 
        n_head=N_HEAD, 
        n_layer=N_LAYER, 
        block_size=BLOCK_SIZE, 
        dropout=DROPOUT
    ).to(DEVICE)
    
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    
    print("\nStarting training loop...")
    for step in range(MAX_ITERS):
        # Every now and then evaluate the loss
        if step % EVAL_INTERVAL == 0 or step == MAX_ITERS - 1:
            losses = estimate_loss(model)
            print(f"Step {step:4d}: Train Loss = {losses['train']:.4f} | Val Loss = {losses['val']:.4f}")
            
            # Print sample text generation to watch progress
            context = torch.zeros((1, 1), dtype=torch.long, device=DEVICE) # '\n' character
            generated = model.generate(context, max_new_tokens=100)[0].tolist()
            print("--- Generated Sample ---")
            print(decode(generated))
            print("------------------------\n")

        # Get batch and train
        xb, yb = get_batch('train')
        logits, loss = model(xb, yb)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

    # Save model weights
    model_path = "generative_brain.pth"
    torch.save(model.state_dict(), model_path)
    print(f"Saved weights to {model_path}")

    # Save metadata
    meta = {
        "chars": chars,
        "n_embd": N_EMBD,
        "n_head": N_HEAD,
        "n_layer": N_LAYER,
        "block_size": BLOCK_SIZE,
        "vocab_size": vocab_size
    }
    with open("generative_meta.json", "w") as f:
        json.dump(meta, f)
    print("Saved metadata to generative_meta.json")

if __name__ == "__main__":
    train()
