import os
import json
import shutil
import unicodedata
from config import CATALOG_FILE

# Catalog safety helpers
CATALOG_BACKUP_FILE = CATALOG_FILE + ".bak"


class CatalogError(Exception):
    """Raised when the catalog cannot safely be read or written."""


def validate_catalog(data):
    """Validate catalog structure and return clean entries plus warnings."""
    if not isinstance(data, list):
        raise CatalogError("Catalog root must be a JSON list.")

    clean = []
    warnings = []
    seen_paths = set()
    # "tags" was added after the original catalog format, so it is optional
    # during loading. Older entries are safely migrated to an empty tag list.
    required = {"filename", "relative_path", "full_path", "size_bytes", "extension"}

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            warnings.append(f"Entry {index} was skipped because it is not an object.")
            continue
        if not required.issubset(item):
            missing = ", ".join(sorted(required - set(item)))
            warnings.append(f"Entry {index} was skipped; missing: {missing}.")
            continue

        item = item.copy()
        item.setdefault("tags", [])
        if not all(isinstance(item[key], str) for key in ("filename", "relative_path", "full_path", "extension")):
            warnings.append(f"Entry {index} was skipped because a path/name field is invalid.")
            continue
        if not isinstance(item["size_bytes"], int) or item["size_bytes"] < 0:
            warnings.append(f"Entry {index} was skipped because size_bytes is invalid.")
            continue
        if not isinstance(item["tags"], list) or not all(isinstance(tag, str) for tag in item["tags"]):
            warnings.append(f"Entry {index} was skipped because tags is invalid.")
            continue

        item["full_path"] = os.path.normpath(item["full_path"])
        item["extension"] = item["extension"].lower()
        item["tags"] = list(dict.fromkeys(item["tags"]))
        if item["full_path"] in seen_paths:
            warnings.append(f"Duplicate path skipped: {item['full_path']}")
            continue
        seen_paths.add(item["full_path"])
        clean.append(item)

    return clean, warnings


def load_catalog():
    if not os.path.exists(CATALOG_FILE):
        return []
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        catalog, warnings = validate_catalog(data)
        if warnings:
            for warning in warnings:
                print(f"Catalog validation error: {warning}")
            raise CatalogError(
                "Catalog contains invalid entries. No changes will be allowed until it is repaired."
            )
        return catalog
    except (json.JSONDecodeError, OSError, CatalogError) as error:
        print(f"\nCATALOG SAFETY ERROR: Could not safely read '{CATALOG_FILE}'.")
        print(f"Reason: {error}")
        if os.path.exists(CATALOG_BACKUP_FILE):
            print(f"Backup available: {CATALOG_BACKUP_FILE}")
        print("The catalog was not modified. Repair or restore it before continuing.")
        raise CatalogError(str(error)) from error


def save_catalog(catalog):
    """Validate, back up, and atomically replace the catalog."""
    clean_catalog, warnings = validate_catalog(catalog)
    if warnings:
        raise CatalogError("Refusing to save a catalog containing invalid entries: " + warnings[0])

    catalog_directory = os.path.dirname(CATALOG_FILE) or "."
    os.makedirs(catalog_directory, exist_ok=True)
    temp_file = CATALOG_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(clean_catalog, file, indent=4, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())

        # Verify the completed temporary file before touching the current catalog.
        with open(temp_file, "r", encoding="utf-8") as file:
            validate_catalog(json.load(file))

        if os.path.exists(CATALOG_FILE):
            shutil.copy2(CATALOG_FILE, CATALOG_BACKUP_FILE)
        os.replace(temp_file, CATALOG_FILE)
    except (OSError, json.JSONDecodeError, CatalogError) as error:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass
        print(f"Catalog save failed: {error}")
        print("The previous catalog and backup were preserved.")
        raise CatalogError(str(error)) from error


