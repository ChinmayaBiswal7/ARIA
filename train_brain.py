import torch
import torch.nn as nn
import torch.optim as optim
import json
import numpy as np
from brain_model import SimpleBrainNN


def train_model():
    print("Training started...")
    
    # 1. Training Data
    try:
        with open('intents.json', 'r') as f:
            intents = json.load(f)
    except FileNotFoundError:
        print("intents.json not found!")
        return

    # Intents: 0 = CHAT, 1 = OPEN_APP, 2 = TYPE_TEXT, 3 = CLOSE_APP
    tag_map = {"CHAT": 0, "OPEN": 1, "TYPE": 2, "CLOSE": 3}

    data = []
    for intent in intents['intents']:
        tag_id = tag_map.get(intent['tag'])
        if tag_id is not None:
            for pattern in intent['patterns']:
                data.append((pattern, tag_id))

    # 2. Preprocessing (Bag of Words)
    all_words = []
    for sentence, _ in data:
        words = sentence.split()
        for w in words:
            if w not in all_words:
                all_words.append(w)

    all_words = sorted(list(set(all_words)))

    def sentence_to_tensor(sentence, all_words):
        input_tensor = np.zeros(len(all_words), dtype=np.float32)
        words = sentence.split()
        for w in words:
            if w in all_words:
                input_tensor[all_words.index(w)] = 1.0
        return torch.tensor(input_tensor)

    # Prepare Inputs and Targets
    X = []
    y = []

    for sentence, label in data:
        X.append(sentence_to_tensor(sentence, all_words))
        y.append(torch.tensor(label, dtype=torch.long))

    if not X:
        print("No training data found.")
        return

    X_train = torch.stack(X)
    y_train = torch.stack(y)

    # 3. Model Setup
    input_size = len(all_words)
    hidden_size = 16
    num_classes = 4 # CHAT, OPEN, TYPE, CLOSE

    model = SimpleBrainNN(input_size, hidden_size, num_classes)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.01)

    # 4. Training Loop
    for epoch in range(1000):
        outputs = model(X_train)
        loss = criterion(outputs, y_train)
        
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        
        # if (epoch+1) % 100 == 0:
        #     print(f'Epoch [{epoch+1}/1000], Loss: {loss.item():.4f}')

    print("Training finished.")

    # 5. Save Model and Artifacts
    torch.save(model.state_dict(), "brain_model.pth")
    print("Model saved to brain_model.pth")

    artifacts = {
        "all_words": all_words,
        "input_size": input_size,
        "hidden_size": hidden_size,
        "num_classes": num_classes,
        "intents": {0: "CHAT", 1: "OPEN", 2: "TYPE", 3: "CLOSE"}
    }

    with open("brain_data.json", "w") as f:
        json.dump(artifacts, f)
    print("Artifacts saved to brain_data.json")

if __name__ == "__main__":
    train_model()
