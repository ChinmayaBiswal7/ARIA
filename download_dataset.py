import sys
import os

def install_and_download():
    # Check dependencies
    try:
        from datasets import load_dataset
        import pandas as pd
    except ImportError:
        print("Required libraries missing. Installing 'datasets' and 'pandas'...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "datasets", "pandas"])
        from datasets import load_dataset
        import pandas as pd

    print("==================================================")
    print("   Hugging Face Dataset Downloader")
    print("==================================================")
    print("1. Databricks Dolly 15k (~13 MB) - Great for Q&A and Chat")
    print("2. Stanford Alpaca (~45 MB) - Multi-task Instructions")
    print("3. Tiny Codes (~15 MB) - Simple Coding Instructions")
    
    choice = input("\nSelect dataset to download (1-3): ").strip()
    
    if choice == "1":
        dataset_name = "databricks/databricks-dolly-15k"
        out_file = "dolly_dataset.csv"
    elif choice == "2":
        dataset_name = "tatsu-lab/alpaca"
        out_file = "alpaca_dataset.csv"
    elif choice == "3":
        dataset_name = "nampdn-ai/tiny-codes"
        out_file = "tiny_codes_dataset.csv"
    else:
        print("Invalid choice. Exiting.")
        return

    print(f"\nDownloading '{dataset_name}' from Hugging Face...")
    try:
        # Load dataset
        ds = load_dataset(dataset_name)
        
        # Access the train split
        split_name = list(ds.keys())[0]
        df = pd.DataFrame(ds[split_name])
        
        print(f"Download complete. Total samples: {len(df)}")
        print(f"Columns available: {list(df.columns)}")
        
        # Save to CSV
        df.to_csv(out_file, index=False, encoding='utf-8')
        print(f"Successfully saved to: {os.path.abspath(out_file)}")
        print("\nFirst 3 rows preview:")
        print(df.head(3))
        
    except Exception as e:
        print(f"\nAn error occurred while downloading: {e}")

if __name__ == "__main__":
    install_and_download()