def choose_file_match(matches, action_text):
    """Safely choose among files that share the same filename."""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    print(f"\nMultiple files have that filename. Choose the file to {action_text}:")
    for number, item in enumerate(matches, start=1):
        print(f"{number}. {item.get('full_path', item.get('relative_path', item['filename']))}")
    choice = input(f"Select a file (1-{len(matches)}, or Enter to cancel): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(matches):
        print("Selection cancelled or invalid.")
        return None
    return matches[int(choice) - 1]

# Read entire file path contents
def scan_entire_folder(target_folder):
    catalog = load_catalog()
    catalog_map = {item["full_path"]: item for item in catalog}
    scanned_paths = set()

    print(f"\nScanning directory: {target_folder}...")
    scanned_count = 0
    for root, dirs, files in os.walk(target_folder):
        for file in files:
            full_path = os.path.normpath(os.path.join(root, file))
            rel_path = os.path.relpath(full_path, target_folder)
            try:
                file_size = os.path.getsize(full_path)
                file_extension = os.path.splitext(file)[1].lower()
                existing_tags = catalog_map.get(full_path, {}).get("tags", [])
                catalog_map[full_path] = {
                    "filename": file, "relative_path": rel_path, "full_path": full_path,
                    "size_bytes": file_size, "extension": file_extension, "tags": existing_tags
                }
                scanned_paths.add(full_path)
                scanned_count += 1
            except (OSError, PermissionError) as error:
                print(f"Skipped inaccessible file: {file} ({error})")

    target_abs = os.path.abspath(target_folder)
    stale_paths = []
    for path in list(catalog_map):
        try:
            under_target = os.path.commonpath([target_abs, os.path.abspath(path)]) == target_abs
        except ValueError:
            under_target = False
        if under_target and path not in scanned_paths and not os.path.exists(path):
            stale_paths.append(path)

    if stale_paths:
        print(f"\nFound {len(stale_paths)} catalog entries whose files no longer exist:")
        for path in stale_paths[:20]:
            print(f"- {path}")
        if len(stale_paths) > 20:
            print(f"...and {len(stale_paths) - 20} more.")
        answer = input("Remove these missing entries from the catalog? (y/n): ").strip().lower()
        if answer in {"y", "yes"}:
            for path in stale_paths:
                catalog_map.pop(path, None)
            print(f"Removed {len(stale_paths)} stale entries.")
        else:
            print("Stale entries were kept, including their tags.")

    updated_catalog = list(catalog_map.values())
    save_catalog(updated_catalog)
    print(f"Scan complete! Cataloged {scanned_count} files (Total entries: {len(updated_catalog)}).")

# Add a file to a specific path
def add_single_file(target_folder):
    catalog = load_catalog()

    raw_input = input("\nEnter the full path of the file to add: ").strip().strip('"').strip("'")
    source_file = os.path.normpath(raw_input)

    if not os.path.isfile(source_file):
        print(f"Error: Could not find file '{source_file}'. Please verify the path.")
        return

    print("\nHow would you like to handle this file?")
    print("1. Catalog only (leave file where it is)")
    print("2. Copy file to target directory and catalog")
    print("3. Move (cut) file to target directory and catalog")
    file_action = input("Select action (1-3): ").strip()

    final_path = source_file

    try:
        if file_action == "2":
            final_path = shutil.copy2(source_file, target_folder)
            print(f"Copied file to: {final_path}")
        elif file_action == "3":
            final_path = shutil.move(source_file, target_folder)
            print(f"Moved file to: {final_path}")
        elif file_action != "1":
            print("Invalid choice. Defaulting to 'Catalog only'.")

        final_path = os.path.normpath(final_path)
        filename = os.path.basename(final_path)
        file_size = os.path.getsize(final_path)
        file_extension = os.path.splitext(filename)[1].lower()

        if final_path.startswith(target_folder):
            rel_path = os.path.relpath(final_path, target_folder)
        else:
            rel_path = filename

        entry = {
            "filename": filename,
            "relative_path": rel_path,
            "full_path": final_path,
            "size_bytes": file_size,
            "extension": file_extension,
            "tags": []
        }

        catalog_map = {item["full_path"]: item for item in catalog}
        catalog_map[final_path] = entry
        save_catalog(list(catalog_map.values()))
        print(f"Successfully logged '{filename}' to {CATALOG_FILE}.")

    except (OSError, PermissionError, shutil.Error) as e:
        print(f"Error processing file: {e}")

# View files in a tree format
def print_tree(directory, prefix=""):
    try:
        items = sorted(os.listdir(directory))
    except (OSError, PermissionError):
        print(prefix + "> [Access Denied]")
        return

    for i, item in enumerate(items):
        path = os.path.join(directory, item)
        print(prefix + "> " + item)

        if os.path.isdir(path):
            extension_prefix = prefix + "  "
            print_tree(path, extension_prefix)

# View files in folder
def handle_view_files(target_folder):
    current_view_folder = target_folder

    while True:
        print(f"\n--- Viewing: {current_view_folder} ---")
        print("1. View immediate files and folders only")
        print("2. View full tree structure (including subfolders)")
        print("0. Return to main menu")
        sub_choice = input("Select an option (0-2): ").strip()

        if sub_choice == "0":
            break

        if sub_choice == "1":
            try:
                print(f"\nContents of: {current_view_folder}")
                for item in sorted(os.listdir(current_view_folder)):
                    path = os.path.join(current_view_folder, item)
                    item_type = "[Folder]" if os.path.isdir(path) else "[File]"
                    print(f"{item_type} {item}")
            except OSError as e:
                print(f"Error accessing directory: {e}")
                continue

        elif sub_choice == "2":
            folder_name = os.path.basename(current_view_folder) or current_view_folder
            print(f"\nTree view of: {folder_name}")
            print_tree(current_view_folder)
        else:
            print("Invalid selection.")
            continue

        print("\nType the name of a [Folder] from above to open it, or press Enter to skip.")
        next_step = input("Folder name to open (or Enter to skip): ").strip()

        if next_step == "":
            continue

        new_path = os.path.join(current_view_folder, next_step)

        if os.path.isdir(new_path):
            current_view_folder = new_path
        else:
            print(f"\nError: '{next_step}' is not a valid folder in the current directory.")

# Add / Scan Files
def handle_scan_or_add(target_folder):
    print("\n--- Scan / Add Options ---")
    print("1. Scan entire target directory")
    print("2. Add a specific file by file path")
    sub_choice = input("Select an option (1-2): ").strip()

    if sub_choice == "1":
        scan_entire_folder(target_folder)
    elif sub_choice == "2":
        add_single_file(target_folder)
    else:
        print("Invalid selection. Returning to main menu.")

# Tag system
def normalize_tag(raw_tag):
    """Return a clean tag, or None when the tag is empty/invisible."""
    tag = " ".join(raw_tag.strip().lower().split())
    if not tag:
        return None
    # Reject control/format characters, including zero-width characters.
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in tag):
        return None
    if not any(not char.isspace() for char in tag):
        return None
    return tag


