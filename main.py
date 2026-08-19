# --- Standard Library Imports ---
import sys
import os
import time
import traceback

# --- PySide6 Imports ---
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QCoreApplication

# --- Local Application Imports ---
from src.ui.main_window import DownloaderApp
from src.core.visual_sorter import VisualSorter
from src.ui.dialogs.TourDialog import TourDialog
from src.config.constants import CONFIG_ORGANIZATION_NAME, CONFIG_APP_NAME_MAIN

# --- Define APP_BASE_DIR globally and make available early ---
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    APP_BASE_DIR = sys._MEIPASS
else:
    APP_BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Optional: Set a global variable or pass it into modules if needed
# Or re-export it via constants.py for cleaner imports

def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    """
    Handles uncaught exceptions by logging them to a file for easier debugging,
    especially for bundled applications.
    """
    # Use APP_BASE_DIR to determine logging location
    log_dir = os.path.join(APP_BASE_DIR, "logs")
    log_file_path = os.path.join(log_dir, "uncaught_exceptions.log")

    try:
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write("-" * 80 + "\n\n")
    except Exception as log_ex:
        # Fallback to stderr if logging to file fails
        print(f"CRITICAL: Failed to write to uncaught_exceptions.log: {log_ex}", file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    
    # Also call the default excepthook
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

# In main.py
def preload_ai_model():
    """Try to preload the AI model if it exists. If not, continue normally."""
    try:
        models_dir = os.path.join(APP_BASE_DIR, "appdata", "models")
        model_path = os.path.join(models_dir, "model.onnx")
        csv_path = os.path.join(models_dir, "selected_tags.csv")
        
        if not os.path.exists(model_path) or not os.path.exists(csv_path):
            # Log to console or internal logging system
            print("ℹ️ Visual Sort AI model not found. This feature will be available once downloaded via settings.")
            return

        # Pre-initialize the singleton if files exist
        from src.core.visual_sorter import VisualSorter
        VisualSorter.get_instance(model_path, csv_path)
        print("✅ Visual Sort AI engine initialized successfully.")
    except Exception as e:
        print(f"⚠️ Note: Visual Sort engine could not be pre-loaded: {e}")

def main():
    """Main entry point for the Kemono Downloader application."""
    
    # Set up global exception handling
    sys.excepthook = handle_uncaught_exception

    try:
        # Set up application metadata for QSettings
        QCoreApplication.setOrganizationName(CONFIG_ORGANIZATION_NAME)
        QCoreApplication.setApplicationName(CONFIG_APP_NAME_MAIN)
        preload_ai_model()

        # --- Windows Taskbar AppUserModelID ---
        # MUST be called BEFORE QApplication() so Windows assigns the correct
        # taskbar group instead of grouping under the python.exe icon.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "KemonoDownloader.App.1"
            )
        except Exception:
            pass  # Non-Windows platforms silently skip this.

        qt_app = QApplication(sys.argv)
        qt_app.setStyle("Fusion")

        # --- Application-level icon (taskbar + all windows) ---
        from PySide6.QtGui import QIcon
        _icon_path = os.path.join(APP_BASE_DIR, "assets", "Kemono.ico")
        if os.path.exists(_icon_path):
            _app_icon = QIcon(_icon_path)
            qt_app.setWindowIcon(_app_icon)
        else:
            _app_icon = None

        # Create the main application window
        downloader_app_instance = DownloaderApp()

        # Belt-and-suspenders: also set directly on the window in case the
        # QApplication-level icon isn't picked up by the specific platform.
        if _app_icon and not _app_icon.isNull():
            downloader_app_instance.setWindowIcon(_app_icon)


        # --- Window Sizing and Positioning ---
        primary_screen = QApplication.primaryScreen()
        if not primary_screen:
            downloader_app_instance.resize(1024, 768)
        else:
            available_geo = primary_screen.availableGeometry()
            screen_width = available_geo.width()
            screen_height = available_geo.height()
            
            min_app_width, min_app_height = 960, 680
            desired_width_ratio, desired_height_ratio = 0.80, 0.85

            app_width = max(min_app_width, int(screen_width * desired_width_ratio))
            app_height = max(min_app_height, int(screen_height * desired_height_ratio))

            app_width = min(app_width, screen_width)
            app_height = min(app_height, screen_height)
            
            downloader_app_instance.resize(app_width, app_height)

        # Show and center the main window
        downloader_app_instance.show()
        if hasattr(downloader_app_instance, '_center_on_screen'):
            downloader_app_instance._center_on_screen()

        # --- First-Run Welcome Tour ---
        if TourDialog.should_show_tour():
            tour_dialog = TourDialog(parent_app=downloader_app_instance)
            tour_dialog.exec()

        # --- Start Application ---
        exit_code = qt_app.exec()
        print(f"Application finished with exit code: {exit_code}")
        sys.exit(exit_code)

    except SystemExit:
        pass
    except Exception as e:
        print("--- CRITICAL APPLICATION STARTUP ERROR ---")
        print(f"An unhandled exception occurred during application startup: {e}")
        traceback.print_exc()
        print("--- END CRITICAL ERROR ---")


if __name__ == '__main__':
    main()