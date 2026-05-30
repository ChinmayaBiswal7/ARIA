import os
import json
import csv
import urllib.request
import sys

COMMANDS_FILE = "custom_commands.json"

def load_existing_commands():
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r") as f:
                data = json.load(f)
                return data.get("commands", [])
        except Exception as e:
            print(f"Error reading {COMMANDS_FILE}: {e}")
    return []

def save_commands(commands):
    try:
        with open(COMMANDS_FILE, "w") as f:
            json.dump({"commands": commands}, f, indent=2)
        print(f"Successfully saved {len(commands)} total commands to {COMMANDS_FILE}.")
    except Exception as e:
        print(f"Error saving to {COMMANDS_FILE}: {e}")

def import_csv(source_path):
    print(f"Importing dataset from: {source_path}")
    rows = []
    
    # Check if source is a URL
    if source_path.startswith("http://") or source_path.startswith("https://"):
        try:
            req = urllib.request.Request(
                source_path, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req) as response:
                csv_data = response.read().decode('utf-8').splitlines()
                reader = csv.DictReader(csv_data)
                for row in reader:
                    rows.append(row)
        except Exception as e:
            print(f"Error downloading online CSV: {e}")
            return
    else:
        # Local file
        if not os.path.exists(source_path):
            print(f"Error: Local file {source_path} does not exist.")
            return
        try:
            with open(source_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except Exception as e:
            print(f"Error reading local CSV: {e}")
            return

    if not rows:
        print("No data found or failed to parse CSV.")
        return

    # Normalize keys to lowercase to find phrase and category columns
    normalized_rows = []
    for r in rows:
        norm_row = {k.lower().strip(): v.strip() for k, v in r.items() if k}
        normalized_rows.append(norm_row)

    # Find headers
    phrase_col = None
    cat_col = None
    for k in ["phrase", "pattern", "command", "text", "input"]:
        if k in normalized_rows[0]:
            phrase_col = k
            break
    for k in ["category", "tag", "action", "type"]:
        if k in normalized_rows[0]:
            cat_col = k
            break

    if not phrase_col or not cat_col:
        print(f"Error: CSV must contain a 'phrase' (or pattern/command) column and a 'category' (or tag/action) column.")
        print(f"Found columns: {list(rows[0].keys())}")
        return

    existing = load_existing_commands()
    existing_phrases = {c["phrase"].lower().strip(): c for c in existing}

    added = 0
    updated = 0

    for row in normalized_rows:
        phrase = row.get(phrase_col)
        category = row.get(cat_col)
        
        if not phrase or not category:
            continue
            
        phrase_clean = phrase.strip()
        category_clean = category.strip().upper()
        
        # Valid categories
        if category_clean not in ["OPEN", "CLOSE", "TYPE", "SEARCH"]:
            print(f"Warning: Skipping invalid category '{category_clean}' for phrase '{phrase_clean}'. Must be OPEN, CLOSE, TYPE, or SEARCH.")
            continue

        key = phrase_clean.lower()
        if key in existing_phrases:
            if existing_phrases[key]["category"] != category_clean:
                existing_phrases[key]["category"] = category_clean
                updated += 1
        else:
            new_cmd = {"phrase": phrase_clean, "category": category_clean}
            existing.append(new_cmd)
            existing_phrases[key] = new_cmd
            added += 1

    print(f"Parsed CSV: Added {added} new commands, updated {updated} existing commands.")
    save_commands(existing)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_csv.py [local_file_path_or_url]")
        # Provide a default template creation if run without args
        print("\nCreating a sample template file 'sample_commands.csv'...")
        with open("sample_commands.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["phrase", "category"])
            writer.writerow(["open telegram", "OPEN"])
            writer.writerow(["close telegram", "CLOSE"])
            writer.writerow(["type hello chinmay", "TYPE"])
            writer.writerow(["search for offline models", "SEARCH"])
        print("Created. Run: python import_csv.py sample_commands.csv")
    else:
        import_csv(sys.argv[1])