def handle_tags(target_folder):
    print("\n--- Tag Management ---")
    print("1. Add a tag to a file")
    print("2. Delete a tag from a file")
    print("3. Search files by tag")
    print("0. Return to main menu")
    sub_choice = input("Select an option (0-3): ").strip()
    catalog = load_catalog()

    if sub_choice == "0" or sub_choice == "":
        return

    if sub_choice == "1":
        search_name = input("Enter the exact filename to tag (or Enter to cancel): ").strip()
        if not search_name:
            return

        matches = [item for item in catalog if item.get("filename", "").lower() == search_name.lower()]
        if not matches:
            print(f"Could not find '{search_name}' in the catalog. Scan/add it first.")
            return

        item = choose_file_match(matches, "tag")
        if item is None:
            return
        new_tag = normalize_tag(input(f"Enter a tag for '{item['filename']}' (or Enter to cancel): "))
        if new_tag is None:
            print("Tag was not added. Tags cannot be blank, whitespace-only, or contain invisible characters.")
            return

        item.setdefault("tags", [])
        if new_tag in item["tags"]:
            print(f"'{item['filename']}' already has the tag '{new_tag}'.")
            return
        item["tags"].append(new_tag)
        save_catalog(catalog)
        print(f"Successfully added tag '{new_tag}' to '{item['filename']}'.")

    elif sub_choice == "2":
        tagged_items = [item for item in catalog if item.get("tags", [])]
        if not tagged_items:
            print("\nNo files currently have tags to delete.")
            return

        print("\n--- Delete Tag Options ---")
        print("1. Browse files that currently have tags")
        print("2. Go directly to deleting a tag")
        print("0. Cancel")
        delete_choice = input("Select an option (0-2): ").strip()

        if delete_choice == "0":
            return
        if delete_choice == "":
            print("Invalid input. Please select 0, 1, or 2.")
            return

        if delete_choice == "1":
            print("\n--- Files with Current Tags ---")
            for number, tagged_item in enumerate(tagged_items, start=1):
                tags_display = ", ".join(tagged_item.get("tags", []))
                print(f"{number}. {tagged_item['filename']} | Tags: {tags_display}")

            continue_delete = input("\nDo you want to delete a tag now? (y/n): ").strip().lower()
            if continue_delete not in {"y", "yes"}:
                print("Returning to the main menu.")
                return
        elif delete_choice != "2":
            print("Invalid selection. Please select 0, 1, or 2.")
            return

        search_name = input("Enter the exact filename (or Enter to cancel): ").strip()
        if not search_name:
            return

        matches = [
            item for item in tagged_items
            if item.get("filename", "").lower() == search_name.lower()
        ]
        if not matches:
            print(f"Could not find a tagged file named '{search_name}'.")
            return

        item = choose_file_match(matches, "remove a tag from")
        if item is None:
            return
        tags = item.get("tags", [])
        print(f"Current tags for '{item['filename']}': {', '.join(tags)}")
        tag_to_delete = normalize_tag(input("Enter the tag to delete (or Enter to cancel): "))
        if tag_to_delete is None:
            return
        if tag_to_delete not in tags:
            print(f"'{item['filename']}' does not have the tag '{tag_to_delete}'.")
            return

        confirmation = input(
            f"Delete tag '{tag_to_delete}' from '{item['filename']}'? (y/n): "
        ).strip().lower()
        if confirmation not in {"y", "yes"}:
            print("Tag deletion cancelled.")
            return
        tags.remove(tag_to_delete)
        save_catalog(catalog)
        print(f"Successfully deleted tag '{tag_to_delete}' from '{item['filename']}'.")

    elif sub_choice == "3":
        all_tags = sorted({tag for item in catalog for tag in item.get("tags", [])})
        if not all_tags:
            print("\nNo tags have been created yet.")
            return
        print(f"\nAvailable tags: {', '.join(all_tags)}")
        search_tag = normalize_tag(input("Enter tag to search for (or Enter to cancel): "))
        if search_tag is None:
            return
        results = [item for item in catalog if search_tag in item.get("tags", [])]
        if results:
            print(f"\n--- Files tagged with '{search_tag}' ---")
            for item in results:
                location = item.get("full_path", item.get("relative_path"))
                print(f"- {item['filename']} (Location: {location})")
        else:
            print(f"\nNo files found with the tag '{search_tag}'.")
    else:
        print("Invalid selection.")


