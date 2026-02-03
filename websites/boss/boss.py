import os
import sys
import warnings

warnings.filterwarnings('ignore')

# 确保能导入项目根目录的 util
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from csv_processor import process_csv, remove_duplicate_jobs, generate_additional_fields


def main_menu():
    print("\n" + "=" * 80)
    print("BOSS Job Scraper (Browser Extension Mode)")
    print("=" * 80)
    print("\nPlease choose an option:")
    print("  1. Start Bridge Server (Connect with Chrome Extension)")
    print("  2. Process with Gemini (generate Chinese fields)")
    print("  3. Remove duplicate items")
    print("  4. Generate salary_english, type, and source_name_english")
    print("  q. Exit")
    print("=" * 80)

    while True:
        try:
            choice = input("\nEnter your choice (1-4, q): ").strip().lower()

            if choice == "q":
                print("Exiting...")
                break
            elif choice == "1":
                print("\n" + "=" * 80)
                print("🚀 Bridge Server Starting... (Listening on http://127.0.0.1:5000)")
                print("Please ensure your Chrome Extension is loaded and active.")
                print("=" * 80 + "\n")
                from server import app
                app.run(port=5000)
                break
            elif choice == "2":
                print("\n" + "=" * 80)
                print("Starting: Process with Gemini (generate Chinese fields)")
                print("=" * 80 + "\n")
                process_csv()
                break
            elif choice == "3":
                print("\n" + "=" * 80)
                print("Starting: Remove duplicate items")
                print("=" * 80 + "\n")
                remove_duplicate_jobs()
                break
            elif choice == "4":
                print("\n" + "=" * 80)
                print("Starting: Generate salary_english, type, and source_name_english")
                print("=" * 80 + "\n")
                generate_additional_fields()
                break
            else:
                print("❌ Invalid choice. Please enter 1, 2, 3, 4, or q.")
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Please try again.")


if __name__ == "__main__":
    main_menu()
