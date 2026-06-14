# train_aria_custom.py
import os
import sys
import numpy as np
import scipy.io.wavfile
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from openwakeword.utils import AudioFeatures
from tqdm import tqdm

# Force stdout and stderr to UTF-8 on Windows to avoid UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def train_custom_model():
    print("=== Training custom ARIA wake word model ===")
    
    # 1. Setup paths
    positive_dir = "samples/aria"
    negative_features_file = "validation_set_features.npy"
    output_onnx_path = r"models/aria.onnx"
    
    os.makedirs("models", exist_ok=True)
    
    if not os.path.exists(positive_dir):
        print(f"Error: positive samples directory '{positive_dir}' not found.")
        return
        
    wav_files = [os.path.join(positive_dir, f) for f in os.listdir(positive_dir) if f.endswith(".wav")]
    if not wav_files:
        print("Error: no positive wav samples found in samples/aria.")
        return
        
    print(f"Found {len(wav_files)} positive wav files.")
    
    # Initialize feature extractor
    print("Initializing OpenWakeWord feature extractor...")
    F = AudioFeatures(device='cpu')
    
    # 2. Extract features from positive samples (with augmentation)
    print("Processing and augmenting positive samples...")
    positive_features_list = []
    
    # Target length is 2 seconds at 16kHz
    target_samples = 32000
    
    for wav_file in tqdm(wav_files):
        try:
            sr, dat = scipy.io.wavfile.read(wav_file)
            if sr != 16000:
                # Resample or skip if not 16000Hz (but we expect them to be 16000Hz)
                continue
                
            L = len(dat)
            if L > target_samples:
                dat = dat[-target_samples:]
                L = target_samples
                
            # Perform 20 augmentations per positive sample
            for _ in range(20):
                # Choose a random offset to place the wake word in the 2-second window
                max_offset = target_samples - L
                offset = np.random.randint(0, max_offset + 1) if max_offset > 0 else 0
                
                # Create a 2-second padded window
                padded = np.zeros(target_samples, dtype=np.int16)
                padded[offset:offset+L] = dat
                
                # Add a small amount of random Gaussian noise
                noise = np.random.normal(0, 15, target_samples).astype(np.float32)
                padded_float = padded.astype(np.float32) + noise
                padded_final = np.clip(padded_float, -32768.0, 32767.0).astype(np.int16)
                
                # Extract features -> shape (16, 96)
                feats = F._get_embeddings(padded_final)
                if feats.shape == (16, 96):
                    positive_features_list.append(feats)
        except Exception as e:
            print(f"Error processing {wav_file}: {e}")
            
    if not positive_features_list:
        print("Error: Could not extract any positive features.")
        return
        
    pos_X = np.stack(positive_features_list)
    print(f"Extracted {pos_X.shape[0]} positive samples of shape {pos_X.shape[1:]}.")
    
    # 3. Load negative features and sample negative examples
    print(f"Loading negative features from {negative_features_file}...")
    if not os.path.exists(negative_features_file):
        print(f"Error: {negative_features_file} not found. Please download it first.")
        return
        
    neg_data = np.load(negative_features_file)
    n_total_neg_frames = neg_data.shape[0]
    
    # Sample 15,000 negative samples of shape (16, 96)
    print("Sampling negative samples...")
    neg_features_list = []
    num_neg_samples = 15000
    
    # Pick random start indices
    start_indices = np.random.randint(0, n_total_neg_frames - 16, num_neg_samples)
    for idx in start_indices:
        neg_slice = neg_data[idx:idx+16]
        neg_features_list.append(neg_slice)
        
    neg_X = np.stack(neg_features_list)
    print(f"Sampled {neg_X.shape[0]} negative samples of shape {neg_X.shape[1:]}.")
    
    # 4. Prepare training dataset
    X = np.vstack((neg_X, pos_X)).astype(np.float32)
    y = np.array([0] * len(neg_X) + [1] * len(pos_X)).astype(np.float32)[..., None]
    
    # Shuffle and split into train and validation
    indices = np.arange(len(X))
    np.random.shuffle(indices)
    X = X[indices]
    y = y[indices]
    
    split = int(0.9 * len(X))
    train_X, val_X = X[:split], X[split:]
    train_y, val_y = y[:split], y[split:]
    
    train_dataset = TensorDataset(torch.from_numpy(train_X), torch.from_numpy(train_y))
    val_dataset = TensorDataset(torch.from_numpy(val_X), torch.from_numpy(val_y))
    
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    
    # 5. Define Model
    print("Defining PyTorch model...")
    class WakeWordClassifier(nn.Module):
        def __init__(self, input_features=16*96, hidden_dim=64):
            super().__init__()
            self.net = nn.Sequential(
                nn.Flatten(),
                nn.Linear(input_features, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, 1),
                nn.Sigmoid()
            )
            
        def forward(self, x):
            return self.net(x)
            
    model = WakeWordClassifier()
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    
    # Give higher weight to negative samples to minimize false positives
    pos_weight = torch.tensor([1.0])
    neg_weight = torch.tensor([3.0]) # penalize false positives 3x more
    
    # 6. Training Loop
    print("Starting training loop...")
    epochs = 30
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        correct = 0
        total = 0
        
        for batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_x)
            
            # Apply weights: loss is sum of weighted individual losses
            loss = criterion(outputs, batch_y)
            # Custom weight mapping
            w = torch.where(batch_y == 1, pos_weight, neg_weight)
            weighted_loss = torch.mean(loss * w)
            
            weighted_loss.backward()
            optimizer.step()
            
            train_loss += weighted_loss.item() * batch_x.size(0)
            preds = (outputs >= 0.5).float()
            correct += (preds == batch_y).sum().item()
            total += batch_y.size(0)
            
        train_loss = train_loss / total
        train_acc = correct / total
        
        # Validation
        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        val_pos_correct = 0
        val_pos_total = 0
        
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                outputs = model(batch_x)
                w = torch.where(batch_y == 1, pos_weight, neg_weight)
                loss = criterion(outputs, batch_y)
                weighted_loss = torch.mean(loss * w)
                
                val_loss += weighted_loss.item() * batch_x.size(0)
                preds = (outputs >= 0.5).float()
                val_correct += (preds == batch_y).sum().item()
                val_total += batch_y.size(0)
                
                # Check recall on positive samples specifically
                pos_mask = (batch_y == 1)
                if pos_mask.any():
                    val_pos_correct += (preds[pos_mask] == 1).sum().item()
                    val_pos_total += pos_mask.sum().item()
                    
        val_loss = val_loss / val_total
        val_acc = val_correct / val_total
        val_recall = val_pos_correct / val_pos_total if val_pos_total > 0 else 0.0
        
        print(f"Epoch {epoch+1:02d}/{epochs} - Train Loss: {train_loss:.4f}, Train Acc: {train_acc*100:.2f}% | Val Loss: {val_loss:.4f}, Val Acc: {val_acc*100:.2f}%, Val Recall (Recall): {val_recall*100:.2f}%")
        
    # 7. Export to ONNX
    print(f"Exporting model to ONNX format at: {output_onnx_path}...")
    model.eval()
    dummy_input = torch.zeros((1, 16, 96))
    
    # Export with name class_mapping as expected by openwakeword
    torch.onnx.export(
        model, 
        dummy_input, 
        output_onnx_path, 
        opset_version=13,
        input_names=['input'],
        output_names=['aria']  # Output name should match the wakeword name!
    )
    print("Custom ONNX model exported successfully!")
    
    # 8. Test verification
    print("Verifying loading exported ONNX model with openwakeword...")
    try:
        from openwakeword.model import Model as OWWModel
        oww = OWWModel(wakeword_models=[output_onnx_path], inference_framework="onnx")
        print("Success! Openwakeword loaded the custom model correctly!")
    except Exception as e:
        print(f"Verification failed: {e}")

if __name__ == "__main__":
    train_custom_model()
