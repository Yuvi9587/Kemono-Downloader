import os
import sys
from PySide6.QtGui import QIcon

_app_icon_cache = None

def get_asset_path(filename):
    """
    Return the path to an asset, works in both dev and packaged environments.
    Handles --onedir where sys._MEIPASS is the _internal folder.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
    # If the filename already starts with 'assets', don't duplicate it.
    normalized_filename = filename.replace('\\', '/')
    if not normalized_filename.startswith('assets/'):
        return os.path.join(base_path, 'assets', filename)
    
    return os.path.join(base_path, filename)

def get_app_icon_object():
    """
    Loads and caches the application icon from the assets folder.
    This function is now centralized to prevent circular imports.

    Returns:
        QIcon: The application icon object.
    """
    global _app_icon_cache
    if _app_icon_cache and not _app_icon_cache.isNull():
        return _app_icon_cache

    icon_path = get_asset_path('Kemono.ico')
    
    if os.path.exists(icon_path):
        _app_icon_cache = QIcon(icon_path)
    else:
        print(f"Warning: Application icon not found at {icon_path}")
        _app_icon_cache = QIcon()
        
    return _app_icon_cache