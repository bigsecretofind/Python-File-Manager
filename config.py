import os
import json
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "lastfolder.json")
CATALOG_FILE = os.path.join(BASE_DIR, "catalog.json")


def save_config(data):
    temp_file = CONFIG_FILE + ".tmp"
    backup_file = CONFIG_FILE + ".bak"
    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
            file.flush()
            os.fsync(file.fileno())
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, backup_file)
        os.replace(temp_file, CONFIG_FILE)
    except OSError as error:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        print(f"Warning: Could not save the last-folder configuration: {error}")


def get_target_directory():
    last_folder = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, dict):
                    last_folder = data.get("last_folder")
                else:
                    print("Warning: lastfolder.json has an invalid structure.")
        except (json.JSONDecodeError, OSError) as error:
            print(f"Warning: Could not read lastfolder.json: {error}")

    if isinstance(last_folder, str) and os.path.isdir(last_folder):
        print(f"Last folder used: {last_folder}")
        while True:
            choice = input("Do you want to use this folder again? (y/n): ").strip().lower()
            if choice in {"y", "yes"}:
                return last_folder
            if choice in {"n", "no"}:
                break
            print("Invalid input. Did you mean Y or N?")

    while True:
        raw_input = input("Enter the directory path to scan: ").strip().strip('"').strip("'")
        if not raw_input:
            print("Error: Directory path cannot be blank.\n")
            continue
        target_folder = os.path.normpath(raw_input)
        if os.path.isdir(target_folder):
            save_config({"last_folder": target_folder})
            return target_folder
        print(f"Error: Could not find '{target_folder}'. Please check that the folder exists and try again.\n")