def handle_filename_search(target_folder):
    """Search catalog entries by full or partial filename."""
    catalog = load_catalog()
    if not catalog:
        print("\nCatalog is empty. Run Option 1 to scan files first.")
        return

    query = input("\nEnter all or part of a filename (or Enter to cancel): ").strip().lower()
    if not query:
        return

    matches = [item for item in catalog if query in item.get("filename", "").lower()]
    if not matches:
        print(f"\nNo filenames containing '{query}' were found.")
        return

    print(f"\n--- Filename search results ({len(matches)} found) ---")
    for item in sorted(matches, key=lambda entry: entry.get("filename", "").lower()):
        location = item.get("full_path", item.get("relative_path"))
        tags = ", ".join(item.get("tags", [])) or "None"
        print(f"- {item['filename']} (Location: {location}, Tags: {tags})")

#File types
CATEGORY_MAP = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"],
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".pptx", ".csv"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg"],
    "Video": [".mp4", ".mkv", ".avi", ".mov", ".ts"],
    "Code / Scripts": [".py", ".js", ".html", ".css", ".json", ".java", ".cpp", ".c"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"]
}

# Size checker
def format_size(size_bytes):
    """Converts bytes into a human-readable string (KB, MB, GB)."""
    if not size_bytes:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def handle_file_categories(target_folder):
    catalog = load_catalog()
    if not catalog:
        print("\nCatalog is currently empty. Run Option 1 to scan files first.")
        return

    print("\n--- View by File Type / Category / Size ---")
    print("1. Search by File Name")
    print("2. Filter by Category (Images, Documents, Video, Code, etc.)")
    print("3. Filter by Specific Extension (e.g. .jpg, .py)")
    print("0. Return to main menu")
    sub_choice = input("Select an option (0-3): ").strip()

    matches = []
    header_title = ""

    if sub_choice == "0" or sub_choice == "":
        return

    if sub_choice == "1":
        query = input("Enter all or part of a filename (or Enter to cancel): ").strip().lower()
        if not query:
            return
        matches = [item for item in catalog if query in item.get("filename", "").lower()]
        header_title = f"Filename Search: {query}"

    elif sub_choice == "2":
        print("\nAvailable Categories:")
        categories = list(CATEGORY_MAP.keys()) + ["Other"]
        for idx, cat in enumerate(categories, 1):
            print(f"{idx}. {cat}")

        cat_choice = input(f"Select a category (1-{len(categories)}): ").strip()
        if not cat_choice.isdigit() or not (1 <= int(cat_choice) <= len(categories)):
            print("Invalid selection.")
            return

        selected_cat = categories[int(cat_choice) - 1]

        if selected_cat == "Other":
            all_known_exts = [ext for exts in CATEGORY_MAP.values() for ext in exts]
            matches = [item for item in catalog if item.get("extension") not in all_known_exts]
        else:
            target_exts = CATEGORY_MAP[selected_cat]
            matches = [item for item in catalog if item.get("extension") in target_exts]

        header_title = f"{selected_cat} Files"

    elif sub_choice == "3":
        all_exts = sorted(set(item.get("extension", "") for item in catalog if item.get("extension")))
        if all_exts:
            print(f"\nAvailable extensions in catalog: {', '.join(all_exts)}")

        search_ext = input("Enter extension to filter by (e.g. .jpg or jpg, or Enter to cancel): ").strip().lower()
        if not search_ext:
            return
        if not search_ext.startswith("."):
            search_ext = "." + search_ext

        matches = [item for item in catalog if item.get("extension", "").lower() == search_ext]
        header_title = f"Files with extension '{search_ext}'"


    else:
        print("Invalid selection.")
        return

    if not matches:
        print(f"\nNo matching files found.")
        return

    # Ask for sorting preference
    print("\nSort by file size?")
    print("1. Largest to Smallest")
    print("2. Smallest to Largest")
    print("3. Default (Unsorted)")
    sort_choice = input("Select sort option (1-3): ").strip()

    if sort_choice == "1":
        matches.sort(key=lambda x: x.get("size_bytes", 0), reverse=True)
        header_title += " (Sorted: Largest to Smallest)"
    elif sort_choice == "2":
        matches.sort(key=lambda x: x.get("size_bytes", 0))
        header_title += " (Sorted: Smallest to Largest)"

    print(f"\n--- {header_title} ({len(matches)} found) ---")
    for item in matches:
        location = item.get("full_path", item.get("relative_path"))
        size_display = format_size(item.get("size_bytes", 0))
        print(f"- {item['filename']} [{size_display}] (Location: {location})")