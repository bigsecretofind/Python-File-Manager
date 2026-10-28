from config import get_target_directory
from catalog_manager import (
    handle_scan_or_add,
    handle_view_files,
    handle_tags,
    handle_file_categories,
    CatalogError,
)


def main_menu():
    target_folder = get_target_directory()

    while True:
        print("\n==============================")
        print("     FILE CATALOGER MENU     ")
        print("==============================")
        print(f"Current Target: {target_folder}")
        print("1. Scan / Add to Catalog")
        print("2. View Directory Contents")
        print("3. Tag Management (Add/Delete/Search)")
        print("4. File Search / Filter Files")
        print("5. [Choice 5]")
        print("6. [Choice 6]")
        print("0. Exit Program")
        print("==============================")

        choice = input("Select an option (0-6): ").strip()

        try:
            if choice == "1":
                handle_scan_or_add(target_folder)
            elif choice == "2":
                handle_view_files(target_folder)
            elif choice == "3":
                handle_tags(target_folder)
            elif choice == "4":
                handle_file_categories(target_folder)
            elif choice in ["5", "6"]:
                print(f"\n[Choice {choice} is reserved for your next feature]")
            elif choice == "0":
                print("\nExiting program. Goodbye!")
                break
            else:
                print("\nInvalid selection. Please enter a number from 0 to 6.")
        except CatalogError:
            print("Returning to the main menu without changing the catalog.")


if __name__ == "__main__":
    main_menu()