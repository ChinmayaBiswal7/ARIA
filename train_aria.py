# train_aria.py

import os
import sys

def train_model():
    print("Initializing OpenWakeWord custom model training...")
    
    # Check if we have positive samples
    positive_dir = "samples/aria"
    if not os.path.exists(positive_dir) or len(os.listdir(positive_dir)) == 0:
        print(f"Error: Positive samples directory '{positive_dir}' is empty or does not exist.")
        print("Please run 'python record_samples.py' first to record your voice samples!")
        sys.exit(1)
        
    try:
        from openwakeword.train import augment_clips
    except (ImportError, OSError) as e:
        print("\n" + "="*80)
        print("Dependency Error: openwakeword training modules could not be imported.")
        print(f"Details: {e}")
        print("This is usually caused by PyTorch/torchaudio DLL conflicts on Windows.")
        print("\nTo resolve this, please reinstall PyTorch and torchaudio using one of the following:")
        print("  1) CPU version:  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --force-reinstall")
        print("  2) CUDA version: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --force-reinstall")
        print("="*80 + "\n")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading training dependencies: {e}")
        sys.exit(1)

    print("Starting training on recorded samples in 'samples/aria'...")
    try:
        train(
            positive_samples="samples/aria/",
            model_name="aria",
            output_dir="models/",
            epochs=100,
        )
        print("\nSuccess! Custom model saved to models/aria.onnx")
    except Exception as e:
        print(f"Training failed: {e}")

if __name__ == "__main__":
    train_model()
