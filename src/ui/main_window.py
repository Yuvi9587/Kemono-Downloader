import sys
import os
import time
import glob
import queue
import random 
import traceback
import html
import http
import json
import re
import asyncio
import subprocess
import datetime
import requests
import cloudscraper
import unicodedata
import itertools
import uuid
import sip
from urllib.parse import urlparse, parse_qs
from collections import deque, defaultdict, Counter
import threading
from concurrent.futures import Future, ThreadPoolExecutor, CancelledError

from PyQt5.QtGui import QIcon, QIntValidator, QDesktopServices, QTextCharFormat
from .assets import get_asset_path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QListWidget, QRadioButton,
    QButtonGroup, QCheckBox, QSplitter, QGroupBox, QDialog, QStackedWidget,
    QScrollArea, QListWidgetItem, QSizePolicy, QProgressBar, QAbstractItemView, QFrame,
    QMainWindow, QAction, QGridLayout, 
)
try:
    from PIL import Image
except ImportError:
    Image = None

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QSettings, QStandardPaths, QUrl, QSize, QProcess, QMutex, QMutexLocker, QCoreApplication
from ..services.drive_downloader import (
    download_mega_file as drive_download_mega_file,
    download_gdrive_file,
    download_dropbox_file,
    download_gofile_folder  
)
from ..core.workers import DownloadThread as BackendDownloadThread, PostProcessorWorker, PostProcessorSignals
from ..services.multipart_downloader import download_file_in_parts, MULTIPART_DOWNLOADER_AVAILABLE
from ..core.api_client import download_from_api
from ..core.discord_client import fetch_server_channels, fetch_channel_messages 
from ..core.manager import DownloadManager
from ..core.fap_nation_client import fetch_fap_nation_data
from ..core.nhentai_client import fetch_nhentai_gallery
from ..core.bunkr_client import fetch_bunkr_data
from ..core.mangadex_client import fetch_mangadex_data  
from ..core.saint2_client import fetch_saint2_data 
from ..core.erome_client import fetch_erome_data
from ..core.Hentai2read_client import run_hentai2read_download as h2r_run_download
from ..core.allcomic_client import get_chapter_list as allcomic_get_list, fetch_chapter_data as allcomic_fetch_data
from ..core.toonily_client import get_chapter_list as toonily_get_list, fetch_chapter_data as toonily_fetch_data
from ..core.pixeldrain_client import fetch_pixeldrain_data 
from ..core.simpcity_client import fetch_single_simpcity_page
from ..core.booru_client import fetch_booru_data, BooruClientException
from .assets import get_app_icon_object
from ..config.constants import *
from ..utils.file_utils import KNOWN_NAMES, clean_folder_name
from ..utils.network_utils import extract_post_info, prepare_cookies_for_request
from ..utils.resolution import setup_ui, get_dark_theme, get_dark_theme as get_theme_stylesheet
from ..utils.command import parse_commands_from_text
from ..i18n.translator import get_translation
from .dialogs.EmptyPopupDialog import EmptyPopupDialog
from .dialogs.CookieHelpDialog import CookieHelpDialog
from .dialogs.FavoriteArtistsDialog import FavoriteArtistsDialog
from .dialogs.KnownNamesFilterDialog import KnownNamesFilterDialog
from .dialogs.HelpGuideDialog import HelpGuideDialog
from .dialogs.FutureSettingsDialog import FutureSettingsDialog, CountdownMessageBox
from .dialogs.ErrorFilesDialog import ErrorFilesDialog
from .dialogs.DownloadHistoryDialog import DownloadHistoryDialog
from ..services.updater import UpdateChecker, UpdateDownloader, PatchUpdateChecker
from .dialogs.Rule34SettingsDialog import Rule34SettingsDialog
from .dialogs.DownloadExtractedLinksDialog import DownloadExtractedLinksDialog
from .dialogs.FavoritePostsDialog import FavoritePostsDialog
from .dialogs.ConfirmAddAllDialog import ConfirmAddAllDialog
from .dialogs.MoreOptionsDialog import MoreOptionsDialog
from .dialogs.SinglePDF import create_single_pdf_from_content
from .dialogs.discord_pdf_generator import create_pdf_from_discord_messages
from .dialogs.SupportDialog import SupportDialog
from .dialogs.KeepDuplicatesDialog import KeepDuplicatesDialog
from .dialogs.MultipartScopeDialog import MultipartScopeDialog
from .dialogs.ExportLinksDialog import ExportLinksDialog
from .dialogs.CustomFilenameDialog import CustomFilenameDialog
from .dialogs.VisualSortDownloadDialog import VisualSortSetupDialog
from .dialogs.Rule34SettingsDialog import Rule34SettingsDialog
from .classes.erome_downloader_thread import EromeDownloadThread
from .classes.saint2_downloader_thread import Saint2DownloadThread
from .classes.discord_downloader_thread import DiscordDownloadThread
from .classes.fap_nation_downloader_thread import FapNationDownloadThread
from .classes.simp_city_downloader_thread import SimpCityDownloadThread
from .classes.allcomic_downloader_thread import AllcomicDownloadThread
from .classes.toonily_downloader_thread import ToonilyDownloadThread
from .classes.bunkr_downloader_thread import BunkrDownloadThread
from .classes.hentai2read_downloader_thread import Hentai2readDownloadThread
from .classes.booru_downloader_thread import BooruDownloadThread
from .classes.pixeldrain_downloader_thread import PixeldrainDownloadThread
from .classes.mangadex_downloader_thread import MangaDexDownloadThread
from .classes.drive_downloader_thread import DriveDownloadThread
from .classes.external_link_downloader_thread import ExternalLinkDownloadThread
from .classes.nhentai_downloader_thread import NhentaiDownloadThread
from .classes.downloader_factory import create_downloader_thread
from .classes.kemono_discord_downloader_thread import KemonoDiscordDownloadThread
from .classes.hentaifox_downloader_thread import HentaiFoxDownloadThread

_ff_ver = (datetime.date.today().toordinal() - 735506) // 28
USERAGENT_FIREFOX = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; "
                     f"rv:{_ff_ver}.0) Gecko/20100101 Firefox/{_ff_ver}.0")

class DynamicFilterHolder:
    """A thread-safe class to hold and update character filters during a download."""
    def __init__(self, initial_filters=None):
        self.lock = threading.Lock()
        self._filters = initial_filters if initial_filters is not None else []

    def get_filters(self):
        with self.lock:
            return [dict(f) for f in self._filters]

    def set_filters(self, new_filters):
        with self.lock:
            self._filters = [dict(f) for f in (new_filters if new_filters else [])]


class PostProcessorSignals(QObject):
    """A collection of signals for the DownloaderApp to communicate with itself across threads."""
    progress_signal = pyqtSignal(str)
    file_download_status_signal = pyqtSignal(bool)
    external_link_signal = pyqtSignal(str, str, str, str, str)
    file_progress_signal = pyqtSignal(str, object)
    file_successfully_downloaded_signal = pyqtSignal(dict)
    missed_character_post_signal = pyqtSignal(str, str)
    worker_finished_signal = pyqtSignal(tuple)
    finished_signal = pyqtSignal(int, int, bool, list)
    retryable_file_failed_signal = pyqtSignal(list)
    permanent_file_failed_signal = pyqtSignal(list)

class DownloaderApp (QWidget ):
    character_prompt_response_signal =pyqtSignal (bool )
    log_signal =pyqtSignal (str )
    add_character_prompt_signal =pyqtSignal (str )
    overall_progress_signal =pyqtSignal (int ,int )
    file_successfully_downloaded_signal =pyqtSignal (dict )
    post_processed_for_history_signal =pyqtSignal (dict )
    finished_signal =pyqtSignal (int ,int ,bool ,list )
    external_link_signal =pyqtSignal (str ,str ,str ,str ,str )
    file_progress_signal =pyqtSignal (str ,object )
    fetch_only_complete_signal = pyqtSignal(list)
    batch_update_check_complete_signal = pyqtSignal(list)


    def __init__(self):

        """
        Initializes the main application window. 
        Sets up core variables, creates necessary 'appdata' directories, 
        loads saved user settings (themes, paths, language), and builds the UI.
        """
        super().__init__()
        
        if getattr(sys, 'frozen', False):
            self.app_base_dir = os.path.dirname(sys.executable)
        else:
            self.app_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            
        user_data_path = os.path.join(self.app_base_dir, "appdata")
        os.makedirs(user_data_path, exist_ok=True)
        self.user_data_path = user_data_path
        
        ini_path = os.path.join(user_data_path, "config.ini")
        self.settings = QSettings(ini_path, QSettings.IniFormat)
        
        self.active_update_profile = None
        self.new_posts_for_update = []
        self.active_update_profiles_list = []
        self.fetched_posts_for_batch_update = []
        self.is_ready_to_download_batch_update = False
        self.is_finishing = False 
        self.finish_lock = threading.Lock() 
        self.add_info_in_pdf_setting = False
        
        self.patch_update_available = False
        self.patch_download_url = ""

        saved_res = self.settings.value(RESOLUTION_KEY, "Auto")
        if saved_res != "Auto":
            try:
                width, height = map(int, saved_res.split('x'))
                self.resize(width, height)
                self._center_on_screen() 
            except ValueError:
                pass

        self.jobs_dir = os.path.join(self.user_data_path, "jobs")
        os.makedirs(self.jobs_dir, exist_ok=True)
        self.is_running_job_queue = False
        self.current_job_file = None

        self.config_file = os.path.join(user_data_path, "Known.txt")
        self.session_file_path = os.path.join(user_data_path, "session.json")
        self.persistent_history_file = os.path.join(user_data_path, "download_history.json")

        self.download_thread = None
        self.thread_pool = None
        self.cancellation_event = threading.Event()
        self.session_lock = threading.Lock()
        self.interrupted_session_data = None
        self.is_restore_pending = False
        self.external_link_download_thread = None
        self.pause_event = threading.Event()
        self.active_futures = []
        self.total_posts_to_process = 0
        self.dynamic_character_filter_holder = DynamicFilterHolder()
        self.processed_posts_count = 0
        self.creator_name_cache = {}
        self.log_signal.emit(f"ℹ️ App base directory: {self.app_base_dir}")
        self.log_signal.emit(f"ℹ️ Persistent history file path set to: {self.persistent_history_file}")
        self.last_downloaded_files_details = deque(maxlen=3)
        self.download_history_candidates = deque(maxlen=8)
        self.final_download_history_entries = []
        self.favorite_download_queue = deque()
        self.is_processing_favorites_queue = False
        self.current_processing_favorite_item_info = None 
        self.download_counter = 0
        self.permanently_failed_files_for_dialog = []
        self.last_link_input_text_for_queue_sync = ""
        self.is_fetcher_thread_running = False
        self._restart_pending = False
        self.download_history_log = deque(maxlen=50)
        self.skip_counter = 0
        self.all_kept_original_filenames = []
        self.cancellation_message_logged_this_session = False
        self.favorite_scope_toggle_button = None
        self.favorite_download_scope = FAVORITE_SCOPE_SELECTED_LOCATION
        self.manga_mode_checkbox = None
        self.selected_cookie_filepath = None
        self.retryable_failed_files_info = []
        self.is_paused = False
        self.worker_to_gui_queue = queue.Queue()
        self.gui_update_timer = QTimer(self)
        self.actual_gui_signals = PostProcessorSignals()
        self.worker_signals = PostProcessorSignals()
        self.prompt_mutex = QMutex()
        self._add_character_response = None
        self._original_scan_content_tooltip = ("If checked, the downloader will scan the HTML content of posts for image URLs (from <img> tags or direct links).\n"
                                               "now This includes resolving relative paths from <img> tags to full URLs.\n"
                                               "Relative paths in <img> tags (e.g., /data/image.jpg) will be resolved to full URLs.\n"
                                               "Useful for cases where images are in the post description but not in the API's file/attachment list.")
        self.downloaded_files = set()
        self.downloaded_files_lock = threading.Lock()
        self.downloaded_file_hashes = set()
        self.downloaded_file_hashes_lock = threading.Lock()
        self.show_external_links = False
        self.external_link_queue = deque()
        self._is_processing_external_link_queue = False
        self._current_link_post_title = None
        self.extracted_links_cache = []
        self.manga_rename_toggle_button = None
        self.favorite_mode_checkbox = None
        self.url_or_placeholder_stack = None
        self.url_input_widget = None
        self.url_placeholder_widget = None
        self.favorite_action_buttons_widget = None
        self.favorite_mode_artists_button = None
        self.favorite_mode_posts_button = None
        self.standard_action_buttons_widget = None
        self.bottom_action_buttons_stack = None
        self.main_log_output = None
        self.external_log_output = None
        self.log_splitter = None
        self.main_splitter = None
        self.reset_button = None
        self.progress_log_label = None
        self.log_verbosity_toggle_button = None
        self.missed_character_log_output = None
        self.log_view_stack = None
        self.current_log_view = 'progress'
        self.link_search_input = None
        self.link_search_button = None
        self.export_links_button = None
        self.radio_only_links = None
        self.radio_only_archives = None
        self.missed_title_key_terms_count = {}
        self.missed_title_key_terms_examples = {}
        self.logged_summary_for_key_term = set()
        self.STOP_WORDS = set(["a", "an", "the", "is", "was", "were", "of", "for", "with", "in", "on", "at", "by", "to", "and", "or", "but", "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her", "its", "our", "their", "com", "net", "org", "www"])
        self.already_logged_bold_key_terms = set()
        self.missed_key_terms_buffer = []
        self.char_filter_scope_toggle_button = None
        self.skip_words_scope = SKIP_SCOPE_POSTS
        self.char_filter_scope = CHAR_SCOPE_TITLE
        self.manga_filename_style = self.settings.value(MANGA_FILENAME_STYLE_KEY, STYLE_POST_TITLE, type=str)
        self.custom_manga_filename_format = self.settings.value(MANGA_CUSTOM_FORMAT_KEY, "{published} {title}", type=str)        
        self.manga_custom_date_format = self.settings.value(MANGA_CUSTOM_DATE_FORMAT_KEY, "YYYY-MM-DD", type=str) 
        self.custom_manga_suffix_format = self.settings.value(MANGA_CUSTOM_SUFFIX_FORMAT_KEY, "001", type=str)
        self.current_theme = self.settings.value(THEME_KEY, "dark", type=str)
        self.only_links_log_display_mode = LOG_DISPLAY_LINKS
        self.mega_download_log_preserved_once = False
        self.allow_multipart_download_setting = False
        self.multipart_scope = 'both'
        self.multipart_parts_count = 4     
        self.multipart_min_size_mb = 100 
        self.use_cookie_setting = False
        self.scan_content_images_setting = self.settings.value(SCAN_CONTENT_IMAGES_KEY, False, type=bool)
        self.cookie_text_setting = ""
        self.current_selected_language = self.settings.value(LANGUAGE_KEY, "en", type=str)
        self.more_filter_scope = None 
        self.text_export_format = 'pdf'
        self.single_pdf_setting = False
        self.keep_duplicates_mode = DUPLICATE_HANDLING_HASH
        self.keep_duplicates_limit = 0 
        self.downloaded_hash_counts = defaultdict(int)
        self.downloaded_hash_counts_lock = threading.Lock()
        self.session_temp_files = []
        self.single_pdf_mode = False

        self.temp_pdf_content_list = []
        self.last_effective_download_dir = None
        self.save_creator_json_enabled_this_session = True 
        self.date_prefix_format = self.settings.value(DATE_PREFIX_FORMAT_KEY, "YYYY-MM-DD {post}", type=str)
        self.is_single_post_session = False 
        self.discord_download_scope = 'files' 
        self.is_fetching_only = False
        self.fetched_posts_for_download = []
        self.is_ready_to_download_fetched = False 
        self.last_logged_filter_mode = None
        self.last_logged_external_link_status = None
        self.allcomic_warning_shown = False 
        self.UI_PROFILES = {
            'kemono': {
                'enabled_radios': ['radio_all', 'radio_videos', 'radio_only_archives', 'radio_only_audio', 'radio_only_links', 'radio_more', 'radio_images'],
                'enabled_checkboxes': ['favorite_mode_checkbox', 'download_thumbnails_checkbox', 'scan_content_images_checkbox', 'keep_duplicates_checkbox'],
                'advanced_enabled': True,
                'filters_enabled': True,
                'force_radio': None
            },
            'image_only': {
                'enabled_radios': ['radio_images'], 
                'enabled_checkboxes': [], 
                'advanced_enabled': False,
                'filters_enabled': False,
                'force_radio': 'radio_images'
            },
            'erome': {
                'enabled_radios': ['radio_all', 'radio_videos', 'radio_images'], 
                'enabled_checkboxes': [],
                'advanced_enabled': False,
                'filters_enabled': False,
                'force_radio': 'radio_all'
            },
            'coomerfans': {
                'enabled_radios': ['radio_all', 'radio_videos', 'radio_images'], 
                'enabled_checkboxes': [],
                'advanced_enabled': True,
                'filters_enabled': False,
                'force_radio': 'radio_all',
                'allowed_advanced': ['use_subfolder_per_post_checkbox', 'manga_mode_checkbox', 'manga_rename_toggle_button', 'date_prefix_checkbox']
            },
            'deviantart': {
                'enabled_radios': ['radio_all', 'radio_images', 'radio_only_archives'],
                'enabled_checkboxes': [],
                'advanced_enabled': True, 
                'filters_enabled': False,
                'force_radio': 'radio_all',
                'allowed_advanced': ['manga_mode_checkbox', 'manga_rename_toggle_button', 'custom_rename_dialog_button']
            },
            'file_host': {
                'enabled_radios': ['radio_all', 'radio_only_archives'],
                'enabled_checkboxes': [],
                'advanced_enabled': False,
                'filters_enabled': False,
                'force_radio': 'radio_all'
            }
        }



        print(f"ℹ️ Known.txt will be loaded/saved at: {self.config_file}")

        try:
            icon_path_for_window = os.path.join(self.app_base_dir, 'assets', 'Kemono.ico')
            
            if os.path.exists(icon_path_for_window):
                self.setWindowIcon(QIcon(icon_path_for_window))
            else:
                if getattr(sys, 'frozen', False):
                    executable_dir = os.path.dirname(sys.executable)
                    fallback_icon_path = os.path.join(executable_dir, 'assets', 'Kemono.ico')
                    if os.path.exists(fallback_icon_path):
                        self.setWindowIcon(QIcon(fallback_icon_path))
                    else:
                        self.log_signal.emit(f"⚠️ Main window icon 'assets/Kemono.ico' not found at {icon_path_for_window} or {fallback_icon_path}")
                else:
                    self.log_signal.emit(f"⚠️ Main window icon 'assets/Kemono.ico' not found at {icon_path_for_window}")
        except Exception as e_icon_app:
            self.log_signal.emit(f"❌ Error setting main window icon in DownloaderApp init: {e_icon_app}")

        self.url_label_widget = None
        self.download_location_label_widget = None
        self.remove_from_filename_label_widget = None
        self.skip_words_label_widget = None
        self.setWindowTitle("Kemono Downloader v9.2.5")
        setup_ui(self)
        self._connect_signals()

        if self.main_log_output: self.main_log_output.document().setMaximumBlockCount(10000)
        if self.external_log_output: self.external_log_output.document().setMaximumBlockCount(10000)
        if hasattr(self, 'missed_character_log_output') and self.missed_character_log_output:
            self.missed_character_log_output.document().setMaximumBlockCount(10000)
        
        if hasattr(self, 'character_input'):
            self.character_input.setToolTip(self._tr("character_input_tooltip", "Enter character names (comma-separated)..."))
        self.log_signal.emit(f"ℹ️ filename style loaded: '{self.manga_filename_style}'")
        self.log_signal.emit(f"ℹ️ Skip words scope loaded: '{self.skip_words_scope}'")
        self.log_signal.emit(f"ℹ️ Character filter scope set to default: '{self.char_filter_scope}'")
        self.log_signal.emit(f"ℹ️ Application language loaded: '{self.current_selected_language.upper()}' (UI may not reflect this yet).")
        self._retranslate_main_ui()
        self._load_persistent_history()
        self._load_saved_download_location()
        self._load_saved_cookie_settings() 
        self._update_button_states_and_connections()
        self._check_for_interrupted_session()
        self._cleanup_after_update() 
        self._check_for_patch_update()

    def _check_for_patch_update(self):
        current_version = self.windowTitle().split(' v')[-1]
        self.patch_checker = PatchUpdateChecker(current_version)
        self.patch_checker.patch_available.connect(self._on_patch_available)
        self.patch_checker.start()

    def _on_patch_available(self, version, download_url):
        self.patch_update_available = True
        self.patch_download_url = download_url
        if hasattr(self, 'future_settings_button'):
            self.future_settings_button.setText("🟢")
            self.future_settings_button.setToolTip(f"Settings (Patch Update v{version} Available!)")
            self.future_settings_button.setStyleSheet("background-color: rgba(0, 255, 0, 0.1); border-radius: 5px;")
            
    def add_current_settings_to_queue(self):
        """
        Takes the current URL and UI settings, packages them into a dictionary, 
        and saves them as a JSON job file to be executed later in batch mode.
        """
        
        def get_creator_specific_path(base_dir, folder_name):
            if not folder_name: 
                return base_dir
            safe_name = clean_folder_name(folder_name)
           
            if base_dir.replace('\\', '/').rstrip('/').endswith(safe_name):
                return base_dir
            return os.path.join(base_dir, safe_name)
        if self.favorite_download_queue:
            count = 0
            base_settings = self._get_current_ui_settings_as_dict()
            items_to_process = list(self.favorite_download_queue)
            
            for item in items_to_process:
                real_url = item.get('url')
                name = item.get('name', 'Unknown')
                
                if not real_url: continue

                job_settings = base_settings.copy()
                job_settings['api_url'] = real_url 
                
                job_settings['output_dir'] = get_creator_specific_path(job_settings['output_dir'], name)

                if self._save_single_job_file(job_settings, name_hint=name):
                    count += 1
            
            if count > 0:
                self.log_signal.emit(f"✅ Added {count} jobs to queue from selection.")
                self.link_input.clear()
                self.favorite_download_queue.clear()
                QMessageBox.information(self, "Queue", f"{count} jobs successfully added to queue!")
            else:
                QMessageBox.warning(self, "Queue Error", "Failed to add selected items to queue.")
            return

   
        url = self.link_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Cannot add to queue: URL is empty.")
            return

        settings = self._get_current_ui_settings_as_dict()
        settings['api_url'] = url 
        
       
        service, user_id, post_id = extract_post_info(url)
        name_hint = "Job"
        
        if service and user_id:
            
            cache_key = (service.lower(), str(user_id))
            cached_name = self.creator_name_cache.get(cache_key)
            
            if cached_name:
                
                name_hint = cached_name
                settings['output_dir'] = get_creator_specific_path(settings['output_dir'], cached_name)
            else:
                if post_id:
                    folder_name = str(post_id)
                else:
                    folder_name = str(user_id)
                
                name_hint = folder_name
                settings['output_dir'] = get_creator_specific_path(settings['output_dir'], folder_name)

        if self._save_single_job_file(settings, name_hint=name_hint):
            self.log_signal.emit(f"✅ Job added to queue: {url}")
            self.link_input.clear()
            QMessageBox.information(self, "Queue", "Job successfully added to queue!")

    def _save_single_job_file(self, settings_dict, name_hint="job"):
        """
        Generates a unique filename and safely writes a job settings dictionary 
        to the disk inside the 'appdata/jobs' folder.
        """
        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:6]
        
        safe_name = "".join(c for c in name_hint if c.isalnum() or c in (' ', '_', '-')).strip()
        if not safe_name: 
            safe_name = "job"
        
        filename = f"job_{timestamp}_{safe_name}_{unique_id}.json"
        filepath = os.path.join(self.jobs_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(settings_dict, f, indent=2)
            return True
        except Exception as e:
            self.log_signal.emit(f"❌ Failed to save job file '{filename}': {e}")
            return False

    def execute_job_queue(self):
        """
        Triggered by the 'Execute Queue' button. 
        Locks the UI, scans the jobs folder for pending JSON files, and kicks off the processing loop.
        """
        job_files = sorted(glob.glob(os.path.join(self.jobs_dir, "job_*.json")))
        
        if not job_files:
            QMessageBox.information(self, "Queue Empty", "No job files found in appdata/jobs.")
            return

      
        self.permanently_failed_files_for_dialog.clear()
        self._update_error_button_count()

        self.log_signal.emit("=" * 40)
        self.log_signal.emit(f"🚀 Starting execution of {len(job_files)} queued jobs.")
        self.is_running_job_queue = True
        self.download_btn.setEnabled(False)
        self.add_queue_btn.setEnabled(False)
        
        self._process_next_queued_job()

    def _process_next_queued_job(self):

        """
        Pops the oldest job file from the queue, loads its settings into the UI, 
        and automatically clicks the 'Start Download' button for it.
        """

        if self.cancellation_event.is_set():
            self.is_running_job_queue = False
            self.log_signal.emit("🛑 Queue execution cancelled.")
            self._update_button_states_and_connections()
            return

        job_files = sorted(glob.glob(os.path.join(self.jobs_dir, "job_*.json")))
        
        if not job_files:
            self.is_running_job_queue = False
            self.current_job_file = None
            self.log_signal.emit("🏁 All queued jobs finished!")
            self.link_input.clear()
            QMessageBox.information(self, "Queue Finished", "All queued jobs have been processed.")
            self._update_button_states_and_connections()
            return

        next_job_path = job_files[0]
        self.current_job_file = next_job_path
        
        self.log_signal.emit(f"📂 Loading job: {os.path.basename(next_job_path)}")
        
        try:
            with open(next_job_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            target_dir = settings.get('output_dir', '')
            if target_dir:
                try:
                    os.makedirs(target_dir, exist_ok=True)
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Warning: Could not pre-create directory '{target_dir}': {e}")

            self._load_ui_from_settings_dict(settings)
            QCoreApplication.processEvents()
            
            self.start_download()
            
        except Exception as e:
            self.log_signal.emit(f"❌ Error loading/starting job '{next_job_path}': {e}")
            failed_path = next_job_path + ".failed"
            os.rename(next_job_path, failed_path)
            self._process_next_queued_job()

    def _run_discord_file_download_thread(self, session, server_id, channel_id, token, output_dir, message_limit=None):
        """
        Runs in a background thread to fetch and download all files from a Discord channel.
        """
        def queue_logger(message):
            self.worker_to_gui_queue.put({'type': 'progress', 'payload': (message,)})

        def queue_progress_label_update(message):
            self.worker_to_gui_queue.put({'type': 'set_progress_label', 'payload': (message,)})

        def check_events():
            if self.cancellation_event.is_set():
                return True
            while self.pause_event.is_set():
                time.sleep(0.5)
                if self.cancellation_event.is_set():
                    return True
            return False

        download_count = 0
        skip_count = 0
        
        try:
            queue_logger("=" * 40)
            queue_logger(f"🚀 Starting Discord download for channel: {channel_id}")
            queue_progress_label_update("Fetching messages...")

            def fetch_discord_api(endpoint):
                headers = {
                    'Authorization': token,
                    'User-Agent': USERAGENT_FIREFOX,
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                }
                try:
                    response = session.get(f"https://discord.com/api/v10{endpoint}", headers=headers)
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    return None

            last_message_id = None
            all_messages = []
            
            while True:
                if check_events(): break
                
                url_endpoint = f"/channels/{channel_id}/messages?limit=100"
                if last_message_id:
                    url_endpoint += f"&before={last_message_id}"
                
                message_batch = fetch_discord_api(url_endpoint)
                if not message_batch:
                    break
                
                all_messages.extend(message_batch)
                
                if message_limit and len(all_messages) >= message_limit:
                    queue_logger(f"   Reached message limit of {message_limit}. Halting fetch.")
                    all_messages = all_messages[:message_limit]
                    break

                last_message_id = message_batch[-1]['id']
                queue_progress_label_update(f"Fetched {len(all_messages)} messages...")
                time.sleep(1)

            if self.cancellation_event.is_set():
                self.finished_signal.emit(0, 0, True, [])
                return

            queue_progress_label_update(f"Collected {len(all_messages)} messages. Starting downloads...")
            total_attachments = sum(len(m.get('attachments', [])) for m in all_messages)
            
            for message in reversed(all_messages):
                if check_events(): break
                for attachment in message.get('attachments', []):
                    if check_events(): break
                    
                    file_url = attachment['url']
                    original_filename = attachment['filename']
                    filepath = os.path.join(output_dir, original_filename)
                    filename_to_use = original_filename

                    counter = 1
                    base_name, extension = os.path.splitext(original_filename)
                    while os.path.exists(filepath):
                        filename_to_use = f"{base_name} ({counter}){extension}"
                        filepath = os.path.join(output_dir, filename_to_use)
                        counter += 1
                    
                    if filename_to_use != original_filename:
                        queue_logger(f"   -> Duplicate name '{original_filename}'. Saving as '{filename_to_use}'.")

                    try:
                        queue_logger(f"   Downloading ({download_count+1}/{total_attachments}): '{filename_to_use}'...")
                        response = requests.get(file_url, stream=True, timeout=60)
                        response.raise_for_status()
                        
                        download_cancelled = False
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if check_events():
                                    download_cancelled = True
                                    break
                                f.write(chunk)
                        
                        if download_cancelled:
                            queue_logger(f"   Download cancelled for '{filename_to_use}'. Deleting partial file.")
                            if os.path.exists(filepath):
                                os.remove(filepath)
                            continue
                        
                        download_count += 1
                    except Exception as e:
                        queue_logger(f"   ❌ Failed to download '{filename_to_use}': {e}")
                        skip_count += 1
        
        finally:
            self.finished_signal.emit(download_count, skip_count, self.cancellation_event.is_set(), [])



    def _cleanup_after_update(self):
        """Deletes the old executable after a successful update."""
        try:
            app_path = sys.executable
            old_app_path = os.path.join(os.path.dirname(app_path), "Kemono.Downloader.exe.old")
            if os.path.exists(old_app_path):
                os.remove(old_app_path)
                self.log_signal.emit("ℹ️ Cleaned up old application file after update.")
        except Exception as e:
            self.log_signal.emit(f"⚠️ Could not remove old application file: {e}")

    def _connect_specialized_thread_signals(self, thread):
        """Connects common signals for specialized downloader threads."""

        is_kemono_discord = isinstance(thread, KemonoDiscordDownloadThread)        
        if hasattr(thread, 'progress_signal'):
            thread.progress_signal.connect(self.handle_main_log)
        if hasattr(thread, 'file_progress_signal'):
            thread.file_progress_signal.connect(self.update_file_progress_display)
        if hasattr(thread, 'overall_progress_signal'):
            thread.overall_progress_signal.connect(self.update_progress_display)
        if hasattr(thread, 'finished_signal'):
            thread.finished_signal.connect(
                lambda dl, skip, cancelled, names=None: self.download_finished(dl, skip, cancelled, names or [])
            )
        if hasattr(thread, 'progress_label_signal'):
            thread.progress_label_signal.connect(self.progress_label.setText)

        if is_kemono_discord and hasattr(thread, 'permanent_file_failed_signal'):
            thread.permanent_file_failed_signal.connect(self._handle_permanent_file_failure_from_thread)
            print("DEBUG: Connected permanent_file_failed_signal for KemonoDiscordDownloadThread.")

    def _apply_theme_and_restart_prompt(self):
        """Applies the theme and prompts the user to restart."""
        if self.current_theme == "dark":
            scale = getattr(self, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle(self._tr("theme_change_title", "Theme Changed"))
        msg_box.setText(self._tr("language_change_message", "A restart is required for these changes to take effect."))
        msg_box.setInformativeText(self._tr("language_change_informative", "Would you like to restart now?"))
        restart_button = msg_box.addButton(self._tr("restart_now_button", "Restart Now"), QMessageBox.ApplyRole)
        ok_button = msg_box.addButton(self._tr("ok_button", "OK"), QMessageBox.AcceptRole)
        msg_box.setDefaultButton(ok_button)
        msg_box.exec_()

        if msg_box.clickedButton() == restart_button:
            self._request_restart_application()

    def _setup_creator_profile(self, creator_name, session_file_path):
        """Prepares the path and loads data for the current creator's profile."""
        if not creator_name:
            self.log_signal.emit("⚠️ Cannot create creator profile: Name not provided.")
            return {}

        appdata_dir = os.path.dirname(session_file_path)
        creator_profiles_dir = os.path.join(appdata_dir, "creator_profiles")
        os.makedirs(creator_profiles_dir, exist_ok=True)

        safe_filename = clean_folder_name(creator_name) + ".json"
        profile_path = os.path.join(creator_profiles_dir, safe_filename)

        if os.path.exists(profile_path):
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.log_signal.emit(f"❌ Error loading creator profile '{safe_filename}': {e}. Starting fresh.")
        return {}

    def _save_creator_profile(self, creator_name, data, session_file_path):
        """Saves the provided data to the current creator's profile file."""
        if not creator_name:
            return
        
        appdata_dir = os.path.dirname(session_file_path)
        creator_profiles_dir = os.path.join(appdata_dir, "creator_profiles")
        safe_filename = clean_folder_name(creator_name) + ".json"
        profile_path = os.path.join(creator_profiles_dir, safe_filename)

        try:
            temp_path = profile_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, profile_path)
        except OSError as e:
            self.log_signal.emit(f"❌ Error saving creator profile to '{profile_path}': {e}")

    def _create_initial_session_file(self, api_url_for_session, override_output_dir_for_session, remaining_queue=None):
        """Creates the initial session file at the start of a new download."""
        if self.is_restore_pending:
            return

        self.log_signal.emit("📝 Creating initial session file for this download...")
        initial_ui_settings = self._get_current_ui_settings_as_dict(
            api_url_override=api_url_for_session,
            output_dir_override=override_output_dir_for_session
        )

        session_data = {
            "ui_settings": initial_ui_settings,
            "download_state": {
                "processed_post_ids": [],
                "permanently_failed_files": [],
                "successfully_downloaded_hashes": [], 
                "last_processed_offset": 0,  
                "manga_counters": {
                    "date_based": 1,
                    "global_numbering": 1
                }
            },
            "remaining_queue": list(remaining_queue) if remaining_queue else []
        }    
        self._save_session_file(session_data)

    def get_checkbox_map(self):
        """Returns a mapping of checkbox attribute names to their corresponding settings key."""
        return {
            'skip_zip_checkbox': 'skip_zip',
            'download_thumbnails_checkbox': 'download_thumbnails',
            'compress_images_checkbox': 'compress_images',
            'use_subfolders_checkbox': 'use_subfolders',
            'use_subfolder_per_post_checkbox': 'use_post_subfolders',
            'use_multithreading_checkbox': 'use_multithreading',
            'external_links_checkbox': 'show_external_links',
            'keep_duplicates_checkbox': 'keep_in_post_duplicates',
            'date_prefix_checkbox': 'use_date_prefix_for_subfolder',
            'manga_mode_checkbox': 'manga_mode_active',
            'scan_content_images_checkbox': 'scan_content_for_images',
            'use_cookie_checkbox': 'use_cookie',
            'favorite_mode_checkbox': 'favorite_mode_active',
            'revisions_checkbox': 'download_revisions',
            'visual_sort_checkbox': 'visual_sort_active'
        }

    def _get_current_ui_settings_as_dict(self, api_url_override=None, output_dir_override=None):
        """Gathers all relevant UI settings into a JSON-serializable dictionary."""
        settings = {}
        
        settings['api_url'] = api_url_override if api_url_override is not None else self.link_input.text().strip()
        settings['output_dir'] = output_dir_override if output_dir_override is not None else self.dir_input.text().strip()
        settings['character_filter_text'] = self.character_input.text().strip()
        settings['skip_words_text'] = self.skip_words_input.text().strip()
        settings['remove_words_text'] = self.remove_from_filename_input.text().strip()
        settings['custom_folder_name'] = self.custom_folder_input.text().strip()
        settings['cookie_text'] = self.cookie_text_input.text().strip()
        if hasattr(self, 'manga_date_prefix_input'):
            settings['manga_date_prefix'] = self.manga_date_prefix_input.text().strip()
        
        try: settings['num_threads'] = int(self.thread_count_input.text().strip())
        except (ValueError, AttributeError): settings['num_threads'] = 4
        try: settings['start_page'] = int(self.start_page_input.text().strip()) if self.start_page_input.text().strip() else None
        except (ValueError, AttributeError): settings['start_page'] = None
        try: settings['end_page'] = int(self.end_page_input.text().strip()) if self.end_page_input.text().strip() else None
        except (ValueError, AttributeError): settings['end_page'] = None

        for checkbox_name, key in self.get_checkbox_map().items():
            if checkbox := getattr(self, checkbox_name, None): settings[key] = checkbox.isChecked()

        settings['filter_mode'] = self.get_filter_mode()
        settings['only_links'] = self.radio_only_links.isChecked()

        settings['skip_words_scope'] = self.skip_words_scope
        settings['char_filter_scope'] = self.char_filter_scope
        settings['manga_filename_style'] = self.manga_filename_style
        settings['allow_multipart_download'] = self.allow_multipart_download_setting
        settings['more_filter_scope'] = self.more_filter_scope
        settings['text_export_format'] = self.text_export_format
        settings['single_pdf_setting'] = self.single_pdf_setting
        settings['add_info_in_pdf'] = self.add_info_in_pdf_setting
        settings['keep_duplicates_mode'] = self.keep_duplicates_mode
        settings['keep_duplicates_limit'] = self.keep_duplicates_limit
        settings['user_data_path'] = getattr(self, 'user_data_path', "")        

        settings['proxy_enabled'] = self.settings.value(PROXY_ENABLED_KEY, False, type=bool)
        settings['proxy_host'] = self.settings.value(PROXY_HOST_KEY, "", type=str)
        settings['proxy_port'] = self.settings.value(PROXY_PORT_KEY, "", type=str)
        settings['proxy_username'] = self.settings.value(PROXY_USERNAME_KEY, "", type=str)
        settings['proxy_password'] = self.settings.value(PROXY_PASSWORD_KEY, "", type=str)
        proxy_type_str = self.settings.value("proxy_type", "HTTP", type=str)

        settings['proxies'] = None
        if settings['proxy_enabled'] and settings['proxy_host'] and settings['proxy_port']:
            
            scheme = "http"
            if proxy_type_str == "SOCKS5":
                scheme = "socks5h"
            elif proxy_type_str == "SOCKS4":
                scheme = "socks4"

            if settings['proxy_username'] and settings['proxy_password']:
                 proxy_str = f"{scheme}://{settings['proxy_username']}:{settings['proxy_password']}@{settings['proxy_host']}:{settings['proxy_port']}"
            else:
                 proxy_str = f"{scheme}://{settings['proxy_host']}:{settings['proxy_port']}"
            
            settings['proxies'] = {'http': proxy_str, 'https': proxy_str}

        return settings


    def _tr (self ,key ,default_text =""):
        """Helper to get translation based on current app language for the main window."""
        if callable (get_translation ):
            return get_translation (self .current_selected_language ,key ,default_text )
        return default_text 

    def _load_saved_download_location (self ):
        saved_location =self .settings .value (DOWNLOAD_LOCATION_KEY ,"",type =str )
        if saved_location and os .path .isdir (saved_location ):
            if hasattr (self ,'dir_input')and self .dir_input :
                self .dir_input .setText (saved_location )
                self .log_signal .emit (f"ℹ️ Loaded saved download location: {saved_location }")
            else :
                self .log_signal .emit (f"⚠️ Found saved download location '{saved_location }', but dir_input not ready.")
        elif saved_location :
            self .log_signal .emit (f"⚠️ Found saved download location '{saved_location }', but it's not a valid directory. Ignoring.")

    def _check_for_interrupted_session(self):
        """
        Runs on boot. Checks if the app crashed during a previous download 
        by looking for an unfinished 'session.json' file, and preps the UI to restore it.
        """
        if os.path.exists(self.session_file_path):
            try:
                with open(self.session_file_path, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                if "ui_settings" not in session_data or "download_state" not in session_data:
                    raise ValueError("Invalid session file structure.")

                failed_files_from_session = session_data.get('download_state', {}).get('permanently_failed_files', [])
                if failed_files_from_session:
                    self.permanently_failed_files_for_dialog.clear()
                    self.permanently_failed_files_for_dialog.extend(failed_files_from_session)
                    self.log_signal.emit(f"ℹ️ Restored {len(failed_files_from_session)} failed file entries from the previous session.")

                remaining_queue_from_session = session_data.get('remaining_queue', [])
                if remaining_queue_from_session:
                    self.favorite_download_queue.clear()
                    self.favorite_download_queue.extend(remaining_queue_from_session)
                    self.log_signal.emit(f"ℹ️ Restored {len(self.favorite_download_queue)} creator(s) to the download queue.")

                self.interrupted_session_data = session_data
                self.log_signal.emit("ℹ️ Incomplete download session found. UI updated for restore.")
                self._prepare_ui_for_restore()

            except Exception as e:
                self.log_signal.emit(f"❌ Error reading session file: {e}. Deleting corrupt session file.")
                os.remove(self.session_file_path)
                self.interrupted_session_data = None
                self.is_restore_pending = False

    def _prepare_ui_for_restore(self):
        """Configures the UI to a 'restore pending' state."""
        if not self.interrupted_session_data:
            return

        self.log_signal.emit("   UI updated for session restore.")
        settings = self.interrupted_session_data.get("ui_settings", {})
        self._load_ui_from_settings_dict(settings)
        
        self.is_restore_pending = True
        self._update_button_states_and_connections()

    def _clear_session_and_reset_ui(self):
        """Clears the session file and resets the UI to its default state."""
        self._clear_session_file()
        self.interrupted_session_data = None
        self.is_restore_pending = False
        self._update_button_states_and_connections()
        self.reset_application_state()

    def _clear_session_file(self):
        """Safely deletes the session file."""
        if os.path.exists(self.session_file_path):
            try:
                os.remove(self.session_file_path)
                self.log_signal.emit("ℹ️ Interrupted session file cleared.")
            except Exception as e:
                self.log_signal.emit(f"❌ Failed to clear session file: {e}")

    def _save_session_file(self, session_data):
        """
        Safely writes the current download progress to 'session.json' using an atomic write 
        (writing to a .tmp file first, then renaming) so a crash during saving doesn't corrupt it.
        """
        temp_session_file_path = self.session_file_path + ".tmp"
        try:
            if 'download_state' in session_data:
                with self.downloaded_file_hashes_lock:
                    session_data['download_state']['successfully_downloaded_hashes'] = list(self.downloaded_file_hashes)
            with open(temp_session_file_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2)
            os.replace(temp_session_file_path, self.session_file_path)
        except Exception as e:
            self.log_signal.emit(f"❌ Failed to save session state: {e}")
            if os.path.exists(temp_session_file_path):
                try:
                    os.remove(temp_session_file_path)
                except Exception as e_rem:
                    self.log_signal.emit(f"❌ Failed to remove temp session file: {e_rem}")

    def _update_button_states_and_connections(self):
        try:
            self.download_btn.clicked.disconnect()
            self.pause_btn.clicked.disconnect()
            self.cancel_btn.clicked.disconnect()
        except TypeError: pass

        is_download_active = self._is_download_active()
        fetch_first_enabled = self.settings.value(FETCH_FIRST_KEY, False, type=bool)
        url_text = self.link_input.text().strip()
        
        is_queue_command = (url_text.lower() == "start queue")
        
        if hasattr(self, 'add_queue_btn'):
            should_enable_queue = (
                not is_download_active and 
                url_text != "" and 
                not is_queue_command and
                not self.is_ready_to_download_fetched and 
                not self.is_ready_to_download_batch_update
            )
            self.add_queue_btn.setEnabled(should_enable_queue)

        print(f"--- DEBUG: Updating buttons (is_download_active={is_download_active}) ---")

        if self.is_ready_to_download_fetched:
            num_posts = len(self.fetched_posts_for_download)
            self.download_btn.setText(f"Start Download ({num_posts} Posts)")
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
            self.download_btn.setEnabled(True)
            self.download_btn.clicked.connect(self.start_download)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setText("Clear Fetch")
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self.reset_application_state)
            return

        elif self.is_ready_to_download_batch_update:
            num_posts = len(self.fetched_posts_for_batch_update)
            self.download_btn.setText(f"Start Download ({num_posts} New Posts)")
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
            self.download_btn.setEnabled(True)
            self.download_btn.clicked.connect(self.start_download)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setText("Clear Update")
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self.reset_application_state)
            return

        if self.active_update_profile and self.new_posts_for_update and not is_download_active:
            num_new = len(self.new_posts_for_update)
            self.download_btn.setText(self._tr("start_download_new_button_text", f"Start Download ({num_new} new)"))
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
            self.download_btn.setEnabled(True)
            self.download_btn.clicked.connect(self.start_download)
            self.download_btn.setToolTip(self._tr("start_download_new_tooltip", "Click to download the new posts found."))

            self.pause_btn.setText(self._tr("pause_download_button_text", "Pause Download"))
            self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/pause.svg")))
            self.pause_btn.setEnabled(False)

            self.cancel_btn.setText(self._tr("clear_selection_button_text", "Clear Selection"))
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self._clear_update_selection)
            self.cancel_btn.setToolTip(self._tr("clear_selection_tooltip", "Click to cancel the update and clear the selection."))

        elif self.active_update_profile and not is_download_active:
            self.download_btn.setText(self._tr("check_for_updates_button_text", "🔄 Check For Updates"))
            self.download_btn.setEnabled(True)
            self.download_btn.clicked.connect(self.start_download)
            self.download_btn.setToolTip(self._tr("check_for_updates_tooltip", "Click to check for new posts from this creator."))

            self.pause_btn.setText(self._tr("pause_download_button_text", "Pause Download"))
            self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/pause.svg")))
            self.pause_btn.setEnabled(False)

            self.cancel_btn.setText(self._tr("clear_selection_button_text", "Clear Selection"))
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self._clear_update_selection)
            self.cancel_btn.setToolTip(self._tr("clear_selection_tooltip", "Click to clear the loaded creator profile and return to normal mode."))

        elif self.is_restore_pending:
            self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
            self.download_btn.setEnabled(True)
            self.download_btn.clicked.connect(self.start_download)
            self.download_btn.setToolTip(self._tr("start_download_discard_tooltip", "Click to start a new download, discarding the previous session."))

            self.pause_btn.setText(self._tr("restore_download_button_text", "Restore Download"))
            self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/resume.svg")))
            self.pause_btn.setEnabled(True)
            self.pause_btn.clicked.connect(self.restore_download)
            self.pause_btn.setToolTip(self._tr("restore_download_button_tooltip", "Click to restore the interrupted download."))

            self.cancel_btn.setText(self._tr("discard_session_button_text", "Discard Session"))
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self._clear_session_and_reset_ui)
            self.cancel_btn.setToolTip(self._tr("discard_session_tooltip", "Click to discard the interrupted session and reset the UI."))

        elif is_download_active:
            print("  --> Button state: ACTIVE DOWNLOAD/FETCH")
            if self.is_fetching_only:
                self.download_btn.setText("⏳ Fetching Pages...")
                self.download_btn.setEnabled(False)
                self.pause_btn.setEnabled(False)
            else:
                if self.is_ready_to_download_fetched:
                    num_posts = len(self.fetched_posts_for_download)
                    self.download_btn.setText(f"Start Download ({num_posts} Posts)")
                    self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
                    self.download_btn.setEnabled(True)
                else:
                    if hasattr(self, 'is_running_job_queue') and self.is_running_job_queue:
                         self.download_btn.setText("🔄 Processing Queue...")
                    else:
                         self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
                         self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
                    
                    self.download_btn.setEnabled(False)
                
                self.pause_btn.setText(self._tr("resume_download_button_text", "Resume Download") if self.is_paused else self._tr("pause_download_button_text", "Pause Download"))
                self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/resume.svg")) if self.is_paused else QIcon(get_asset_path("assets/Svg/pause.svg")))
                self.pause_btn.setEnabled(True)
                self.pause_btn.clicked.connect(self._handle_pause_resume_action)
            print("  --> Button state: IDLE")

            self.cancel_btn.setText(self._tr("cancel_button_text", "Cancel & Reset UI"))
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.clicked.connect(self.cancel_download_button_action)
        
        else:
            if is_queue_command:
                self.download_btn.setText("Execute Queue")
                self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/resume.svg")))
                self.download_btn.setEnabled(True)
                if hasattr(self, 'execute_job_queue'):
                    self.download_btn.clicked.connect(self.execute_job_queue)
            else:
                _, _, post_id = extract_post_info(url_text)
                is_single_post = bool(post_id)

                if fetch_first_enabled and not is_single_post and url_text:
                    self.download_btn.setText("📄 Fetch Pages")
                else:
                    self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
                    self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
                
                self.download_btn.setEnabled(True)
                self.download_btn.clicked.connect(self.start_download)

            self.pause_btn.setText(self._tr("pause_download_button_text", "Pause Download"))
            self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/pause.svg")))
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setText(self._tr("cancel_button_text", "Cancel & Reset UI"))
            self.cancel_btn.setEnabled(False)

        
    def _run_fetch_only_thread(self, fetch_args):
        """
        Runs in a background thread to ONLY fetch all posts without downloading.
        """
        all_posts = []
        try:
            post_generator = download_from_api(**fetch_args)
            for post_batch in post_generator:
                if self.cancellation_event.is_set():
                    break
                all_posts.extend(post_batch)
        except Exception as e:
            self.log_signal.emit(f"❌ Error during fetch-only operation: {e}")
        finally:
            self.fetch_only_complete_signal.emit(all_posts)

    def _fetch_only_finished(self, fetched_posts):
        """
        Called on the main thread when the fetch-only operation is complete.
        Updates the UI to the 'ready to download' state.
        """
        print("\n--- DEBUG: Entering _fetch_only_finished ---\n")
        self.download_thread = None        
        self.is_fetching_only = False

        if self.cancellation_event.is_set():
            self.log_signal.emit("ℹ️ Page fetching was cancelled.")
            self._update_button_states_and_connections()
            self.set_ui_enabled(True)
            return

        self.fetched_posts_for_download = fetched_posts
        self.is_ready_to_download_fetched = True
        self.log_signal.emit(f"✅ Fetch complete. Found {len(self.fetched_posts_for_download)} posts.")
        self.log_signal.emit("=" * 40)
        self.log_signal.emit("✅ Stage 1 complete. All post data has been fetched.")
        self.log_signal.emit("   💡 You can now disconnect your VPN (if used) before starting the download.")
        self.log_signal.emit("   Press the 'Start Download' button to begin Stage 2: Downloading files.")
        self.progress_label.setText(f"Found {len(self.fetched_posts_for_download)} posts. Ready to download.")
        
        self._update_button_states_and_connections()
        self.set_ui_enabled(True)

    def _start_download_of_fetched_posts(self):
        """
        Initiates the download of the posts that were previously fetched.
        """
        self.is_ready_to_download_fetched = False
        self.log_signal.emit("=" * 40)
        self.log_signal.emit(f"🚀 Starting Stage 2: Downloading files for {len(self.fetched_posts_for_download)} fetched posts.")
        self.log_signal.emit("   💡 If you disconnected your VPN, downloads will now use your regular connection.")

        raw_character_filters_text = self.character_input.text().strip()
        parsed_filters, download_commands = self._parse_character_filters(raw_character_filters_text)
        domain_override = download_commands.get('domain_override')
        
        args_template = self.last_start_download_args
        args_template['add_info_in_pdf'] = self.add_info_in_pdf_setting        
        args_template['filter_character_list'] = parsed_filters
        args_template['domain_override'] = domain_override
        
        self.set_ui_enabled(False)
        self.download_btn.setText("Downloading...")
        self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
        self.download_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel & Reset UI")
        try:
            self.cancel_btn.clicked.disconnect()
            self.pause_btn.clicked.disconnect()
        except TypeError:
            pass
        self.cancel_btn.clicked.connect(self.cancel_download_button_action)
        self.pause_btn.clicked.connect(self._handle_pause_resume_action)

        args_template = self.last_start_download_args
        args_template['fetch_first'] = False

        num_threads = int(self.thread_count_input.text()) if self.use_multithreading_checkbox.isChecked() else 1
        self.thread_pool = ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix='PostWorker_')

        self.total_posts_to_process = len(self.fetched_posts_for_download)
        self.processed_posts_count = 0
        self.overall_progress_signal.emit(self.total_posts_to_process, 0)

        ppw_expected_keys = list(PostProcessorWorker.__init__.__code__.co_varnames)[1:]

        for post_data in self.fetched_posts_for_download:
            self._submit_post_to_worker_pool(
                post_data, args_template, 1, self.worker_to_gui_queue, ppw_expected_keys, {}
            )

        self.fetched_posts_for_download = []
        self.is_fetcher_thread_running = False
        self._check_if_all_work_is_done()

    def update_discord_button_visibility(self, text=""):
        if not hasattr(self, 'save_discord_as_pdf_btn'):
            return
        url_text = self.link_input.text().strip()
        service, _, _ = extract_post_info(url_text)
        is_discord = (service == 'discord')
        self.save_discord_as_pdf_btn.setVisible(is_discord)

    def _clear_update_selection(self):
        """Clears the loaded creator profile and fully resets the UI to its default state."""
        self.log_signal.emit("ℹ️ Update selection cleared. Resetting UI to defaults.")
        self.active_update_profile = None
        self.new_posts_for_update = []
        self._perform_soft_ui_reset()

    def _retranslate_main_ui (self ):

        """
        Updates all static text labels, buttons, and tooltips in the UI 
        to match the currently selected language.
        """

        if self .url_label_widget :
            self .url_label_widget .setText (self ._tr ("creator_post_url_label","URL:"))
        if self .download_location_label_widget :
            self .download_location_label_widget .setText (self ._tr ("download_location_label",f"<img src='{get_asset_path('assets/Svg/folder.svg')}' width='13' height='13' align='top'> Download Location:"))
        if hasattr (self ,'character_label')and self .character_label :
            self .character_label .setText (self ._tr ("filter_by_character_label",f"<img src='{get_asset_path('assets/Svg/target.svg')}' width='13' height='13' align='top'> Filter by Character(s) (comma-separated):"))
        if self .skip_words_label_widget :
            self .skip_words_label_widget .setText (self ._tr ("skip_with_words_label",f"<img src='{get_asset_path('assets/Svg/block.svg')}' width='13' height='13' align='top'> Skip with Words (comma-separated):"))
        if self .remove_from_filename_label_widget :
            self .remove_from_filename_label_widget .setText (self ._tr ("remove_words_from_name_label","✂️ Remove Words from name:"))
        if hasattr (self ,'radio_all'):self .radio_all .setText (self ._tr ("filter_all_radio","All"))
        if hasattr (self ,'radio_images'):self .radio_images .setText (self ._tr ("filter_images_radio","Images/GIFs"))
        if hasattr (self ,'radio_videos'):self .radio_videos .setText (self ._tr ("filter_videos_radio","Videos"))
        if hasattr (self ,'radio_only_archives'):self .radio_only_archives .setText (self ._tr ("filter_archives_radio","Only Archives"))
        if hasattr (self ,'radio_only_links'):self .radio_only_links .setText (self ._tr ("filter_links_radio","Only Links"))
        if hasattr (self ,'radio_only_audio'):self .radio_only_audio .setText (self ._tr ("filter_audio_radio","Only Audio"))
        if hasattr (self ,'favorite_mode_checkbox'):self .favorite_mode_checkbox .setText (self ._tr ("favorite_mode_checkbox_label","Favorite Mode"))
        if hasattr (self ,'dir_button'):self .dir_button .setText (self ._tr ("browse_button_text","Browse..."))
        self ._update_char_filter_scope_button_text ()
        self ._update_skip_scope_button_text ()

        if hasattr (self ,'skip_zip_checkbox'):self .skip_zip_checkbox .setText (self ._tr ("skip_zip_checkbox_label","Skip .zip"))
        if hasattr (self ,'download_thumbnails_checkbox'):self .download_thumbnails_checkbox .setText (self ._tr ("download_thumbnails_checkbox_label","Download Thumbnails Only"))
        if hasattr (self ,'scan_content_images_checkbox'):self .scan_content_images_checkbox .setText (self ._tr ("scan_content_images_checkbox_label","Scan Content for Images"))
        if hasattr (self ,'compress_images_checkbox'):self .compress_images_checkbox .setText (self ._tr ("compress_images_checkbox_label","Compress to WebP"))
        if hasattr (self ,'use_subfolders_checkbox'):self .use_subfolders_checkbox .setText (self ._tr ("separate_folders_checkbox_label","Separate Folders by Known.txt"))
        if hasattr (self ,'use_subfolder_per_post_checkbox'):self .use_subfolder_per_post_checkbox .setText (self ._tr ("subfolder_per_post_checkbox_label","Subfolder per Post"))
        if hasattr (self ,'use_cookie_checkbox'):self .use_cookie_checkbox .setText (self ._tr ("use_cookie_checkbox_label","Use Cookie"))
        if hasattr (self ,'use_multithreading_checkbox'):self .update_multithreading_label (self .thread_count_input .text ()if hasattr (self ,'thread_count_input')else "1")
        if hasattr (self ,'external_links_checkbox'):self .external_links_checkbox .setText (self ._tr ("show_external_links_checkbox_label","Show External Links in Log"))
        if hasattr (self ,'manga_mode_checkbox'):self .manga_mode_checkbox .setText (self ._tr ("manga_comic_mode_checkbox_label","Renaming Mode"))
        if hasattr (self ,'thread_count_label'):self .thread_count_label .setText (self ._tr ("threads_label","Threads:"))

        if hasattr (self ,'character_input'):
            self .character_input .setToolTip (self ._tr ("character_input_tooltip","Enter character names (comma-separated)..."))
        if hasattr (self ,'download_btn'):self .download_btn .setToolTip (self ._tr ("start_download_button_tooltip","Click to start the download or link extraction process with the current settings."))





        current_download_is_active =self ._is_download_active ()if hasattr (self ,'_is_download_active')else False 
        self .set_ui_enabled (not current_download_is_active )

        if hasattr (self ,'known_chars_label'):self .known_chars_label .setText (self ._tr ("known_chars_label_text",f"<img src='{get_asset_path('assets/Svg/mask.svg')}' width='13' height='13' align='top'> Known Shows/Characters (for Folder Names):"))
        if hasattr (self ,'open_known_txt_button'):self .open_known_txt_button .setText (self ._tr ("open_known_txt_button_text","Open Known.txt"));self .open_known_txt_button .setToolTip (self ._tr ("open_known_txt_button_tooltip","Open the 'Known.txt' file..."))
        if hasattr (self ,'add_char_button'):self .add_char_button .setText (self ._tr ("add_char_button_text","Add"));self .add_char_button .setToolTip (self ._tr ("add_char_button_tooltip","Add the name from the input field..."))
        if hasattr (self ,'add_to_filter_button'):self .add_to_filter_button .setText (self ._tr ("add_to_filter_button_text","Add to Filter"));self .add_to_filter_button .setToolTip (self ._tr ("add_to_filter_button_tooltip","Select names from 'Known Shows/Characters' list..."))
        if hasattr (self ,'character_list'):
            self .character_list .setToolTip (self ._tr ("known_chars_list_tooltip","This list displays all names and groups from your 'Known.txt' file.\nThese entries are used by the 'Separate Folder by Known.txt' option to create folders automatically from post titles.\n\nYou can select items here and use the 'Add to Filter' button to quickly add them to the character filter field."))
        if hasattr (self ,'delete_char_button'):self .delete_char_button .setText (self ._tr ("delete_char_button_text","Delete Selected"));self .delete_char_button .setToolTip (self ._tr ("delete_char_button_tooltip","Delete the selected name(s)..."))

        if hasattr (self ,'cancel_btn'):self .cancel_btn .setToolTip (self ._tr ("cancel_button_tooltip","Click to cancel the ongoing download/extraction process and reset the UI fields (preserving URL and Directory)."))
        if hasattr (self ,'error_btn'):self .error_btn .setText (self ._tr ("error_button_text","Error"));self .error_btn .setToolTip (self ._tr ("error_button_tooltip","View files skipped due to errors and optionally retry them."))
        if hasattr (self ,'progress_log_label'):self .progress_log_label .setText (self ._tr ("progress_log_label_text",f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Progress Log:"))
        if hasattr (self ,'reset_button'):self .reset_button .setText (self ._tr ("reset_button_text","🔄 Reset"));self .reset_button .setToolTip (self ._tr ("reset_button_tooltip","Reset all inputs and logs to default state (only when idle)."))
        self ._update_multipart_toggle_button_text ()
        if hasattr (self ,'progress_label')and not self ._is_download_active ():self .progress_label .setText (self ._tr ("progress_idle_text","Progress: Idle"))
        if hasattr (self ,'favorite_mode_artists_button'):self .favorite_mode_artists_button .setText (self ._tr ("favorite_artists_button_text","🖼️ Favorite Artists"));self .favorite_mode_artists_button .setToolTip (self ._tr ("favorite_artists_button_tooltip","Browse and download from your favorite artists..."))
        if hasattr (self ,'favorite_mode_posts_button'):self .favorite_mode_posts_button .setText (self ._tr ("favorite_posts_button_text","📄 Favorite Posts"));self .favorite_mode_posts_button .setToolTip (self ._tr ("favorite_posts_button_tooltip","Browse and download your favorite posts..."))
        self ._update_favorite_scope_button_text ()
        if hasattr (self ,'page_range_label'):self .page_range_label .setText (self ._tr ("page_range_label_text","Page Range:"))
        if hasattr (self ,'start_page_input'):
            self .start_page_input .setPlaceholderText (self ._tr ("start_page_input_placeholder","Start"))
            self .start_page_input .setToolTip (self ._tr ("start_page_input_tooltip","For creator URLs: Specify the starting page number..."))
        if hasattr (self ,'to_label'):self .to_label .setText (self ._tr ("page_range_to_label_text","to"))
        if hasattr (self ,'end_page_input'):
            self .end_page_input .setPlaceholderText (self ._tr ("end_page_input_placeholder","End"))
            self .end_page_input .setToolTip (self ._tr ("end_page_input_tooltip","For creator URLs: Specify the ending page number..."))
        if hasattr (self ,'fav_mode_active_label'):
            self .fav_mode_active_label .setText (self ._tr ("fav_mode_active_label_text",f"<img src='{get_asset_path('assets/Svg/star.svg')}' width='13' height='13' align='top'> Favorite Mode is active..."))
        if hasattr (self ,'cookie_browse_button'):
            self .cookie_browse_button .setToolTip (self ._tr ("cookie_browse_button_tooltip","Browse for a cookie file..."))
        if hasattr(self, 'rule34_settings_btn'):
            self.rule34_settings_btn.clicked.connect(self._show_rule34_settings_dialog)       
        self ._update_manga_filename_style_button_text ()
        if hasattr (self ,'export_links_button'):self .export_links_button .setText (self ._tr ("export_links_button_text","Export Links"))
        if hasattr (self ,'download_extracted_links_button'):self .download_extracted_links_button .setText (self ._tr ("download_extracted_links_button_text","Download"))
        self ._update_log_display_mode_button_text ()


        if hasattr (self ,'radio_all'):self .radio_all .setToolTip (self ._tr ("radio_all_tooltip","Download all file types found in posts."))
        if hasattr (self ,'radio_images'):self .radio_images .setToolTip (self ._tr ("radio_images_tooltip","Download only common image formats (JPG, PNG, GIF, WEBP, etc.)."))
        if hasattr (self ,'radio_videos'):self .radio_videos .setToolTip (self ._tr ("radio_videos_tooltip","Download only common video formats (MP4, MKV, WEBM, MOV, etc.)."))
        if hasattr (self ,'radio_only_archives'):self .radio_only_archives .setToolTip (self ._tr ("radio_only_archives_tooltip","Exclusively download .zip and .rar files. Other file-specific options are disabled."))
        if hasattr (self ,'radio_only_audio'):self .radio_only_audio .setToolTip (self ._tr ("radio_only_audio_tooltip","Download only common audio formats (MP3, WAV, FLAC, etc.)."))
        if hasattr (self ,'radio_only_links'):self .radio_only_links .setToolTip (self ._tr ("radio_only_links_tooltip","Extract and display external links from post descriptions instead of downloading files.\nDownload-related options will be disabled."))


        if hasattr (self ,'use_subfolders_checkbox'):self .use_subfolders_checkbox .setToolTip (self ._tr ("use_subfolders_checkbox_tooltip","When checked, the post title will be scanned for names listed in 'Known.txt' to automatically create a subfolder.\n\nExample: A post titled 'Tifa in Nibelheim' will be saved in a 'Tifa' folder if 'Tifa' is in Known.txt.\n\nNote: If 'Filter by Character' is used, that filter will take priority for folder naming."))
        if hasattr (self ,'use_subfolder_per_post_checkbox'):self .use_subfolder_per_post_checkbox .setToolTip (self ._tr ("use_subfolder_per_post_checkbox_tooltip","Creates a subfolder for each post..."))
        if hasattr (self ,'use_cookie_checkbox'):self .use_cookie_checkbox .setToolTip (self ._tr ("use_cookie_checkbox_tooltip","If checked, will attempt to use cookies..."))
        if hasattr (self ,'use_multithreading_checkbox'):self .use_multithreading_checkbox .setToolTip (self ._tr ("use_multithreading_checkbox_tooltip","Enables concurrent operations..."))
        if hasattr (self ,'thread_count_input'):self .thread_count_input .setToolTip (self ._tr ("thread_count_input_tooltip","Number of concurrent operations..."))
        if hasattr (self ,'external_links_checkbox'):self .external_links_checkbox .setToolTip (self ._tr ("external_links_checkbox_tooltip","If checked, a secondary log panel appears..."))
        if hasattr (self ,'manga_mode_checkbox'):self .manga_mode_checkbox .setToolTip (self ._tr ("manga_mode_checkbox_tooltip","Downloads posts from oldest to newest..."))

        if hasattr (self ,'scan_content_images_checkbox'):self .scan_content_images_checkbox .setToolTip (self ._tr ("scan_content_images_checkbox_tooltip",self ._original_scan_content_tooltip ))
        if hasattr (self ,'download_thumbnails_checkbox'):self .download_thumbnails_checkbox .setToolTip (self ._tr ("download_thumbnails_checkbox_tooltip","Rewrites file URLs to download the smaller thumbnail version from the server instead of the full-sized file."))
        if hasattr (self ,'skip_words_input'):
            self .skip_words_input .setToolTip (self ._tr ("skip_words_input_tooltip",
            ("Enter words, comma-separated, to skip downloading certain content (e.g., WIP, sketch, preview).\n\n"
            "The 'Scope: [Type]' button next to this input cycles how this filter applies:\n"
            "- Scope: Files: Skips individual files if their names contain any of these words.\n"
            "- Scope: Posts: Skips entire posts if their titles contain any of these words.\n"
            "- Scope: Both: Applies both (post title first, then individual files if post title is okay).")))
        if hasattr (self ,'remove_from_filename_input'):
            self .remove_from_filename_input .setToolTip (self ._tr ("remove_words_input_tooltip",
            ("Enter words, comma-separated, to remove from downloaded filenames (case-insensitive).\n"
            "Useful for cleaning up common prefixes/suffixes.\nExample: patreon, kemono, [HD], _final")))

        if hasattr (self ,'link_input'):
            self .link_input .setPlaceholderText (self ._tr ("link_input_placeholder_text","e.g., https://kemono.su/patreon/user/12345 or .../post/98765, https://pixeldrain.com/u/V, https://saint2.su/embed/2H "))
            self .link_input .setToolTip (self ._tr ("link_input_tooltip_text","Enter the full URL..."))
        if hasattr (self ,'dir_input'):
            self .dir_input .setPlaceholderText (self ._tr ("dir_input_placeholder_text","Select folder where downloads will be saved"))
            self .dir_input .setToolTip (self ._tr ("dir_input_tooltip_text","Enter or browse to the main folder..."))
        if hasattr (self ,'character_input'):
            self .character_input .setPlaceholderText (self ._tr ("character_input_placeholder_text","e.g., Tifa, Aerith, (Cloud, Zack)"))
        if hasattr (self ,'custom_folder_input'):
            self .custom_folder_input .setPlaceholderText (self ._tr ("custom_folder_input_placeholder_text","Optional: Save this post to specific folder"))
            self .custom_folder_input .setToolTip (self ._tr ("custom_folder_input_tooltip_text","If downloading a single post URL..."))
        if hasattr (self ,'skip_words_input'):
            self .skip_words_input .setPlaceholderText (self ._tr ("skip_words_input_placeholder_text","e.g., WM, WIP, sketch, preview"))
        if hasattr (self ,'remove_from_filename_input'):
            self .remove_from_filename_input .setPlaceholderText (self ._tr ("remove_from_filename_input_placeholder_text","e.g., patreon, HD"))
        self ._update_cookie_input_placeholders_and_tooltips ()
        if hasattr (self ,'character_search_input'):
            self .character_search_input .setPlaceholderText (self ._tr ("character_search_input_placeholder_text","Search characters..."))
            self .character_search_input .setToolTip (self ._tr ("character_search_input_tooltip_text","Type here to filter the list..."))
        if hasattr (self ,'new_char_input'):
            self .new_char_input .setPlaceholderText (self ._tr ("new_char_input_placeholder_text","Add new show/character name"))
            self .new_char_input .setToolTip (self ._tr ("new_char_input_tooltip_text","Enter a new show, game, or character name..."))
        if hasattr (self ,'link_search_input'):
            self .link_search_input .setPlaceholderText (self ._tr ("link_search_input_placeholder_text","Search Links..."))
            self .link_search_input .setToolTip (self ._tr ("link_search_input_tooltip_text","When in 'Only Links' mode..."))
        if hasattr (self ,'manga_date_prefix_input'):
            self .manga_date_prefix_input .setPlaceholderText (self ._tr ("manga_date_prefix_input_placeholder_text","Prefix for Manga Filenames"))
            self .manga_date_prefix_input .setToolTip (self ._tr ("manga_date_prefix_input_tooltip_text","Optional prefix for 'Date Based'..."))
        if hasattr (self ,'empty_popup_button'):self .empty_popup_button .setToolTip (self ._tr ("empty_popup_button_tooltip_text","Open Creator Selection..."))
        if hasattr (self ,'known_names_help_button'):self .known_names_help_button .setToolTip (self ._tr ("known_names_help_button_tooltip_text","Open the application feature guide."))
        if hasattr (self ,'future_settings_button'):self .future_settings_button .setToolTip (self ._tr ("future_settings_button_tooltip_text","Open application settings..."))
        if hasattr (self ,'link_search_button'):self .link_search_button .setToolTip (self ._tr ("link_search_button_tooltip_text","Filter displayed links"))
 
    def _get_tooltip_for_character_input (self ):
        return (
        self ._tr ("character_input_tooltip","Default tooltip if translation fails.")
        )
    def _connect_signals (self ):
        """
        The central nervous system of the UI. 
        Hooks up all buttons, checkboxes, and background thread events 
        to their respective trigger functions.
        """

        self .actual_gui_signals .progress_signal .connect (self .handle_main_log )
        self .actual_gui_signals .file_progress_signal .connect (self .update_file_progress_display )
        self .actual_gui_signals .missed_character_post_signal .connect (self .handle_missed_character_post )
        self .actual_gui_signals .external_link_signal .connect (self .handle_external_link_signal )
        self .actual_gui_signals .file_successfully_downloaded_signal .connect (self ._handle_actual_file_downloaded )
        self.actual_gui_signals.worker_finished_signal.connect(self._handle_worker_result)       
        self .actual_gui_signals .file_download_status_signal .connect (lambda status :None )
        self.batch_update_check_complete_signal.connect(self._batch_update_check_finished)        
        self.fetch_only_complete_signal.connect(self._fetch_only_finished)

        if hasattr (self ,'character_input'):
            self .character_input .textChanged .connect (self ._on_character_input_changed_live )
        if hasattr (self ,'use_cookie_checkbox'):
            self .use_cookie_checkbox .toggled .connect (self ._update_cookie_input_visibility )
        if hasattr (self ,'link_input'):
            self.link_input.textChanged.connect(self._update_ui_for_url_change)
            self.link_input.textChanged.connect(self._update_contextual_ui_elements) 
            self.link_input.textChanged.connect(self._update_button_states_and_connections)
            self.link_input.textChanged.connect(self._update_booru_inputs_visibility) 
        if hasattr(self, 'discord_scope_toggle_button'):
            self.discord_scope_toggle_button.clicked.connect(self._cycle_discord_scope)
        if hasattr (self ,'cookie_browse_button'):
            self .cookie_browse_button .clicked .connect (self ._browse_cookie_file )
        if hasattr (self ,'cookie_text_input'):
            self .cookie_text_input .textChanged .connect (self ._handle_cookie_text_manual_change )


        if hasattr(self, 'keep_duplicates_checkbox'):
            self.keep_duplicates_checkbox.toggled.connect(self._handle_keep_duplicates_toggled)
        self .gui_update_timer .timeout .connect (self ._process_worker_queue )
        self .gui_update_timer .start (100 )
        self .log_signal .connect (self .handle_main_log )
        self .add_character_prompt_signal .connect (self .prompt_add_character )
        self .character_prompt_response_signal .connect (self .receive_add_character_result )
        self .overall_progress_signal .connect (self .update_progress_display )
        self .post_processed_for_history_signal .connect (self ._add_to_history_candidates )
        self .finished_signal .connect (self .download_finished )
        if hasattr (self ,'character_search_input'):self .character_search_input .textChanged .connect (self .filter_character_list )
        if hasattr (self ,'external_links_checkbox'):self .external_links_checkbox .toggled .connect (self .update_external_links_setting )
        if hasattr (self ,'thread_count_input'):self .thread_count_input .textChanged .connect (self .update_multithreading_label )
        if hasattr (self ,'use_subfolder_per_post_checkbox'):self .use_subfolder_per_post_checkbox .toggled .connect (self .update_ui_for_subfolders )
        if hasattr (self ,'use_multithreading_checkbox'):self .use_multithreading_checkbox .toggled .connect (self ._handle_multithreading_toggle )

        if hasattr (self ,'radio_group')and self .radio_group :
            self .radio_group .buttonToggled .connect (self ._handle_filter_mode_change )

        if self .reset_button :self .reset_button .clicked .connect (self .reset_application_state )
        if self .log_verbosity_toggle_button :self .log_verbosity_toggle_button .clicked .connect (self .toggle_active_log_view )

        if self .link_search_button :self .link_search_button .clicked .connect (self ._filter_links_log )
        if self .link_search_input :
            self .link_search_input .returnPressed .connect (self ._filter_links_log )
            self .link_search_input .textChanged .connect (self ._filter_links_log )
        if self .export_links_button :self .export_links_button .clicked .connect (self ._export_links_to_file )

        if hasattr(self, 'simpcity_save_external_links_cb'):
            self.simpcity_save_external_links_cb.toggled.connect(self._handle_simpcity_save_external_links_toggled)

        if self .manga_mode_checkbox :self .manga_mode_checkbox .toggled .connect (self .update_ui_for_manga_mode )


        if hasattr (self ,'download_extracted_links_button'):
            self .download_extracted_links_button .clicked .connect (self ._show_download_extracted_links_dialog )

        if hasattr (self ,'log_display_mode_toggle_button'):
            self .log_display_mode_toggle_button .clicked .connect (self ._toggle_log_display_mode )

        if self .manga_rename_toggle_button :self .manga_rename_toggle_button .clicked .connect (self ._toggle_manga_filename_style )

        if hasattr (self ,'link_input'):
            self .link_input .textChanged .connect (lambda :self .update_ui_for_manga_mode (self .manga_mode_checkbox .isChecked ()if self .manga_mode_checkbox else False ))

        if self .skip_scope_toggle_button :
            self .skip_scope_toggle_button .clicked .connect (self ._cycle_skip_scope )

        if self .char_filter_scope_toggle_button :
            self .char_filter_scope_toggle_button .clicked .connect (self ._cycle_char_filter_scope )

        if hasattr (self ,'multipart_toggle_button'):self .multipart_toggle_button .clicked .connect (self ._toggle_multipart_mode )


        if hasattr (self ,'favorite_mode_checkbox'):
            self .favorite_mode_checkbox .toggled .connect (self ._handle_favorite_mode_toggle )

        if hasattr (self ,'open_known_txt_button'):
            self .open_known_txt_button .clicked .connect (self ._open_known_txt_file )

        if hasattr (self ,'add_to_filter_button'):
            self .add_to_filter_button .clicked .connect (self ._show_add_to_filter_dialog )
        if hasattr (self ,'favorite_mode_artists_button'):
            self .favorite_mode_artists_button .clicked .connect (self ._show_favorite_artists_dialog )
        if hasattr (self ,'favorite_mode_posts_button'):
            self .favorite_mode_posts_button .clicked .connect (self ._show_favorite_posts_dialog )
        if hasattr (self ,'favorite_scope_toggle_button'):
            self .favorite_scope_toggle_button .clicked .connect (self ._cycle_favorite_scope )
        if hasattr (self ,'history_button'):
            self .history_button .clicked .connect (self ._show_download_history_dialog )
        if hasattr (self ,'error_btn'):
            self .error_btn .clicked .connect (self ._show_error_files_dialog )
        if hasattr(self, 'support_button'): 
            self.support_button.clicked.connect(self._show_support_dialog)

        if hasattr(self, 'use_subfolders_checkbox'):
            self.use_subfolders_checkbox.toggled.connect(self._enforce_visual_sort_pipeline_rules)

        if hasattr(self, 'visual_sort_checkbox'):
            self.visual_sort_checkbox.toggled.connect(self._handle_visual_sort_toggled)

    def _handle_visual_sort_toggled(self, checked):
        if not checked:
            self._enforce_visual_sort_pipeline_rules(True)
            return
        if getattr(self, '_is_loading_settings', False):
            self._enforce_visual_sort_pipeline_rules(False)
            return
        try:
            
            dialog = VisualSortSetupDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                self.log_signal.emit("✅ Visual Sort enabled and settings applied.")
                self._enforce_visual_sort_pipeline_rules(True)
            else:
                self.visual_sort_checkbox.blockSignals(True)
                self.visual_sort_checkbox.setChecked(False)
                self.visual_sort_checkbox.blockSignals(False)
                self.log_signal.emit("ℹ️ Visual Sort setup cancelled.")
                self._enforce_visual_sort_pipeline_rules(True)
                
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error launching Visual Sort setup: {e}")
            
            self.visual_sort_checkbox.blockSignals(True)
            self.visual_sort_checkbox.setChecked(False)
            self.visual_sort_checkbox.blockSignals(False)
            self._enforce_visual_sort_pipeline_rules(True)

    def _enforce_visual_sort_pipeline_rules(self, verbose=False):
        """Dynamically forces UI settings when the Cascade Pipeline (Known.txt + AI) is active."""
        known_txt_on = getattr(self, 'use_subfolders_checkbox', None) and self.use_subfolders_checkbox.isChecked()
        visual_sort_on = getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked()

        if known_txt_on and visual_sort_on:
            if hasattr(self, 'use_subfolder_per_post_checkbox'):
                self.use_subfolder_per_post_checkbox.setChecked(False)
                self.use_subfolder_per_post_checkbox.setEnabled(False)

            self.char_filter_scope = CHAR_SCOPE_BOTH
            self._update_char_filter_scope_button_text()
            if hasattr(self, 'char_filter_scope_toggle_button'):
                self.char_filter_scope_toggle_button.setEnabled(False)
                
            if verbose:
                self.log_signal.emit("ℹ️ Smart Pipeline Active: 'Subfolder per post' automatically disabled & Scope forced to 'Both'.")
        else:
            if hasattr(self, 'use_subfolders_checkbox'):
                self.update_ui_for_subfolders(self.use_subfolders_checkbox.isChecked())
                
            current_filter_mode = self.get_filter_mode()
            is_only_links = (current_filter_mode == 'all' and getattr(self, 'radio_only_links', None) and self.radio_only_links.isChecked())
            
            if not is_only_links and hasattr(self, 'char_filter_scope_toggle_button') and not self._is_download_active():
                self.char_filter_scope_toggle_button.setEnabled(True)

    def get_booru_credentials(self):
        """Extracts the api_key and user_id from the unified pasted string."""
        
        raw_creds = ""
        if hasattr(self, 'booru_creds_input'):
            raw_creds = self.booru_creds_input.text().strip()
            
        parsed = parse_qs(raw_creds.lstrip('?&'))
        
        api_key = parsed.get('api_key', [''])[0]
        user_id = parsed.get('user_id', [''])[0]
        
        return api_key, user_id

    def _update_booru_inputs_visibility(self, text=""):
        url_text = self.link_input.text().strip().lower()
        
        is_rule34 = "rule34.xxx" in url_text
        is_standard_booru = "gelbooru.com" in url_text or "danbooru.donmai.us" in url_text
        
        if is_rule34 or is_standard_booru:
            self.booru_inputs_widget.setVisible(True)
            self.rule34_settings_btn.setVisible(True)
            
            if is_standard_booru:
                self.rule34_settings_btn.setText("⚙️ Booru Settings")
            else:
                self.rule34_settings_btn.setText("⚙️ Rule34 Settings")
        else:
            self.booru_inputs_widget.setVisible(False)

    def _on_character_input_changed_live (self ,text ):
        """
        Called when the character input field text changes.
        If a download is active (running or paused), this updates the dynamic filter holder.
        """
        if self ._is_download_active ():
            QCoreApplication .processEvents ()
            raw_character_filters_text =self .character_input .text ().strip ()
            parsed_filters =self ._parse_character_filters (raw_character_filters_text )

            self .dynamic_character_filter_holder .set_filters (parsed_filters )

    def _parse_single_filter_part(self, part_str):
        part_str = part_str.strip()
        if not part_str: return None
        
        is_tilde_group = part_str.startswith("(") and part_str.endswith(")~")
        is_standard_group = part_str.startswith("(") and part_str.endswith(")") and not is_tilde_group
        
        if is_tilde_group:
            inner_content = part_str[1:-2].strip()
            components_distinct = False
        elif is_standard_group:
            inner_content = part_str[1:-1].strip()
            components_distinct = True
        else:
            inner_content = part_str
            components_distinct = False

        and_parts = []
        current_buffer = ""
        depth = 0
        for char in inner_content:
            if char == '(': depth += 1; current_buffer += char
            elif char == ')':
                if depth > 0: depth -= 1
                current_buffer += char
            elif char == '+' and depth == 0:
                if current_buffer.strip(): and_parts.append(current_buffer.strip())
                current_buffer = ""
            else:
                current_buffer += char
        if current_buffer.strip():
            and_parts.append(current_buffer.strip())

        if len(and_parts) > 1:
            and_components = []
            for sub_part in and_parts:
                sub_obj = self._parse_single_filter_part(sub_part)
                if sub_obj:
                    and_components.append(sub_obj)
            
            if not and_components: return None
            
            folder_name = " + ".join([c["name"] for c in and_components])
            
            return {
                "name": folder_name,
                "is_group": is_standard_group or is_tilde_group,
                "is_and_condition": True,
                "and_components": and_components,
                "aliases": [folder_name],
                "components_are_distinct_for_known_txt": components_distinct
            }
        else:
            or_parts = []
            current_buffer = ""
            depth = 0
            for char in inner_content:
                if char == '(': depth += 1; current_buffer += char
                elif char == ')':
                    if depth > 0: depth -= 1
                    current_buffer += char
                elif char == ',' and depth == 0:
                    if current_buffer.strip(): or_parts.append(current_buffer.strip())
                    current_buffer = ""
                else:
                    current_buffer += char
            if current_buffer.strip():
                or_parts.append(current_buffer.strip())

            aliases = [p for p in or_parts if p]
            if not aliases: return None
            
            folder_name = " ".join(aliases)
            return {
                "name": folder_name,
                "is_group": is_standard_group or is_tilde_group or len(aliases) > 1,
                "is_and_condition": False,
                "aliases": aliases,
                "components_are_distinct_for_known_txt": components_distinct
            }

    def _parse_character_filters(self, raw_text):
        """
        Helper to parse character filter string into a list of filter objects
        and extract special commands.
        Returns a tuple: (list_of_filter_objects, dict_of_commands)
        """
        text_without_commands, commands = parse_commands_from_text(raw_text)

        parsed_character_filter_objects = []
        if text_without_commands:
            raw_parts = []
            current_part_buffer = ""
            depth = 0
            for char_token in text_without_commands:
                if char_token == '(':
                    depth += 1
                    current_part_buffer += char_token
                elif char_token == ')':
                    if depth > 0: depth -= 1
                    current_part_buffer += char_token
                elif char_token == ',' and depth == 0:
                    if current_part_buffer.strip(): raw_parts.append(current_part_buffer.strip())
                    current_part_buffer = ""
                else:
                    current_part_buffer += char_token
            if current_part_buffer.strip(): raw_parts.append(current_part_buffer.strip())

            for part_str in raw_parts:
                obj = self._parse_single_filter_part(part_str)
                if obj:
                    parsed_character_filter_objects.append(obj)

        return parsed_character_filter_objects, commands

    def _process_worker_queue (self ):
        """Processes messages from the worker queue and emits Qt signals from the GUI thread."""
        while not self .worker_to_gui_queue .empty ():
            try :
                item =self .worker_to_gui_queue .get_nowait ()
                signal_type =item .get ('type')
                payload =item .get ('payload',tuple ())

                if signal_type =='progress':
                    self .actual_gui_signals .progress_signal .emit (*payload )
                elif signal_type =='file_download_status':
                    self .actual_gui_signals .file_download_status_signal .emit (*payload )
                elif signal_type =='external_link':
                    self .actual_gui_signals .external_link_signal .emit (*payload )
                elif signal_type =='file_progress':
                    self .actual_gui_signals .file_progress_signal .emit (*payload )
                elif signal_type =='missed_character_post':
                    self .actual_gui_signals .missed_character_post_signal .emit (*payload )
                elif signal_type =='file_successfully_downloaded':
                    self ._handle_actual_file_downloaded (payload [0 ]if payload else {})
                elif signal_type =='file_successfully_downloaded':
                    self ._handle_file_successfully_downloaded (payload [0 ])
                elif signal_type == 'worker_finished':
                    self.actual_gui_signals.worker_finished_signal.emit(payload[0] if payload else tuple())
                elif signal_type == 'set_progress_label' and self.progress_label:
                    self.progress_label.setText(payload[0] if payload else "")
                elif signal_type == 'set_ui_enabled':
                    self.set_ui_enabled(payload[0] if payload else True)
                else:
                    self .log_signal .emit (f"⚠️ Unknown signal type from worker queue: {signal_type }")
                self .worker_to_gui_queue .task_done ()
            except queue .Empty :
                break 
            except Exception as e :
                self .log_signal .emit (f"❌ Error processing worker queue: {e }")

    def load_known_names_from_util(self):
        """
        Reads the 'Known.txt' file from the disk on startup. 
        Parses the names and aliases, and populates the UI list and background filtering arrays.
        """
        global KNOWN_NAMES 
        
        parsed_known_objects = []
        
        active_categories = getattr(self, 'active_known_categories', [])
        current_category = "Uncategorized"

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        
                        if line.startswith("# ---") and line.endswith("---"):
                            current_category = line.replace("# ---", "").replace("---", "").strip()
                            continue
                            
                        if not line or line.startswith('#'): 
                            continue 
                            
                        if active_categories and current_category not in active_categories:
                            continue

                        if line.startswith("(") and line.endswith(")"):
                            content = line[1:-1].strip()
                            parts = [p.strip() for p in content.split(',') if p.strip()]
                            if parts:
                                folder_name_raw = parts[0] 
                                folder_name_cleaned = clean_folder_name(folder_name_raw)

                                unique_aliases_set = {p for p in parts}
                                final_aliases_list = sorted(list(unique_aliases_set), key=str.lower)

                                if not folder_name_cleaned:
                                    continue 

                                parsed_known_objects.append({
                                    "name": folder_name_cleaned,
                                    "is_group": True,
                                    "aliases": final_aliases_list 
                                })
                        else:
                            parsed_known_objects.append({
                                "name": clean_folder_name(line),
                                "is_group": False,
                                "aliases": [line]
                            })
            except Exception as e:
                self.log_signal.emit(f"❌ Error loading list from '{self.config_file}': {e}")
                
        KNOWN_NAMES[:] = parsed_known_objects
        
        if hasattr(self, 'character_list'):
            self.character_list.clear()
            self.character_list.addItems([entry["name"] for entry in KNOWN_NAMES])
            
        log_msg = f"ℹ️ Loaded {len(KNOWN_NAMES)} names from Known.txt"
        if hasattr(self, 'log_signal'): 
            self.log_signal.emit(log_msg)

    def start_discord_pdf_save(self):
        """
        Validates the Discord URL and opens a 'Save As' dialog so the user can 
        choose where to output the final generated PDF log of Discord messages.
        """
        if self._is_download_active():
            QMessageBox.warning(self, "Busy", "Another operation is already in progress.")
            return

        api_url = self.link_input.text().strip()
        
        server_id = None
        channel_id = None
        
        if "/discord/server/" in api_url.lower():
            parts = api_url.split("/discord/server/")[1].strip("/").split("/")
            if len(parts) >= 1:
                server_id = parts[0]
            if len(parts) >= 2:
                channel_id = parts[1]
        
        if not server_id:
            QMessageBox.critical(self, "Input Error", "Could not detect a valid Discord Server ID in the URL.\nPlease ensure it looks like: kemono.cr/discord/server/123/456")
            return

        default_filename = f"discord_{server_id}_{channel_id or 'server'}.pdf"
        filepath, _ = QFileDialog.getSaveFileName(self, "Save Discord Log as PDF", default_filename, "PDF Files (*.pdf)")

        if not filepath:
            self.log_signal.emit("ℹ️ Discord PDF save cancelled by user.")
            return        
        self.set_ui_enabled(False)

        
        session = requests.Session()
        
        pdf_thread = threading.Thread(
            target=self._run_discord_pdf_creation_thread, 
            args=(session, api_url, server_id, channel_id, filepath), 
            daemon=True
        )
        pdf_thread.start()

    def _run_discord_pdf_creation_thread(self, session, api_url, server_id, channel_id, output_filepath, message_limit=None):
        def queue_logger(message):
            self.worker_to_gui_queue.put({'type': 'progress', 'payload': (message,)})
        
        def queue_progress_label_update(message):
            self.worker_to_gui_queue.put({'type': 'set_progress_label', 'payload': (message,)})

        queue_logger("=" * 40)
        queue_logger(f"🚀 Starting Kemono Discord PDF export for: {api_url}")
        queue_progress_label_update("Fetching messages from Kemono API...")

        all_messages = []
        channels_to_process = []
        server_name_for_pdf = server_id

        if channel_id:
            channels_to_process.append({'id': channel_id, 'name': channel_id})
        else:
            queue_logger("   Fetching channel list for server...")
            channels = fetch_server_channels(server_id, logger=queue_logger)
            if channels:
                channels_to_process.extend(channels)

        if not channels_to_process:
            queue_logger("❌ Could not determine any channels to process.")
            self.finished_signal.emit(0, 0, False, [])
            return

        for i, channel in enumerate(channels_to_process):
            chan_name = channel.get('name', channel.get('id', 'unknown'))
            queue_progress_label_update(f"Fetching from channel {i+1}/{len(channels_to_process)}: #{chan_name}")
            
            try:
                message_generator = fetch_channel_messages(
                    channel['id'], 
                    logger=queue_logger, 
                    cancellation_event=self.cancellation_event, 
                    pause_event=self.pause_event, 
                    cookies_dict=None
                )
                
                for message_batch in message_generator:
                    if self.cancellation_event.is_set():
                        break
                    if message_batch:
                        all_messages.extend(message_batch)
                        queue_progress_label_update(f"Fetched {len(all_messages)} messages...")
            except Exception as e:
                queue_logger(f"❌ Error fetching messages for channel {chan_name}: {e}")

            if self.cancellation_event.is_set():
                break

        if not all_messages:
            queue_logger("   No messages were found or fetched to create a PDF.")
            self.finished_signal.emit(0, 0, self.cancellation_event.is_set(), [])
            return
            
        queue_progress_label_update(f"Collected {len(all_messages)} total messages. Generating PDF...")
        
        try:
            all_messages.sort(key=lambda x: x.get('published', ''))
        except Exception:
            all_messages.reverse()
        font_base_dir = getattr(sys, '_MEIPASS', self.app_base_dir)
        font_path = os.path.join(font_base_dir, 'data', 'dejavu-sans', 'DejaVuSans.ttf')

        success = create_pdf_from_discord_messages(
            all_messages,
            server_name_for_pdf,
            channels_to_process[0].get('name', channel_id) if len(channels_to_process) == 1 else "All Channels",
            output_filepath,
            font_path,
            logger=queue_logger
        )

        if success:
            queue_progress_label_update(f"✅ PDF export complete!")
        else:
            queue_progress_label_update(f"❌ PDF export failed. Check log for details.")
        
        self.finished_signal.emit(0, len(all_messages), self.cancellation_event.is_set(), [])

    def save_known_names(self):
        """
        Safely writes any new or deleted characters back to the 'Known.txt' file. 
        Carefully preserves user-made `# comments` and empty lines in the text file.
        """
        global KNOWN_NAMES
        if getattr(self, 'active_known_categories', []):
            return
        try:
            config_dir = os.path.dirname(self.config_file)
            os.makedirs(config_dir, exist_ok=True)

            surviving_names = {entry["name"] for entry in KNOWN_NAMES}
            
            final_lines = []
            seen_names_in_file = set()

            if os.path.exists(self.config_file):
                self.log_signal.emit("ℹ️ Re-reading Known.txt to preserve comments and formatting...")
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        raw_line = line.strip()
                        
                        if not raw_line or raw_line.startswith('#'):
                            final_lines.append(line.rstrip('\n'))
                            continue
                        
                        is_group = raw_line.startswith('(') and raw_line.endswith(')')
                        if is_group:
                            content = raw_line[1:-1].strip()
                            parts = [p.strip() for p in content.split(',') if p.strip()]
                            if parts:
                                primary_name = clean_folder_name(parts[0]) 
                            else:
                                continue
                        else:
                            primary_name = clean_folder_name(raw_line)

                        if primary_name in surviving_names:
                            final_lines.append(raw_line)
                            seen_names_in_file.add(primary_name)
            
            for entry in KNOWN_NAMES:
                if entry["name"] not in seen_names_in_file:
                    if entry["is_group"]:
                        final_lines.append(f"({', '.join(entry['aliases'])})")
                    else:
                        final_lines.append(entry["name"])

            with open(self.config_file, 'w', encoding='utf-8') as f:
                for line in final_lines:
                    f.write(line + '\n')

            if hasattr(self, 'log_signal'):
                self.log_signal.emit(f"💾 Saved known entries to {self.config_file}")

        except Exception as e:
            log_msg = f"❌ Error saving config '{self.config_file}': {e}"
            if hasattr(self, 'log_signal'):
                self.log_signal.emit(log_msg)
            QMessageBox.warning(self, "Config Save Error", f"Could not save list to {self.config_file}:\n{e}")

    def closeEvent (self ,event ):
        self .save_known_names ()
        self .settings .setValue (MANGA_FILENAME_STYLE_KEY ,self .manga_filename_style )
        self .settings .setValue (ALLOW_MULTIPART_DOWNLOAD_KEY ,self .allow_multipart_download_setting )
        self .settings .setValue (COOKIE_TEXT_KEY ,self .cookie_text_input .text ()if hasattr (self ,'cookie_text_input')else "")
        self .settings .setValue (SCAN_CONTENT_IMAGES_KEY ,self .scan_content_images_checkbox .isChecked ()if hasattr (self ,'scan_content_images_checkbox')else False )
        self .settings .setValue (USE_COOKIE_KEY ,self .use_cookie_checkbox .isChecked ()if hasattr (self ,'use_cookie_checkbox')else False )
        self .settings .setValue (THEME_KEY ,self .current_theme )
        self .settings .setValue (LANGUAGE_KEY ,self .current_selected_language )
        self .settings .sync ()
        self ._save_persistent_history ()

        should_exit =True 
        is_downloading =self ._is_download_active ()

        if is_downloading :
            reply =QMessageBox .question (self ,"Confirm Exit",
            "Download in progress. Are you sure you want to exit and cancel?",
            QMessageBox .Yes |QMessageBox .No ,QMessageBox .No )
            if reply ==QMessageBox .Yes :
                self .log_signal .emit ("⚠️ Cancelling active download due to application exit...")
                self .cancellation_event .set ()
                if self .download_thread and self .download_thread .isRunning ():
                    self .download_thread .requestInterruption ()
                    self .log_signal .emit ("   Signaled single download thread to interrupt.")
                if self .download_thread and self .download_thread .isRunning ():
                    self .log_signal .emit ("   Waiting for single download thread to finish...")
                    self .download_thread .wait (3000 )
                    if self .download_thread .isRunning ():
                        self .log_signal .emit ("   ⚠️ Single download thread did not terminate gracefully.")

                if self .thread_pool :
                    self .log_signal .emit ("   Shutting down thread pool (waiting for completion)...")
                    self .thread_pool .shutdown (wait =True ,cancel_futures =True )
                    self .log_signal .emit ("   Thread pool shutdown complete.")
                    self .thread_pool =None 
                self .log_signal .emit ("   Cancellation for exit complete.")
            else :
                should_exit =False 
                self .log_signal .emit ("ℹ️ Application exit cancelled.")
                event .ignore ()
                return 

        if should_exit :
            self .log_signal .emit ("ℹ️ Application closing.")
            if self .thread_pool :
                self .log_signal .emit ("   Final thread pool check: Shutting down...")
                self .cancellation_event .set ()
                self .thread_pool .shutdown (wait =True ,cancel_futures =True )
                self .thread_pool =None 
            self .log_signal .emit ("👋 Exiting application.")
            event .accept ()


    def _request_restart_application (self ):
        self .log_signal .emit ("🔄 Application restart requested by user for language change.")
        self ._restart_pending =True 
        self .close ()

    def _do_actual_restart (self ):
        try :
            self .log_signal .emit ("   Performing application restart...")
            python_executable =sys .executable 
            script_args =sys .argv 


            if getattr (sys ,'frozen',False ):



                QProcess .startDetached (python_executable ,script_args [1 :])
            else :


                QProcess .startDetached (python_executable ,script_args )

            QCoreApplication .instance ().quit ()
        except Exception as e :
            self .log_signal .emit (f"❌ CRITICAL: Failed to start new application instance: {e }")
            QMessageBox .critical (self ,"Restart Failed",
            f"Could not automatically restart the application: {e }\n\nPlease restart it manually.")

    def _load_persistent_history (self ):
        """Loads download history from a persistent file."""
        self .log_signal .emit (f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Attempting to load history from: {self .persistent_history_file }")
        if os .path .exists (self .persistent_history_file ):
            try :
                with open (self .persistent_history_file ,'r',encoding ='utf-8')as f :
                    loaded_data =json .load (f )
                
                if isinstance (loaded_data ,dict ):
                    self .last_downloaded_files_details .clear ()
                    self .last_downloaded_files_details .extend (loaded_data .get ("last_downloaded_files",[]))
                    self .final_download_history_entries =loaded_data .get ("first_processed_posts",[])
                    self .log_signal .emit (f"✅ Loaded {len (self .last_downloaded_files_details )} last downloaded files and {len (self .final_download_history_entries )} first processed posts from persistent history.")
                elif loaded_data is None and os .path .getsize (self .persistent_history_file )==0 :
                    self .log_signal .emit (f"ℹ️ Persistent history file is empty. Initializing with empty history.")
                    self .final_download_history_entries =[]
                    self .last_downloaded_files_details .clear ()
                elif isinstance(loaded_data, list):
                    self.log_signal.emit("⚠️ Persistent history file is in old format (only first_processed_posts). Converting to new format.")
                    self.final_download_history_entries = loaded_data
                    self.last_downloaded_files_details.clear()
                    self._save_persistent_history()
                else :
                    self .log_signal .emit (f"⚠️ Persistent history file has incorrect format. Expected list, got {type (loaded_history )}. Ignoring.")
                    self .final_download_history_entries =[]
            except json .JSONDecodeError :
                self .log_signal .emit (f"⚠️ Error decoding persistent history file. It might be corrupted. Ignoring.")
                self .final_download_history_entries =[]
            except Exception as e :
                self .log_signal .emit (f"❌ Error loading persistent history: {e }")
                self .final_download_history_entries =[]
        else :
            self .log_signal .emit (f"⚠️ Persistent history file NOT FOUND at: {self .persistent_history_file }. Starting with empty history.")
            self .final_download_history_entries =[]
            self ._save_persistent_history ()


    def _save_persistent_history(self):
        """Saves download history to a persistent file."""
        self.log_signal.emit(f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Attempting to save history to: {self.persistent_history_file}")
        try:
            history_dir = os.path.dirname(self.persistent_history_file)
            self.log_signal.emit(f"   History directory: {history_dir}")
            if not os.path.exists(history_dir):
                os.makedirs(history_dir, exist_ok=True)
                self.log_signal.emit(f"   Created history directory: {history_dir}")
            
            history_data = {
                "last_downloaded_files": list(self.last_downloaded_files_details),
                "first_processed_posts": self.final_download_history_entries
            }
            with open(self.persistent_history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2)
            self.log_signal.emit(f"✅ Saved {len(self.final_download_history_entries)} history entries to: {self.persistent_history_file}")
        except Exception as e:
            self.log_signal.emit(f"❌ Error saving persistent history to {self.persistent_history_file}: {e}")

   
    def _load_creator_name_cache_from_json (self ):
        """Loads creator id-name-service mappings from creators.json into self.creator_name_cache."""
        self .log_signal .emit ("ℹ️ Attempting to load creators.json for creator name cache.")

        creators_file_path = os.path.join(self.app_base_dir, "data", "creators.json")

        if not os .path .exists (creators_file_path ):
            self .log_signal .emit (f"⚠️ 'creators.json' not found at {creators_file_path }. Creator name cache will be empty.")
            self .creator_name_cache .clear ()
            return 

        try :
            with open (creators_file_path ,'r',encoding ='utf-8')as f :
                loaded_data =json .load (f )

            creators_list =[]
            if isinstance (loaded_data ,list )and len (loaded_data )>0 and isinstance (loaded_data [0 ],list ):
                creators_list =loaded_data [0 ]
            elif isinstance (loaded_data ,list )and all (isinstance (item ,dict )for item in loaded_data ):
                creators_list =loaded_data 
            else :
                self .log_signal .emit (f"⚠️ 'creators.json' has an unexpected format. Creator name cache may be incomplete.")

            for creator_data in creators_list :
                creator_id =creator_data .get ("id")
                name =creator_data .get ("name")
                service =creator_data .get ("service")
                if creator_id and name and service :
                    self .creator_name_cache [(service .lower (),str (creator_id ))]=name 
         
            print(f"DEBUG: Loaded {len(self.creator_name_cache)} creators from {creators_file_path}")
            self .log_signal .emit (f"✅ Successfully loaded {len (self .creator_name_cache )} creator names into cache from 'creators.json'.")
        except Exception as e :
            self .log_signal .emit (f"❌ Error loading 'creators.json' for name cache: {e }")
            self .creator_name_cache .clear ()

    def _show_download_history_dialog (self ):
        """Shows the dialog with the finalized download history."""
        last_3_downloaded =list (self .last_downloaded_files_details )
        first_processed =self .final_download_history_entries 

        if not last_3_downloaded and not first_processed :
            QMessageBox .information (
            self ,
            self ._tr ("download_history_dialog_title_empty","Download History (Empty)"),
            self ._tr ("no_download_history_header","No Downloads Yet")
            )
            return 

        dialog = DownloadHistoryDialog(last_3_downloaded, first_processed, self)
        dialog .exec_ ()

    def _handle_actual_file_downloaded (self ,file_details_dict ):
        """Handles a successfully downloaded file for the 'last 3 downloaded' history."""
        if not file_details_dict :
            return 
        file_details_dict ['download_timestamp']=time .time ()
        creator_key =(file_details_dict .get ('service','').lower (),str (file_details_dict .get ('user_id','')))
        file_details_dict ['creator_display_name']=self .creator_name_cache .get (creator_key ,file_details_dict .get ('folder_context_name','Unknown Creator/Series'))
        self .last_downloaded_files_details .append (file_details_dict )


    def _handle_file_successfully_downloaded (self ,history_entry_dict ):
        """Handles a successfully downloaded file for history logging."""
        if len (self .download_history_log )>=self .download_history_log .maxlen :
            self .download_history_log .popleft ()
        self .download_history_log .append (history_entry_dict )


    def _handle_actual_file_downloaded (self ,file_details_dict ):
        """Handles a successfully downloaded file for the 'last 3 downloaded' history."""
        if not file_details_dict :
            return 

        file_details_dict ['download_timestamp']=time .time ()


        creator_key =(
        file_details_dict .get ('service','').lower (),
        str (file_details_dict .get ('user_id',''))
        )
        creator_display_name =self .creator_name_cache .get (creator_key ,file_details_dict .get ('folder_context_name','Unknown Creator'))
        file_details_dict ['creator_display_name']=creator_display_name 

        self .last_downloaded_files_details .append (file_details_dict )


    def _handle_favorite_mode_toggle (self ,checked ):
        """
        Swaps the main UI layout. Hides the standard URL input bar and replaces it 
        with the 'Favorite Artists' and 'Favorite Posts' buttons.
        """
        if not self .url_or_placeholder_stack or not self .bottom_action_buttons_stack :
            return 

            self ._handle_favorite_mode_toggle (self .favorite_mode_checkbox .isChecked ())
        self ._update_favorite_scope_button_text ()
        if hasattr (self ,'link_input'):
            self .last_link_input_text_for_queue_sync =self .link_input .text ()

    def _update_download_extracted_links_button_state (self ):
        if hasattr (self ,'download_extracted_links_button')and self .download_extracted_links_button :
            is_only_links =self .radio_only_links and self .radio_only_links .isChecked ()
            if not is_only_links :
                self .download_extracted_links_button .setEnabled (False )
                return 

            supported_platforms_for_button ={'mega','google drive','dropbox'}
            has_supported_links =any (
                link_info [3 ].lower ()in supported_platforms_for_button for link_info in self .extracted_links_cache
                for link_info in self.extracted_links_cache 
           
            )
            self .download_extracted_links_button .setEnabled (is_only_links and has_supported_links )

    def _show_download_extracted_links_dialog (self ):
        """Shows the placeholder dialog for downloading extracted links."""
        if not (self .radio_only_links and self .radio_only_links .isChecked ()):
            self .log_signal .emit ("ℹ️ Download extracted links button clicked, but not in 'Only Links' mode.")
            return 

        supported_platforms ={'mega','google drive','dropbox'}
        links_to_show_in_dialog =[]
        for link_data_tuple in self .extracted_links_cache :
            platform =link_data_tuple [3 ].lower ()
            if platform in supported_platforms :
                links_to_show_in_dialog .append ({
                'title':link_data_tuple [0 ],
                'link_text':link_data_tuple [1 ],
                'url':link_data_tuple [2 ],
                'platform':platform ,
                'key':link_data_tuple [4 ]
                })

        if not links_to_show_in_dialog :
            QMessageBox .information (self ,"No Supported Links","No Mega, Google Drive, or Dropbox links were found in the extracted links.")
            return 

        dialog = DownloadExtractedLinksDialog(links_to_show_in_dialog, self)
        dialog .download_requested .connect (self ._handle_extracted_links_download_request )
        dialog .exec_ ()

    def _handle_extracted_links_download_request (self ,selected_links_info ):
        if not selected_links_info :
            self .log_signal .emit ("ℹ️ No links selected for download from dialog.")
            return 


        if self .radio_only_links and self .radio_only_links .isChecked ()and self .only_links_log_display_mode ==LOG_DISPLAY_DOWNLOAD_PROGRESS :
            self .main_log_output .clear ()
            self .log_signal .emit ("ℹ️ Displaying Mega download progress (extracted links hidden)...")
            self .mega_download_log_preserved_once =False 

        current_main_dir =self .dir_input .text ().strip ()
        download_dir_for_mega =""

        if current_main_dir and os .path .isdir (current_main_dir ):
            download_dir_for_mega =current_main_dir 
            self .log_signal .emit (f"ℹ️ Using existing main download location for external links: {download_dir_for_mega }")
        else :
            if not current_main_dir :
                self .log_signal .emit ("ℹ️ Main download location is empty. Prompting for download folder.")
            else :
                self .log_signal .emit (
                f"⚠️ Main download location '{current_main_dir }' is not a valid directory. Prompting for download folder.")


            suggestion_path =current_main_dir if current_main_dir else QStandardPaths .writableLocation (QStandardPaths .DownloadLocation )

            chosen_dir =QFileDialog .getExistingDirectory (
            self ,
            self ._tr ("select_download_folder_mega_dialog_title","Select Download Folder for External Links"),
            suggestion_path ,
            options =QFileDialog .ShowDirsOnly |QFileDialog .DontUseNativeDialog 
            )

            if not chosen_dir :
                self .log_signal .emit ("ℹ️ External links download cancelled - no download directory selected from prompt.")
                return 
            download_dir_for_mega =chosen_dir 


        self .log_signal .emit (f"ℹ️ Preparing to download {len (selected_links_info )} selected external link(s) to: {download_dir_for_mega }")
        if not os .path .exists (download_dir_for_mega ):
            self .log_signal .emit (f"❌ Critical Error: Selected download directory '{download_dir_for_mega }' does not exist.")
            return 


        tasks_for_thread =selected_links_info 

        if self .external_link_download_thread and self .external_link_download_thread .isRunning ():
            QMessageBox .warning (self ,"Busy","Another external link download is already in progress.")
            return 

        self .external_link_download_thread =ExternalLinkDownloadThread (
        tasks_for_thread ,
        download_dir_for_mega ,
        self .log_signal .emit ,
        self 
        )
        self .external_link_download_thread .finished .connect (self ._on_external_link_download_thread_finished )

        self .external_link_download_thread .progress_signal .connect (self .handle_main_log )
        self .external_link_download_thread .file_complete_signal .connect (self ._on_single_external_file_complete )

        self.external_link_download_thread.file_progress_signal.connect(self.update_file_progress_display)

        self.external_link_download_thread.overall_progress_signal.connect(lambda total, processed: self.update_progress_display(total, processed, unit="files"))

        self .set_ui_enabled (False )

        self .progress_label .setText (self ._tr ("progress_processing_post_text","Progress: Processing post {processed_posts}...").format (processed_posts =f"External Links (0/{len (tasks_for_thread )})"))
        self .external_link_download_thread .start ()

    def _on_external_link_download_thread_finished (self ):
        self .log_signal .emit ("✅ External link download thread finished.")
        self .progress_label .setText (f"{self ._tr ('status_completed','Completed')}: External link downloads. {self ._tr ('ready_for_new_task_text','Ready for new task.')}")

        self .mega_download_log_preserved_once =True 
        self .log_signal .emit ("INTERNAL: mega_download_log_preserved_once SET to True.")

        if self .radio_only_links and self .radio_only_links .isChecked ():
            self .log_signal .emit (HTML_PREFIX +"<br><hr>--- End of Mega Download Log ---<br>")



        self .set_ui_enabled (True )



        if self .mega_download_log_preserved_once :
            self .mega_download_log_preserved_once =False 
            self .log_signal .emit ("INTERNAL: mega_download_log_preserved_once RESET to False.")

        if self .external_link_download_thread :
            self .external_link_download_thread .deleteLater ()
            self .external_link_download_thread =None 

    def _on_single_external_file_complete (self ,url ,success ):
        pass 


    def _show_future_settings_dialog(self):
        """Shows the placeholder dialog for future settings."""
        
        dialog = FutureSettingsDialog(self)
        dialog.exec_()

    def _show_rule34_settings_dialog(self):
        """Opens the dedicated settings dialog for Rule34 downloads."""
        try:
            
            dialog = Rule34SettingsDialog(self)
            
            if dialog.exec_() == QDialog.Accepted:
                self.log_signal.emit("✅ Rule34 Settings updated.")
                    
        except ImportError:
            self.log_signal.emit("⚠️ Rule34SettingsDialog file not created yet!")

    def _show_support_dialog(self): 
        """Shows the support/donation dialog."""
        dialog = SupportDialog(self)
        dialog.exec_()

    def _check_if_all_work_is_done(self):
        """
        Checks if the fetcher thread is done AND if all submitted tasks have been processed OR if a cancellation was requested.
        If so, finalizes the download. This is the central point for completion logic.
        """
        fetcher_is_done = not self.is_fetcher_thread_running
        all_workers_are_done = (self.processed_posts_count >= self.total_posts_to_process)
        is_cancelled = self.cancellation_event.is_set()

        if fetcher_is_done and (all_workers_are_done or is_cancelled):
            if not self.is_finishing:
                if is_cancelled:
                    self.log_signal.emit("🏁 Fetcher cancelled. Finalizing...")
                else:
                    self.log_signal.emit("🏁 All fetcher and worker tasks complete. Finalizing...")
                
                self.finished_signal.emit(self.download_counter, self.skip_counter, is_cancelled, self.all_kept_original_filenames)

    def _sync_queue_with_link_input (self ,current_text ):
        """
        Synchronizes the favorite_download_queue with the link_input text.
        Removes creators from the queue if their names are removed from the input field.
        Only affects items added via 'creator_popup_selection'.
        """
        if not self .favorite_download_queue :
            self .last_link_input_text_for_queue_sync =current_text 
            return 

        current_names_in_input ={name .strip ().lower ()for name in current_text .split (',')if name .strip ()}

        queue_copy =list (self .favorite_download_queue )
        removed_count =0 

        for item in queue_copy :
            if item .get ('type')=='creator_popup_selection':
                item_name_lower =item .get ('name','').lower ()
                if item_name_lower and item_name_lower not in current_names_in_input :
                    try :
                        self .favorite_download_queue .remove (item )
                        self .log_signal .emit (f"ℹ️ Creator '{item .get ('name')}' removed from download queue due to removal from URL input.")
                        removed_count +=1 
                    except ValueError :
                        self .log_signal .emit (f"⚠️ Tried to remove '{item .get ('name')}' from queue, but it was not found (sync).")

        self .last_link_input_text_for_queue_sync =current_text 

    def _browse_cookie_file(self):
        """Opens a file dialog to select a cookie file and updates BOTH text inputs."""
        start_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        if not start_dir:
            start_dir = os.path.dirname(self.config_file)

        filepath, _ = QFileDialog.getOpenFileName(self, "Select Cookie File", start_dir, "Text files (*.txt);;All files (*)")
        
        if filepath:
            self.selected_cookie_filepath = filepath
            self.log_signal.emit(f"ℹ️ Selected cookie file: {filepath}")

            all_cookie_inputs = []
            if hasattr(self, 'cookie_text_input'):
                all_cookie_inputs.append(self.cookie_text_input)


            for text_input in all_cookie_inputs:
                text_input.blockSignals(True)
                text_input.setText(filepath)
                text_input.setToolTip(self._tr("cookie_text_input_tooltip_file_selected", "Using selected cookie file: {filepath}").format(filepath=filepath))
                text_input.setReadOnly(True)
                text_input.blockSignals(False)


    def _update_cookie_input_placeholders_and_tooltips (self ):
        if hasattr (self ,'cookie_text_input'):
            if self .selected_cookie_filepath :
                self .cookie_text_input .setPlaceholderText (self ._tr ("cookie_text_input_placeholder_with_file_selected_text","Using selected cookie file..."))
                self .cookie_text_input .setToolTip (self ._tr ("cookie_text_input_tooltip_file_selected","Using selected cookie file: {filepath}").format (filepath =self .selected_cookie_filepath ))
            else :
                self .cookie_text_input .setPlaceholderText (self ._tr ("cookie_text_input_placeholder_no_file_selected_text","Cookie string (if no cookies.txt selected)"))
                self .cookie_text_input .setToolTip (self ._tr ("cookie_text_input_tooltip","Enter your cookie string directly..."))
                self .cookie_text_input .setReadOnly (True )
                self .cookie_text_input .setPlaceholderText ("")
                self .cookie_text_input .blockSignals (False )

    def _center_on_screen (self ):
        """Centers the widget on the screen."""
        try :
            primary_screen =QApplication .primaryScreen ()
            if not primary_screen :
                screens =QApplication .screens ()
                if not screens :return 
                primary_screen =screens [0 ]

            available_geo =primary_screen .availableGeometry ()
            widget_geo =self .frameGeometry ()

            x =available_geo .x ()+(available_geo .width ()-widget_geo .width ())//2 
            y =available_geo .y ()+(available_geo .height ()-widget_geo .height ())//2 
            self .move (x ,y )
        except Exception as e :
            self .log_signal .emit (f"⚠️ Error centering window: {e }")

    def _handle_cookie_text_manual_change (self ,text ):
        """Handles manual changes to the cookie text input, especially clearing a browsed path."""
        if not hasattr (self ,'cookie_text_input')or not hasattr (self ,'use_cookie_checkbox'):
            return 
        if self .selected_cookie_filepath and not text .strip ()and self .use_cookie_checkbox .isChecked ():
            self .selected_cookie_filepath =None 
            self .cookie_text_input .setReadOnly (False )
            self ._update_cookie_input_placeholders_and_tooltips ()
            self .log_signal .emit ("ℹ️ Browsed cookie file path cleared from input. Switched to manual cookie string mode.")


    def browse_directory (self ):
        initial_dir_text =self .dir_input .text ()
        start_path =""
        if initial_dir_text and os .path .isdir (initial_dir_text ):
            start_path =initial_dir_text 
        else :
            home_location =QStandardPaths .writableLocation (QStandardPaths .HomeLocation )
            documents_location =QStandardPaths .writableLocation (QStandardPaths .DocumentsLocation )
            if home_location and os .path .isdir (home_location ):
                start_path =home_location 
            elif documents_location and os .path .isdir (documents_location ):
                start_path =documents_location 

        self .log_signal .emit (f"ℹ️ Opening folder dialog. Suggested start path: '{start_path }'")

        try :
            folder =QFileDialog .getExistingDirectory (
            self ,
            "Select Download Folder",
            start_path ,
            options =QFileDialog .DontUseNativeDialog |QFileDialog .ShowDirsOnly 
            )

            if folder :
                self .dir_input .setText (folder )
                self .log_signal .emit (f"ℹ️ Folder selected: {folder }")
            else :
                self .log_signal .emit (f"ℹ️ Folder selection cancelled by user.")
        except RuntimeError as e :
            self .log_signal .emit (f"❌ RuntimeError opening folder dialog: {e }. This might indicate a deeper Qt or system issue.")
            QMessageBox .critical (self ,"Dialog Error",f"A runtime error occurred while trying to open the folder dialog: {e }")
        except Exception as e :
            self .log_signal .emit (f"❌ Unexpected error opening folder dialog: {e }\n{traceback .format_exc (limit =3 )}")
            QMessageBox .critical (self ,"Dialog Error",f"An unexpected error occurred with the folder selection dialog: {e }")

    def handle_main_log(self, message):
        """
        The central logging hub. Receives text strings or HTML from background threads 
        and safely appends them to the main UI console without freezing the app.
        """
        if isinstance(message, str) and message.startswith("RENAMING_MODE_FETCH_PROGRESS:"):
            try:
                parts = message.split(":")
                fetched_count = int(parts[1])
                page_num = int(parts[2])
                self.progress_label.setText(self._tr("progress_fetching_manga_pages", "Progress: Fetching Page {page} ({count} posts found)...").format(page=page_num, count=fetched_count))
                QCoreApplication.processEvents() 
            except (ValueError, IndexError):
                try:
                    fetched_count = int(message.split(":")[1])
                    self.progress_label.setText(self._tr("progress_fetching_manga_posts", "Progress: Fetching Manga Posts ({count})...").format(count=fetched_count))
                    QCoreApplication.processEvents()
                except (ValueError, IndexError):
                    pass 
            return 
        elif isinstance(message, str) and message.startswith("RENAMING_MODE_FETCH_COMPLETE:"):
            try:
                total_posts = int(message.split(":")[1])
                self.total_posts_to_process = total_posts
                self.processed_posts_count = 0
                self.update_progress_display(self.total_posts_to_process, self.processed_posts_count)
            except (ValueError, IndexError):
                pass
            return 

        if message.startswith("TEMP_FILE_PATH:"):
            filepath = message.split(":", 1)[1]
            if self.single_pdf_setting:
                self.session_temp_files.append(filepath)
            return
            
        is_html_message = message.startswith(HTML_PREFIX)
        
        try:
            if is_html_message:
                display_message = message[len(HTML_PREFIX):]
                safe_message = str(display_message).replace('\x00', '[NULL]')
                self.main_log_output.append(safe_message)
            else:
                self.main_log_output.setCurrentCharFormat(QTextCharFormat())
                
                safe_message = str(message).replace('\x00', '[NULL]')
                for line in safe_message.split('\n'):
                    self.main_log_output.append(line)

            scrollbar = self.main_log_output.verticalScrollBar()
            if scrollbar.value() >= scrollbar.maximum() - 30:
                scrollbar.setValue(scrollbar.maximum())
                
        except Exception as e:
            print(f"GUI Main Log Error: {e}\nOriginal Message: {message}")
  
    def _extract_key_term_from_title (self ,title ):
        if not title :
            return None 
        title_cleaned =re .sub (r'\[.*?\]','',title )
        title_cleaned =re .sub (r'\(.*?\)','',title_cleaned )
        title_cleaned =title_cleaned .strip ()
        word_matches =list (re .finditer (r'\b[a-zA-Z][a-zA-Z0-9_-]*\b',title_cleaned ))

        capitalized_candidates =[]
        for match in word_matches :
            word =match .group (0 )
            if word .istitle ()and word .lower ()not in self .STOP_WORDS and len (word )>2 :
                if not (len (word )>3 and word .isupper ()):
                    capitalized_candidates .append ({'text':word ,'len':len (word ),'pos':match .start ()})

        if capitalized_candidates :
            capitalized_candidates .sort (key =lambda x :(x ['len'],x ['pos']),reverse =True )
            return capitalized_candidates [0 ]['text']
        non_capitalized_words_info =[]
        for match in word_matches :
            word =match .group (0 )
            if word .lower ()not in self .STOP_WORDS and len (word )>3 :
                non_capitalized_words_info .append ({'text':word ,'len':len (word ),'pos':match .start ()})

        if non_capitalized_words_info :
            non_capitalized_words_info .sort (key =lambda x :(x ['len'],x ['pos']),reverse =True )
            return non_capitalized_words_info [0 ]['text']

        return None 

    def handle_missed_character_post (self ,post_title ,reason ):
        if self .missed_character_log_output :
            key_term =self ._extract_key_term_from_title (post_title )

            if key_term :
                normalized_key_term =key_term .lower ()
                if normalized_key_term not in self .already_logged_bold_key_terms :
                    self .already_logged_bold_key_terms .add (normalized_key_term )
                    self .missed_key_terms_buffer .append (key_term )
                    self ._refresh_missed_character_log ()
        else :
            print (f"Debug (Missed Char Log): Title='{post_title }', Reason='{reason }'")

    def _refresh_missed_character_log (self ):
        if self .missed_character_log_output :
            self .missed_character_log_output .clear ()
            sorted_terms =sorted (self .missed_key_terms_buffer ,key =str .lower )
            separator_line ="-"*40 

            for term in sorted_terms :
                display_term =term .capitalize ()

                self .missed_character_log_output .append (separator_line )
                self .missed_character_log_output .append (f'<p align="center"><b><font style="font-size: 12.4pt; color: #87CEEB;">{display_term }</font></b></p>')
                self .missed_character_log_output .append (separator_line )
                self .missed_character_log_output .append ("")

            scrollbar =self .missed_character_log_output .verticalScrollBar ()
            scrollbar .setValue (0 )

    def _is_download_active (self ):
        single_thread_active = False
        if self.download_thread:
            if hasattr(self.download_thread, 'isRunning') and self.download_thread.isRunning():
                single_thread_active = True
            elif hasattr(self.download_thread, 'is_alive') and self.download_thread.is_alive():
                single_thread_active = True

        fetcher_active =hasattr (self ,'is_fetcher_thread_running')and self .is_fetcher_thread_running 
        pool_has_active_tasks =self .thread_pool is not None and any (not f .done ()for f in self .active_futures if f is not None )
        retry_pool_active =hasattr (self ,'retry_thread_pool')and self .retry_thread_pool is not None and hasattr (self ,'active_retry_futures')and any (not f .done ()for f in self .active_retry_futures if f is not None )
        external_dl_thread_active =hasattr (self ,'external_link_download_thread')and self .external_link_download_thread is not None and self .external_link_download_thread .isRunning ()
        
        fetching_only_active = hasattr(self, 'is_fetching_only') and self.is_fetching_only
        print("--- DEBUG: _is_download_active check ---")
        print(f"  single_thread_active: {single_thread_active} (thread is {self.download_thread})")
        print(f"  is_fetcher_thread_running: {self.is_fetcher_thread_running}")
        print(f"  is_fetching_only: {self.is_fetching_only}")
        result = single_thread_active or fetcher_active or pool_has_active_tasks or retry_pool_active or external_dl_thread_active or fetching_only_active
        print(f"  ==> Returning: {result}")
        return result

    def handle_external_link_signal (self ,post_title ,link_text ,link_url ,platform ,decryption_key ):
        """
        Catches external links (Mega, Google Drive, etc.) found inside post descriptions 
        by the background worker and adds them to the processing queue.
        """
        link_data =(post_title ,link_text ,link_url ,platform ,decryption_key )
        self .external_link_queue .append (link_data )
        if self .radio_only_links and self .radio_only_links .isChecked ():
            self .extracted_links_cache .append (link_data )
            self ._update_download_extracted_links_button_state ()

        is_only_links_mode =self .radio_only_links and self .radio_only_links .isChecked ()
        should_display_in_external_log =self .show_external_links and not is_only_links_mode 

        if not (is_only_links_mode or should_display_in_external_log ):
            self ._is_processing_external_link_queue =False 
            if self .external_link_queue :
                QTimer .singleShot (0 ,self ._try_process_next_external_link )
            return 

        if link_data not in self .extracted_links_cache :
            self .extracted_links_cache .append (link_data )
            
        if not self._is_processing_external_link_queue:
            QTimer.singleShot(0, self._try_process_next_external_link)

    def _try_process_next_external_link (self ):
        if self ._is_processing_external_link_queue or not self .external_link_queue :
            return 

        is_only_links_mode =self .radio_only_links and self .radio_only_links .isChecked ()
        should_display_in_external_log =self .show_external_links and not is_only_links_mode 

        if not (is_only_links_mode or should_display_in_external_log ):
            self ._is_processing_external_link_queue =False 
            if self .external_link_queue :
                QTimer .singleShot (0 ,self ._try_process_next_external_link )
            return 

        self ._is_processing_external_link_queue =True 
        link_data =self .external_link_queue .popleft ()

        QTimer .singleShot (0 ,lambda data =link_data :self ._display_and_schedule_next (data ))

    def _display_and_schedule_next(self, link_data):
        """
        Pops a single extracted link from the queue, formats it nicely, prints it to the log, 
        and then schedules the next link. Processing them one by one prevents UI freezing.
        """
        post_title, link_text, link_url, platform, decryption_key = link_data
        is_only_links_mode = self.radio_only_links and self.radio_only_links.isChecked()

        cleaned_link_text = link_text.strip()
        display_text = ""
        if cleaned_link_text and cleaned_link_text.lower() != platform.lower() and cleaned_link_text != link_url:
            display_text = cleaned_link_text
        else:
            try:
                path = urlparse(link_url).path
                filename = os.path.basename(path)
                if filename:
                    display_text = filename
            except Exception:
                pass
        if not display_text:
            display_text = link_url

        if len(display_text) > 50:
            display_text = display_text[:50].strip() + "..."

        platform_display = platform.capitalize()
        plain_link_info_line = f"  {platform_display} - {link_url} - ({display_text})"
        if decryption_key:
            plain_link_info_line += f" (Decryption Key: {decryption_key})"

        if is_only_links_mode:
            if post_title != self._current_link_post_title:
                if self._current_link_post_title is not None:
                    separator_html = f'{HTML_PREFIX}<hr style="border: 1px solid #444;">'
                    self.log_signal.emit(separator_html)

                title_html = f'<p style="font-size: 11pt; color: #87CEEB; margin-top: 2px; margin-bottom: 2px;"><b>{html.escape(post_title)}</b></p>'
                self.log_signal.emit(HTML_PREFIX + title_html)
                self._current_link_post_title = post_title

            self.main_log_output.append(plain_link_info_line)

        elif self.show_external_links:
            if self.external_log_output and self.external_log_output.isVisible():
                if post_title != self._current_link_post_title:
                    if self._current_link_post_title is not None:
                        self.external_log_output.append("-" * 45)
                    
                    self.external_log_output.append(f"📌 {post_title}")
                    self._current_link_post_title = post_title
                
                self.external_log_output.append(plain_link_info_line)
                
                scrollbar = self.external_log_output.verticalScrollBar()
                if scrollbar.value() >= scrollbar.maximum() - 50:
                    scrollbar.setValue(scrollbar.maximum())

        self._is_processing_external_link_queue = False
        self._try_process_next_external_link()

    def _append_to_external_log (self ,formatted_link_text ,separator ):
        if not (self .external_log_output and self .external_log_output .isVisible ()):
            return 

        try :
            self .external_log_output .append (formatted_link_text )
            self .external_log_output .append ("")

            scrollbar =self .external_log_output .verticalScrollBar ()
            if scrollbar .value ()>=scrollbar .maximum ()-50 :
                scrollbar .setValue (scrollbar .maximum ())
        except Exception as e :
            self .log_signal .emit (f"GUI External Log Append Error: {e }\nOriginal Message: {formatted_link_text }")
            print (f"GUI External Log Error (Append): {e }\nOriginal Message: {formatted_link_text }")


    def update_file_progress_display (self ,filename ,progress_info ):


        if isinstance(progress_info, str):
            self.file_progress_label.setText(f"{filename} {progress_info}")
            return

        if not filename and progress_info is None :
            self .file_progress_label .setText ("")
            return 

        if isinstance (progress_info ,list ):
            if not progress_info :
                self .file_progress_label .setText (self ._tr ("downloading_multipart_initializing_text","File: {filename} - Initializing parts...").format (filename =filename ))
                return 

            total_downloaded_overall =sum (cs .get ('downloaded',0 )for cs in progress_info )
            total_file_size_overall =sum (cs .get ('total',0 )for cs in progress_info )

            active_chunks_count =0 
            combined_speed_bps =0 
            for cs in progress_info :
                if cs .get ('active',False ):
                    active_chunks_count +=1 
                    combined_speed_bps +=cs .get ('speed_bps',0 )

            dl_mb =total_downloaded_overall /(1024 *1024 )
            total_mb =total_file_size_overall /(1024 *1024 )
            speed_MBps =(combined_speed_bps /8 )/(1024 *1024 )

            progress_text =self ._tr ("downloading_multipart_text","DL '{filename}...': {downloaded_mb:.1f}/{total_mb:.1f} MB ({parts} parts @ {speed:.2f} MB/s)").format (filename =filename [:20 ],downloaded_mb =dl_mb ,total_mb =total_mb ,parts =active_chunks_count ,speed =speed_MBps )
            self .file_progress_label .setText (progress_text )

        elif isinstance (progress_info ,tuple )and len (progress_info )==2 :
            downloaded_bytes ,total_bytes =progress_info 

            if not filename and total_bytes ==0 and downloaded_bytes ==0 :
                self .file_progress_label .setText ("")
                return 

            max_fn_len =25 
            disp_fn =filename if len (filename )<=max_fn_len else filename [:max_fn_len -3 ].strip ()+"..."

            dl_mb =downloaded_bytes /(1024 *1024 )
            if total_bytes >0 :
                tot_mb =total_bytes /(1024 *1024 )
                prog_text_base =self ._tr ("downloading_file_known_size_text","Downloading '{filename}' ({downloaded_mb:.1f}MB / {total_mb:.1f}MB)").format (filename =disp_fn ,downloaded_mb =dl_mb ,total_mb =tot_mb )
            else :
                prog_text_base =self ._tr ("downloading_file_unknown_size_text","Downloading '{filename}' ({downloaded_mb:.1f}MB)").format (filename =disp_fn ,downloaded_mb =dl_mb )

            self .file_progress_label .setText (prog_text_base )
        elif filename and progress_info is None :
            self .file_progress_label .setText ("")
        elif not filename and not progress_info :
            self .file_progress_label .setText ("")

    def _clear_stale_temp_files(self):
        """On startup, cleans any temp files from a previous crashed session."""
        try:
            temp_dir = os.path.join(self.app_base_dir, "appdata")
            if not os.path.isdir(temp_dir):
                return
            
            for filename in os.listdir(temp_dir):
                if filename.startswith("tmp_") and filename.endswith(".json"):
                    try:
                        os.remove(os.path.join(temp_dir, filename))
                        self.log_signal.emit(f"   🧹 Removed stale temp file: {filename}")
                    except OSError:
                        pass
        except Exception as e:
            self.log_signal.emit(f"⚠️ Error cleaning stale temp files: {e}")

    def _cleanup_temp_files(self):
        """Deletes all temporary files collected during the session."""
        if not self.session_temp_files:
            return
        
        self.log_signal.emit("   Cleaning up temporary files...")
        for filepath in self.session_temp_files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                self.log_signal.emit(f"   ⚠️ Could not delete temp file '{filepath}': {e}")
        self.session_temp_files = []

    def update_external_links_setting(self, checked, log_change=True):
        is_only_links_mode = self.radio_only_links and self.radio_only_links.isChecked()
        is_only_archives_mode = self.radio_only_archives and self.radio_only_archives.isChecked()
        is_only_audio_mode = hasattr(self, 'radio_only_audio') and self.radio_only_audio.isChecked()

        if is_only_links_mode or is_only_archives_mode or is_only_audio_mode:
            if self.external_log_output: self.external_log_output.hide()
            if self.log_splitter: self.log_splitter.setSizes([self.height(), 0])
            return

        self.show_external_links = checked

        if log_change and self.last_logged_external_link_status != checked:
            if checked:
                self.log_signal.emit("ℹ️ External Links Log Enabled")
            else:
                self.log_signal.emit("ℹ️ External Links Log Disabled")
            self.last_logged_external_link_status = checked

        if checked:
            if self.external_log_output: self.external_log_output.show()
            if self.log_splitter: self.log_splitter.setSizes([self.height() // 2, self.height() // 2])
            if self.main_log_output: self.main_log_output.setMinimumHeight(50)
            if self.external_log_output: self.external_log_output.setMinimumHeight(50)
            if self.external_log_output:
                self.external_log_output.clear()
                self.external_log_output.append("🔗 External Links Found:")
            self._try_process_next_external_link()
        else:
            if self.external_log_output: self.external_log_output.hide()
            if self.log_splitter: self.log_splitter.setSizes([self.height(), 0])
            if self.main_log_output: self.main_log_output.setMinimumHeight(0)
            if self.external_log_output: self.external_log_output.setMinimumHeight(0)
            if self.external_log_output: self.external_log_output.clear()

    def _handle_filter_mode_change(self, button, checked):
        """
        Triggered when the user clicks All, Images, Videos, Archives, or Links.
        Dynamically disables conflicting settings (e.g., disabling Multithreading if 'Only Links' is selected).
        """
        if not button or not checked:
            return

        new_mode_text = button.text()
        if self.last_logged_filter_mode != new_mode_text:
            self.log_signal.emit(f"ℹ️ Filter mode changed to: {new_mode_text}")
            self.last_logged_filter_mode = new_mode_text

        is_only_links = (button == self.radio_only_links)

        if hasattr(self, 'use_multithreading_checkbox') and hasattr(self, 'thread_count_input'):
            if is_only_links:
                self.use_multithreading_checkbox.setChecked(True)
                self.thread_count_input.setText("20")
                self.thread_count_input.setEnabled(False) 
                self.thread_count_label.setEnabled(False)
                self.update_multithreading_label("20")
            else:
                is_multithreading_checked = self.use_multithreading_checkbox.isChecked()
                self.thread_count_input.setEnabled(is_multithreading_checked)
                self.thread_count_label.setEnabled(is_multithreading_checked)

        if button != self.radio_more and checked:
            self.radio_more.setText("More")
            self.more_filter_scope = None
            self.single_pdf_setting = False
            if hasattr(self, 'use_subfolders_checkbox'):
                self.use_subfolders_checkbox.setEnabled(True)

        is_only_audio = (hasattr(self, 'radio_only_audio') and self.radio_only_audio is not None and button == self.radio_only_audio)
        is_only_archives = (hasattr(self, 'radio_only_archives') and self.radio_only_archives is not None and button == self.radio_only_archives)

        if self.skip_scope_toggle_button:
            self.skip_scope_toggle_button.setVisible(True)
        if hasattr(self, 'multipart_toggle_button') and self.multipart_toggle_button:
            self.multipart_toggle_button.setVisible(not (is_only_links or is_only_archives or is_only_audio))

        if self.link_search_input: self.link_search_input.setVisible(is_only_links)
        if self.link_search_button: self.link_search_button.setVisible(is_only_links)
        if self.export_links_button:
            self.export_links_button.setVisible(is_only_links)
            self.export_links_button.setEnabled(is_only_links and bool(self.extracted_links_cache))

        if hasattr(self, 'download_extracted_links_button') and self.download_extracted_links_button:
            self.download_extracted_links_button.setVisible(is_only_links)
            self._update_download_extracted_links_button_state()


        if self.download_btn:
            if self.is_ready_to_download_fetched:
                return 

            if is_only_links:
                self.download_btn.setText(self._tr("extract_links_button_text", "Extract Links"))
                self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/link.svg")))
            else:
                self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
                self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
        if not is_only_links and self.link_search_input: self.link_search_input.clear()

        file_download_mode_active = not is_only_links

        if self.use_subfolders_checkbox: self.use_subfolders_checkbox.setEnabled(file_download_mode_active)
        if self.skip_words_input: self.skip_words_input.setEnabled(True)
        if self.skip_scope_toggle_button: self.skip_scope_toggle_button.setEnabled(file_download_mode_active)
        if hasattr(self, 'remove_from_filename_input'): self.remove_from_filename_input.setEnabled(file_download_mode_active)

        if self.skip_zip_checkbox:
            can_skip_zip = file_download_mode_active and not is_only_archives
            self.skip_zip_checkbox.setEnabled(can_skip_zip)
            if is_only_archives:
                self.skip_zip_checkbox.setChecked(False)

        other_file_proc_enabled = file_download_mode_active and not is_only_archives
        if self.download_thumbnails_checkbox: self.download_thumbnails_checkbox.setEnabled(other_file_proc_enabled)
        if self.compress_images_checkbox: self.compress_images_checkbox.setEnabled(other_file_proc_enabled)

        if self.external_links_checkbox:
            can_show_external_log_option = file_download_mode_active and not is_only_archives
            self.external_links_checkbox.setEnabled(can_show_external_log_option)
            if not can_show_external_log_option:
                self.external_links_checkbox.setChecked(False)

        if is_only_links:
            self.progress_log_label.setText(f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Extracted Links Log:")
        else:
            self.progress_log_label.setText(self._tr("progress_log_label_text", f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Progress Log:"))
        
        self.update_external_links_setting(self.external_links_checkbox.isChecked() if self.external_links_checkbox else False)
        
        if is_only_links:
            self._filter_links_log()

        if hasattr(self, 'log_display_mode_toggle_button'):
            self.log_display_mode_toggle_button.setVisible(is_only_links)
            self._update_log_display_mode_button_text()

        subfolders_on = self.use_subfolders_checkbox.isChecked() if self.use_subfolders_checkbox else False
        manga_on = self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False

        character_filter_should_be_active = True

        if self.character_filter_widget:
            self.character_filter_widget.setVisible(character_filter_should_be_active)

        enable_character_filter_related_widgets = character_filter_should_be_active

        if self.character_input:
            self.character_input.setEnabled(enable_character_filter_related_widgets)
            if not enable_character_filter_related_widgets:
                self.character_input.clear()

        if self.char_filter_scope_toggle_button:
            self.char_filter_scope_toggle_button.setEnabled(enable_character_filter_related_widgets)

        self.update_ui_for_subfolders(subfolders_on)
        self.update_custom_folder_visibility()
        self.update_ui_for_manga_mode(self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False)

    def _filter_links_log (self ):
        """
        Filters the extracted links log based on what the user types in the search bar.
        Instantly hides links that don't match the search term.
        """
        if not (self .radio_only_links and self .radio_only_links .isChecked ()):return

        search_term =self .link_search_input .text ().lower ().strip ()if self .link_search_input else ""

        if self .mega_download_log_preserved_once and self .only_links_log_display_mode ==LOG_DISPLAY_DOWNLOAD_PROGRESS :
            self .log_signal .emit ("INTERNAL: _filter_links_log - Preserving Mega log.")
            return
        elif self .only_links_log_display_mode ==LOG_DISPLAY_DOWNLOAD_PROGRESS :
            if self .main_log_output :self .main_log_output .clear ()
            self .log_signal .emit ("ℹ️ Switched to Mega download progress view. Extracted links are hidden.\n"
            "   Perform a Mega download to see its progress here, or switch back to 🔗 view.")
            return

        if self .main_log_output :self .main_log_output .clear ()
        self._current_link_post_title = None

        filtered_link_queue = deque()
        for post_title ,link_text ,link_url ,platform ,decryption_key in self .extracted_links_cache :
            
            matches_search =(not search_term or
            (post_title and search_term in post_title.lower()) or
            search_term in link_text .lower ()or
            search_term in link_url .lower ()or
            search_term in platform .lower ()or
            (decryption_key and search_term in decryption_key .lower ()))
            
            if matches_search :
                filtered_link_queue.append((post_title, link_text, link_url, platform, decryption_key))

        if not filtered_link_queue:
             self .log_signal .emit ("   (No links extracted yet or all filtered out in links view)")
        else:
            self.external_link_queue.clear()
            self.external_link_queue.extend(filtered_link_queue)
            self._try_process_next_external_link()

        if self .main_log_output :self .main_log_output .verticalScrollBar ().setValue (self .main_log_output .verticalScrollBar ().maximum ())
        
    def _display_and_schedule_next (self ,link_data ):
        post_title ,link_text ,link_url ,platform ,decryption_key =link_data
        is_only_links_mode =self .radio_only_links and self .radio_only_links .isChecked ()

        if is_only_links_mode :
            if post_title != self._current_link_post_title:
                if self._current_link_post_title is not None:
                    separator_html = f'{HTML_PREFIX}<hr style="border: 1px solid #444;">'
                    self.log_signal.emit(separator_html)

                title_html = f'<p style="font-size: 11pt; color: #87CEEB; margin-top: 2px; margin-bottom: 2px;"><b>{html.escape(post_title)}</b></p>'
                self.log_signal.emit(HTML_PREFIX + title_html)
                self._current_link_post_title = post_title

            cleaned_link_text = link_text.strip()
            display_text = ""
            if cleaned_link_text and cleaned_link_text.lower() != platform.lower() and cleaned_link_text != link_url:
                display_text = cleaned_link_text
            else:
                try:
                    path = urlparse(link_url).path
                    filename = os.path.basename(path)
                    if filename:
                        display_text = filename
                except Exception:
                    pass
            if not display_text:
                display_text = link_url

            if len(display_text) > 50:
                display_text = display_text[:50].strip() + "..."

            platform_display = platform.capitalize()
            plain_link_info_line = f"  {platform_display} - {link_url} - ({display_text})"
            if decryption_key:
                plain_link_info_line += f" (Decryption Key: {decryption_key})"

            self.main_log_output.append(plain_link_info_line)

        elif self .show_external_links :
            separator ="-"*45
            formatted_link_info = f"{link_text} - {link_url} - {platform}"
            if decryption_key:
                formatted_link_info += f" (Decryption Key: {decryption_key})"
            self._append_to_external_log(formatted_link_info, separator)

        self ._is_processing_external_link_queue =False
        self ._try_process_next_external_link ()

    def _handle_simpcity_save_external_links_toggled(self, checked):
        if checked:
            self._open_simpcity_external_links_config_dialog()
        else:
            self.simpcity_external_links_config = None
            self.log_signal.emit("ℹ️ 'Save External Links' disabled.")

    def _open_simpcity_external_links_config_dialog(self):
        from .dialogs.ExportLinksDialog import ExportLinksDialog
        dialog = ExportLinksDialog(links_data=None, parent=self, default_config=getattr(self, 'simpcity_external_links_config', None), context='simpcity')
        from PyQt5.QtWidgets import QDialog
        if dialog.exec_() == QDialog.Accepted:
            self.simpcity_external_links_config = dialog.get_config()
            self.log_signal.emit("✅ 'Save External Links' configured.")
        else:
            if not getattr(self, 'simpcity_external_links_config', None):
                self.simpcity_save_external_links_cb.blockSignals(True)
                self.simpcity_save_external_links_cb.setChecked(False)
                self.simpcity_save_external_links_cb.blockSignals(False)
            self.log_signal.emit("ℹ️ External Links configuration cancelled.")

    def _export_links_to_file(self):
        """
        Opens a new, advanced dialog to handle exporting extracted links in various formats.
        """
        if not (self.radio_only_links and self.radio_only_links.isChecked()):
            QMessageBox.information(self, "Export Links", "Link export is only available in 'Only Links' mode.")
            return

        if not self.extracted_links_cache:
            QMessageBox.information(self, "Export Links", "No links have been extracted yet.")
            return

        dialog = ExportLinksDialog(self.extracted_links_cache, self, context='kemono')
        
        if dialog.exec_() == QDialog.Accepted:
            self.log_signal.emit("✅ Links successfully exported with selected options.")
        else:
            self.log_signal.emit("ℹ️ Link export was cancelled by the user.")

    def _set_inputs_read_only(self, read_only):
        """
        Locks all text boxes and checkboxes, but keeps action buttons (like Start/Cancel) clickable.
        Used when loading a saved Creator Profile where settings shouldn't be manually changed.
        """
        widgets_to_lock = [
            self.link_input, self.dir_input, self.character_input, 
            self.skip_words_input, self.remove_from_filename_input,
            self.custom_folder_input, self.cookie_text_input,
            self.thread_count_input, self.start_page_input, self.end_page_input,
            self.use_subfolders_checkbox, self.use_subfolder_per_post_checkbox,
            self.skip_zip_checkbox, self.download_thumbnails_checkbox,
            self.compress_images_checkbox, self.scan_content_images_checkbox,
            self.use_cookie_checkbox, self.manga_mode_checkbox,
            self.radio_all, self.radio_images, self.radio_videos,
            self.char_filter_scope_toggle_button, self.skip_scope_toggle_button
        ]
        
        for widget in widgets_to_lock:
            if widget:
                widget.setEnabled(not read_only)

    def get_filter_mode (self ):
        if self.radio_more and self.radio_more.isChecked():
            return 'text_only'
        elif self.radio_only_links and self.radio_only_links.isChecked():
            return 'all'
        elif self .radio_images .isChecked ():
            return 'image'
        elif self .radio_videos .isChecked ():
            return 'video'
        elif self .radio_only_archives and self .radio_only_archives .isChecked ():
            return 'archive'
        elif hasattr (self ,'radio_only_audio')and self .radio_only_audio .isChecked ():
            return 'audio'
        elif self .radio_all .isChecked ():
            return 'all'
        return 'all'


    def get_skip_words_scope (self ):
        return self .skip_words_scope 


    def _update_skip_scope_button_text (self ):
        if self .skip_scope_toggle_button :
            if self .skip_words_scope ==SKIP_SCOPE_FILES :
                self .skip_scope_toggle_button .setText (self ._tr ("skip_scope_files_text","Scope: Files"))
                self .skip_scope_toggle_button .setToolTip (self ._tr ("skip_scope_files_tooltip","Tooltip for skip scope files"))
            elif self .skip_words_scope ==SKIP_SCOPE_POSTS :
                self .skip_scope_toggle_button .setText (self ._tr ("skip_scope_posts_text","Scope: Posts"))
                self .skip_scope_toggle_button .setToolTip (self ._tr ("skip_scope_posts_tooltip","Tooltip for skip scope posts"))
            elif self .skip_words_scope ==SKIP_SCOPE_BOTH :
                self .skip_scope_toggle_button .setText (self ._tr ("skip_scope_both_text","Scope: Both"))
                self .skip_scope_toggle_button .setToolTip (self ._tr ("skip_scope_both_tooltip","Tooltip for skip scope both"))
            else :
                self .skip_scope_toggle_button .setText (self ._tr ("skip_scope_unknown_text","Scope: Unknown"))
                self .skip_scope_toggle_button .setToolTip (self ._tr ("skip_scope_unknown_tooltip","Tooltip for skip scope unknown"))


    def _cycle_skip_scope (self ):
        if self .skip_words_scope ==SKIP_SCOPE_POSTS :
            self .skip_words_scope =SKIP_SCOPE_FILES 
        elif self .skip_words_scope ==SKIP_SCOPE_FILES :
            self .skip_words_scope =SKIP_SCOPE_BOTH 
        elif self .skip_words_scope ==SKIP_SCOPE_BOTH :
            self .skip_words_scope =SKIP_SCOPE_POSTS 
        else :
            self .skip_words_scope =SKIP_SCOPE_POSTS 

        self ._update_skip_scope_button_text ()
        self .settings .setValue (SKIP_WORDS_SCOPE_KEY ,self .skip_words_scope )
        self .log_signal .emit (f"ℹ️ Skip words scope changed to: '{self .skip_words_scope }'")

    def get_char_filter_scope (self ):
        return self .char_filter_scope 

    def _update_char_filter_scope_button_text (self ):
        if self .char_filter_scope_toggle_button :
            if self .char_filter_scope ==CHAR_SCOPE_FILES :
                self .char_filter_scope_toggle_button .setText (self ._tr ("char_filter_scope_files_text","Filter: Files"))
                self .char_filter_scope_toggle_button .setToolTip (self ._tr ("char_filter_scope_files_tooltip","Tooltip for char filter files"))
            elif self .char_filter_scope ==CHAR_SCOPE_TITLE :
                self .char_filter_scope_toggle_button .setText (self ._tr ("char_filter_scope_title_text","Filter: Title"))
                self .char_filter_scope_toggle_button .setToolTip (self ._tr ("char_filter_scope_title_tooltip","Tooltip for char filter title"))
            elif self .char_filter_scope ==CHAR_SCOPE_BOTH :
                self .char_filter_scope_toggle_button .setText (self ._tr ("char_filter_scope_both_text","Filter: Both"))
                self .char_filter_scope_toggle_button .setToolTip (self ._tr ("char_filter_scope_both_tooltip","Tooltip for char filter both"))
            elif self .char_filter_scope ==CHAR_SCOPE_COMMENTS :
                self .char_filter_scope_toggle_button .setText (self ._tr ("char_filter_scope_comments_text","Filter: Comments (Beta)"))
                self .char_filter_scope_toggle_button .setToolTip (self ._tr ("char_filter_scope_comments_tooltip","Tooltip for char filter comments"))
            else :
                self .char_filter_scope_toggle_button .setText (self ._tr ("char_filter_scope_unknown_text","Filter: Unknown"))
                self .char_filter_scope_toggle_button .setToolTip (self ._tr ("char_filter_scope_unknown_tooltip","Tooltip for char filter unknown"))

    def _cycle_char_filter_scope (self ):
        if self .char_filter_scope ==CHAR_SCOPE_TITLE :
            self .char_filter_scope =CHAR_SCOPE_FILES 
        elif self .char_filter_scope ==CHAR_SCOPE_FILES :
            self .char_filter_scope =CHAR_SCOPE_BOTH 
        elif self .char_filter_scope ==CHAR_SCOPE_BOTH :
            self .char_filter_scope =CHAR_SCOPE_COMMENTS 
        elif self .char_filter_scope ==CHAR_SCOPE_COMMENTS :
            self .char_filter_scope =CHAR_SCOPE_TITLE 
        else :
            self .char_filter_scope =CHAR_SCOPE_TITLE 

        self ._update_char_filter_scope_button_text ()
        self .settings .setValue (CHAR_FILTER_SCOPE_KEY ,self .char_filter_scope )
        self .log_signal .emit (f"ℹ️ Character filter scope changed to: '{self .char_filter_scope }'")

    def _handle_ui_add_new_character (self ):
        """Handles adding a new character from the UI input field."""
        if getattr(self, 'active_known_categories', []):
            QMessageBox.warning(self, "Filter Active", "You cannot add new characters while Series Expansions are filtered.\nPlease uncheck all boxes in Visual Sort Settings first.")
            return
        name_from_ui_input =self .new_char_input .text ().strip ()
        successfully_added_any =False 

        if not name_from_ui_input :
            QMessageBox .warning (self ,"Input Error","Name cannot be empty.")
            return 

        if name_from_ui_input .startswith ("(")and name_from_ui_input .endswith (")~"):
            content =name_from_ui_input [1 :-2 ].strip ()
            aliases =[alias .strip ()for alias in content .split (',')if alias .strip ()]
            if aliases :
                folder_name =" ".join (aliases )
                if self .add_new_character (name_to_add =folder_name ,
                is_group_to_add =True ,
                aliases_to_add =aliases ,
                suppress_similarity_prompt =False ):
                    successfully_added_any =True 
            else :
                QMessageBox .warning (self ,"Input Error","Empty group content for `~` format.")

        elif name_from_ui_input .startswith ("(")and name_from_ui_input .endswith (")"):
            content =name_from_ui_input [1 :-1 ].strip ()
            names_to_add_separately =[name .strip ()for name in content .split (',')if name .strip ()]
            if names_to_add_separately :
                for name_item in names_to_add_separately :
                    if self .add_new_character (name_to_add =name_item ,
                    is_group_to_add =False ,
                    aliases_to_add =[name_item ],
                    suppress_similarity_prompt =False ):
                        successfully_added_any =True 
            else :
                QMessageBox .warning (self ,"Input Error","Empty group content for standard group format.")
        else :
            if self .add_new_character (name_to_add =name_from_ui_input ,
            is_group_to_add =False ,
            aliases_to_add =[name_from_ui_input ],
            suppress_similarity_prompt =False ):
                successfully_added_any =True 

        if successfully_added_any :
            self .new_char_input .clear ()
            self .save_known_names ()


    def add_new_character (self ,name_to_add ,is_group_to_add ,aliases_to_add ,suppress_similarity_prompt =False ):
        """
        Validates user input from the 'Add Character' box. 
        Checks for exact duplicates or dangerously similar overlaps before adding 
        the new character/group to the Known Names list.
        """
        global KNOWN_NAMES ,clean_folder_name 
        if not name_to_add :
            QMessageBox .warning (self ,"Input Error","Name cannot be empty.");return False 

        name_to_add_lower =name_to_add .lower ()
        for kn_entry in KNOWN_NAMES :
            if kn_entry ["name"].lower ()==name_to_add_lower :
                QMessageBox .warning (self ,"Duplicate Name",f"The primary folder name '{name_to_add }' already exists.");return False 
            if not is_group_to_add and name_to_add_lower in [a .lower ()for a in kn_entry ["aliases"]]:
                QMessageBox .warning (self ,"Duplicate Alias",f"The name '{name_to_add }' already exists as an alias for '{kn_entry ['name']}'.");return False 

        similar_names_details =[]
        for kn_entry in KNOWN_NAMES :
            for term_to_check_similarity_against in kn_entry ["aliases"]:
                term_lower =term_to_check_similarity_against .lower ()
                if name_to_add_lower !=term_lower and (name_to_add_lower in term_lower or term_lower in name_to_add_lower ):
                    similar_names_details .append ((name_to_add ,kn_entry ["name"]))
                    break 
            for new_alias in aliases_to_add :
                if new_alias .lower ()!=term_to_check_similarity_against .lower ()and (new_alias .lower ()in term_to_check_similarity_against .lower ()or term_to_check_similarity_against .lower ()in new_alias .lower ()):
                    similar_names_details .append ((new_alias ,kn_entry ["name"]))
                    break 

        if similar_names_details and not suppress_similarity_prompt :
            if similar_names_details :
                first_similar_new ,first_similar_existing =similar_names_details [0 ]
                shorter ,longer =sorted ([first_similar_new ,first_similar_existing ],key =len )

                msg_box =QMessageBox (self )
                msg_box .setIcon (QMessageBox .Warning )
                msg_box .setWindowTitle ("Potential Name Conflict")
                msg_box .setText (
                f"The name '{first_similar_new }' is very similar to an existing name: '{first_similar_existing }'.\n\n"
                f"This could lead to unexpected folder grouping (e.g., under '{clean_folder_name (shorter )}' instead of a more specific '{clean_folder_name (longer )}' or vice-versa).\n\n"
                "Do you want to change the name you are adding, or proceed anyway?"
                )
                change_button =msg_box .addButton ("Change Name",QMessageBox .RejectRole )
                proceed_button =msg_box .addButton ("Proceed Anyway",QMessageBox .AcceptRole )
                msg_box .setDefaultButton (proceed_button )
                msg_box .setEscapeButton (change_button )
                msg_box .exec_ ()

                if msg_box .clickedButton ()==change_button :
                    self .log_signal .emit (f"ℹ️ User chose to change '{first_similar_new }' due to similarity with an alias of '{first_similar_existing }'.")
                    return False 
                self .log_signal .emit (f"⚠️ User proceeded with adding '{first_similar_new }' despite similarity with an alias of '{first_similar_existing }'.")
        new_entry ={
        "name": clean_folder_name(name_to_add),
        "is_group":is_group_to_add ,
        "aliases":sorted (list (set (aliases_to_add )),key =str .lower )
        }
        if is_group_to_add :
            for new_alias in new_entry ["aliases"]:
                if any (new_alias .lower ()==kn_entry ["name"].lower ()for kn_entry in KNOWN_NAMES if kn_entry ["name"].lower ()!=name_to_add_lower ):
                    QMessageBox .warning (self ,"Alias Conflict",f"Alias '{new_alias }' (for group '{name_to_add }') conflicts with an existing primary name.");return False 
        KNOWN_NAMES .append (new_entry )
        self .character_list .clear ()
        self .character_list .addItems ([entry ["name"]for entry in KNOWN_NAMES ])
        self .filter_character_list (self .character_search_input .text ())

        log_msg_suffix =f" (as group with aliases: {', '.join (new_entry ['aliases'])})"if is_group_to_add and len (new_entry ['aliases'])>1 else ""
        self .log_signal .emit (f"✅ Added '{name_to_add }' to known names list{log_msg_suffix }.")
        self .new_char_input .clear ()
        return True 

    def _handle_more_options_toggled(self, button, checked):
        """
        Launches the advanced configuration dialog for Text and PDF extraction 
        (e.g., choosing whether to extract Comments or Post Descriptions).
        """
        if button == self.radio_more and checked:
            if getattr(self, '_is_loading_settings', False):
                return
            current_scope = self.more_filter_scope or MoreOptionsDialog.SCOPE_CONTENT
            current_format = self.text_export_format or 'pdf'

            url_text = self.link_input.text().strip() if self.link_input else ""
            service, _, _ = extract_post_info(url_text)
            is_simpcity = (service == 'simpcity')

            dialog = MoreOptionsDialog(
                self,
                current_scope=current_scope,
                current_format=current_format,
                single_pdf_checked=self.single_pdf_setting,
                add_info_checked=self.add_info_in_pdf_setting,
                is_simpcity=is_simpcity
            )

            if dialog.exec_() == QDialog.Accepted:
                self.more_filter_scope = dialog.get_selected_scope()
                self.text_export_format = dialog.get_selected_format()
                self.single_pdf_setting = dialog.get_single_pdf_state()
                self.add_info_in_pdf_setting = dialog.get_add_info_state()

                is_any_pdf_mode = (self.text_export_format == 'pdf')
                scope_text = "Comments" if self.more_filter_scope == MoreOptionsDialog.SCOPE_COMMENTS else "Description"
                
                format_extras = []
                if self.single_pdf_setting:
                    format_extras.append("Single")
                if is_any_pdf_mode and self.add_info_in_pdf_setting:
                    format_extras.append("Info")
                
                extra_str = f" [{'+'.join(format_extras)}]" if format_extras else ""
                format_display = f" ({self.text_export_format.upper()}{extra_str})"
                
                self.radio_more.setText(f"{scope_text}{format_display}")

                if hasattr(self, 'use_multithreading_checkbox'):
                    self.use_multithreading_checkbox.setEnabled(not is_any_pdf_mode)
                    if is_any_pdf_mode:
                        self.use_multithreading_checkbox.setChecked(False)
                    self._handle_multithreading_toggle(self.use_multithreading_checkbox.isChecked())

                if hasattr(self, 'use_subfolders_checkbox'):
                    self.use_subfolders_checkbox.setEnabled(not self.single_pdf_setting)
                    if self.single_pdf_setting:
                        self.use_subfolders_checkbox.setChecked(False)

                if hasattr(self, 'use_subfolder_per_post_checkbox'):
                    self.use_subfolder_per_post_checkbox.setEnabled(not self.single_pdf_setting)
                    if self.single_pdf_setting:
                        self.use_subfolder_per_post_checkbox.setChecked(False)

                self.log_signal.emit(f"ℹ️ 'More' filter set: {scope_text}, Format: {self.text_export_format.upper()}")
                if is_any_pdf_mode:
                    status_single = "Enabled" if self.single_pdf_setting else "Disabled"
                    status_info = "Enabled" if self.add_info_in_pdf_setting else "Disabled"
                    self.log_signal.emit(f"   ↳ PDF Options: Single PDF={status_single}, Add Info Page={status_info}")
                    self.log_signal.emit("   ↳ Multithreading disabled for PDF export.")

            else:
                self.log_signal.emit("ℹ️ 'More' filter selection cancelled. Reverting to 'All'.")
                if hasattr(self, 'radio_all'):
                    self.radio_all.setChecked(True)

       
        elif button != self.radio_more and checked:
            self.radio_more.setText("More")
            self.more_filter_scope = None
            self.single_pdf_setting = False
            self.add_info_in_pdf_setting = False
            
            
            if hasattr(self, 'use_multithreading_checkbox'):
                self.use_multithreading_checkbox.setEnabled(True)
                self._update_multithreading_for_date_mode()
            
            if hasattr(self, 'use_subfolders_checkbox'):
                self.use_subfolders_checkbox.setEnabled(True)
                
            if hasattr(self, 'use_subfolder_per_post_checkbox'):
                self.update_ui_for_subfolders(self.use_subfolders_checkbox.isChecked())

    def delete_selected_character (self ):
        if getattr(self, 'active_known_categories', []):
            QMessageBox.warning(self, "Filter Active", "You cannot delete characters while Series Expansions are filtered.\nPlease uncheck all boxes in Visual Sort Settings first.")
            return
        global KNOWN_NAMES 
        selected_items =self .character_list .selectedItems ()
        if not selected_items :
            QMessageBox .warning (self ,"Selection Error","Please select one or more names to delete.");return 

        primary_names_to_remove ={item .text ()for item in selected_items }
        confirm =QMessageBox .question (self ,"Confirm Deletion",
        f"Are you sure you want to delete {len (primary_names_to_remove )} selected entry/entries (and their aliases)?",
        QMessageBox .Yes |QMessageBox .No ,QMessageBox .No )
        if confirm ==QMessageBox .Yes :
            original_count =len (KNOWN_NAMES )
            KNOWN_NAMES [:]=[entry for entry in KNOWN_NAMES if entry ["name"]not in primary_names_to_remove ]
            removed_count =original_count -len (KNOWN_NAMES )

            if removed_count >0 :
                self .log_signal .emit (f"Removed {removed_count } name(s).")
                self .character_list .clear ()
                self .character_list .addItems ([entry ["name"]for entry in KNOWN_NAMES ])
                self .filter_character_list (self .character_search_input .text ())
                self .save_known_names ()
            else :
                self .log_signal .emit ("ℹ️ No names were removed (they might not have been in the list).")


    def update_custom_folder_visibility (self ,url_text =None ):
        if url_text is None :
            url_text =self .link_input .text ()

        service ,_ ,post_id =extract_post_info (url_text .strip ())

        if service == 'simpcity' and getattr(self, 'radio_more', None) and self.radio_more.isChecked():
            from .dialogs.MoreOptionsDialog import MoreOptionsDialog
            if getattr(self, 'more_filter_scope', None) == MoreOptionsDialog.SCOPE_COMMENTS or getattr(self, 'add_info_in_pdf_setting', False):
                self.more_filter_scope = MoreOptionsDialog.SCOPE_CONTENT
                self.add_info_in_pdf_setting = False
                
                is_any_pdf_mode = (self.text_export_format == 'pdf')
                format_extras = []
                if self.single_pdf_setting:
                    format_extras.append("Single")
                extra_str = f" [{'+'.join(format_extras)}]" if format_extras else ""
                format_display = f" ({self.text_export_format.upper()}{extra_str})"
                self.radio_more.setText(f"Description{format_display}")

        is_single_post_url =bool (post_id )
        
        subfolders_by_known_txt_enabled = getattr(self, 'use_subfolders_checkbox', None) and self.use_subfolders_checkbox.isChecked()
        subfolder_per_post_enabled = getattr(self, 'use_subfolder_per_post_checkbox', None) and self.use_subfolder_per_post_checkbox.isChecked()
        any_subfolder_option_enabled = subfolders_by_known_txt_enabled or subfolder_per_post_enabled

        not_only_links_or_archives_mode =not (
        (self .radio_only_links and self .radio_only_links .isChecked ())or 
        (self .radio_only_archives and self .radio_only_archives .isChecked ())or 
        (hasattr (self ,'radio_only_audio')and self .radio_only_audio .isChecked ())
        )

        should_show_custom_folder =is_single_post_url and any_subfolder_option_enabled and not_only_links_or_archives_mode 

        if self .custom_folder_widget :
            self .custom_folder_widget .setVisible (should_show_custom_folder )

        if not (self .custom_folder_widget and self .custom_folder_widget .isVisible ()):
            if self .custom_folder_input :self .custom_folder_input .clear ()


    def update_ui_for_subfolders(self, separate_folders_by_name_title_checked: bool):
        current_filter_mode = self.get_filter_mode()
        can_enable_sfp = current_filter_mode not in ['audio', 'text_only']

        known_txt_on = getattr(self, 'use_subfolders_checkbox', None) and self.use_subfolders_checkbox.isChecked()
        visual_sort_on = getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked()
        
        if known_txt_on and visual_sort_on:
            can_enable_sfp = False

        if hasattr(self, 'use_subfolder_per_post_checkbox') and self.use_subfolder_per_post_checkbox:
            self.use_subfolder_per_post_checkbox.setEnabled(can_enable_sfp)
            if not can_enable_sfp:
                self.use_subfolder_per_post_checkbox.setChecked(False)

        if hasattr(self, 'date_prefix_checkbox') and self.date_prefix_checkbox:
            can_enable_date_prefix = (
                self.use_subfolder_per_post_checkbox.isEnabled() and 
                self.use_subfolder_per_post_checkbox.isChecked()
            )
            self.date_prefix_checkbox.setEnabled(can_enable_date_prefix)
            if not can_enable_date_prefix:
                self.date_prefix_checkbox.setChecked(False)

        if hasattr(self, 'update_custom_folder_visibility'):
            self.update_custom_folder_visibility()


    def _update_cookie_input_visibility (self ,checked ):
        cookie_text_input_exists =hasattr (self ,'cookie_text_input')
        cookie_browse_button_exists =hasattr (self ,'cookie_browse_button')

        if cookie_text_input_exists or cookie_browse_button_exists :
            is_only_links =self .radio_only_links and self .radio_only_links .isChecked ()
            if cookie_text_input_exists :self .cookie_text_input .setVisible (checked )
            if cookie_browse_button_exists :self .cookie_browse_button .setVisible (checked )

            can_enable_cookie_text =checked and not is_only_links 
            enable_state_for_fields =can_enable_cookie_text and (self .download_btn .isEnabled ()or self .is_paused )

            if cookie_text_input_exists :
                self .cookie_text_input .setEnabled (enable_state_for_fields )
                if self .selected_cookie_filepath and checked :
                    self .cookie_text_input .setText (self .selected_cookie_filepath )
                    self .cookie_text_input .setReadOnly (True )
                    self .cookie_text_input .setPlaceholderText ("")
                elif checked :
                    self .cookie_text_input .setReadOnly (False )
                    self .cookie_text_input .setPlaceholderText ("Cookie string (if no cookies.txt)")

            if cookie_browse_button_exists :self .cookie_browse_button .setEnabled (enable_state_for_fields )


    def update_page_range_enabled_state (self ):
        url_text =self .link_input .text ().strip ()if self .link_input else ""
        _ ,_ ,post_id =extract_post_info (url_text )

        is_creator_feed =not post_id if url_text else False 
        enable_page_range =is_creator_feed 

        for widget in [self .page_range_label ,self .start_page_input ,self .to_label ,self .end_page_input ]:
            if widget :widget .setEnabled (enable_page_range )

        if not enable_page_range :
            if self .start_page_input :self .start_page_input .clear ()
            if self .end_page_input :self .end_page_input .clear ()


    def _update_manga_filename_style_button_text (self ):
        if self .manga_rename_toggle_button :
            if self .manga_filename_style ==STYLE_POST_TITLE :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_post_title_text","Name: Post Title"))

            elif self .manga_filename_style ==STYLE_ORIGINAL_NAME :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_date_original_text","Date + Original"))

            elif self .manga_filename_style ==STYLE_POST_TITLE_GLOBAL_NUMBERING :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_title_global_num_text","Name: Title+G.Num"))

            elif self .manga_filename_style ==STYLE_DATE_BASED :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_date_based_text","Name: Date Based"))
            
            elif self .manga_filename_style ==STYLE_POST_ID:
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_post_id_text","Name: Post ID"))

            elif self .manga_filename_style ==STYLE_DATE_POST_TITLE :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_date_post_title_text","Name: Date + Title"))

            elif self.manga_filename_style == STYLE_CUSTOM:
                self.manga_rename_toggle_button.setText(self._tr("manga_style_custom_text", "Name: Custom"))

            else :
                self .manga_rename_toggle_button .setText (self ._tr ("manga_style_unknown_text","Name: Unknown Style"))

            self .manga_rename_toggle_button .setToolTip ("Click to cycle Manga Filename Style (when Renaming Mode is active for a creator feed).")

    def _toggle_manga_filename_style(self):
        url_text = self.link_input.text().strip() if self.link_input else ""
        service, _, post_id = extract_post_info(url_text)
        
        print(f"DEBUG: Toggle Style - URL: {url_text}, Service Detected: {service}")

        if service == 'deviantart':
            self.log_signal.emit("ℹ️ DeviantArt mode allows only Custom Renaming format.")
            
            self.manga_filename_style = STYLE_CUSTOM
            self.settings.setValue(MANGA_FILENAME_STYLE_KEY, self.manga_filename_style)
            self.settings.sync()
            self._update_manga_filename_style_button_text()
            
            self._show_custom_rename_dialog()
            return

        if service == 'simpcity':
            self.log_signal.emit("ℹ️ SimpCity mode allows only Custom Renaming format.")
            
            self.manga_filename_style = STYLE_CUSTOM
            self.settings.setValue(MANGA_FILENAME_STYLE_KEY, self.manga_filename_style)
            self.settings.sync()
            self._update_manga_filename_style_button_text()
            
            self._show_custom_rename_dialog()
            return

        is_single_post = bool(post_id)
        is_coomerfans = 'coomerfans.com' in url_text.lower()
        current_style = self.manga_filename_style
        new_style = ""
        
        if is_single_post:
             if current_style == STYLE_POST_TITLE:
                new_style = STYLE_DATE_POST_TITLE
             elif current_style == STYLE_DATE_POST_TITLE:
                new_style = STYLE_ORIGINAL_NAME
             elif current_style == STYLE_ORIGINAL_NAME:
                new_style = STYLE_POST_ID
             elif current_style == STYLE_POST_ID:
                new_style = STYLE_CUSTOM  
             elif current_style == STYLE_CUSTOM:  
                new_style = STYLE_POST_TITLE  
             else:
                new_style = STYLE_POST_TITLE
        elif service == 'coomerfans' or is_coomerfans:
             if current_style == STYLE_POST_TITLE:
                 new_style = STYLE_DATE_POST_TITLE
             else:
                 new_style = STYLE_POST_TITLE
        else:
             if current_style == STYLE_POST_TITLE:
                new_style = STYLE_ORIGINAL_NAME 
             elif current_style == STYLE_ORIGINAL_NAME:
                new_style = STYLE_DATE_POST_TITLE 
             elif current_style == STYLE_DATE_POST_TITLE:
                new_style = STYLE_POST_TITLE_GLOBAL_NUMBERING 
             elif current_style == STYLE_POST_TITLE_GLOBAL_NUMBERING:
                new_style = STYLE_DATE_BASED 
             elif current_style == STYLE_DATE_BASED:
                new_style = STYLE_POST_ID 
             elif current_style == STYLE_POST_ID: 
                new_style = STYLE_CUSTOM 
             elif current_style == STYLE_CUSTOM:
                new_style = STYLE_POST_TITLE
             else:
                new_style = STYLE_POST_TITLE 

        self.manga_filename_style = new_style 
        self.settings.setValue(MANGA_FILENAME_STYLE_KEY, self.manga_filename_style)
        self.settings.sync()
        self._update_manga_filename_style_button_text()
        self.update_ui_for_manga_mode(self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False)
        
    def _handle_favorite_mode_toggle (self ,checked ):
        if not self .url_or_placeholder_stack or not self .bottom_action_buttons_stack :
            return 

        self .url_or_placeholder_stack .setCurrentIndex (1 if checked else 0 )
        self .bottom_action_buttons_stack .setCurrentIndex (1 if checked else 0 )

        if checked :
            if self .link_input :
                self .link_input .clear ()
                self .link_input .setEnabled (False )
            for widget in [self .page_range_label ,self .start_page_input ,self .to_label ,self .end_page_input ]:
                if widget :widget .setEnabled (False )
            if self .start_page_input :self .start_page_input .clear ()
            if self .end_page_input :self .end_page_input .clear ()

            self .update_custom_folder_visibility ()
            self .update_page_range_enabled_state ()
            if self .manga_mode_checkbox :
                pass
            if hasattr (self ,'use_cookie_checkbox'):
                self .use_cookie_checkbox .setChecked (True )
                self .use_cookie_checkbox .setEnabled (False )
            if hasattr (self ,'use_cookie_checkbox'):
                self ._update_cookie_input_visibility (True )
            self .update_ui_for_manga_mode (False )

            if hasattr (self ,'favorite_mode_artists_button'):
                self .favorite_mode_artists_button .setEnabled (True )
            if hasattr (self ,'favorite_mode_posts_button'):
                self .favorite_mode_posts_button .setEnabled (True )

        else :
            if self .link_input :self .link_input .setEnabled (True )
            self .update_page_range_enabled_state ()
            self .update_custom_folder_visibility ()
            self .update_ui_for_manga_mode (self .manga_mode_checkbox .isChecked ()if self .manga_mode_checkbox else False )

            if hasattr (self ,'use_cookie_checkbox'):
                self .use_cookie_checkbox .setEnabled (True )
            if hasattr (self ,'use_cookie_checkbox'):
                self ._update_cookie_input_visibility (self .use_cookie_checkbox .isChecked ())

            if hasattr (self ,'favorite_mode_artists_button'):
                self .favorite_mode_artists_button .setEnabled (False )
            if hasattr (self ,'favorite_mode_posts_button'):
                self .favorite_mode_posts_button .setEnabled (False )

    def update_ui_for_manga_mode (self ,checked ):
        """
        Adjusts the UI when Renaming Mode (Manga Mode) is toggled.
        Hides or shows the custom date prefix input and disables features like 
        Discord page ranges that conflict with manga sorting.
        """
        url_text =self .link_input .text ().strip ()if self .link_input else ""
        service, _, _ = extract_post_info(url_text)
        is_discord_url = (service == 'discord')

        if is_discord_url:
            if self.manga_mode_checkbox:
                self.manga_mode_checkbox.setEnabled(False)
                self.manga_mode_checkbox.setChecked(False)
            if self.page_range_label: self.page_range_label.setEnabled(False)
            if self.start_page_input: self.start_page_input.setEnabled(False)
            if self.to_label: self.to_label.setEnabled(False)
            if self.end_page_input: self.end_page_input.setEnabled(False)
            checked = False

        is_only_links_mode =self .radio_only_links and self .radio_only_links .isChecked ()
        is_only_archives_mode =self .radio_only_archives and self .radio_only_archives .isChecked ()
        is_only_audio_mode =hasattr (self ,'radio_only_audio')and self .radio_only_audio .isChecked ()

        _ ,_ ,post_id =extract_post_info (url_text )

        is_creator_feed =not post_id if url_text else False 
        is_single_post = bool(post_id)
        is_favorite_mode_on =self .favorite_mode_checkbox .isChecked ()if self .favorite_mode_checkbox else False 

        if self.favorite_download_queue and all(item.get('type') == 'single_post_from_popup' for item in self.favorite_download_queue):
            is_single_post = True

        can_enable_manga_checkbox = (is_favorite_mode_on or not is_discord_url)        
        if self .manga_mode_checkbox :
            self .manga_mode_checkbox .setEnabled (can_enable_manga_checkbox)
            if not can_enable_manga_checkbox and self .manga_mode_checkbox .isChecked ():
                self .manga_mode_checkbox .setChecked (False )
                checked =self .manga_mode_checkbox .isChecked ()

        manga_mode_effectively_on = can_enable_manga_checkbox and checked

        sequential_styles = [STYLE_DATE_BASED, STYLE_POST_TITLE_GLOBAL_NUMBERING]
        if is_single_post and self.manga_filename_style in sequential_styles:
            self.manga_filename_style = STYLE_POST_TITLE 
            self._update_manga_filename_style_button_text()

        if self .manga_rename_toggle_button :
            self .manga_rename_toggle_button .setVisible (manga_mode_effectively_on and not (is_only_links_mode or is_only_archives_mode or is_only_audio_mode ))

        if not is_discord_url:
            self .update_page_range_enabled_state ()

        current_filename_style =self .manga_filename_style 
        show_date_prefix_input =(
        manga_mode_effectively_on and 
        (current_filename_style ==STYLE_DATE_BASED) and 
        not (is_only_links_mode or is_only_archives_mode or is_only_audio_mode )
        )
        if hasattr (self ,'manga_date_prefix_input'):
            self .manga_date_prefix_input .setVisible (show_date_prefix_input )
            if show_date_prefix_input :
                self .manga_date_prefix_input .setMaximumWidth (120 )
                self .manga_date_prefix_input .setMinimumWidth (60 )
            else :
                self .manga_date_prefix_input .clear ()
                self .manga_date_prefix_input .setMaximumWidth (16777215 )
                self .manga_date_prefix_input .setMinimumWidth (0 )

        if hasattr(self, 'multipart_toggle_button'):
            hide_multipart_button_due_mode = is_only_links_mode or is_only_archives_mode or is_only_audio_mode
            self.multipart_toggle_button.setVisible(not hide_multipart_button_due_mode)
  
        if hasattr(self, 'custom_rename_dialog_button'):
            is_custom_mode = self.manga_filename_style == STYLE_CUSTOM
            self.custom_rename_dialog_button.setVisible(manga_mode_effectively_on and is_custom_mode)

        self ._update_multithreading_for_date_mode ()

    def filter_character_list (self ,search_text ):
        search_text_lower =search_text .lower ()
        for i in range (self .character_list .count ()):
            item =self .character_list .item (i )
            item .setHidden (search_text_lower not in item .text ().lower ())

    def _show_custom_rename_dialog(self):
        """Shows the dialog to edit the custom manga filename format."""
        
        url_text = self.link_input.text().strip() if self.link_input else ""
        service, _, _ = extract_post_info(url_text)
        is_deviantart = (service == 'deviantart')
        is_simpcity = (service == 'simpcity')

        dialog = CustomFilenameDialog(
            self.custom_manga_filename_format, 
            self.manga_custom_date_format, 
            self.custom_manga_suffix_format,
            self, 
            is_deviantart=is_deviantart,
            is_simpcity=is_simpcity
        )
        
        if dialog.exec_() == QDialog.Accepted:
            self.custom_manga_filename_format = dialog.get_format_string()
            self.manga_custom_date_format = dialog.get_date_format_string()
            self.custom_manga_suffix_format = dialog.get_suffix_format_string()
            self.settings.setValue(MANGA_CUSTOM_FORMAT_KEY, self.custom_manga_filename_format)
            self.settings.setValue(MANGA_CUSTOM_DATE_FORMAT_KEY, self.manga_custom_date_format)
            self.settings.setValue(MANGA_CUSTOM_SUFFIX_FORMAT_KEY, self.custom_manga_suffix_format)
            self.log_signal.emit(f"ℹ️ Custom filename format set to: '{self.custom_manga_filename_format}'")
            self.log_signal.emit(f"ℹ️ Custom date format set to: '{self.manga_custom_date_format}'")
            self.log_signal.emit(f"ℹ️ Custom suffix format set to: '{self.custom_manga_suffix_format}'")
            self._update_manga_filename_style_button_text()

    def update_multithreading_label (self ,text ):
        if self .use_multithreading_checkbox .isChecked ():
            base_text =self ._tr ("use_multithreading_checkbox_base_label","Use Multithreading")
            try :
                num_threads_val =int (text )
                if num_threads_val >0 :self .use_multithreading_checkbox .setText (f"{base_text } ({num_threads_val } Threads)")
                else :self .use_multithreading_checkbox .setText (f"{base_text } (Invalid: >0)")
            except ValueError :
                self .use_multithreading_checkbox .setText (f"{base_text } (Invalid Input)")
        else :
            self .use_multithreading_checkbox .setText (f"{self ._tr ('use_multithreading_checkbox_base_label','Use Multithreading')} (1 Thread)")


    def _handle_multithreading_toggle (self ,checked ):
        if not checked :
            self .thread_count_input .setEnabled (False )
            self .thread_count_label .setEnabled (False )
            self .use_multithreading_checkbox .setText ("Use Multithreading (1 Thread)")
        else :
            self .thread_count_input .setEnabled (True )
            self .thread_count_label .setEnabled (True )
            self .update_multithreading_label (self .thread_count_input .text ())

    def _update_multithreading_for_date_mode (self ):
        """
        Checks if Renaming Mode is ON and 'Date Based' style is selected.
        If so, disables multithreading. Otherwise, enables it.
        """
        if not hasattr (self ,'manga_mode_checkbox')or not hasattr (self ,'use_multithreading_checkbox'):
            return 

        manga_on =self .manga_mode_checkbox .isChecked ()
        is_sequential_style_requiring_single_thread =(
        self .manga_filename_style ==STYLE_DATE_BASED or 
        self .manga_filename_style ==STYLE_POST_TITLE_GLOBAL_NUMBERING 
        )
        if manga_on and is_sequential_style_requiring_single_thread :
            if self .use_multithreading_checkbox .isChecked ()or self .use_multithreading_checkbox .isEnabled ():
                if self .use_multithreading_checkbox .isChecked ():
                    self .log_signal .emit ("ℹ️ Manga Date Mode: Multithreading for post processing has been disabled to ensure correct sequential file numbering.")
                self .use_multithreading_checkbox .setChecked (False )
            self .use_multithreading_checkbox .setEnabled (False )
            self ._handle_multithreading_toggle (False )
        else:
            if not self.use_multithreading_checkbox.isEnabled():
                self.use_multithreading_checkbox.setEnabled(True)
                self.use_multithreading_checkbox.setChecked(True)
            
            self._handle_multithreading_toggle(self.use_multithreading_checkbox.isChecked())

    def update_progress_display(self, total, processed, unit="posts"):
        """Updates the main progress label with total, processed, and percentage."""
        if total > 0:
            progress_percent = (processed / total) * 100
            self.progress_label.setText(f"Progress: {processed} / {total} {unit} ({progress_percent:.1f}%)")
        elif processed > 0:
            self.progress_label.setText(f"Progress: Processing {unit} {processed}...")
        else:
            self.progress_label.setText("Progress: Starting...")

        if total > 0 or processed > 0:
            self.file_progress_label.setText("")

    def _set_ui_for_specialized_downloader(self, is_specialized):
        """Disables or enables UI elements for non-standard downloaders."""
        widgets_to_disable = [
            self.page_range_label, self.start_page_input, self.to_label, self.end_page_input,
            self.character_filter_widget, self.skip_words_input, self.skip_scope_toggle_button,
            self.remove_from_filename_input, self.radio_images, self.radio_videos,
            self.radio_only_archives, self.radio_only_links, self.radio_only_audio, self.radio_more,
            self.skip_zip_checkbox, self.download_thumbnails_checkbox, self.compress_images_checkbox,
            self.use_subfolders_checkbox, self.use_subfolder_per_post_checkbox,
            self.scan_content_images_checkbox, self.external_links_checkbox, self.manga_mode_checkbox,
            self.use_cookie_checkbox, self.keep_duplicates_checkbox, self.date_prefix_checkbox,
            self.manga_rename_toggle_button, self.manga_date_prefix_input,
            self.multipart_toggle_button, self.custom_folder_input, self.custom_folder_label,
            self.discord_scope_toggle_button
        ]

        enable_state = not is_specialized

        for widget in widgets_to_disable:
            if widget:
                widget.setEnabled(enable_state)
        
        if is_specialized and self.radio_all:
            self.radio_all.setChecked(True)
            self.radio_all.setEnabled(False)
        elif self.radio_all:
            self.radio_all.setEnabled(True)

        if enable_state:
            self._update_all_ui_states()

    def _update_all_ui_states(self):
        """A single function to call all UI update methods to restore state."""
        is_manga_checked = self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False
        is_subfolder_checked = self.use_subfolders_checkbox.isChecked() if self.use_subfolders_checkbox else False
        is_cookie_checked = self.use_cookie_checkbox.isChecked() if self.use_cookie_checkbox else False
        
        self.update_ui_for_manga_mode(is_manga_checked)
        self.update_custom_folder_visibility()
        self.update_page_range_enabled_state()
        if self.radio_group.checkedButton():
             self._handle_filter_mode_change(self.radio_group.checkedButton(), True)
        self.update_ui_for_subfolders(is_subfolder_checked)
        self._update_cookie_input_visibility(is_cookie_checked)

    def _apply_ui_profile(self, profile_name):
        """Universally toggles all UI elements based on a dictionary profile."""
        if not hasattr(self, 'UI_PROFILES'):
            return
            
        profile = self.UI_PROFILES.get(profile_name, self.UI_PROFILES['kemono'])

        def get_widget(name):
            if hasattr(self, 'ui') and hasattr(self.ui, name):
                return getattr(self.ui, name)
            return getattr(self, name, None)

        all_radios = ['radio_all', 'radio_videos', 'radio_only_archives', 'radio_only_audio', 'radio_only_links', 'radio_more', 'radio_images']
        for r in all_radios:
            widget = get_widget(r)
            if widget:
                widget.setEnabled(r in profile['enabled_radios'])

        if profile['force_radio']:
            force_widget = get_widget(profile['force_radio'])
            if force_widget:
                force_widget.setChecked(True)

        all_checkboxes = ['favorite_mode_checkbox', 'download_thumbnails_checkbox', 'scan_content_images_checkbox', 'keep_duplicates_checkbox']
        for c in all_checkboxes:
            widget = get_widget(c)
            if widget:
                widget.setEnabled(c in profile['enabled_checkboxes'])

        adv_widget = get_widget('advanced_settings_widget')
        if adv_widget:
            adv_widget.setEnabled(profile['advanced_enabled'])
            
            if profile['advanced_enabled']:
                
                if 'allowed_advanced' in profile:
                    for chk in adv_widget.findChildren(QCheckBox):
                        chk.setEnabled(False)
                    
                    for allowed_name in profile['allowed_advanced']:
                        allowed_widget = get_widget(allowed_name)
                        if allowed_widget:
                            allowed_widget.setEnabled(True)
                else:
                    for chk in adv_widget.findChildren(QCheckBox):
                        chk.setEnabled(True)

    def _update_contextual_ui_elements(self, text=""):
        """Shows or hides UI elements based on the URL, like the Discord scope button."""
        
        if 'allporncomic.com' in text.lower() and not hasattr(self, 'allcomic_warning_shown'):
            self.allcomic_warning_shown = False
        if 'allporncomic.com' in text.lower() and not self.allcomic_warning_shown:
            warning_html = (
                f'{HTML_PREFIX}'
                '<div>'
                '<h2 style="color: #f0ad4e; margin-top: 8px; margin-bottom: 4px;">⚠️ AllPornComic - High Risk of IP Block</h2>'
                '<p style="margin-top: 0; margin-bottom: 4px;">This site is known for aggressively blocking IP addresses that download too quickly, causing connection errors.</p>'
                '<p style="font-weight: bold; margin-top: 4px; margin-bottom: 2px;">To avoid this, please follow these recommendations:</p>'
                '<p style="margin: 0 0 2px 20px;">&bull; <b>Use a VPN:</b> This is the most effective way to avoid a block on your home IP.</p>'
                '<p style="margin: 0 0 2px 20px;">&bull; <b>Pace Yourself:</b> Avoid downloading entire large series at once. Download a few chapters, wait, then download more.</p>'
                '<p style="margin: 0 0 2px 20px;">&bull; <b>If You Get Blocked:</b> Stop all downloads from the site, wait for an hour, or switch your VPN server/location.</p>'
                '</div>'
            )
            self.log_signal.emit(warning_html)
            self.allcomic_warning_shown = True
        
        if not hasattr(self, 'discord_scope_toggle_button'): return
        
        url_text = self.link_input.text().strip()
        service, _, _ = extract_post_info(url_text) 

        is_any_discord_url = (service == 'discord')
        is_simpcity = (service == 'simpcity')
        is_saint2 = 'saint2.su' in url_text or 'saint2.pk' in url_text or 'turbo.cr' in url_text
        is_erome = 'erome.com' in url_text
        is_coomerfans = 'coomerfans.com' in url_text
        is_hotleaks = 'hotleaks.tv' in url_text
        
        is_specialized = service in ['bunkr', 'nhentai', 'hentai2read', 'simpcity', 'deviantart'] or is_saint2 or is_erome or is_coomerfans or is_hotleaks
        is_specialized_for_disabling = service in ['bunkr', 'nhentai', 'hentai2read', 'deviantart'] or is_saint2 or is_erome or is_coomerfans or is_hotleaks     
      
        self._set_ui_for_specialized_downloader(is_specialized_for_disabling)

        if hasattr(self, 'simpcity_settings_widget'):
            self.simpcity_settings_widget.setVisible(is_simpcity)
        
        if service == 'deviantart':
            self._apply_ui_profile('deviantart')
            
            
            if getattr(self, 'manga_filename_style', None) != STYLE_CUSTOM:
                self.log_signal.emit("ℹ️ DeviantArt mode allows only Custom Renaming format. Switched to Custom.")
            
            if hasattr(self, 'manga_mode_checkbox') and self.manga_mode_checkbox:
                self.manga_mode_checkbox.setEnabled(True)
                self.manga_mode_checkbox.setToolTip("Enable Custom Renaming for DeviantArt")
            
            self.manga_filename_style = STYLE_CUSTOM
            
            if hasattr(self, '_update_manga_filename_style_button_text'):
                self._update_manga_filename_style_button_text()
            
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(False) 
                self.manga_rename_toggle_button.setToolTip("DeviantArt only supports Custom Renaming.")
            
            if hasattr(self, 'manga_mode_checkbox') and self.manga_mode_checkbox.isChecked():
                if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                    self.manga_rename_toggle_button.setVisible(True)
                if hasattr(self, 'custom_rename_dialog_button'):
                    self.custom_rename_dialog_button.setVisible(True)
                    
        elif service in ['allcomic', 'pixiv', 'instagram', 'nhentai', 'hentaifox', 'hentai2read', 'mangadex'] or any(domain in url_text.lower() for domain in ['allporncomic.com', 'nhentai.net', 'hentaifox.com', 'hentai2read.com', 'mangadex.org']):
            self._apply_ui_profile('image_only')
            
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(True)
            
        elif service == 'erome' or 'erome.com' in url_text.lower():
            self._apply_ui_profile('erome')
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(True)
                
        elif is_coomerfans:
            self._apply_ui_profile('coomerfans')
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(True)
            if hasattr(self, 'skip_words_input') and self.skip_words_input:
                self.skip_words_input.setEnabled(True)
            if hasattr(self, 'skip_scope_toggle_button') and self.skip_scope_toggle_button:
                self.skip_scope_toggle_button.setEnabled(True)

        elif is_hotleaks:
            self.filter_group_box.setVisible(False)
            self.text_extractor_group.setVisible(False)
            self.simpcity_options_group.setVisible(False)
            self.pdf_checkbox.setEnabled(False)
            self.zip_checkbox.setEnabled(False)
            
            self.media_group_box.setVisible(True)
            self.media_radio_all.setChecked(True)
            self.media_radio_all.setEnabled(False)
            self.media_radio_images.setEnabled(False)
            self.media_radio_videos.setEnabled(False)

        elif service in ['mega', 'google drive', 'dropbox', 'gofile']:
            self._apply_ui_profile('file_host')
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(True)
                
        elif not is_specialized_for_disabling:
            self._apply_ui_profile('kemono')
            if hasattr(self, 'manga_rename_toggle_button') and self.manga_rename_toggle_button:
                self.manga_rename_toggle_button.setEnabled(True)

        is_official_discord_url = 'discord.com' in url_text and is_any_discord_url

        if is_official_discord_url:
            self.remove_from_filename_label_widget.setText("🔑 Discord Token:")
            self.remove_from_filename_input.setPlaceholderText("Enter your Discord Authorization Token here")
            self.remove_from_filename_input.setEchoMode(QLineEdit.Password) 
            saved_token = self.settings.value(DISCORD_TOKEN_KEY, "")
            if saved_token:
                self.remove_from_filename_input.setText(saved_token)
        else:
            self.remove_from_filename_label_widget.setText(self._tr("remove_words_from_name_label", "✂️ Remove Words from name:"))
            self.remove_from_filename_input.setPlaceholderText(self._tr("remove_from_filename_input_placeholder_text", "e.g., patreon, HD"))
            self.remove_from_filename_input.setEchoMode(QLineEdit.Normal)

        if hasattr(self, 'discord_scope_toggle_button'):
            self.discord_scope_toggle_button.setVisible(is_any_discord_url)
        if hasattr(self, 'discord_message_limit_input'):
            self.discord_message_limit_input.setVisible(is_official_discord_url)

        if is_any_discord_url: 
            if hasattr(self, '_update_discord_scope_button_text'):
                self._update_discord_scope_button_text()
        elif not is_specialized:
            if hasattr(self, 'download_btn'):
                 self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
                 self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))

        # Apply SimpCity-specific overrides last to ensure they aren't undone by generic UI profiles
        if hasattr(self, 'use_cookie_checkbox'):
            if is_simpcity:
                self.use_cookie_checkbox.setChecked(True)
                self.use_cookie_checkbox.setEnabled(False)
            elif not is_specialized_for_disabling:
                self.use_cookie_checkbox.setEnabled(True)

    def _update_discord_scope_button_text(self):
        """Updates the text of the discord scope button and the main download button."""
        if self.discord_download_scope == 'files':
            self.discord_scope_toggle_button.setText("Scope: Files")
            self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
        else:
             self.discord_scope_toggle_button.setText("Scope: Messages")
             self.download_btn.setText("📄 Save Messages as PDF")

    def _cycle_discord_scope(self):
        """Toggles between 'files' and 'messages' for Discord downloads."""
        self.discord_download_scope = 'messages' if self.discord_download_scope == 'files' else 'files'
        self._update_discord_scope_button_text()

    def get_dark_theme(self, scale=1):
        """
        Wrapper method to make the dark theme function accessible to child dialogs.
        """
        
        actual_scale = getattr(self, 'scale_factor', scale)
        return get_theme_stylesheet(actual_scale)

    def start_download(self, direct_api_url=None, override_output_dir=None, is_restore=False, is_continuation=False, item_type_from_queue=None):

        """
        THE MAIN DOWNLOAD MANAGER.
        Validates all UI inputs, handles proxy/cookie setups, determines if the URL is for a 
        specialized site (like Discord/Bunkr) or standard Kemono/Coomer, and spins up the 
        appropriate multi-threaded or single-threaded background workers.
        """
        global KNOWN_NAMES, BackendDownloadThread, PostProcessorWorker, extract_post_info, MAX_FILE_THREADS_PER_POST_OR_WORKER
        
        if getattr(self, 'discord_download_scope', 'files') == 'messages':
            current_url = direct_api_url if direct_api_url else self.link_input.text().strip()
            
            service, _, _ = extract_post_info(current_url)
            if service == 'discord':
                self.start_discord_pdf_save()
                return

        self.is_main_download_active = True


        if not is_restore and not is_continuation:
            if self.main_log_output: self.main_log_output.clear()
            if self.external_log_output: self.external_log_output.clear()
            if self.missed_character_log_output: self.missed_character_log_output.clear()
            self.missed_key_terms_buffer.clear()
            self.already_logged_bold_key_terms.clear()

        if self.is_ready_to_download_batch_update:
            self._start_download_of_batch_update()
            return True

        if not direct_api_url:
            api_url_text = self.link_input.text().strip().lower()
            batch_handlers = {            
                'kemono.cr': {
                    'name': 'Kemono Batch',
                    'txt_file': 'kemono.txt',
                    'url_regex': r'https?://(?:www\.)?kemono\.(?:su|party|cr)/[^/\s]+/user/\d+(?:/post/\d+)?/?'
                },
                'kemono.su': {
                    'name': 'Kemono Batch',
                    'txt_file': 'kemono.txt',
                    'url_regex': r'https?://(?:www\.)?kemono\.(?:su|party|cr)/[^/\s]+/user/\d+(?:/post/\d+)?/?'
                },
                'pawchive.st': {
                    'name': 'Kemono Batch',
                    'txt_file': 'kemono.txt',
                    'url_regex': r'https?://(?:www\.)?pawchive\.st/[^/\s]+/user/\d+(?:/post/\d+)?/?'
                },

                'coomer.st': {
                    'name': 'Coomer Batch',
                    'txt_file': 'coomer.txt',
                    'url_regex': r'https?://(?:www\.)?coomer\.(?:su|party|st)/[^/\s]+/user/[^/\s]+(?:/post/\d+)?/?'
                },
                'coomer.su': {
                    'name': 'Coomer Batch',
                    'txt_file': 'coomer.txt',
                    'url_regex': r'https?://(?:www\.)?coomer\.(?:su|party|st)/[^/\s]+/user/[^/\s]+(?:/post/\d+)?/?'
                },
                'hentaifox.com': {
                    'name': 'HentaiFox',
                    'txt_file': 'hentaifox.txt',
                    'url_regex': r'https?://(?:www\.)?hentaifox\.com/(?:g|gallery)/\d+/?'
                },
                'allporncomic.com': {
                    'name': 'AllPornComic',
                    'txt_file': 'allporncomic.txt',
                    'url_regex': r'https?://allporncomic\.com/porncomic/[^/\s]+(?:/[^/\s]+)?/?'
                },
                'nhentai.net': {
                    'name': 'nhentai',
                    'txt_file': 'nhentai.txt',
                    'url_regex': r'https?://nhentai\.net/g/\d+/?'
                },
                'fap-nation.com': {
                    'name': 'Fap-Nation',
                    'txt_file': 'fap-nation.txt',
                    'url_regex': r'https?://(?:www\.)?fap-nation\.(?:com|org)/[^/\s]+/?'
                },
                'fap-nation.org': {
                    'name': 'Fap-Nation',
                    'txt_file': 'fap-nation.txt',
                    'url_regex': r'https?://(?:www\.)?fap-nation\.(?:com|org)/[^/\s]+/?'
                },
                'saint2.su': {
                    'name': 'Saint2/Turbo',
                    'txt_file': 'saint2.su.txt',
                    'url_regex': r'https?://(?:saint\d*\.(?:su|pk|cr|to)|turbo\.cr)/(?:a|d|embed)/[^/?#\s]+'
                },
                'turbo.cr': {
                    'name': 'Saint2/Turbo',
                    'txt_file': 'turbo.cr.txt',
                    'url_regex': r'https?://(?:saint\d*\.(?:su|pk|cr|to)|turbo\.cr)/(?:a|d|embed)/[^/?#\s]+'
                },
                'hentai2read.com': {
                    'name': 'Hentai2Read',
                    'txt_file': 'hentai2read.txt',
                    'url_regex': r'https?://hentai2read\.com/[^/\s]+(?:/\d+)?/?'
                },
                'rule34video.com': {
                    'name': 'Rule34Video.com',
                    'txt_file': 'rule34video.txt', 
                    'url_regex': r'https?://rule34video\.com/video/\d+/[^/\s]+/?'
                }
            }

            if api_url_text in batch_handlers:
                handler = batch_handlers[api_url_text]
                name = handler['name']
                txt_file = handler['txt_file']
                url_regex = handler['url_regex']

                self.log_signal.emit("=" * 40)
                self.log_signal.emit(f"🚀 {name} batch download mode detected.")
                
                txt_path = os.path.join(self.user_data_path, txt_file)
                self.log_signal.emit(f"   Looking for batch file at: {txt_path}")

                if not os.path.exists(txt_path):
                    QMessageBox.warning(self, "File Not Found", f"To use batch mode, create a file named '{txt_file}' in your 'appdata' folder.\n\nPlace one {name} URL on each line.")
                    self.log_signal.emit(f"   ❌ '{txt_file}' not found. Aborting batch download.")
                    return False

                urls_to_download = []
                try:
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            found_urls = re.findall(url_regex, line)
                            if found_urls:
                                urls_to_download.extend(found_urls)
                except Exception as e:
                    QMessageBox.critical(self, "File Error", f"Could not read '{txt_file}':\n{e}")
                    self.log_signal.emit(f"   ❌ Error reading '{txt_file}': {e}")
                    return False

                if not urls_to_download:
                    QMessageBox.information(self, "Empty File", f"No valid {name} URLs were found in '{txt_file}'.")
                    self.log_signal.emit(f"   '{txt_file}' was found but contained no valid URLs.")
                    return False
                
                self.log_signal.emit(f"   Found {len(urls_to_download)} URLs to process.")
                self.favorite_download_queue.clear()
             
                self_managed_folder_sites = [
                    'allporncomic.com', 'allcomic.com', 
                    'fap-nation.com', 'fap-nation.org', 
                    'toonily.com', 'toonily.me',
                    'hentai2read.com',
                    'saint2.su', 'saint2.pk', 'turbo.cr',
                    'imgur.com', 'bunkr.',
                    'hentaifox.com'
                ]

                for url in urls_to_download:
                    is_self_managed = any(site in url.lower() for site in self_managed_folder_sites)
                    
                    service_extracted, user_id_extracted, pid = extract_post_info(url)
                    
                    force_folder = False
                    folder_name_to_use = "Unknown_Batch_Item"
                    item_type = 'post'

                    if is_self_managed:
                        force_folder = False
                        folder_name_to_use = "Auto-Detected"
                        item_type = 'post'

                    elif service_extracted:
                        item_type = 'post' if pid else 'artist'
                        force_folder = True
                        
                        cache_key = (service_extracted.lower(), str(user_id_extracted))
                        creator_name = self.creator_name_cache.get(cache_key)
                        
                        if creator_name:
                            folder_name_to_use = clean_folder_name(creator_name)
                        else:
                            folder_name_to_use = f"{service_extracted}_{user_id_extracted}"
                    
                    else:
                        try:
                            path_parts = urlparse(url).path.strip('/').split('/')
                            folder_candidate = path_parts[-1] if path_parts else "Unknown_Item"
                            folder_name_to_use = clean_folder_name(folder_candidate)
                            force_folder = True
                        except Exception:
                            folder_name_to_use = "Unknown_Batch_Item"
                            force_folder = True

                    self.favorite_download_queue.append({
                        'url': url,
                        'name': f"{name} batch: {folder_name_to_use}",
                        'name_for_folder': folder_name_to_use,
                        'type': item_type,
                        'force_artist_folder': force_folder
                    })

                if not self.is_processing_favorites_queue:
                       self._process_next_favorite_download()
                return True

        if self.is_ready_to_download_fetched:
            self._start_download_of_fetched_posts()
            return True

        self.is_finishing = False
        if self.active_update_profile:
            if not self.new_posts_for_update:
                return self._check_for_updates()
            else:
                return self._start_confirmed_update_download()

        self.is_finishing = False
        self.downloaded_hash_counts.clear()

        if not is_restore and not is_continuation:

            if not self.is_running_job_queue:
                self.permanently_failed_files_for_dialog.clear()

            self.permanently_failed_files_for_dialog.clear()

        self.retryable_failed_files_info.clear()
        self._update_error_button_count()

        self._clear_stale_temp_files()
        self.session_temp_files = []
        self.temp_pdf_content_list = []

        processed_post_ids_for_restore = []
        manga_counters_for_restore = None
        start_offset_for_restore = 0

        if is_restore and self.interrupted_session_data:
            self.log_signal.emit("   Restoring session state...")
            download_state = self.interrupted_session_data.get("download_state", {})
            processed_post_ids_for_restore = download_state.get("processed_post_ids", [])
            start_offset_for_restore = download_state.get("last_processed_offset", 0)
            restored_hashes = download_state.get("successfully_downloaded_hashes", [])
            if restored_hashes:
                with self.downloaded_file_hashes_lock:
                    self.downloaded_file_hashes.update(restored_hashes)
                self.log_signal.emit(f"   Restored memory of {len(restored_hashes)} successfully downloaded files.")
            manga_counters_for_restore = download_state.get("manga_counters")
            if processed_post_ids_for_restore:
                self.log_signal.emit(f"   Will skip {len(processed_post_ids_for_restore)} already processed posts.")
            if start_offset_for_restore > 0:
                self.log_signal.emit(f"   Resuming fetch from page offset: {start_offset_for_restore}")
            if manga_counters_for_restore:
                self.log_signal.emit(f"   Restoring manga counters: {manga_counters_for_restore}")

        if self._is_download_active():
            QMessageBox.warning(self, "Busy", "A download is already in progress.")
            return False

        if not is_restore and not direct_api_url and self.favorite_download_queue and not self.is_processing_favorites_queue:
            self.log_signal.emit(f"ℹ️ Detected {len(self.favorite_download_queue)} item(s) in the queue. Starting processing...")
            self.cancellation_message_logged_this_session = False
            self._process_next_favorite_download()
            return True

        if not is_restore and self.interrupted_session_data:
            self.log_signal.emit("ℹ️ New download started. Discarding previous interrupted session.")
            self._clear_session_file()
            self.interrupted_session_data = None
            self.is_restore_pending = False

        api_url = direct_api_url if direct_api_url else self.link_input.text().strip()
        
        main_ui_download_dir = self.dir_input.text().strip()
        extract_links_only = (self.radio_only_links and self.radio_only_links.isChecked())
        effective_output_dir_for_run = ""

        if override_output_dir:
            if not main_ui_download_dir:
                QMessageBox.critical(self, "Configuration Error",
                                     "The main 'Download Location' must be set in the UI "
                                     "before downloading favorites with 'Artist Folders' scope.")
                if self.is_processing_favorites_queue:
                    self.log_signal.emit(f"❌ Favorite download for '{api_url}' skipped: Main download directory not set.")
                return False

            if not os.path.isdir(main_ui_download_dir):
                QMessageBox.critical(self, "Directory Error",
                                     f"The main 'Download Location' ('{main_ui_download_dir}') "
                                     "does not exist or is not a directory. Please set a valid one for 'Artist Folders' scope.")
                if self.is_processing_favorites_queue:
                    self.log_signal.emit(f"❌ Favorite download for '{api_url}' skipped: Main download directory invalid.")
                return False
            effective_output_dir_for_run = os.path.normpath(override_output_dir)
        else:
            if not extract_links_only and not main_ui_download_dir:
                QMessageBox.critical(self, "Input Error", "Download Directory is required.")
                return False

            if not extract_links_only and main_ui_download_dir and not os.path.isdir(main_ui_download_dir):
                reply = QMessageBox.question(self, "Create Directory?",
                                             f"The directory '{main_ui_download_dir}' does not exist.\nCreate it now?",
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    try:
                        os.makedirs(main_ui_download_dir, exist_ok=True)
                        self.log_signal.emit(f"ℹ️ Created directory: {main_ui_download_dir}")
                    except Exception as e:
                        QMessageBox.critical(self, "Directory Error", f"Could not create directory: {e}")
                        return False
                else:
                    self.log_signal.emit("❌ Download cancelled: Output directory does not exist and was not created.")
                    return False
            effective_output_dir_for_run = os.path.normpath(main_ui_download_dir) if main_ui_download_dir else ""

        self.last_effective_download_dir = effective_output_dir_for_run
        if not is_restore:
            self._create_initial_session_file(api_url, effective_output_dir_for_run, remaining_queue=self.favorite_download_queue)

        self.download_history_candidates.clear()
        self._update_button_states_and_connections()

        if self.favorite_mode_checkbox and self.favorite_mode_checkbox.isChecked() and not direct_api_url and not api_url:
            QMessageBox.information(self, "Favorite Mode Active",
                                    "Favorite Mode is active. Please use the 'Favorite Artists' or 'Favorite Posts' buttons to start downloads in this mode, or uncheck 'Favorite Mode' to use the URL input.")
            self.set_ui_enabled(True)
            return False

        if not api_url and not self.favorite_download_queue:
            QMessageBox.critical(self, "Input Error", "URL is required.")
            return False
        elif not api_url and self.favorite_download_queue:
            self.log_signal.emit("ℹ️ URL input is empty, but queue has items. Processing queue...")
            self.cancellation_message_logged_this_session = False
            self._process_next_favorite_download()
            return True

        self.cancellation_message_logged_this_session = False
        
        service, id1, id2 = extract_post_info(api_url)

        ui_settings = self._get_current_ui_settings_as_dict()
        proxies_to_use = ui_settings.get('proxies')

        specialized_thread = create_downloader_thread(
            main_app=self,
            api_url=api_url,
            service=service,
            id1=id1,
            id2=id2,
            effective_output_dir_for_run=effective_output_dir_for_run
        )

        if specialized_thread:
            if specialized_thread == "COOKIE_ERROR":
                cookie_dialog = CookieHelpDialog(self, offer_download_without_option=False)
                cookie_dialog.exec_()
                return False

            if specialized_thread == "FETCH_ERROR":
                QMessageBox.critical(self, "Error", "Could not retrieve gallery data for the provided URL.")
                return False

            self.set_ui_enabled(False)
            self.download_thread = specialized_thread
            
            if hasattr(self.download_thread, 'proxies'):
                self.download_thread.proxies = proxies_to_use
            
            if proxies_to_use and isinstance(proxies_to_use, dict) and 'http' in proxies_to_use:
                self.log_signal.emit(f"🌍 Proxy Enabled: Routing traffic through {proxies_to_use['http']}")

            self._connect_specialized_thread_signals(self.download_thread)
            self.download_thread.start()
            self._update_button_states_and_connections()
            return True

        user_id, post_id_from_url = id1, id2

        if direct_api_url and not post_id_from_url and item_type_from_queue and 'post' in item_type_from_queue:
            self.log_signal.emit(f"❌ CRITICAL ERROR: Could not parse post ID from the queued POST URL: {api_url}")
            self.log_signal.emit("   Skipping this item. This might be due to an unsupported URL format or a temporary issue.")
            self.download_finished(
                total_downloaded=0, 
                total_skipped=1, 
                cancelled_by_user=False, 
                kept_original_names_list=[]
            )
            return False

        self.save_creator_json_enabled_this_session = self.settings.value(SAVE_CREATOR_JSON_KEY, True, type=bool)
        self.is_single_post_session = bool(post_id_from_url) 

        if not self.is_single_post_session:
            self.save_creator_json_enabled_this_session = self.settings.value(SAVE_CREATOR_JSON_KEY, True, type=bool)

            creator_profile_data = {}
            if self.save_creator_json_enabled_this_session:
                creator_name_for_profile = None
                if self.is_processing_favorites_queue and self.current_processing_favorite_item_info:
                    creator_name_for_profile = self.current_processing_favorite_item_info.get('name_for_folder')
                else:
                    if service:
                        creator_key = (service.lower(), str(user_id))
                        creator_name_for_profile = self.creator_name_cache.get(creator_key)
                    else:
                        creator_name_for_profile = None

                if not creator_name_for_profile:
                    safe_service = service if service else "unknown"
                    safe_user = user_id if user_id else "unknown"
                    creator_name_for_profile = f"{safe_service}_{safe_user}"
                    self.log_signal.emit(f"⚠️ Creator name not in cache. Using '{creator_name_for_profile}' for profile file.")
                    
                creator_profile_data = self._setup_creator_profile(creator_name_for_profile, self.session_file_path)
            
                current_settings = self._get_current_ui_settings_as_dict(api_url_override=api_url, output_dir_override=effective_output_dir_for_run)
                creator_profile_data['settings'] = current_settings
            
                creator_profile_data.setdefault('creator_url', [])
                if api_url not in creator_profile_data['creator_url']:
                    creator_profile_data['creator_url'].append(api_url)

                if self.active_update_profile:
                    self.log_signal.emit("   Update session active: Loading existing processed post IDs to find new content.")
                    profile_processed_ids = set(creator_profile_data.get('processed_post_ids', []))
                
                elif not is_restore:
                    self.log_signal.emit("   Fresh download session: Clearing previous post history for this creator to re-download all.")
                    if 'processed_post_ids' in creator_profile_data:
                        creator_profile_data['processed_post_ids'] = []

                creator_profile_data.setdefault('processed_post_ids', [])
                self._save_creator_profile(creator_name_for_profile, creator_profile_data, self.session_file_path)
                self.log_signal.emit(f"✅ Profile for '{creator_name_for_profile}' loaded/created. Settings saved.")
        
        profile_processed_ids = set()

        session_processed_ids = set(processed_post_ids_for_restore)
        combined_processed_ids = session_processed_ids.union(profile_processed_ids)
        processed_post_ids_for_this_run = list(combined_processed_ids)

        use_subfolders = self.use_subfolders_checkbox.isChecked()
        use_post_subfolders = self.use_subfolder_per_post_checkbox.isChecked()
        compress_images = self.compress_images_checkbox.isChecked()
        download_thumbnails = self.download_thumbnails_checkbox.isChecked()

        use_multithreading_enabled_by_checkbox = self.use_multithreading_checkbox.isChecked()
        try:
            num_threads_from_gui = int(self.thread_count_input.text().strip())
            if num_threads_from_gui < 1: num_threads_from_gui = 1
        except ValueError:
            QMessageBox.critical(self, "Thread Count Error", "Invalid number of threads. Please enter a positive number.")
            return False

        if use_multithreading_enabled_by_checkbox:
            if num_threads_from_gui > MAX_THREADS:
                hard_warning_msg = (
                    f"You've entered a thread count ({num_threads_from_gui}) exceeding the maximum of {MAX_THREADS}.\n\n"
                    "Using an extremely high number of threads can lead to:\n"
                    "  - Diminishing returns (no significant speed increase).\n"
                    "  - Increased system instability or application crashes.\n"
                    "  - Higher chance of being rate-limited or temporarily IP-banned by the server.\n\n"
                    f"The thread count has been automatically capped to {MAX_THREADS} for stability."
                )
                QMessageBox.warning(self, "High Thread Count Warning", hard_warning_msg)
                num_threads_from_gui = MAX_THREADS
                self.thread_count_input.setText(str(MAX_THREADS))
                self.log_signal.emit(f"⚠️ User attempted {num_threads_from_gui} threads, capped to {MAX_THREADS}.")

        raw_skip_words_text = self.skip_words_input.text().strip()
        skip_words_parts = [part.strip() for part in raw_skip_words_text.split(',') if part.strip()]
        skip_words_list = []
        skip_file_size_mb = None
        size_pattern = re.compile(r'\[(\d+)\]')

        for part in skip_words_parts:
            match = size_pattern.fullmatch(part)
            if match:
                skip_file_size_mb = int(match.group(1))
                self.log_signal.emit(f"ℹ️ File size skip rule found: Will skip files smaller than {skip_file_size_mb} MB.")
            else:
                skip_words_list.append(part.lower())

        raw_remove_filename_words = self.remove_from_filename_input.text().strip() if hasattr(self, 'remove_from_filename_input') else ""
        allow_multipart = self.allow_multipart_download_setting
        remove_from_filename_words_list = [word.strip() for word in raw_remove_filename_words.split(',') if word.strip()]
        scan_content_for_images = self.scan_content_images_checkbox.isChecked() if hasattr(self, 'scan_content_images_checkbox') else False
        use_cookie_from_checkbox = self.use_cookie_checkbox.isChecked() if hasattr(self, 'use_cookie_checkbox') else False
        app_base_dir_for_cookies = os.path.dirname(self.config_file)
        cookie_text_from_input = self.cookie_text_input.text().strip() if hasattr(self, 'cookie_text_input') and use_cookie_from_checkbox else ""

        use_cookie_for_this_run = use_cookie_from_checkbox
        selected_cookie_file_path_for_backend = self.selected_cookie_filepath if use_cookie_from_checkbox and self.selected_cookie_filepath else None

        if use_cookie_from_checkbox and not direct_api_url:
            temp_cookies_for_check = prepare_cookies_for_request(
                use_cookie_for_this_run,
                cookie_text_from_input,
                selected_cookie_file_path_for_backend,
                app_base_dir_for_cookies,
                lambda msg: self.log_signal.emit(f"[UI Cookie Check] {msg}")
            )
            if temp_cookies_for_check is None:
                cookie_dialog = CookieHelpDialog(self, offer_download_without_option=True)
                dialog_exec_result = cookie_dialog.exec_()

                if cookie_dialog.user_choice == CookieHelpDialog.CHOICE_PROCEED_WITHOUT_COOKIES and dialog_exec_result == QDialog.Accepted:
                    self.log_signal.emit("ℹ️ User chose to download without cookies for this session.")
                    use_cookie_for_this_run = False
                elif cookie_dialog.user_choice == CookieHelpDialog.CHOICE_CANCEL_DOWNLOAD or dialog_exec_result == QDialog.Rejected:
                    self.log_signal.emit("❌ Download cancelled by user at cookie prompt.")
                    return False
                else:
                    self.log_signal.emit("⚠️ Cookie dialog closed or unexpected choice. Aborting download.")
                    return False

        current_skip_words_scope = self.get_skip_words_scope()
        manga_mode_is_checked = self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False

        backend_filter_mode = self.get_filter_mode()
        text_only_scope_for_run = self.more_filter_scope if backend_filter_mode == 'text_only' else None
        export_format_for_run = self.text_export_format if backend_filter_mode == 'text_only' else 'txt'
        checked_radio_button = self.radio_group.checkedButton()
        user_selected_filter_text = checked_radio_button.text() if checked_radio_button else "All"

        if selected_cookie_file_path_for_backend:
            cookie_text_from_input = ""

        if backend_filter_mode == 'archive':
            effective_skip_zip = False
        else:
            effective_skip_zip = self.skip_zip_checkbox.isChecked()
            if backend_filter_mode == 'audio':
                effective_skip_zip = self.skip_zip_checkbox.isChecked()

        creator_folder_ignore_words_for_run = None
        is_full_creator_download = not post_id_from_url

        if compress_images and Image is None:
            QMessageBox.warning(self, "Missing Dependency", "Pillow library (for image compression) not found. Compression will be disabled.")
            compress_images = False;
            self.compress_images_checkbox.setChecked(False)

        fetch_first_enabled = self.settings.value(FETCH_FIRST_KEY, False, type=bool)

        log_messages = ["=" * 40, f"🚀 Starting {'Link Extraction' if extract_links_only else ('Archive Download' if backend_filter_mode == 'archive' else 'Download')} @ {time.strftime('%Y-%m-%d %H:%M:%S')}", f"    URL: {api_url}"]

        current_mode_log_text = "Download"
        if extract_links_only: current_mode_log_text = "Link Extraction"
        elif backend_filter_mode == 'archive': current_mode_log_text = "Archive Download"
        elif backend_filter_mode == 'audio': current_mode_log_text = "Audio Download"

        current_char_filter_scope = self.get_char_filter_scope()
        manga_mode = manga_mode_is_checked

        manga_date_prefix_text = ""
        if manga_mode and (self.manga_filename_style == STYLE_DATE_BASED or self.manga_filename_style == STYLE_ORIGINAL_NAME) and hasattr(self, 'manga_date_prefix_input'):
            manga_date_prefix_text = self.manga_date_prefix_input.text().strip()
            if manga_date_prefix_text:
                log_messages.append(f"      ↳ Manga Date Prefix: '{manga_date_prefix_text}'")

        start_page_str, end_page_str = self.start_page_input.text().strip(), self.end_page_input.text().strip()
        start_page, end_page = None, None
        is_creator_feed = bool(not post_id_from_url)

        if is_creator_feed:
            try:
                if start_page_str: start_page = int(start_page_str)
                if end_page_str: end_page = int(end_page_str)

                if start_page is not None and start_page <= 0: raise ValueError("Start page must be positive.")
                if end_page is not None and end_page <= 0: raise ValueError("End page must be positive.")
                if start_page and end_page and start_page > end_page: raise ValueError("Start page cannot be greater than end page.")

            except ValueError as e:
                QMessageBox.critical(self, "Page Range Error", f"Invalid page range: {e}")
                return False
        self.external_link_queue.clear();
        self.extracted_links_cache = [];
        self._is_processing_external_link_queue = False;
        self._current_link_post_title = None

        raw_character_filters_text = self.character_input.text().strip()
        parsed_character_filter_objects, download_commands = self._parse_character_filters(raw_character_filters_text)
        handle_unknown_command = download_commands.get('handle_unknown', False)

        domain_override_command = download_commands.get('domain_override')

        actual_filters_to_use_for_run = []

        needs_folder_naming_validation = (use_subfolders or manga_mode) and not extract_links_only

        if parsed_character_filter_objects:
            actual_filters_to_use_for_run = parsed_character_filter_objects

            if not extract_links_only:
                self.log_signal.emit(f"ℹ️ Using character filters for matching: {', '.join(item['name'] for item in actual_filters_to_use_for_run)}")

                filter_objects_to_potentially_add_to_known_list = []
                for filter_item_obj in parsed_character_filter_objects:
                    item_primary_name = filter_item_obj["name"]
                    cleaned_name_test = clean_folder_name(item_primary_name)
                    if needs_folder_naming_validation and not cleaned_name_test:
                        QMessageBox.warning(self, "Invalid Filter Name for Folder", f"Filter name '{item_primary_name}' is invalid for a folder and will be skipped for Known.txt interaction.")
                        self.log_signal.emit(f"⚠️ Skipping invalid filter for Known.txt interaction: '{item_primary_name}'")
                        continue

                    an_alias_is_already_known = False
                    if any(kn_entry["name"].lower() == item_primary_name.lower() for kn_entry in KNOWN_NAMES):
                        an_alias_is_already_known = True
                    elif filter_item_obj["is_group"] and needs_folder_naming_validation:
                        for alias_in_filter_obj in filter_item_obj["aliases"]:
                            if any(kn_entry["name"].lower() == alias_in_filter_obj.lower() or alias_in_filter_obj.lower() in [a.lower() for a in kn_entry["aliases"]] for kn_entry in KNOWN_NAMES):
                                an_alias_is_already_known = True;
                                break

                    if an_alias_is_already_known and filter_item_obj["is_group"]:
                        self.log_signal.emit(f"ℹ️ An alias from group '{item_primary_name}' is already known. Group will not be prompted for Known.txt addition.")

                    should_prompt_to_add_to_known_list = (
                            needs_folder_naming_validation and not manga_mode and
                            not any(kn_entry["name"].lower() == item_primary_name.lower() for kn_entry in KNOWN_NAMES) and
                            not an_alias_is_already_known
                    )
                    if should_prompt_to_add_to_known_list:
                        if not any(obj_to_add["name"].lower() == item_primary_name.lower() for obj_to_add in filter_objects_to_potentially_add_to_known_list):
                            filter_objects_to_potentially_add_to_known_list.append(filter_item_obj)
                    elif manga_mode and needs_folder_naming_validation and item_primary_name.lower() not in {kn_entry["name"].lower() for kn_entry in KNOWN_NAMES} and not an_alias_is_already_known:
                        self.log_signal.emit(f"ℹ️ Renaming Mode: Using filter '{item_primary_name}' for this session without adding to Known Names.")

                if filter_objects_to_potentially_add_to_known_list:
                    confirm_dialog = ConfirmAddAllDialog(filter_objects_to_potentially_add_to_known_list, self, self)
                    dialog_result = confirm_dialog.exec_()

                    if dialog_result == CONFIRM_ADD_ALL_CANCEL_DOWNLOAD:
                        self.log_signal.emit("❌ Download cancelled by user at new name confirmation stage.")
                        return False
                    elif isinstance(dialog_result, list):
                        if dialog_result:
                            self.log_signal.emit(f"ℹ️ User chose to add {len(dialog_result)} new entry/entries to Known.txt.")
                            for filter_obj_to_add in dialog_result:
                                def add_filter_obj(obj_to_add):
                                    if obj_to_add.get("is_and_condition") and obj_to_add.get("components_are_distinct_for_known_txt"):
                                        self.log_signal.emit(f"    Processing AND group '{obj_to_add['name']}' to add its components individually.")
                                        for comp in obj_to_add["and_components"]:
                                            add_filter_obj(comp)
                                    elif obj_to_add.get("components_are_distinct_for_known_txt"):
                                        self.log_signal.emit(f"    Processing group '{obj_to_add['name']}' to add its components individually to Known.txt.")
                                        for alias_component in obj_to_add["aliases"]:
                                            self.add_new_character(
                                                name_to_add=alias_component,
                                                is_group_to_add=False,
                                                aliases_to_add=[alias_component],
                                                suppress_similarity_prompt=True
                                            )
                                    else:
                                        self.add_new_character(
                                            name_to_add=obj_to_add["name"],
                                            is_group_to_add=obj_to_add["is_group"],
                                            aliases_to_add=obj_to_add["aliases"],
                                            suppress_similarity_prompt=True
                                        )
                                add_filter_obj(filter_obj_to_add)
                        else:
                            self.log_signal.emit("ℹ️ User confirmed adding, but no names were selected in the dialog. No new names added to Known.txt.")
                    elif dialog_result == CONFIRM_ADD_ALL_SKIP_ADDING:
                        self.log_signal.emit("ℹ️ User chose not to add new names to Known.txt for this session.")
            else:
                self.log_signal.emit(f"ℹ️ Using character filters for link extraction: {', '.join(item['name'] for item in actual_filters_to_use_for_run)}")

        self.dynamic_character_filter_holder.set_filters(actual_filters_to_use_for_run)

        creator_folder_ignore_words_for_run = None
        character_filters_are_empty = not actual_filters_to_use_for_run
        if is_full_creator_download and character_filters_are_empty:
            creator_folder_ignore_words_for_run = CREATOR_DOWNLOAD_DEFAULT_FOLDER_IGNORE_WORDS
            log_messages.append(f"    Creator Download (No Char Filter): Applying default folder name ignore list ({len(creator_folder_ignore_words_for_run)} words).")

        custom_folder_name_cleaned = None
        if use_subfolders and post_id_from_url and self.custom_folder_widget and self.custom_folder_widget.isVisible() and not extract_links_only:
            raw_custom_name = self.custom_folder_input.text().strip()
            if raw_custom_name:
                cleaned_custom = clean_folder_name(raw_custom_name)
                if cleaned_custom:
                    custom_folder_name_cleaned = cleaned_custom
                else:
                    self.log_signal.emit(f"⚠️ Invalid custom folder name ignored: '{raw_custom_name}' (resulted in empty string after cleaning).")

        self.main_log_output.clear()
        if extract_links_only: self.main_log_output.append("🔗 Extracting Links...");
        elif backend_filter_mode == 'archive': self.main_log_output.append("Downloading Archives Only...")

        if self.external_log_output: self.external_log_output.clear()
        if self.show_external_links and not extract_links_only and backend_filter_mode != 'archive':
            self.external_log_output.append("🔗 External Links Found:")

        self.file_progress_label.setText("");
        self.cancellation_event.clear();
        self.active_futures = []
        self.total_posts_to_process = 0;
        self.processed_posts_count = 0;
        self.download_counter = 0;
        self.skip_counter = 0
        self.progress_label.setText(self._tr("progress_initializing_text", "Progress: Initializing..."))

        self.retryable_failed_files_info.clear()
        self._update_error_button_count()

        manga_date_file_counter_ref_for_thread = None
        if manga_mode and self.manga_filename_style == STYLE_DATE_BASED and not extract_links_only:
            start_val = 1
            if is_restore and manga_counters_for_restore:
                start_val = manga_counters_for_restore.get('date_based', 1)
            self.log_signal.emit(f"ℹ️ Manga Date Mode: Initializing shared file counter starting at {start_val}.")
            manga_date_file_counter_ref_for_thread = [start_val, threading.Lock()]

        manga_global_file_counter_ref_for_thread = None
        if manga_mode and self.manga_filename_style == STYLE_POST_TITLE_GLOBAL_NUMBERING and not extract_links_only:
            start_val = 1
            if is_restore and manga_counters_for_restore:
                start_val = manga_counters_for_restore.get('global_numbering', 1)
            self.log_signal.emit(f"ℹ️ Manga Title+GlobalNum Mode: Initializing shared file counter starting at {start_val}.")
            manga_global_file_counter_ref_for_thread = [start_val, threading.Lock()]

        effective_num_post_workers = 1
        effective_num_file_threads_per_worker = 1

        if post_id_from_url:
            if use_multithreading_enabled_by_checkbox:
                effective_num_file_threads_per_worker = max(1, min(num_threads_from_gui, MAX_FILE_THREADS_PER_POST_OR_WORKER))
        else:
            if manga_mode and self.manga_filename_style == STYLE_DATE_BASED:
                effective_num_post_workers = 1
            elif manga_mode and self.manga_filename_style == STYLE_POST_TITLE_GLOBAL_NUMBERING:
                effective_num_post_workers = 1
                effective_num_file_threads_per_worker = 1
            elif use_multithreading_enabled_by_checkbox:
                effective_num_post_workers = max(1, min(num_threads_from_gui, MAX_THREADS))
                effective_num_file_threads_per_worker = 1

        if not extract_links_only: log_messages.append(f"    Save Location: {effective_output_dir_for_run}")

        if post_id_from_url:
            log_messages.append(f"    Mode: Single Post")
            log_messages.append(f"      ↳ File Downloads: Up to {effective_num_file_threads_per_worker} concurrent file(s)")
        else:
            log_messages.append(f"    Mode: Creator Feed")
            log_messages.append(f"    Post Processing: {'Multi-threaded (' + str(effective_num_post_workers) + ' workers)' if effective_num_post_workers > 1 else 'Single-threaded (1 worker)'}")
            pr_log = "All"
            if start_page or end_page:
                pr_log = f"{f'From {start_page} ' if start_page else ''}{'to ' if start_page and end_page else ''}{f'{end_page}' if end_page else (f'Up to {end_page}' if end_page else (f'From {start_page}' if start_page else 'Specific Range'))}".strip()

            if manga_mode:
                log_messages.append(f"    Page Range: {pr_log if pr_log else 'All'} (Renaming Mode - Oldest Posts Processed First within range)")
            else:
                log_messages.append(f"    Page Range: {pr_log if pr_log else 'All'}")

        if not extract_links_only:
            log_messages.append(f"    Subfolders: {'Enabled' if use_subfolders else 'Disabled'}")
            if use_subfolders and self.use_subfolder_per_post_checkbox.isChecked():
                use_date_prefix = self.date_prefix_checkbox.isChecked() if hasattr(self, 'date_prefix_checkbox') else False
                log_messages.append(f"      ↳ Date Prefix for Post Subfolders: {'Enabled' if use_date_prefix else 'Disabled'}")
            if use_subfolders:
                if custom_folder_name_cleaned: log_messages.append(f"    Custom Folder (Post): '{custom_folder_name_cleaned}'")
            if actual_filters_to_use_for_run:
                log_messages.append(f"    Character Filters: {', '.join(item['name'] for item in actual_filters_to_use_for_run)}")
                log_messages.append(f"      ↳ Char Filter Scope: {current_char_filter_scope.capitalize()}")
            elif use_subfolders:
                log_messages.append(f"    Folder Naming: Automatic (based on title/known names)")

            keep_duplicates = self.keep_duplicates_checkbox.isChecked() if hasattr(self, 'keep_duplicates_checkbox') else False
            log_messages.extend([
                f"    File Type Filter: {user_selected_filter_text} (Backend processing as: {backend_filter_mode})",
                f"    Keep In-Post Duplicates: {'Enabled' if keep_duplicates else 'Disabled'}",
                f"    Skip Archives: {'.zip' if effective_skip_zip else ''}{', ' if effective_skip_zip else ''}{'None (Archive Mode)' if backend_filter_mode == 'archive' else ('None' if not (effective_skip_zip ) else '')}",
                f"    Skip Words Scope: {current_skip_words_scope.capitalize()}",
                f"    Remove Words from Filename: {', '.join(remove_from_filename_words_list) if remove_from_filename_words_list else 'None'}",
                f"    Compress Images: {'Enabled' if compress_images else 'Disabled'}",
                f"    Thumbnails Only: {'Enabled' if download_thumbnails else 'Disabled'}"
            ])
            log_messages.append(f"    Scan Post Content for Images: {'Enabled' if scan_content_for_images else 'Disabled'}")
        else:
            log_messages.append(f"    Mode: Extracting Links Only")

        log_messages.append(f"    Show External Links: {'Enabled' if self.show_external_links and not extract_links_only and backend_filter_mode != 'archive' else 'Disabled'}")

        if manga_mode:
            log_messages.append(f"    Renaming Mode: Enabled")
            
            style_display_names = {
                STYLE_POST_TITLE: "Post Title",
                STYLE_ORIGINAL_NAME: "Date + Original",
                STYLE_DATE_POST_TITLE: "Date + Title",
                STYLE_POST_TITLE_GLOBAL_NUMBERING: "Title + Global Numbering",
                STYLE_DATE_BASED: "Date Based",
                STYLE_POST_ID: "Post ID",
                STYLE_CUSTOM: f"Custom ({self.custom_manga_filename_format})"
            }
            style_text = style_display_names.get(self.manga_filename_style, "Unknown")
            log_messages.append(f"      ↳ Filename Style: {style_text}")

            if self.manga_filename_style == STYLE_CUSTOM and '{content}' in self.custom_manga_filename_format:
                log_messages.append(f"      ↳ ⚠️ WARNING: Custom renaming uses {{Description}}. Fetching post content requires an extra API request per post, significantly slowing down the download.")

            if actual_filters_to_use_for_run:
                log_messages.append(f"      ↳ Character Filter (for naming/folder): {', '.join(item['name'] for item in actual_filters_to_use_for_run)}")
            
            log_messages.append(f"      ↳ Filename Collisions: Will be handled with a numeric suffix (e.g., _1, _2).")

        log_messages.append(f"    Use Cookie ('cookies.txt'): {'Enabled' if use_cookie_from_checkbox else 'Disabled'}")
        if use_cookie_from_checkbox and cookie_text_from_input:
            log_messages.append(f"      ↳ Cookie Text Provided: Yes (length: {len(cookie_text_from_input)})")
        elif use_cookie_from_checkbox and selected_cookie_file_path_for_backend:
            log_messages.append(f"      ↳ Cookie File Selected: {os.path.basename(selected_cookie_file_path_for_backend)}")
        should_use_multithreading_for_posts = use_multithreading_enabled_by_checkbox and not post_id_from_url
        if manga_mode and (self.manga_filename_style == STYLE_DATE_BASED or self.manga_filename_style == STYLE_POST_TITLE_GLOBAL_NUMBERING) and not post_id_from_url:
            enforced_by_style = "Date Mode" if self.manga_filename_style == STYLE_DATE_BASED else "Title+GlobalNum Mode"
            should_use_multithreading_for_posts = False
            log_messages.append(f"    Threading: Single-threaded (posts) - Enforced by Manga {enforced_by_style} (Actual workers: {effective_num_post_workers if effective_num_post_workers > 1 else 1})")
        else:
            log_messages.append(f"    Threading: {'Multi-threaded (posts)' if should_use_multithreading_for_posts else 'Single-threaded (posts)'}")
        if should_use_multithreading_for_posts:
            log_messages.append(f"    Number of Post Worker Threads: {effective_num_post_workers}")
     
        proxy_enabled_log = self.settings.value(PROXY_ENABLED_KEY, False, type=bool)
        if proxy_enabled_log:
            p_host = self.settings.value(PROXY_HOST_KEY, "")
            p_port = self.settings.value(PROXY_PORT_KEY, "")
            log_messages.append(f"    🌍 Proxy Enabled: Routing traffic through {p_host}:{p_port}")
        else:
            log_messages.append(f"    Proxy: Disabled")

        if domain_override_command:
            self.log_signal.emit(f"ℹ️ Domain Override Active: Will probe for the correct 'n*' subdomain on the '.{domain_override_command}' domain for each file.")

        if domain_override_command:
            self.log_signal.emit(f"ℹ️ Domain override command found: Forcing download URLs to use '.{domain_override_command}'")
     
        log_messages.append("=" * 40)
        for msg in log_messages: self.log_signal.emit(msg)

        self.set_ui_enabled(False)

        current_proxies = self._get_current_ui_settings_as_dict().get('proxies')
        args_template = {
            'api_url_input': api_url,
            'download_root': effective_output_dir_for_run,
            'creator_name_cache': self.creator_name_cache, 
            'output_dir': effective_output_dir_for_run,
            'known_names': list(KNOWN_NAMES),
            'known_names_copy': list(KNOWN_NAMES),
            'filter_character_list': actual_filters_to_use_for_run,
            'archive_only_mode': download_commands.get('archive_only', False), 
            'domain_override': domain_override_command, 
            'filter_mode': backend_filter_mode,
            'text_only_scope': text_only_scope_for_run,
            'text_export_format': export_format_for_run,
            'single_pdf_mode': self.single_pdf_setting,
            'skip_zip': effective_skip_zip,
            'use_subfolders': use_subfolders,
            'use_post_subfolders': use_post_subfolders,
            'compress_images': compress_images,
            'download_thumbnails': download_thumbnails,
            'service': service,
            'user_id': user_id,
            'downloaded_files': self.downloaded_files,
            'downloaded_files_lock': self.downloaded_files_lock,
            'downloaded_file_hashes': self.downloaded_file_hashes,
            'downloaded_file_hashes_lock': self.downloaded_file_hashes_lock,
            'skip_words_list': skip_words_list,
            'skip_file_size_mb': skip_file_size_mb,
            'skip_words_scope': current_skip_words_scope,
            'remove_from_filename_words_list': remove_from_filename_words_list,
            'char_filter_scope': current_char_filter_scope,
            'show_external_links': self.show_external_links,
            'extract_links_only': extract_links_only,
            'start_page': start_page,
            'end_page': end_page,
            'target_post_id_from_initial_url': post_id_from_url,
            'custom_folder_name': custom_folder_name_cleaned,
            'manga_mode_active': manga_mode,
            'unwanted_keywords': FOLDER_NAME_STOP_WORDS,
            'cancellation_event': self.cancellation_event,
            'manga_date_prefix': manga_date_prefix_text,
            'dynamic_character_filter_holder': self.dynamic_character_filter_holder,
            'pause_event': self.pause_event,
            'scan_content_for_images': scan_content_for_images,
            'manga_filename_style': self.manga_filename_style,
            'num_file_threads_for_worker': effective_num_file_threads_per_worker,
            'manga_date_file_counter_ref': manga_date_file_counter_ref_for_thread,
            'allow_multipart_download': allow_multipart,
            'multipart_scope': self.multipart_scope,
            'multipart_parts_count': self.multipart_parts_count,
            'multipart_min_size_mb': self.multipart_min_size_mb,
            'cookie_text': cookie_text_from_input,
            'selected_cookie_file': selected_cookie_file_path_for_backend,
            'manga_global_file_counter_ref': manga_global_file_counter_ref_for_thread,
            'app_base_dir': app_base_dir_for_cookies,
            'project_root_dir': self.app_base_dir,
            'use_cookie': use_cookie_for_this_run,
            'session_file_path': self.session_file_path,
            'session_lock': self.session_lock,
            'creator_download_folder_ignore_words': creator_folder_ignore_words_for_run,
            'use_date_prefix_for_subfolder': self.date_prefix_checkbox.isChecked() if hasattr(self, 'date_prefix_checkbox') else False,
            'date_prefix_format': self.date_prefix_format,            
            'keep_in_post_duplicates': self.keep_duplicates_checkbox.isChecked(),
            'keep_duplicates_mode': self.keep_duplicates_mode,
            'keep_duplicates_limit': self.keep_duplicates_limit,
            'manga_custom_filename_format': self.custom_manga_filename_format, 
            'manga_custom_date_format': self.manga_custom_date_format,
            'manga_custom_suffix_format': self.custom_manga_suffix_format,
    
            'downloaded_hash_counts': self.downloaded_hash_counts,
            'downloaded_hash_counts_lock': self.downloaded_hash_counts_lock,
            'skip_current_file_flag': None,
            'processed_post_ids': processed_post_ids_for_this_run,
            'start_offset': start_offset_for_restore, 
            'fetch_first': fetch_first_enabled, 
            'sfp_threshold': download_commands.get('sfp_threshold'),
            'handle_unknown_mode': handle_unknown_command,
            'add_info_in_pdf': self.add_info_in_pdf_setting,     
            'proxies': current_proxies,  
            'download_revisions': self.revisions_checkbox.isChecked() if hasattr(self, 'revisions_checkbox') else False,                
            'visual_sort_active': getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked(),
            'user_data_path': getattr(self, 'user_data_path', "")
        }

        args_template['override_output_dir'] = override_output_dir

        fetch_first_enabled = self.settings.value(FETCH_FIRST_KEY, False, type=bool)
        self.last_start_download_args = args_template.copy()

        if fetch_first_enabled and not post_id_from_url:
            self.log_signal.emit("=" * 40)
            self.log_signal.emit("🚀 'Fetch First' mode is active. Starting Stage 1: Fetching all post data.")
            self.log_signal.emit("   💡 If you are using a VPN for this stage, ensure it is connected now.")
            self.is_fetching_only = True
            self.set_ui_enabled(False)
            self._update_button_states_and_connections()
            self.progress_label.setText("Progress: Fetching pages...")
            
            fetch_thread_args = {
                'api_url_input': api_url, 'logger': self.log_signal.emit,
                'start_page': start_page, 'end_page': end_page,
                'manga_mode': manga_mode, 'cancellation_event': self.cancellation_event,
                'pause_event': self.pause_event, 'use_cookie': use_cookie_for_this_run,
                'cookie_text': cookie_text_from_input, 'selected_cookie_file': selected_cookie_file_path_for_backend,
                'app_base_dir': app_base_dir_for_cookies,
                'manga_filename_style_for_sort_check': self.manga_filename_style,
                'processed_post_ids': processed_post_ids_for_this_run,
                'fetch_all_first': True,
                'proxies': self._get_current_ui_settings_as_dict().get('proxies')
            }
            
            self.download_thread = threading.Thread(target=self._run_fetch_only_thread, args=(fetch_thread_args,), daemon=True)
            self.download_thread.start()
            return True

        try:
            if should_use_multithreading_for_posts:
                self.log_signal.emit(f"    Initializing multi-threaded {current_mode_log_text.lower()} with {effective_num_post_workers} post workers...")
                args_template['emitter'] = self.worker_to_gui_queue
                self.start_multi_threaded_download(num_post_workers=effective_num_post_workers, **args_template)
            else:
                self.log_signal.emit(f"    Initializing single-threaded {'link extraction' if extract_links_only else 'download'}...")
                dt_expected_keys = [
                    'api_url_input', 'output_dir', 'known_names_copy', 'cancellation_event',
                    'filter_character_list', 'filter_mode', 'skip_zip',
                    'use_subfolders', 'use_post_subfolders', 'custom_folder_name',
                    'compress_images', 'download_thumbnails', 'service', 'user_id',
                    'downloaded_files', 'downloaded_file_hashes', 'pause_event', 'remove_from_filename_words_list',
                    'downloaded_files_lock', 'downloaded_file_hashes_lock', 'dynamic_character_filter_holder', 'session_file_path',
                    'session_lock', 'start_offset', 
                    'skip_words_list', 'skip_words_scope', 'char_filter_scope',
                    'show_external_links', 'extract_links_only', 'num_file_threads_for_worker',
                    'start_page', 'end_page', 'target_post_id_from_initial_url',
                    'manga_date_file_counter_ref',
                    'manga_global_file_counter_ref', 'manga_date_prefix',
                    'manga_mode_active', 'unwanted_keywords', 'manga_filename_style', 'scan_content_for_images',
                    'allow_multipart_download', 'use_cookie', 'cookie_text', 'app_base_dir', 'selected_cookie_file', 'override_output_dir', 'project_root_dir',
                    'text_only_scope', 'text_export_format', 'date_prefix_format',
                    'single_pdf_mode','multipart_parts_count', 'multipart_min_size_mb', 
                    'use_date_prefix_for_subfolder','keep_in_post_duplicates', 'keep_duplicates_mode',
                    'keep_duplicates_limit', 'downloaded_hash_counts', 'downloaded_hash_counts_lock',
                    'processed_post_ids', 'domain_override',
                    'archive_only_mode', 'skip_file_size_mb', 
                    'manga_custom_filename_format','manga_custom_date_format', 'manga_custom_suffix_format', 'sfp_threshold', 'download_revisions', 'creator_name_cache',
                    'proxies', 'visual_sort_active', 'user_data_path', 'add_info_in_pdf'

                ]
                args_template['skip_current_file_flag'] = None
                single_thread_args = {key: args_template[key] for key in dt_expected_keys if key in args_template}
                single_thread_args['fetch_first'] = args_template.get('fetch_first', False)
                self.start_single_threaded_download(**single_thread_args)
        except Exception as e:
            self._update_button_states_and_connections()
            self.log_signal.emit(f"❌ CRITICAL ERROR preparing download: {e}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Start Error", f"Failed to start process:\n{e}")
            self.download_finished(0, 0, False, [])
            if self.pause_event: self.pause_event.clear()
            self.is_paused = False
        return True
  
    def restore_download(self):
        """Initiates the download restoration process."""
        if self._is_download_active():
            QMessageBox.warning(self, "Busy", "A download is already in progress.")
            return

        if not self.interrupted_session_data:
            self.log_signal.emit("❌ No session data to restore.")
            self._clear_session_and_reset_ui()
            return

        remaining_queue_from_session = self.interrupted_session_data.get("remaining_queue", [])
        if remaining_queue_from_session:
            self.favorite_download_queue.clear()
            self.favorite_download_queue.extend(remaining_queue_from_session)
            self.is_processing_favorites_queue = True
            self.log_signal.emit(f"ℹ️ Restored {len(self.favorite_download_queue)} item(s) to the download queue. Processing will continue automatically.")

        self.log_signal.emit("🔄 Preparing to restore download session...")

        settings = self.interrupted_session_data.get("ui_settings", {})
        restore_url = settings.get("api_url")
        restore_dir = settings.get("output_dir")

        if not restore_url:
            QMessageBox.critical(self, "Restore Error", "Session file is corrupt. Cannot restore because the URL is missing.")
            self._clear_session_and_reset_ui()
            return

        self.is_restore_pending = True
        self.start_download(direct_api_url=restore_url, override_output_dir=restore_dir, is_restore=True)

    def _update_ui_for_url_change(self, text=""):
        """A single, authoritative function to update all UI states based on the URL."""
        url_text = self.link_input.text().strip()
        service, _, _ = extract_post_info(url_text)

        widgets_to_manage = [
            self.page_range_label, self.start_page_input, self.to_label, self.end_page_input,
            self.character_filter_widget, self.skip_words_input, self.skip_scope_toggle_button,
            self.remove_from_filename_input, self.radio_all, self.radio_images, self.radio_videos,
            self.radio_only_archives, self.radio_only_links, self.radio_only_audio, self.radio_more,
            self.skip_zip_checkbox, self.download_thumbnails_checkbox, self.compress_images_checkbox,
            self.use_subfolders_checkbox, self.use_subfolder_per_post_checkbox,
            self.scan_content_images_checkbox, self.external_links_checkbox, self.manga_mode_checkbox,
            self.use_cookie_checkbox, self.keep_duplicates_checkbox, self.date_prefix_checkbox,
            self.manga_rename_toggle_button, self.manga_date_prefix_input,
            self.multipart_toggle_button, self.custom_folder_input, self.custom_folder_label
        ]

        if service in ['bunkr', 'nhentai']:
            self.progress_log_label.setText(f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Progress Log:")
            self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))
            
            for widget in widgets_to_manage:
                if widget:
                    widget.setEnabled(False)

            if self.radio_all:
                self.radio_all.setChecked(True)

            if hasattr(self, 'discord_scope_toggle_button'):
                self.discord_scope_toggle_button.setVisible(False)
            if hasattr(self, 'save_discord_as_pdf_btn'):
                self.save_discord_as_pdf_btn.setVisible(False)
            
            return

        
        for widget in widgets_to_manage:
            if widget:
                widget.setEnabled(True)

        is_discord = (service == 'discord')
        if hasattr(self, 'discord_scope_toggle_button'):
            self.discord_scope_toggle_button.setVisible(is_discord)
        if hasattr(self, 'save_discord_as_pdf_btn'):
            self.save_discord_as_pdf_btn.setVisible(is_discord)
        if hasattr(self, 'discord_message_limit_input'):
            self.discord_message_limit_input.setVisible(is_discord)
        if is_discord:
            self._update_discord_scope_button_text()
        else:
            self.download_btn.setText(self._tr("start_download_button_text", "Start Download"))
            self.download_btn.setIcon(QIcon(get_asset_path("assets/Svg/download.svg")))

        is_manga_checked = self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False
        is_subfolder_checked = self.use_subfolders_checkbox.isChecked() if self.use_subfolders_checkbox else False
        is_cookie_checked = self.use_cookie_checkbox.isChecked() if self.use_cookie_checkbox else False
        
        self.update_ui_for_manga_mode(is_manga_checked)
        self.update_custom_folder_visibility()
        self.update_page_range_enabled_state()
        if self.radio_group and self.radio_group.checkedButton():
            self._handle_filter_mode_change(self.radio_group.checkedButton(), True)
        if hasattr(self, 'use_subfolders_checkbox'):
            self.update_ui_for_subfolders(self.use_subfolders_checkbox.isChecked())
        else:
            self.update_ui_for_subfolders(False)
        is_fav_mode_active = self.favorite_mode_checkbox.isChecked() if self.favorite_mode_checkbox else False
        self._handle_favorite_mode_toggle(is_fav_mode_active)
        
        self._enforce_visual_sort_pipeline_rules()

    def start_single_threaded_download (self ,**kwargs ):
        global BackendDownloadThread 
        try :
            self .download_thread =BackendDownloadThread (**kwargs )
            if self .pause_event :self .pause_event .clear ()
            self .is_paused =False 
            if hasattr (self .download_thread ,'progress_signal'):self .download_thread .progress_signal .connect (self .handle_main_log )
            if hasattr (self .download_thread ,'add_character_prompt_signal'):self .download_thread .add_character_prompt_signal .connect (self .add_character_prompt_signal )
            if hasattr (self .download_thread ,'finished_signal'):self .download_thread .finished_signal .connect (self .download_finished )
            if hasattr (self .download_thread ,'receive_add_character_result'):self .character_prompt_response_signal .connect (self .download_thread .receive_add_character_result )
            if hasattr (self .download_thread ,'external_link_signal'):self .download_thread .external_link_signal .connect (self .handle_external_link_signal )
            if hasattr (self .download_thread ,'file_progress_signal'):self .download_thread .file_progress_signal .connect (self .update_file_progress_display )
            if hasattr (self .download_thread ,'missed_character_post_signal'):
                self .download_thread .missed_character_post_signal .connect (self .handle_missed_character_post )
            if hasattr(self.download_thread, 'overall_progress_signal'): self.download_thread.overall_progress_signal.connect(self.update_progress_display)           
            if hasattr (self .download_thread ,'retryable_file_failed_signal'):

                if hasattr (self .download_thread ,'file_successfully_downloaded_signal'):
                    self .download_thread .file_successfully_downloaded_signal .connect (self ._handle_actual_file_downloaded )
                if hasattr (self .download_thread ,'post_processed_for_history_signal'):
                    self .download_thread .post_processed_for_history_signal .connect (self ._add_to_history_candidates )
                self .download_thread .retryable_file_failed_signal .connect (self ._handle_retryable_file_failure )
                if hasattr (self .download_thread ,'permanent_file_failed_signal'):
                    self .download_thread .permanent_file_failed_signal .connect (self ._handle_permanent_file_failure_from_thread )
            self .download_thread .start ()
            self .log_signal .emit ("✅ Single download thread (for posts) started.")
            self._update_button_states_and_connections()
        except Exception as e :
            self .log_signal .emit (f"❌ CRITICAL ERROR starting single-thread: {e }\n{traceback .format_exc ()}")
            QMessageBox .critical (self ,"Thread Start Error",f"Failed to start download process: {e }")
            if self .pause_event :self .pause_event .clear ()
            self .is_paused =False 

    def _show_error_files_dialog (self ):
        """Shows the dialog with files that were skipped due to errors."""
        dialog = ErrorFilesDialog(self.permanently_failed_files_for_dialog, self, self)
        dialog.retry_selected_signal.connect(self._handle_retry_from_error_dialog)
        dialog.exec_()
        
    def _handle_retry_from_error_dialog (self ,selected_files_to_retry ):
        self ._start_failed_files_retry_session (files_to_retry_list =selected_files_to_retry )
        self._update_error_button_count()

    def _handle_retryable_file_failure (self ,list_of_retry_details ):
        """Appends details of files that failed but might be retryable later."""
        if list_of_retry_details :
            self .retryable_failed_files_info .extend (list_of_retry_details )

    def _handle_permanent_file_failure_from_thread (self ,list_of_permanent_failure_details ):
        """Handles permanently failed files signaled by the single BackendDownloadThread."""
        if list_of_permanent_failure_details :
            self .permanently_failed_files_for_dialog .extend (list_of_permanent_failure_details )
            self .log_signal .emit (f"ℹ️ {len (list_of_permanent_failure_details )} file(s) from single-thread download marked as permanently failed for this session.")
            self._update_error_button_count()

    def _start_batch_update_check(self, profiles_list):
        """
        Disables the UI and spawns a background thread to check multiple saved 
        Creator Profiles for new posts simultaneously.
        """
        self.set_ui_enabled(False)
        self.progress_label.setText(self._tr("batch_update_checking", "Checking for updates..."))
        self.cancellation_event.clear()
        
        self.download_thread = threading.Thread(
            target=self._run_batch_update_check_thread,
            args=(profiles_list,),
            daemon=True
        )
        self.download_thread.start()
        self._update_button_states_and_connections()

    def _run_batch_update_check_thread(self, profiles_list):
        """
        Runs in the background. Pings the API for each creator in the profiles list, 
        compares the API posts against the saved 'processed_post_ids', and compiles a list of new content.
        """
        master_new_post_list = []
        total_profiles = len(profiles_list)
        
        for i, profile in enumerate(profiles_list):
            if self.cancellation_event.is_set():
                break
            
            profile_name = profile.get('name', 'Unknown')
            self.log_signal.emit(f"Checking {profile_name} ({i+1}/{total_profiles})...")
            
            try:
                profile_data = profile.get('data', {})
                url = profile_data.get('creator_url', [])[0]
                processed_ids = set(profile_data.get('processed_post_ids', []))
                creator_settings = profile_data.get('settings', {})
                
                use_cookie = self.use_cookie_checkbox.isChecked()
                cookie_text = self.cookie_text_input.text()
                cookie_file = self.selected_cookie_filepath
                
                post_generator = download_from_api(
                    api_url_input=url,
                    logger=lambda msg: None,
                    cancellation_event=self.cancellation_event,
                    pause_event=self.pause_event,
                    use_cookie=use_cookie,
                    cookie_text=cookie_text,
                    selected_cookie_file=cookie_file,
                    app_base_dir=self.app_base_dir,
                    processed_post_ids=processed_ids,
                    end_page=5
                )
                
                for post_batch in post_generator:
                    if self.cancellation_event.is_set(): break
                    for post_data in post_batch:
                        master_new_post_list.append({
                            'post_data': post_data,
                            'profile_data': profile_data,
                            'creator_name': profile_name
                        })

            except Exception as e:
                self.log_signal.emit(f"❌ Error checking {profile_name}: {e}")
        
        self.batch_update_check_complete_signal.emit(master_new_post_list)

    def _batch_update_check_finished(self, all_new_posts_list):
        """
        Runs when the batch checker thread finishes. Re-enables the UI and updates 
        the Start Download button to show exactly how many new posts were found across all creators.
        """
        self.download_thread = None
        
        if self.cancellation_event.is_set():
            self.log_signal.emit("ℹ️ Update check was cancelled.")
            self.reset_application_state()
            return

        if not all_new_posts_list:
            self.log_signal.emit("✅ All selected creators are up to date! No new posts found.")
            QMessageBox.information(self, "Up to Date", "No new posts were found for the selected creators.")
            self.reset_application_state()
            return
            
        total_posts = len(all_new_posts_list)
        
        creators_with_new_posts = sorted(list(set(p['creator_name'] for p in all_new_posts_list)))
        total_creators = len(creators_with_new_posts)
        
        self.log_signal.emit("=" * 40)
        
        if creators_with_new_posts:
            self.log_signal.emit(f"Creators With New Posts - {', '.join(creators_with_new_posts)}")
        
        self.log_signal.emit(f"✅ Update check complete. Found {total_posts} new post(s) across {total_creators} creator(s).")
        
        self.log_signal.emit("   Click 'Start Download' to begin.")
        
        self.fetched_posts_for_batch_update = all_new_posts_list
        self.is_ready_to_download_batch_update = True
        
        self.progress_label.setText(f"Found {total_posts} new posts. Ready to download.")
        self.set_ui_enabled(True)
        
        if getattr(self, 'update_settings_read_only_mode', False):
            self._set_inputs_read_only(True)
            
        self._update_button_states_and_connections()

    def _show_update_check_dialog(self):
        """
        Opens the UI menu for selecting which creator profiles to scan for updates.
        """
        if self.is_restore_pending:
            QMessageBox.warning(self, "Restore Pending", "Please restore or discard the previous session first.")
            return

        dialog = UpdateCheckDialog(self.user_data_path, self, self)
        
        if dialog.exec_() == QDialog.Accepted:
            profiles = dialog.get_selected_profiles()
            if not profiles: return

            self.active_update_profiles_list = profiles
            
            
            if dialog.should_load_into_ui():
                first_profile_settings = profiles[0]['data'].get('settings', {})
                self._load_ui_from_settings_dict(first_profile_settings)
                
                if dialog.should_enable_editing():
                    self.update_settings_read_only_mode = False
                    self.override_update_profile_settings = True
                    self.log_signal.emit("ℹ️ Settings loaded in EDITABLE mode.")
                else:
                    self.update_settings_read_only_mode = True
                    self.override_update_profile_settings = False
                    self.log_signal.emit("ℹ️ Settings loaded in READ-ONLY mode.")
            else:
                self.update_settings_read_only_mode = False
                self.override_update_profile_settings = False


            self._start_batch_update_check(self.active_update_profiles_list)

    def _start_download_of_batch_update(self):
        """
        (GUI THREAD)
        Initiates the download of the posts found during the batch update check.
        
        --- THIS IS THE CORRECTED ROBUST VERSION ---
        """
        self.is_ready_to_download_batch_update = False
        self.log_signal.emit("=" * 40)
        self.log_signal.emit(f"🚀 Starting batch download for {len(self.fetched_posts_for_batch_update)} new post(s)...")

        if self.main_log_output: self.main_log_output.clear()
        if self.external_log_output: self.external_log_output.clear()
        if self.missed_character_log_output: self.missed_character_log_output.clear()
        self.missed_key_terms_buffer.clear()
        self.already_logged_bold_key_terms.clear()

        self.set_ui_enabled(False)

        num_threads = int(self.thread_count_input.text()) if self.use_multithreading_checkbox.isChecked() else 1
        self.thread_pool = ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix='PostWorker_')

        self.total_posts_to_process = len(self.fetched_posts_for_batch_update)
        self.processed_posts_count = 0
        self.overall_progress_signal.emit(self.total_posts_to_process, 0)
        
        ppw_expected_keys = list(PostProcessorWorker.__init__.__code__.co_varnames)[1:]
        
        current_proxies = self._get_current_ui_settings_as_dict().get('proxies')        
        live_runtime_args = {
            'emitter': self.worker_to_gui_queue,
            'creator_name_cache': self.creator_name_cache,
            'known_names': list(KNOWN_NAMES),
            'unwanted_keywords': FOLDER_NAME_STOP_WORDS,
            'pause_event': self.pause_event,
            'cancellation_event': self.cancellation_event,
            'downloaded_files': self.downloaded_files,
            'downloaded_files_lock': self.downloaded_files_lock,
            'downloaded_file_hashes': self.downloaded_file_hashes,
            'downloaded_file_hashes_lock': self.downloaded_file_hashes_lock,
            'dynamic_character_filter_holder': self.dynamic_character_filter_holder,
            'num_file_threads': 1,
            'manga_date_file_counter_ref': None,
            'manga_global_file_counter_ref': None,
            'creator_download_folder_ignore_words': CREATOR_DOWNLOAD_DEFAULT_FOLDER_IGNORE_WORDS,
            'downloaded_hash_counts': self.downloaded_hash_counts,
            'downloaded_hash_counts_lock': self.downloaded_hash_counts_lock,
            'skip_current_file_flag': None,
            'session_file_path': self.session_file_path,
            'session_lock': self.session_lock,
            'project_root_dir': self.app_base_dir,
            'app_base_dir': self.app_base_dir,
            'start_offset': 0,
            'fetch_first': False,
            'use_cookie': self.use_cookie_checkbox.isChecked(),
            'cookie_text': self.cookie_text_input.text(),
            'selected_cookie_file': self.selected_cookie_filepath,
            'add_info_in_pdf': self.add_info_in_pdf_setting,       
            'proxies': current_proxies,    
            'download_revisions': self.revisions_checkbox.isChecked() if hasattr(self, 'revisions_checkbox') else False,           
            'visual_sort_active': getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked(),
            'user_data_path': getattr(self, 'user_data_path', "")
        }

        default_profile_settings = {
            'output_dir': self.dir_input.text().strip(),
            'api_url': '',
            'character_filter_text': '',
            'skip_words_text': '',
            'remove_words_text': '',
            'custom_folder_name': None,
            'filter_mode': 'all',
            'text_only_scope': None,
            'text_export_format': 'txt',
            'single_pdf_mode': False,
            'skip_zip': False,
            'use_subfolders': False,
            'use_post_subfolders': False,
            'compress_images': False,
            'download_thumbnails': False,
            'skip_words_scope': SKIP_SCOPE_FILES,
            'char_filter_scope': CHAR_SCOPE_FILES,
            'show_external_links': False,
            'extract_links_only': False,
            'manga_mode_active': False,
            'manga_filename_style': STYLE_POST_TITLE,
            'allow_multipart_download': False,
            'manga_date_prefix': '',
            'scan_content_for_images': False,
            'use_date_prefix_for_subfolder': False,
            'date_prefix_format': "YYYY-MM-DD {post}",
            'keep_in_post_duplicates': False,
            'keep_duplicates_mode': DUPLICATE_HANDLING_HASH,
            'keep_duplicates_limit': 0,
            'multipart_scope': 'both',
            'multipart_parts_count': 4,
            'multipart_min_size_mb': 100,
            'manga_custom_filename_format': "{published} {title}",
            'manga_custom_date_format': "YYYY-MM-DD",
            'target_post_id_from_initial_url': None,
            'override_output_dir': None,
            'processed_post_ids': [],
            'add_info_in_pdf': False,
            'visual_sort_active': False,
            'user_data_path': getattr(self, 'user_data_path', "")
        }

        for item in self.fetched_posts_for_batch_update:
            post_data = item['post_data']
            
            full_profile_data = item.get('profile_data', {})
            saved_settings = full_profile_data.get('settings', {})
            args_for_this_worker = default_profile_settings.copy()
            
            if getattr(self, 'override_update_profile_settings', False):
                current_ui_settings = self._get_current_ui_settings_as_dict(
                    api_url_override=saved_settings.get('api_url')
                )
                args_for_this_worker.update(current_ui_settings)
                
                full_profile_data['settings'] = current_ui_settings
                
                creator_name = item.get('creator_name')
                if creator_name:
                    self._save_creator_profile(creator_name, full_profile_data, self.session_file_path)
                    
            else:
                args_for_this_worker.update(saved_settings)
            
            args_for_this_worker.update(live_runtime_args)
            
            args_for_this_worker['service'] = post_data.get('service')
            args_for_this_worker['user_id'] = post_data.get('user')
            
            args_for_this_worker['download_root'] = args_for_this_worker.get('output_dir')
            
            raw_filters = args_for_this_worker.get('character_filter_text', '')
            parsed_filters, commands = self._parse_character_filters(raw_filters)
            args_for_this_worker['filter_character_list'] = parsed_filters
            args_for_this_worker['domain_override'] = commands.get('domain_override')
            args_for_this_worker['archive_only_mode'] = commands.get('archive_only', False)
            args_for_this_worker['sfp_threshold'] = commands.get('sfp_threshold')
            args_for_this_worker['handle_unknown_mode'] = commands.get('handle_unknown', False)
            
            skip_words_parts = [part.strip() for part in args_for_this_worker.get('skip_words_text', '').split(',') if part.strip()]
            args_for_this_worker['skip_file_size_mb'] = None
            args_for_this_worker['skip_words_list'] = []
            size_pattern = re.compile(r'\[(\d+)\]')
            for part in skip_words_parts:
                match = size_pattern.fullmatch(part)
                if match:
                    args_for_this_worker['skip_file_size_mb'] = int(match.group(1))
                else:
                    args_for_this_worker['skip_words_list'].append(part.lower())

            raw_remove_words = args_for_this_worker.get('remove_words_text', '')
            args_for_this_worker['remove_from_filename_words_list'] = [word.strip() for word in raw_remove_words.split(',') if word.strip()]

            args_for_this_worker['processed_post_ids'] = list(full_profile_data.get('processed_post_ids', []))

            args_for_this_worker['api_url_input'] = args_for_this_worker.get('api_url', '')

            self._submit_post_to_worker_pool(
                post_data, 
                args_for_this_worker, 
                1,
                self.worker_to_gui_queue, 
                ppw_expected_keys, 
                {}
            )

        self.fetched_posts_for_batch_update = []
        self.is_fetcher_thread_running = False
        self._check_if_all_work_is_done()

    def _submit_post_to_worker_pool (self ,post_data_item ,worker_args_template ,num_file_dl_threads_for_each_worker ,emitter_for_worker ,ppw_expected_keys ,ppw_optional_keys_with_defaults ):
        """Helper to prepare and submit a single post processing task to the thread pool."""
        global PostProcessorWorker 
        if not isinstance (post_data_item ,dict ):
            self .log_signal .emit (f"⚠️ Skipping invalid post data item (not a dict): {type (post_data_item )}");
            return False 

        worker_init_args ={}
        missing_keys =[]
        for key in ppw_expected_keys :
            if key =='post_data':worker_init_args [key ]=post_data_item 
            elif key =='num_file_threads':worker_init_args [key ]=num_file_dl_threads_for_each_worker 
            elif key =='emitter':worker_init_args [key ]=emitter_for_worker 
            elif key in worker_args_template :worker_init_args [key ]=worker_args_template [key ]
            elif key in ppw_optional_keys_with_defaults :pass 
            else :missing_keys .append (key )

        if missing_keys :
            self .log_signal .emit (f"❌ CRITICAL ERROR: Missing keys for PostProcessorWorker: {', '.join (missing_keys )}");
            self .cancellation_event .set ()
            return False 

        if 'output_dir' in worker_init_args:
            worker_init_args['download_root'] = worker_init_args.pop('output_dir')
        if 'initial_target_post_id' in worker_init_args:
            worker_init_args['target_post_id_from_initial_url'] = worker_init_args.pop('initial_target_post_id')
        if 'filter_character_list_objects_initial' in worker_init_args:
            worker_init_args['filter_character_list'] = worker_init_args.pop('filter_character_list_objects_initial')

        try :
            worker_instance =PostProcessorWorker (**worker_init_args )
            if self .thread_pool :
                future =self .thread_pool .submit (worker_instance .process )
                self .active_futures .append (future )
                return True 
            else :
                self .log_signal .emit ("⚠️ Thread pool not available. Cannot submit task.");
                self .cancellation_event .set ()
                return False 
        except TypeError as te :
            self .log_signal .emit (f"❌ TypeError creating PostProcessorWorker: {te }\n    Passed Args: [{', '.join (sorted (worker_init_args .keys ()))}]\n{traceback .format_exc (limit =5 )}")
            self .cancellation_event .set ()
            return False 
        except RuntimeError :
            self .log_signal .emit (f"⚠️ RuntimeError submitting task (pool likely shutting down).")
            self .cancellation_event .set ()
            return False 
        except Exception as e :
            self .log_signal .emit (f"❌ Error submitting post {post_data_item .get ('id','N/A')} to worker: {e }")
            self .cancellation_event .set ()
            return False

    def _load_ui_from_settings_dict(self, settings: dict):
        """Populates the UI with values from a settings dictionary."""
        self._is_loading_settings = True
        
        try:
            self.link_input.setText(settings.get('api_url', ''))
            self.dir_input.setText(settings.get('output_dir', ''))
            self.character_input.setText(settings.get('character_filter_text', ''))
            self.skip_words_input.setText(settings.get('skip_words_text', ''))
            self.remove_from_filename_input.setText(settings.get('remove_words_text', ''))
            self.custom_folder_input.setText(settings.get('custom_folder_name', ''))
            self.cookie_text_input.setText(settings.get('cookie_text', ''))
            if hasattr(self, 'manga_date_prefix_input'):
                self.manga_date_prefix_input.setText(settings.get('manga_date_prefix', ''))
            self.thread_count_input.setText(str(settings.get('num_threads', 4)))
            self.start_page_input.setText(str(settings.get('start_page', '')) if settings.get('start_page') is not None else '')
            self.end_page_input.setText(str(settings.get('end_page', '')) if settings.get('end_page') is not None else '')
            
            for checkbox_name, key in self.get_checkbox_map().items():
                checkbox = getattr(self, checkbox_name, None)
                if checkbox:
                    checkbox.setChecked(settings.get(key, False))
                    
            if settings.get('only_links'): self.radio_only_links.setChecked(True)
            else:
                filter_mode = settings.get('filter_mode', 'all')
                if filter_mode == 'image': self.radio_images.setChecked(True)
                elif filter_mode == 'video': self.radio_videos.setChecked(True)
                elif filter_mode == 'archive': self.radio_only_archives.setChecked(True)
                elif filter_mode == 'audio' and hasattr(self, 'radio_only_audio'): self.radio_only_audio.setChecked(True)
                else: self.radio_all.setChecked(True)

            self.keep_duplicates_mode = settings.get('keep_duplicates_mode', DUPLICATE_HANDLING_HASH)
            self.keep_duplicates_limit = settings.get('keep_duplicates_limit', 0)
            if hasattr(self, 'keep_duplicates_checkbox'):
                is_keep_mode = (self.keep_duplicates_mode == DUPLICATE_HANDLING_KEEP_ALL)
                self.keep_duplicates_checkbox.setChecked(is_keep_mode)
                
            self.more_filter_scope = settings.get('more_filter_scope')
            self.text_export_format = settings.get('text_export_format', 'pdf')
            self.single_pdf_setting = settings.get('single_pdf_setting', False)
            self.add_info_in_pdf_setting = settings.get('add_info_in_pdf', False)
            
            if self.radio_more.isChecked() and self.more_filter_scope:
                scope_text = "Comments" if self.more_filter_scope == MoreOptionsDialog.SCOPE_COMMENTS else "Description"
                format_display = f" ({self.text_export_format.upper()})"
                if self.single_pdf_setting:
                    format_display = " (Single PDF)"
                self.radio_more.setText(f"{scope_text}{format_display}")
                
            self.skip_words_scope = settings.get('skip_words_scope', SKIP_SCOPE_POSTS)
            self.char_filter_scope = settings.get('char_filter_scope', CHAR_SCOPE_TITLE)
            self.manga_filename_style = settings.get('manga_filename_style', STYLE_POST_TITLE)
            self.allow_multipart_download_setting = settings.get('allow_multipart_download', False)
            
            self._update_skip_scope_button_text()
            self._update_char_filter_scope_button_text()
            self._update_manga_filename_style_button_text()
            self._update_multipart_toggle_button_text()

            if 'proxy_enabled' in settings:
                self.settings.setValue(PROXY_ENABLED_KEY, settings['proxy_enabled'])
            if 'proxy_host' in settings:
                self.settings.setValue(PROXY_HOST_KEY, settings['proxy_host'])
            if 'proxy_port' in settings:
                self.settings.setValue(PROXY_PORT_KEY, settings['proxy_port'])
            if 'proxy_username' in settings:
                self.settings.setValue(PROXY_USERNAME_KEY, settings['proxy_username'])
            if 'proxy_password' in settings:
                self.settings.setValue(PROXY_PASSWORD_KEY, settings['proxy_password'])
                
            self.settings.sync()
            
        finally:
            self._is_loading_settings = False
            self._enforce_visual_sort_pipeline_rules(False)

    def start_multi_threaded_download(self, num_post_workers, **kwargs):
        """
        Initializes the ThreadPoolExecutor for downloading an entire creator's feed.
        Spawns the PostFetcher thread to grab API data, which then feeds tasks to the worker pool.
        """
        global PostProcessorWorker
        if self.thread_pool is None:
            if self.pause_event: self.pause_event.clear()
            self.is_paused = False
            self.thread_pool = ThreadPoolExecutor(max_workers=num_post_workers, thread_name_prefix='PostWorker_')

        self.active_futures = []
        self.processed_posts_count = 0; self.total_posts_to_process = 0; self.download_counter = 0; self.skip_counter = 0
        self.all_kept_original_filenames = []
        self.is_fetcher_thread_running = True

        fetcher_thread_args = {
            'api_url': kwargs.get('api_url_input'),
            'worker_args_template': kwargs,
            'num_post_workers': num_post_workers,
            'processed_post_ids': kwargs.get('processed_post_ids', [])
        }

        fetcher_thread = threading.Thread(
            target=self._fetch_and_queue_posts,
            args=(fetcher_thread_args,),  
            daemon=True,
            name="PostFetcher"
        )
        
        fetcher_thread.start()
        self.log_signal.emit(f"✅ Post fetcher thread started. {num_post_workers} post worker threads initializing...")
        self._update_button_states_and_connections()

    def _fetch_and_queue_posts(self, fetcher_args):
        """
        Runs in a background thread. Talks to the Kemono/Coomer API to get post data, 
        checks if the post has already been downloaded (history), and if it's new, 
        hands it off to the PostProcessorWorker pool.
        """
        global PostProcessorWorker, download_from_api
        
        worker_args_template = fetcher_args['worker_args_template']
        def logger_func(msg):
            try:
                if not sip.isdeleted(self):
                    self.log_signal.emit(f"[Fetcher] {msg}")
            except (RuntimeError, ImportError, AttributeError):
                pass
        try:
            post_generator = download_from_api(
                api_url_input=worker_args_template.get('api_url_input'),
                logger=logger_func,
                start_page=worker_args_template.get('start_page'),
                end_page=worker_args_template.get('end_page'),
                manga_mode=worker_args_template.get('manga_mode_active'),
                cancellation_event=self.cancellation_event,
                pause_event=self.pause_event,
                use_cookie=worker_args_template.get('use_cookie'),
                cookie_text=worker_args_template.get('cookie_text'),
                selected_cookie_file=worker_args_template.get('selected_cookie_file'),
                app_base_dir=worker_args_template.get('app_base_dir'),
                manga_filename_style_for_sort_check=worker_args_template.get('manga_filename_style'),
                processed_post_ids=worker_args_template.get('processed_post_ids', []),
                fetch_all_first=worker_args_template.get('fetch_first', False),
                proxies=worker_args_template.get('proxies')
            )

            ppw_expected_keys = list(PostProcessorWorker.__init__.__code__.co_varnames)[1:]
            num_file_dl_threads = worker_args_template.get('num_file_threads_for_worker', 1)
            emitter = worker_args_template.get('emitter')
            
            fetch_first_enabled = worker_args_template.get('fetch_first', False)

            if fetch_first_enabled:
                logger_func("   Fetch First: All posts have been fetched. Now queuing for download...")
                all_posts = [post for batch in post_generator for post in batch]
                
                self.total_posts_to_process = len(all_posts)
                self.overall_progress_signal.emit(self.total_posts_to_process, self.processed_posts_count)

                for post_data in all_posts:
                    if self.cancellation_event.is_set():
                        break
                    self._submit_post_to_worker_pool(post_data, worker_args_template, num_file_dl_threads, emitter, ppw_expected_keys, {})

            else:
                for posts_batch_from_api in post_generator:
                    if self.cancellation_event.is_set():
                        break

                    processed_post_ids_set = set(worker_args_template.get('processed_post_ids', []))
                    new_posts_to_process = [
                        post for post in posts_batch_from_api if post.get('id') not in processed_post_ids_set
                    ]

                    if new_posts_to_process:
                        for post_data in new_posts_to_process:
                            if self.cancellation_event.is_set():
                                break
                            self._submit_post_to_worker_pool(post_data, worker_args_template, num_file_dl_threads, emitter, ppw_expected_keys, {})
                        
                        self.total_posts_to_process += len(new_posts_to_process)
                        self.overall_progress_signal.emit(self.total_posts_to_process, self.processed_posts_count)

        except Exception as e:
            logger_func(f"❌ Critical error during post fetching: {e}\n{traceback.format_exc(limit=2)}")
        finally:
            self.is_fetcher_thread_running = False
            logger_func("ℹ️ Post fetcher thread has finished submitting tasks.")
            self._check_if_all_work_is_done()

    def _handle_worker_result(self, result_tuple: tuple):
        """
        The funnel where all background workers report their results back to the main UI.
        Updates the progress bar, logs skipped/failed files, and checks if the entire job is done.
        """
        if getattr(self, 'is_in_retry_session', False):
            return

        self.processed_posts_count += 1
        
        try:
            (downloaded, skipped, kept_originals, retryable,
             permanent, history_data,
             temp_filepath) = result_tuple

            if temp_filepath: 
                self.session_temp_files.append(temp_filepath)
                
                if self.single_pdf_setting:
                    try:
                        with open(temp_filepath, 'r', encoding='utf-8') as f:
                            post_content_data = json.load(f)
                            self.temp_pdf_content_list.append(post_content_data)
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ Error reading temp file for PDF aggregation: {e}")            
            with self.downloaded_files_lock:
                self.download_counter += downloaded
                self.skip_counter += skipped

            if permanent:
                self.permanently_failed_files_for_dialog.extend(permanent)
                self._update_error_button_count()
            
            if history_data and not permanent:
                self._add_to_history_candidates(history_data)
            elif history_data and permanent:
                post_id = history_data.get('post_id', 'N/A')
                self.log_signal.emit(f"⚠️ Post {post_id} had permanent file failures. It will NOT be marked as processed and will be retried on the next session/update.")

            self.overall_progress_signal.emit(self.total_posts_to_process, self.processed_posts_count)

        except Exception as e:
            self.log_signal.emit(f"❌ Error in _handle_worker_result: {e}\n{traceback.format_exc(limit=2)}")

        self._check_if_all_work_is_done()

        if not self.is_fetcher_thread_running and self.processed_posts_count >= self.total_posts_to_process:
            if getattr(self, 'is_in_retry_session', False):
                return
            self.finished_signal.emit(self.download_counter, self.skip_counter, self.cancellation_event.is_set(), self.all_kept_original_filenames)

    def _trigger_single_pdf_creation(self):
        """
        Called after all text/images for a post are downloaded in 'Single PDF' mode. 
        Sorts the temporary data chronologically and starts the background PDF generator thread.
        """
        if not self.temp_pdf_content_list:
            self.log_signal.emit("⚠️ No content collected for Single PDF.")
            return

        self.log_signal.emit("   Sorting collected content for PDF...")
        def sort_key(post):
            p_date = post.get('published') or "0000-00-00"
            a_date = post.get('added') or "0000-00-00"
            pid = post.get('id') or "0"
            return (p_date, a_date, pid)

        sorted_content = sorted(self.temp_pdf_content_list, key=sort_key)

        first_post = sorted_content[0]
        creator_name = first_post.get('creator_name') or first_post.get('user') or "Unknown_Creator"
        clean_creator = clean_folder_name(creator_name)
        
        filename = f"[{clean_creator}] Complete_Collection.pdf"
        
        base_dir = self.last_effective_download_dir
        if not base_dir:
            base_dir = self.dir_input.text().strip()
        if not base_dir:
             base_dir = self.app_base_dir
             
        output_path = os.path.join(base_dir, filename)

        font_base_dir = getattr(sys, '_MEIPASS', self.app_base_dir)
        font_path = os.path.join(font_base_dir, 'data', 'dejavu-sans', 'DejaVuSans.ttf')
        add_info = True 
        if hasattr(self, 'more_options_dialog') and self.more_options_dialog:
            add_info = self.more_options_dialog.get_add_info_state()
        elif hasattr(self, 'add_info_in_pdf_setting'):
            add_info = self.add_info_in_pdf_setting

        self.pdf_thread = PdfGenerationThread(
            posts_data=sorted_content,
            output_filename=output_path,
            font_path=font_path,
            add_info_page=add_info,
            logger_func=self.log_signal.emit
        )

        self.pdf_thread.finished_signal.connect(self._on_pdf_generation_finished)
        self.pdf_thread.start()

    def _on_pdf_generation_finished(self, success, message):
        """Callback for when the PDF thread is done."""
        if success:
            self.log_signal.emit(f"✅ {message}")
            QMessageBox.information(self, "PDF Created", message)
        else:
            self.log_signal.emit(f"❌ PDF Creation Error: {message}")
            QMessageBox.warning(self, "PDF Error", f"Could not create PDF: {message}")
        
        self.temp_pdf_content_list = []

    def _add_to_history_candidates(self, history_data):
        """Adds processed post data to the history candidates list and updates the creator profile."""        
        if self.save_creator_json_enabled_this_session and not self.is_single_post_session:
            post_id = history_data.get('post_id')
            service = history_data.get('service')
            user_id = history_data.get('user_id')
            if post_id and service and user_id:
                creator_key = (service.lower(), str(user_id))
                creator_name = self.creator_name_cache.get(creator_key, f"{service}_{user_id}")
                
                profile_data = self._setup_creator_profile(creator_name, self.session_file_path)
                
                if post_id not in profile_data.get('processed_post_ids', []):
                    profile_data.setdefault('processed_post_ids', []).append(post_id)
                    self._save_creator_profile(creator_name, profile_data, self.session_file_path)

        if history_data and len(self.download_history_candidates) < 8:
            history_data['download_date_timestamp'] = time.time()
            creator_key = (history_data.get('service','').lower(), str(history_data.get('user_id','')))
            history_data['creator_name'] = self.creator_name_cache.get(creator_key, history_data.get('user_id','Unknown'))
            self.download_history_candidates.append(history_data)


    def _finalize_download_history (self ):
        """Processes candidates and selects the final 3 history entries.
        Only updates final_download_history_entries if new candidates are available.
        """
        if not self .download_history_candidates :


            self .log_signal .emit ("ℹ️ No new history candidates from this session. Preserving existing history.")


            self .download_history_candidates .clear ()
            return 

        candidates =list (self .download_history_candidates )
        now =datetime .datetime .now (datetime .timezone .utc )

        def get_sort_key (entry ):
            upload_date_str =entry .get ('upload_date_str')
            if not upload_date_str :
                return datetime .timedelta .max 
            try :

                upload_dt =datetime .datetime .fromisoformat (upload_date_str .replace ('Z','+00:00'))
                if upload_dt .tzinfo is None :
                    upload_dt =upload_dt .replace (tzinfo =datetime .timezone .utc )
                return abs (now -upload_dt )
            except ValueError :
                return datetime .timedelta .max 

        candidates .sort (key =get_sort_key )
        self .final_download_history_entries =candidates [:3 ]
        self .log_signal .emit (f"ℹ️ Finalized download history: {len (self .final_download_history_entries )} entries selected.")
        self .download_history_candidates .clear ()


        self ._save_persistent_history ()

    def _get_configurable_widgets_on_pause (self ):
        """Returns a list of widgets that should be re-enabled when paused."""
        return [
        self .dir_input ,self .dir_button ,
        self .character_input ,self .char_filter_scope_toggle_button ,
        self .skip_words_input ,self .skip_scope_toggle_button ,
        self .remove_from_filename_input ,
        self .radio_all ,self .radio_images ,self .radio_videos ,
        self .radio_only_archives ,self .radio_only_links ,
        self .skip_zip_checkbox ,
        self .download_thumbnails_checkbox ,self .compress_images_checkbox ,
        self .use_subfolders_checkbox ,self .use_subfolder_per_post_checkbox ,
        self .manga_mode_checkbox ,
        self .manga_rename_toggle_button ,
        self .cookie_browse_button ,
        self .favorite_mode_checkbox ,
        self .multipart_toggle_button ,
        self .cookie_text_input ,
        self .scan_content_images_checkbox ,
        self .use_cookie_checkbox ,
        self .external_links_checkbox 
        ]

    def set_ui_enabled (self ,enabled ):
        """
        Locks or unlocks the entire UI. 
        Called when a download starts (to prevent users from changing settings mid-download) 
        and unlocks when the download finishes or cancels.
        """
        all_potentially_toggleable_widgets =[
        self .link_input ,self .dir_input ,self .dir_button ,
        self .page_range_label ,self .start_page_input ,self .to_label ,self .end_page_input ,
        self .character_input ,self .char_filter_scope_toggle_button ,self .character_filter_widget ,
        self .filters_and_custom_folder_container_widget ,
        self .custom_folder_label ,self .custom_folder_input ,
        self .skip_words_input ,self .skip_scope_toggle_button ,self .remove_from_filename_input ,
        self .radio_all ,self .radio_images ,self .radio_videos ,self .radio_only_archives ,self .radio_only_links ,
        self .skip_zip_checkbox , self .download_thumbnails_checkbox ,self .compress_images_checkbox ,
        self .use_subfolders_checkbox ,self .use_subfolder_per_post_checkbox ,self .scan_content_images_checkbox ,
        self .use_multithreading_checkbox ,self .thread_count_input ,self .thread_count_label ,
        self .favorite_mode_checkbox ,
        self .external_links_checkbox ,self .manga_mode_checkbox ,self .manga_rename_toggle_button ,self .use_cookie_checkbox ,self .cookie_text_input ,self .cookie_browse_button ,
        self .multipart_toggle_button ,self .radio_only_audio ,
        self .character_search_input ,self .new_char_input ,self .add_char_button ,self .add_to_filter_button ,self .delete_char_button ,
        self .reset_button, self.radio_more, self.keep_duplicates_checkbox
        ]

        widgets_to_enable_on_pause =self ._get_configurable_widgets_on_pause ()
        is_fav_mode_active =self .favorite_mode_checkbox .isChecked ()if self .favorite_mode_checkbox else False 
        download_is_active_or_paused =not enabled 

        if not enabled :
            if self .bottom_action_buttons_stack :
                self .bottom_action_buttons_stack .setCurrentIndex (0 )

            if self .external_link_download_thread and self .external_link_download_thread .isRunning ():
                self .log_signal .emit ("ℹ️ Cancelling active Mega download due to UI state change.")
                self .external_link_download_thread .cancel ()
        else :
            pass 


        for widget in all_potentially_toggleable_widgets :
            if not widget :continue 


            if widget is self .favorite_mode_artists_button or widget is self .favorite_mode_posts_button :continue 
            elif self .is_paused and widget in widgets_to_enable_on_pause :
                widget .setEnabled (True )
            elif widget is self .favorite_mode_checkbox :
                widget .setEnabled (enabled )
            elif widget is self .use_cookie_checkbox and is_fav_mode_active :
                widget .setEnabled (False )
            elif widget is self .use_cookie_checkbox and self .is_paused and widget in widgets_to_enable_on_pause :
                widget .setEnabled (True )
            else :
                widget .setEnabled (enabled )

        if self .link_input :
            self .link_input .setEnabled (enabled and not is_fav_mode_active )



        if not enabled :
            if self .favorite_mode_artists_button :
                self .favorite_mode_artists_button .setEnabled (False )
            if self .favorite_mode_posts_button :
                self .favorite_mode_posts_button .setEnabled (False )

        if self .download_btn :
            self .download_btn .setEnabled (enabled and not is_fav_mode_active )


        if self .external_links_checkbox :
            is_only_links =self .radio_only_links and self .radio_only_links .isChecked ()
            is_only_archives =self .radio_only_archives and self .radio_only_archives .isChecked ()
            is_only_audio =hasattr (self ,'radio_only_audio')and self .radio_only_audio .isChecked ()
            can_enable_ext_links =enabled and not is_only_links and not is_only_archives and not is_only_audio 
            self .external_links_checkbox .setEnabled (can_enable_ext_links )
            if self .is_paused and not is_only_links and not is_only_archives and not is_only_audio :
                self .external_links_checkbox .setEnabled (True )
        if hasattr (self ,'use_cookie_checkbox'):
            self ._update_cookie_input_visibility (self .use_cookie_checkbox .isChecked ())

        if self .log_verbosity_toggle_button :self .log_verbosity_toggle_button .setEnabled (True )

        multithreading_currently_on =self .use_multithreading_checkbox .isChecked ()
        if self .thread_count_input :self .thread_count_input .setEnabled (enabled and multithreading_currently_on )
        if self .thread_count_label :self .thread_count_label .setEnabled (enabled and multithreading_currently_on )

        subfolders_currently_on =self .use_subfolders_checkbox .isChecked ()
        if self .use_subfolder_per_post_checkbox :
            self .use_subfolder_per_post_checkbox .setEnabled (enabled or (self .is_paused and self .use_subfolder_per_post_checkbox in widgets_to_enable_on_pause ))
        if self .cancel_btn :self .cancel_btn .setEnabled (download_is_active_or_paused )
        if self .pause_btn :
            self .pause_btn .setEnabled (download_is_active_or_paused )
            if download_is_active_or_paused :
                self .pause_btn .setText (self ._tr ("resume_download_button_text","Resume Download")if self .is_paused else self ._tr ("pause_download_button_text","Pause Download"))
                self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/resume.svg")) if self.is_paused else QIcon(get_asset_path("assets/Svg/pause.svg")))
                self .pause_btn .setToolTip (self ._tr ("resume_download_button_tooltip","Click to resume the download.")if self .is_paused else self ._tr ("pause_download_button_tooltip","Click to pause the download."))
            else :
                self .pause_btn .setText (self ._tr ("pause_download_button_text","Pause Download"))
                self.pause_btn.setIcon(QIcon(get_asset_path("assets/Svg/pause.svg")))
                self .pause_btn .setToolTip (self ._tr ("pause_download_button_tooltip","Click to pause the ongoing download process."))
                self .is_paused =False 
        if self .cancel_btn :self .cancel_btn .setText (self ._tr ("cancel_button_text","❌ Cancel & Reset UI"))
        if enabled :
            if self .pause_event :self .pause_event .clear ()
        if enabled or self .is_paused :
            self ._handle_multithreading_toggle (multithreading_currently_on )
            self .update_ui_for_manga_mode (self .manga_mode_checkbox .isChecked ()if self .manga_mode_checkbox else False )
            self .update_custom_folder_visibility (self .link_input .text ())
            self .update_page_range_enabled_state ()
            if self .radio_group and self .radio_group .checkedButton ():
                self ._handle_filter_mode_change (self .radio_group .checkedButton (),True )
            self .update_ui_for_subfolders (subfolders_currently_on )
            self ._handle_favorite_mode_toggle (is_fav_mode_active )

    def _handle_pause_resume_action(self):
        if not self._is_download_active():
            return

        self.is_paused = not self.is_paused

        if isinstance(self.download_thread, DiscordDownloadThread):
            if self.is_paused:
                self.download_thread.pause()
            else:
                self.download_thread.resume()
        else:
            if self.is_paused:
                self.pause_event.set()
                self.log_signal.emit("⏸️ Download paused. Workers will halt on their next check.")
            else:
                self.pause_event.clear()
                self.log_signal.emit("▶️ Download resumed.")

        self.set_ui_enabled(False)

    def _perform_soft_ui_reset (self ,preserve_url =None ,preserve_dir =None ):
        """Resets UI elements and some state to app defaults, then applies preserved inputs."""
        self .log_signal .emit ("🔄 Performing soft UI reset...")
        self .link_input .clear ()
        self .dir_input .clear ()
        self .custom_folder_input .clear ();self .character_input .clear ();
        self .skip_words_input .clear ();self .start_page_input .clear ();self .end_page_input .clear ();self .new_char_input .clear ();
        if hasattr (self ,'remove_from_filename_input'):self .remove_from_filename_input .clear ()
        self .character_search_input .clear ();self .thread_count_input .setText ("4");self .radio_all .setChecked (True );
        self .skip_zip_checkbox .setChecked (True );self .download_thumbnails_checkbox .setChecked (False );
        self .compress_images_checkbox .setChecked (False );self .use_subfolders_checkbox .setChecked (False );
        self .use_subfolder_per_post_checkbox .setChecked (True );self .use_multithreading_checkbox .setChecked (True );
        if self .favorite_mode_checkbox :self .favorite_mode_checkbox .setChecked (False )
        if hasattr (self ,'scan_content_images_checkbox'):self .scan_content_images_checkbox .setChecked (False )
        self .external_links_checkbox .setChecked (False )
        if self .manga_mode_checkbox :self .manga_mode_checkbox .setChecked (False )
        if hasattr (self ,'use_cookie_checkbox'):self .use_cookie_checkbox .setChecked (self .use_cookie_setting )
        if hasattr (self ,'cookie_text_input'):self .cookie_text_input .setText (self .cookie_text_setting if self .use_cookie_setting else "")
        self .allow_multipart_download_setting =False 
        self ._update_multipart_toggle_button_text ()

        self .skip_words_scope =SKIP_SCOPE_POSTS 
        self ._update_skip_scope_button_text ()

        if hasattr (self ,'manga_date_prefix_input'):self .manga_date_prefix_input .clear ()

        self .char_filter_scope =CHAR_SCOPE_TITLE 
        self ._update_char_filter_scope_button_text ()

        self .manga_filename_style =STYLE_POST_TITLE 
        self ._update_manga_filename_style_button_text ()
        if preserve_url is not None :
            self .link_input .setText (preserve_url )
        if preserve_dir is not None :
            self .dir_input .setText (preserve_dir )
        self .external_link_queue .clear ();self .extracted_links_cache =[]
        self ._is_processing_external_link_queue =False ;self ._current_link_post_title =None 
        if self .pause_event :self .pause_event .clear ()
        self.is_restore_pending = False
        self .total_posts_to_process =0 ;self .processed_posts_count =0 
        self .download_counter =0 ;self .skip_counter =0 
        self .all_kept_original_filenames =[]
        self .is_paused =False 
        self ._handle_multithreading_toggle (self .use_multithreading_checkbox .isChecked ())
     
        self._update_button_states_and_connections()
        self .favorite_download_queue .clear ()
        self .is_processing_favorites_queue =False 

        self .only_links_log_display_mode =LOG_DISPLAY_LINKS 

        if hasattr (self ,'link_input'):
            if self .download_extracted_links_button :
                self .download_extracted_links_button .setEnabled (False )

            self .last_link_input_text_for_queue_sync =self .link_input .text ()
        self .permanently_failed_files_for_dialog .clear ()
        self .filter_character_list (self .character_search_input .text ())
        self .favorite_download_scope =FAVORITE_SCOPE_SELECTED_LOCATION 
        self ._update_favorite_scope_button_text ()

        self .set_ui_enabled (True )
        self.interrupted_session_data = None
        self .update_custom_folder_visibility (self .link_input .text ())
        self .update_page_range_enabled_state ()
        self ._update_cookie_input_visibility (self .use_cookie_checkbox .isChecked ()if hasattr (self ,'use_cookie_checkbox')else False )
        if hasattr (self ,'favorite_mode_checkbox'):
            self ._handle_favorite_mode_toggle (False )

        self .log_signal .emit ("✅ Soft UI reset complete. Preserved URL and Directory (if provided).")

    def _update_log_display_mode_button_text (self ):
        if hasattr (self ,'log_display_mode_toggle_button'):
            if self .only_links_log_display_mode ==LOG_DISPLAY_LINKS :
                self .log_display_mode_toggle_button .setText (self ._tr ("log_display_mode_links_view_text","🔗 Links View"))
                self .log_display_mode_toggle_button .setToolTip (
                "Current View: Extracted Links.\n"
                "After Mega download, Mega log is shown THEN links are appended.\n"
                "Click to switch to 'Download Progress View'."
                )
            else :
                self .log_display_mode_toggle_button .setText (self ._tr ("log_display_mode_progress_view_text","⬇️ Progress View"))
                self .log_display_mode_toggle_button .setToolTip (
                "Current View: Mega Download Progress.\n"
                "After Mega download, ONLY Mega log is shown (links hidden).\n"
                "Click to switch to 'Extracted Links View'."
                )

    def _toggle_log_display_mode (self ):
        self .only_links_log_display_mode =LOG_DISPLAY_DOWNLOAD_PROGRESS if self .only_links_log_display_mode ==LOG_DISPLAY_LINKS else LOG_DISPLAY_LINKS 
        self ._update_log_display_mode_button_text ()
        self ._filter_links_log ()

    def cancel_download_button_action(self):
        """
        Handles the user clicking the 'Cancel' button.
        This version forcefully shuts down thread pools.
        """
        if not self._is_download_active() and not self.is_paused:
            self.log_signal.emit("ℹ️ Cancel button clicked, but no download is active.")
            return

        if self.is_paused:
            self.log_signal.emit("❌ Cancellation requested while paused. Stopping all workers...")
        else:
            self.log_signal.emit("❌ Cancellation requested by user. Stopping all workers...")

        self.progress_label.setText(self._tr("status_cancelling", "Cancelling... Please wait."))
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        if hasattr(self, 'reset_button'):
            self.reset_button.setEnabled(False)
            
        if not self.cancellation_event.is_set():
            self.cancellation_event.set()

        if self.download_thread and hasattr(self.download_thread, 'requestInterruption'):
            self.download_thread.requestInterruption()
            self.log_signal.emit("    Signaled single download thread to interrupt.")
        
        if self.external_link_download_thread and self.external_link_download_thread.isRunning():
            self.log_signal.emit("    Cancelling active External Link download thread...")
            self.external_link_download_thread.cancel()

        if isinstance(self.download_thread, NhentaiDownloadThread): 
            self.log_signal.emit("    Signaling nhentai download thread to cancel.")
            self.download_thread.cancel()
        if isinstance(self.download_thread, BunkrDownloadThread):
            self.log_signal.emit("    Signaling Bunkr download thread to cancel.")
            self.download_thread.cancel()
        if isinstance(self.download_thread, Saint2DownloadThread):
            self.log_signal.emit("    Signaling Saint2 download thread to cancel.")
            self.download_thread.cancel()
        if isinstance(self.download_thread, EromeDownloadThread):
            self.log_signal.emit("    Signaling Erome download thread to cancel.")
            self.download_thread.cancel()
        if isinstance(self.download_thread, Hentai2readDownloadThread):
            self.log_signal.emit("    Signaling Hentai2Read download thread to cancel.")
            self.download_thread.cancel()
            
        if self.thread_pool:
            self.log_signal.emit("    Signaling worker pool to shut down...")
            self.thread_pool.shutdown(wait=False, cancel_futures=True)
            self.thread_pool = None
            self.active_futures = []
            self.log_signal.emit("    Worker pool shutdown initiated.")

        if hasattr(self, 'retry_thread_pool') and self.retry_thread_pool:
            self.log_signal.emit("    Signaling retry worker pool to shut down...")
            self.retry_thread_pool.shutdown(wait=False, cancel_futures=True)
            self.retry_thread_pool = None
            self.active_retry_futures = []
            self.log_signal.emit("    Retry pool shutdown initiated.")
            
        self.download_finished(0, 0, True, [])

    def _get_domain_for_service(self, service_name: str) -> str:
        """Determines the base domain for a given service."""
        if not isinstance(service_name, str):
            return "kemono.cr"
        service_lower = service_name.lower()
        coomer_primary_services = {'onlyfans', 'fansly', 'manyvids', 'candfans', 'gumroad', 'subscribestar', 'dlsite'}
        if service_lower in coomer_primary_services:
            return "coomer.st"
        return "kemono.cr"

    def download_finished(self, total_downloaded, total_skipped, cancelled_by_user, kept_original_names_list=None):
        """
        The cleanup function. Runs when a download completely finishes or is cancelled.
        Unlocks the UI, saves the final download history, triggers auto-retries for failed files, 
        and optionally shuts down the PC if requested.
        """
        if not getattr(self, 'is_main_download_active', True):
            return
            
        self.is_main_download_active = False
        if not self.finish_lock.acquire(blocking=False):
            return

        lock_held = True 

        try:
            if self.is_finishing:
                return
            self.is_finishing = True

            if cancelled_by_user:
                self.log_signal.emit("✅ Cancellation complete. Resetting UI.")
                
                if getattr(self, 'is_running_job_queue', False):
                    self.log_signal.emit("🛑 Queue execution stopped by user.")
                    self.is_running_job_queue = False
                    self.current_job_file = None

                self._clear_session_file()
                self.interrupted_session_data = None
                self.is_restore_pending = False
                current_url = self.link_input.text()
                current_dir = self.dir_input.text()
                self._perform_soft_ui_reset(preserve_url=current_url, preserve_dir=current_dir)
                self.progress_label.setText(f"{self._tr('status_cancelled_by_user', 'Cancelled by user')}. {self._tr('ready_for_new_task_text', 'Ready for new task.')}")
                self.file_progress_label.setText("")
                if self.pause_event: self.pause_event.clear()
                self.is_paused = False
                return

            self.log_signal.emit("🏁 Download of current item complete.")

            if self.is_processing_favorites_queue and self.favorite_download_queue:
                self.log_signal.emit("✅ Item finished. Processing next in queue...")
                if self.download_thread and isinstance(self.download_thread, QThread):
                    self.download_thread.deleteLater()
                self.download_thread = None 
                self.is_finishing = False 

                self.finish_lock.release()
                lock_held = False 
                
                self._process_next_favorite_download()
                return  

            if getattr(self, 'is_running_job_queue', False) and getattr(self, 'current_job_file', None):
                self.log_signal.emit(f"✅ Job finished. Deleting job file: {os.path.basename(self.current_job_file)}")
                
                if self.retryable_failed_files_info:
                    self.log_signal.emit(f"⚠️ Job had {len(self.retryable_failed_files_info)} incomplete files. Adding to cumulative error report.")
                    self.permanently_failed_files_for_dialog.extend(self.retryable_failed_files_info)
                    self._update_error_button_count()
                    self.retryable_failed_files_info.clear()

                self._finalize_download_history()
                if self.thread_pool:
                    self.thread_pool.shutdown(wait=False)
                    self.thread_pool = None
                self._cleanup_temp_files()
                self.single_pdf_setting = False

                try:
                    if os.path.exists(self.current_job_file):
                        os.remove(self.current_job_file)
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Failed to delete finished job file: {e}")

                self.current_job_file = None
                self.is_finishing = False 
                
                self.finish_lock.release()
                lock_held = False
                
                QTimer.singleShot(100, self._process_next_queued_job)
                return

            if self.is_processing_favorites_queue:
                self.is_processing_favorites_queue = False
                self.log_signal.emit("✅ All items from the download queue have been processed.")

            if not cancelled_by_user and not self.retryable_failed_files_info:
                self._clear_session_file()
                self.interrupted_session_data = None
                self.is_restore_pending = False

            self._finalize_download_history()
            status_message = self._tr("status_completed", "Completed")

            if self.radio_only_links and self.radio_only_links.isChecked():
                self.log_signal.emit("ℹ️ Link extraction complete. Refreshing link view...")
                self.only_links_log_display_mode = LOG_DISPLAY_LINKS
                self._update_log_display_mode_button_text()
                self._filter_links_log()
            
            if self.thread_pool:
                self.thread_pool.shutdown(wait=False) 
                self.thread_pool = None

            if self.single_pdf_setting and self.session_temp_files:
                try:
                    self._trigger_single_pdf_creation()
                finally:
                    self._cleanup_temp_files()
            else:
                self._cleanup_temp_files()
                self.single_pdf_setting = False

            if kept_original_names_list is None:
                kept_original_names_list = list(self.all_kept_original_filenames) if hasattr(self, 'all_kept_original_filenames') else []
            if kept_original_names_list is None:
                kept_original_names_list = []

            if kept_original_names_list:
                intro_msg = (
                    HTML_PREFIX +
                    "<p>ℹ️ The following files from multi-file manga posts "
                    "(after the first file) kept their <b>original names</b>:</p>"
                )
                self.log_signal.emit(intro_msg)
                html_list_items = "<ul>"
                for name in kept_original_names_list:
                    html_list_items += f"<li><b>{name}</b></li>"
                html_list_items += "</ul>"
                self.log_signal.emit(HTML_PREFIX + html_list_items)
                self.log_signal.emit("=" * 40)

            if self.download_thread:
                if isinstance(self.download_thread, QThread):
                    try:
                        if hasattr(self.download_thread, 'progress_signal'): self.download_thread.progress_signal.disconnect(self.handle_main_log)
                        if hasattr(self.download_thread, 'add_character_prompt_signal'): self.download_thread.add_character_prompt_signal.disconnect(self.add_character_prompt_signal)
                        if hasattr(self.download_thread, 'finished_signal'): self.download_thread.finished_signal.disconnect(self.download_finished)
                        if hasattr(self.download_thread, 'receive_add_character_result'): self.character_prompt_response_signal.disconnect(self.download_thread.receive_add_character_result)
                        if hasattr(self.download_thread, 'external_link_signal'): self.download_thread.external_link_signal.disconnect(self.handle_external_link_signal)
                        if hasattr(self.download_thread, 'file_progress_signal'): self.download_thread.file_progress_signal.disconnect(self.update_file_progress_display)
                        if hasattr(self.download_thread, 'missed_character_post_signal'): self.download_thread.missed_character_post_signal.disconnect(self.handle_missed_character_post)
                        if hasattr(self.download_thread, 'retryable_file_failed_signal'): self.download_thread.retryable_file_failed_signal.disconnect(self._handle_retryable_file_failure)
                        if hasattr(self.download_thread, 'file_successfully_downloaded_signal'): self.download_thread.file_successfully_downloaded_signal.disconnect(self._handle_actual_file_downloaded)
                        if hasattr(self.download_thread, 'post_processed_for_history_signal'): self.download_thread.post_processed_for_history_signal.disconnect(self._add_to_history_candidates)
                    except (TypeError, RuntimeError) as e:
                        self.log_signal.emit(f"ℹ️ Note during single-thread signal disconnection: {e}")

                    self.download_thread.deleteLater()
                    self.download_thread = None
                else:
                    self.download_thread = None

            self.progress_label.setText(
                f"{status_message}: "
                f"{total_downloaded} {self._tr('files_downloaded_label', 'downloaded')}, "
                f"{total_skipped} {self._tr('files_skipped_label', 'skipped')}."
            )
            self.file_progress_label.setText("")

            if not cancelled_by_user and self.retryable_failed_files_info:
                num_failed = len(self.retryable_failed_files_info)
                reply = QMessageBox.question(self, "Retry Failed Downloads?",
                                             f"{num_failed} file(s) failed with potentially recoverable errors (e.g., IncompleteRead).\n\n"
                                             "Would you like to attempt to download these failed files again?",
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    self.is_finishing = False
                    
                    self.finish_lock.release()
                    lock_held = False
                    
                    self._start_failed_files_retry_session()
                    return
                else:
                    self.log_signal.emit("ℹ️ User chose not to retry failed files.")
                    self.permanently_failed_files_for_dialog.extend(self.retryable_failed_files_info)
                    if self.permanently_failed_files_for_dialog:
                        self.log_signal.emit(f"🆘 Error button enabled. {len(self.permanently_failed_files_for_dialog)} file(s) can be viewed.")
                    self.cancellation_message_logged_this_session = False
                    self.retryable_failed_files_info.clear()

            auto_retry_enabled = self.settings.value(AUTO_RETRY_ON_FINISH_KEY, False, type=bool)
            
            if not cancelled_by_user and auto_retry_enabled and self.permanently_failed_files_for_dialog:
                num_files_to_retry = len(self.permanently_failed_files_for_dialog)
                self.log_signal.emit("=" * 40)
                self.log_signal.emit(f"🔄 Auto-retry is enabled. Starting a new session for {num_files_to_retry} previously failed file(s)...")
                
                self._start_failed_files_retry_session(files_to_retry_list=list(self.permanently_failed_files_for_dialog))
                
                self.is_finishing = False 
                
                self.finish_lock.release()
                lock_held = False
                return 

            self.is_fetcher_thread_running = False
            
            if not cancelled_by_user and not self.is_processing_favorites_queue:
                if not getattr(self, 'is_running_job_queue', False):
                    self._execute_post_download_action()

            self.set_ui_enabled(True)
            self._update_button_states_and_connections()
            self.cancellation_message_logged_this_session = False
            self.active_update_profile = None 
        
        finally:
            if lock_held:
                self.finish_lock.release()

    def _execute_post_download_action(self):
        """Checks the settings and performs the chosen action after downloads complete."""
        action = self.settings.value(POST_DOWNLOAD_ACTION_KEY, "off")

        if action == "off":
            return

        elif action == "notify":
            QApplication.beep()
            self.log_signal.emit("✅ Download complete! Notification sound played.")
            return
        
        confirm_title = self._tr("action_confirmation_title", "Action After Download")
        confirm_text = ""
        
        if action == "sleep":
            confirm_text = self._tr("confirm_sleep_text", "All downloads are complete. The computer will now go to sleep.")
        elif action == "shutdown":
            confirm_text = self._tr("confirm_shutdown_text", "All downloads are complete. The computer will now shut down.")
        
        dialog = CountdownMessageBox(
            title=confirm_title,
            text=confirm_text,
            countdown_seconds=10,
            parent_app=self,
            parent=self
        )

        if dialog.exec_() == QDialog.Accepted:
            self.log_signal.emit(f"ℹ️ Performing post-download action: {action.capitalize()}")
            try:
                if sys.platform == "win32":
                    if action == "sleep":
                        subprocess.run(["powercfg", "-hibernate", "off"])
                        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
                        subprocess.run(["powercfg", "-hibernate", "on"])
                    elif action == "shutdown":
                        subprocess.run(["shutdown", "/s", "/t", "1"])
                elif sys.platform == "darwin":
                    if action == "sleep":
                        subprocess.run(["pmset", "sleepnow"])
                    elif action == "shutdown":
                        subprocess.run(["osascript", "-e", "tell app \"System Events\" to shut down"])
                else:
                    if action == "sleep":
                        subprocess.run(["systemctl", "suspend"])
                    elif action == "shutdown":
                        subprocess.run(["systemctl", "poweroff"])
            except Exception as e:
                self.log_signal.emit(f"❌ Failed to execute post-download action '{action}': {e}")
        else:
            self.log_signal.emit(f"ℹ️ Post-download '{action}' cancelled by user.")

    def _handle_keep_duplicates_toggled(self, checked):
        """Shows the duplicate handling dialog when the checkbox is checked."""
        if checked:
            if getattr(self, '_is_loading_settings', False):
                return
            dialog = KeepDuplicatesDialog(self.keep_duplicates_mode, self.keep_duplicates_limit, self)
            if dialog.exec_() == QDialog.Accepted:
                options = dialog.get_selected_options()
                self.keep_duplicates_mode = options["mode"]
                self.keep_duplicates_limit = options["limit"]

                limit_text = f"with a limit of {self.keep_duplicates_limit}" if self.keep_duplicates_limit > 0 else "with no limit"
                self.log_signal.emit(f"ℹ️ Duplicate handling mode set to: '{self.keep_duplicates_mode}' {limit_text}.")
                self.log_signal.emit(f"")
                self.log_signal.emit(f"")
                if self.keep_duplicates_mode == DUPLICATE_HANDLING_KEEP_ALL:
                    self._log_keep_everything_warning()
            else:
                self.keep_duplicates_checkbox.setChecked(False)
        else:
            self.keep_duplicates_mode = DUPLICATE_HANDLING_HASH
            self.keep_duplicates_limit = 0
            self.log_signal.emit("ℹ️ 'Keep Duplicates' disabled. Reverted to default hash checking.")

    def _log_keep_everything_warning(self):
        """Logs a formatted warning when the 'Keep Everything' mode is selected."""
     
        warning_html = (
            f'{HTML_PREFIX}'
            '<h2 style="margin-top: 8px; margin-bottom: 4px; font-weight: bold;">⚠️ ATTENTION: "Keep Everything" Enabled</h2>'
            '<h3><p style="margin-top: 0; margin-bottom: 4px;">This mode will download every single file from the API response for a post,</p>'
            '<p style="margin-top: 0; margin-bottom: 4px;">even if they have identical content. This can lead to many redundant files.</p>'
            '<p style="margin-top: 0; margin-bottom: 4px;"><b>Recommendation:</b> Consider using the <b>limit feature</b>.</p>'
            '<p style="margin-top: 0; margin-bottom: 0;">For example, setting the limit to <b>2</b> will download a file with the same content up to two times.</p></h3>'
        )
        self.log_signal.emit(warning_html)

    def _handle_thumbnail_mode_change (self ,thumbnails_checked ):
        """Handles UI changes when 'Download Thumbnails Only' is toggled."""
        pass

        if thumbnails_checked :
            self .scan_content_images_checkbox .setChecked (True )
            self .scan_content_images_checkbox .setEnabled (False )
            self .scan_content_images_checkbox .setToolTip (
            "Automatically enabled and locked because 'Download Thumbnails Only' is active.\n"
            "In this mode, only images found by content scanning will be downloaded."
            )
        else :
            self .scan_content_images_checkbox .setEnabled (True )
            self .scan_content_images_checkbox .setChecked (False )
            self .scan_content_images_checkbox .setToolTip (self ._original_scan_content_tooltip )

    def _start_failed_files_retry_session(self, files_to_retry_list=None):
        """
        Takes files that failed due to network errors (500, timeouts) and feeds them 
        into a dedicated retry thread pool, bypassing the API check entirely.
        """
        if getattr(self, 'is_in_retry_session', False):
            self.log_signal.emit("⚠️ Ignored ghost thread attempting to start overlapping retry session.")
            return
            
        self.is_in_retry_session = True
        
        if files_to_retry_list:
            raw_files_list = list(files_to_retry_list)
            
            retry_urls = {f.get('file_info', {}).get('url') for f in files_to_retry_list if f.get('file_info', {}).get('url')}
            
            updated_permanent_errors = []
            for failed_job in self.permanently_failed_files_for_dialog:
                job_url = failed_job.get('file_info', {}).get('url')
                if job_url not in retry_urls:
                    updated_permanent_errors.append(failed_job)
                    
            self.permanently_failed_files_for_dialog = updated_permanent_errors
        else:
            raw_files_list = list(self.retryable_failed_files_info)
            self.retryable_failed_files_info.clear()

        unique_files = []
        seen_urls = set()
        
        for job in raw_files_list:
            file_url = job.get('file_info', {}).get('url')
            if file_url:
                if file_url not in seen_urls:
                    seen_urls.add(file_url)
                    unique_files.append(job)
            else:
                unique_files.append(job)
                
        self.files_for_current_retry_session = unique_files

        self.log_signal.emit(f"🔄 Starting retry session for {len(self.files_for_current_retry_session)} unique file(s)...")
        self.set_ui_enabled(False)
        if self.cancel_btn: 
            self.cancel_btn.setText(self._tr("cancel_retry_button_text", "Cancel Retry"))

        raw_character_filters_text = self.character_input.text().strip()
        _, download_commands = self._parse_character_filters(raw_character_filters_text)
        domain_override_command = download_commands.get('domain_override')
        sfp_threshold_command = download_commands.get('sfp_threshold')
        handle_unknown_command = download_commands.get('handle_unknown', False) 

        if domain_override_command:
            self.log_signal.emit(f"ℹ️ Retry Session: Domain override '[.{domain_override_command}]' is active.")

        self.active_retry_futures = []
        self.processed_retry_count = 0 
        self.succeeded_retry_count = 0 
        self.failed_retry_count_in_session = 0 
        self.total_files_for_retry = len(self.files_for_current_retry_session)
        self.active_retry_futures_map = {}

        self.progress_label.setText(self._tr("progress_posts_text", "Progress: {processed_posts} / {total_posts} posts ({progress_percent:.1f}%)").format(processed_posts=0, total_posts=self.total_files_for_retry, progress_percent=0.0).replace("posts", "files"))
        self.cancellation_event.clear()

        num_retry_threads = 1 
        try:
            num_threads_from_gui = int(self.thread_count_input.text().strip())
            num_retry_threads = max(1, min(num_threads_from_gui, MAX_FILE_THREADS_PER_POST_OR_WORKER, self.total_files_for_retry if self.total_files_for_retry > 0 else 1))
        except ValueError:
            num_retry_threads = 1 

        self.retry_thread_pool = ThreadPoolExecutor(max_workers=num_retry_threads, thread_name_prefix='RetryFile_')
        
        common_ppw_args_for_retry = {
            'download_root': self.dir_input.text().strip(),
            'known_names': list(KNOWN_NAMES),
            'emitter': self.worker_to_gui_queue,
            'unwanted_keywords': {'spicy', 'hd', 'nsfw', '4k', 'preview', 'teaser', 'clip'},
            'creator_name_cache': self.creator_name_cache,
            'domain_override': domain_override_command,
            'sfp_threshold': sfp_threshold_command, 
            'handle_unknown_mode': handle_unknown_command, 
            'filter_mode': self.get_filter_mode(),
            'skip_zip': self.skip_zip_checkbox.isChecked(),
            'use_subfolders': self.use_subfolders_checkbox.isChecked(),
            'use_post_subfolders': self.use_subfolder_per_post_checkbox.isChecked(),
            'compress_images': self.compress_images_checkbox.isChecked(),
            'download_thumbnails': self.download_thumbnails_checkbox.isChecked(),
            'pause_event': self.pause_event,
            'cancellation_event': self.cancellation_event,
            'downloaded_files': self.downloaded_files,
            'downloaded_file_hashes': self.downloaded_file_hashes,
            'downloaded_files_lock': self.downloaded_files_lock,
            'downloaded_file_hashes_lock': self.downloaded_file_hashes_lock,
            'skip_words_list': [word.strip().lower() for word in self.skip_words_input.text().strip().split(',') if word.strip()],
            'skip_words_scope': self.get_skip_words_scope(),
            'char_filter_scope': self.get_char_filter_scope(),
            'remove_from_filename_words_list': [word.strip() for word in self.remove_from_filename_input.text().strip().split(',') if word.strip()] if hasattr(self, 'remove_from_filename_input') else [],
            'allow_multipart_download': self.allow_multipart_download_setting,
            'filter_character_list': None,
            'dynamic_character_filter_holder': None,
            'target_post_id_from_initial_url': None,
            'custom_folder_name': None,
            'num_file_threads': 1,
            'add_info_in_pdf': self.add_info_in_pdf_setting,
            'use_cookie': self.use_cookie_checkbox.isChecked(),
            'cookie_text': self.cookie_text_input.text(),
            'selected_cookie_file': self.selected_cookie_filepath,
            'app_base_dir': self.app_base_dir,
            'manga_date_file_counter_ref': None,
            'download_revisions': self.revisions_checkbox.isChecked() if hasattr(self, 'revisions_checkbox') else False,
            'visual_sort_active': getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked(),
            'user_data_path': getattr(self, 'user_data_path', "")
        }

        for job_details in self.files_for_current_retry_session:
            future = self.retry_thread_pool.submit(self._execute_single_file_retry, job_details, common_ppw_args_for_retry)
            future.add_done_callback(self._handle_retry_future_result)
            self.active_retry_futures_map[future] = job_details 
            self.active_retry_futures.append(future)

    def _execute_single_file_retry(self, job_details, common_args):
        """
        Reconstructs the original environment (Known.txt rules, AI rules, output paths) 
        for a single failed file and forces the PostProcessorWorker to try downloading it again.
        """

        file_info = job_details.get('file_info', {})
        file_url = file_info.get('url', '')
        
        if 'path' not in file_info and file_url:
            file_info['path'] = urlparse(file_url).path

        dummy_post_data = {
            'id': job_details.get('original_post_id_for_log', 'unknown_id'),
            'title': job_details.get('post_title', ''),
            'file': file_info,
            'attachments': [],
            'content': '',
            'published': job_details.get('published') or job_details.get('added'),
            'added': job_details.get('added')
        }

        service = job_details.get('service', '')
        user_id = str(job_details.get('user_id', ''))
        
        override_dir = job_details.get('override_output_dir') or job_details.get('target_folder_path')
        
        base_dir = self.dir_input.text().strip()
        if not override_dir or os.path.normpath(override_dir) == os.path.normpath(base_dir):
            if service and user_id and hasattr(self, 'creator_name_cache'):
                creator_name = self.creator_name_cache.get((service.lower(), str(user_id)), str(user_id))
                safe_creator_name = clean_folder_name(creator_name)
                
                if safe_creator_name:
                    override_dir = os.path.join(base_dir, safe_creator_name)

        ppw_init_args = {
            **common_args, 
            'post_data': dummy_post_data, 
            'service': service, 
            'user_id': user_id, 
            'api_url_input': job_details.get('api_url_input', ''),
            'override_output_dir': override_dir
        }
        
        worker = PostProcessorWorker(**ppw_init_args)

        self.log_signal.emit(f"   🔄 Retry Pipeline: Processing '{file_info.get('name', 'file')}' in '{override_dir}'...")
        result_tuple = worker.process()
        
        result_tuple = worker.process()
        
        dl_count = result_tuple[0]
        skip_count = result_tuple[1]
        retryable_errors = result_tuple[3]
        permanent_errors = result_tuple[4]

        if retryable_errors or permanent_errors:
            return False 

        is_successful_download = (dl_count > 0)
        is_resolved_as_skipped = (skip_count > 0 and dl_count == 0)

        return is_successful_download or is_resolved_as_skipped

    def _handle_retry_future_result (self ,future ):
        self .processed_retry_count +=1 
        was_successful =False 
        try :
            if future .cancelled ():
                self .log_signal .emit ("    A retry task was cancelled.")
            elif future .exception ():
                self .log_signal .emit (f"❌ Retry task worker error: {future .exception ()}")
            else :
                was_successful =future .result ()
                job_details =self .active_retry_futures_map .pop (future ,None )
                if was_successful :
                    self .succeeded_retry_count +=1 
                else :
                    self .failed_retry_count_in_session +=1 
                    if job_details :
                        self .permanently_failed_files_for_dialog .append (job_details )
        except Exception as e :
            self .log_signal .emit (f"❌ Error in _handle_retry_future_result: {e }")
            self .failed_retry_count_in_session +=1 

        progress_percent_retry =(self .processed_retry_count /self .total_files_for_retry *100 )if self .total_files_for_retry >0 else 0 
        self .progress_label .setText (
        self ._tr ("progress_posts_text","Progress: {processed_posts} / {total_posts} posts ({progress_percent:.1f}%)").format (processed_posts =self .processed_retry_count ,total_posts =self .total_files_for_retry ,progress_percent =progress_percent_retry ).replace ("posts","files")+
        f" ({self ._tr ('succeeded_text','Succeeded')}: {self .succeeded_retry_count }, {self ._tr ('failed_text','Failed')}: {self .failed_retry_count_in_session })"
        )

        if self .processed_retry_count >=self .total_files_for_retry :
            if all (f .done ()for f in self .active_retry_futures ):
                QTimer .singleShot (0 ,self ._retry_session_finished )


    def _retry_session_finished(self):
        self.log_signal.emit("🏁 Retry session finished.")
        self.log_signal.emit(f"    Summary: {self.succeeded_retry_count} Succeeded, {self.failed_retry_count_in_session} Failed.")
        self.is_in_retry_session = False
        if self.retry_thread_pool:
            self.retry_thread_pool.shutdown(wait=True)
            self.retry_thread_pool = None

        auto_retry_enabled = self.settings.value(AUTO_RETRY_ON_FINISH_KEY, False, type=bool)
        
        if auto_retry_enabled and self.failed_retry_count_in_session > 0:
            num_files_to_retry = self.failed_retry_count_in_session
            self.log_signal.emit("=" * 40)
            self.log_signal.emit(f"🔄 Auto-retry is enabled. Looping again for {num_files_to_retry} newly failed file(s)...")
            
            self._start_failed_files_retry_session(files_to_retry_list=list(self.permanently_failed_files_for_dialog))
            return

        if os.path.exists(self.session_file_path):
            try:
                with self.session_lock:
                    with open(self.session_file_path, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    
                    if 'download_state' in session_data:
                        session_data['download_state']['permanently_failed_files'] = self.permanently_failed_files_for_dialog
                    self._save_session_file(session_data)
                    self.log_signal.emit("ℹ️ Session file updated with retry results.")

            except Exception as e:
                self.log_signal.emit(f"⚠️ Could not update session file after retry: {e}")

        if self.external_link_download_thread and not self.external_link_download_thread.isRunning():
            self.external_link_download_thread.deleteLater()
            self.external_link_download_thread = None

        self.active_retry_futures.clear()
        self.active_retry_futures_map.clear()
        self.files_for_current_retry_session.clear()

        if self.permanently_failed_files_for_dialog:
            self.log_signal.emit(f"🆘 {self._tr('error_button_text','Error')} button enabled. {len(self.permanently_failed_files_for_dialog)} file(s) ultimately failed and can be viewed.")

        self.set_ui_enabled(not self._is_download_active())
        if self.cancel_btn:
            self.cancel_btn.setText(self._tr("cancel_button_text", "Cancel & Reset UI"))
            
        self.progress_label.setText(
            f"{self._tr('retry_finished_text','Retry Finished')}. "
            f"{self._tr('succeeded_text','Succeeded')}: {self.succeeded_retry_count}, "
            f"{self._tr('failed_text','Failed')}: {self.failed_retry_count_in_session}. "
            f"{self._tr('ready_for_new_task_text','Ready for new task.')}"
        )
        self.file_progress_label.setText("")
        
        if self.pause_event:
            self.pause_event.clear()
        self.is_paused = False
        
        self._update_error_button_count()

    def toggle_active_log_view (self ):
        if self .current_log_view =='progress':
            self .current_log_view ='missed_character'
            if self .log_view_stack :self .log_view_stack .setCurrentIndex (1 )
            if self .log_verbosity_toggle_button :
                self .log_verbosity_toggle_button .setIcon (QIcon (self .CLOSED_EYE_ICON_PATH ))
                self .log_verbosity_toggle_button .setToolTip ("Current View: Missed Character Log. Click to switch to Progress Log.")
            if self .progress_log_label :self .progress_log_label .setText (self ._tr ("missed_character_log_label_text",f"<img src='{get_asset_path('assets/Svg/block.svg')}' width='13' height='13' align='top'> Missed Character Log:"))
        else :
            self .current_log_view ='progress'
            if self .log_view_stack :self .log_view_stack .setCurrentIndex (0 )
            if self .log_verbosity_toggle_button :
                self .log_verbosity_toggle_button .setIcon (QIcon (self .EYE_ICON_PATH ))
                self .log_verbosity_toggle_button .setToolTip ("Current View: Progress Log. Click to switch to Missed Character Log.")
            if self .progress_log_label :self .progress_log_label .setText (self ._tr ("progress_log_label_text",f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Progress Log:"))

    def reset_application_state(self):
        """
        The panic button / clear state function.
        Forcefully shuts down all active threads, deletes temporary files, clears all input 
        boxes, and resets the application back to its default idle state.
        """
        self.log_signal.emit("🔄 Resetting application state to defaults...")

        if self._is_download_active():
            self.log_signal.emit("   Cancelling all active background tasks for reset...")
            self.cancellation_event.set() 

            if self.download_thread and self.download_thread.isRunning():
                self.download_thread.requestInterruption()
            if self.thread_pool:
                self.thread_pool.shutdown(wait=False, cancel_futures=True)
                self.thread_pool = None
            if self.external_link_download_thread and self.external_link_download_thread.isRunning():
                self.external_link_download_thread.cancel()
            if hasattr(self, 'retry_thread_pool') and self.retry_thread_pool:
                self.retry_thread_pool.shutdown(wait=False, cancel_futures=True)
                self.retry_thread_pool = None
        
        self.cancellation_event.clear()

        if self.pause_event:
            self.pause_event.clear()
        self.is_paused = False

        self._clear_session_file()
        self._perform_soft_ui_reset()
        self._load_saved_download_location()
        self.main_log_output.clear()
        self.external_log_output.clear()
        if self.missed_character_log_output:
            self.missed_character_log_output.clear()

        self.current_log_view = 'progress'
        if self.log_view_stack:
            self.log_view_stack.setCurrentIndex(0)
        if self.progress_log_label:
            self.progress_log_label.setText(self._tr("progress_log_label_text", f"<img src='{get_asset_path('assets/Svg/scroll.svg')}' width='13' height='13' align='top'> Progress Log:"))
        if self.log_verbosity_toggle_button:
            self.log_verbosity_toggle_button.setIcon(QIcon(self.EYE_ICON_PATH))
            self.log_verbosity_toggle_button.setToolTip("Current View: Progress Log. Click to switch to Missed Character Log.")
        self.external_link_queue.clear()
        self.extracted_links_cache = []
        self._is_processing_external_link_queue = False
        self._current_link_post_title = None
        self.progress_label.setText(self._tr("progress_idle_text", "Progress: Idle"))
        self.file_progress_label.setText("")
        with self.downloaded_files_lock:
            self.downloaded_files.clear()
        with self.downloaded_file_hashes_lock:
            self.downloaded_file_hashes.clear()
        self.missed_title_key_terms_count.clear()
        self.missed_title_key_terms_examples.clear()
        self.logged_summary_for_key_term.clear()
        self.already_logged_bold_key_terms.clear()
        self.missed_key_terms_buffer.clear()
        self.favorite_download_queue.clear()
        self.only_links_log_display_mode = LOG_DISPLAY_LINKS
        self.mega_download_log_preserved_once = False
        self.permanently_failed_files_for_dialog.clear()
        self._update_error_button_count()
        self.favorite_download_scope = FAVORITE_SCOPE_SELECTED_LOCATION
        self._update_favorite_scope_button_text()
        self.retryable_failed_files_info.clear()
        self.cancellation_message_logged_this_session = False
        self.is_processing_favorites_queue = False
        self.total_posts_to_process = 0
        self.processed_posts_count = 0
        self.download_counter = 0
        self.skip_counter = 0
        self.all_kept_original_filenames = []
        self.is_paused = False
        self.is_fetcher_thread_running = False
        self.interrupted_session_data = None
        self.is_restore_pending = False

        self.active_update_profile = None
        self.settings.setValue(MANGA_FILENAME_STYLE_KEY, self.manga_filename_style)
        self.settings.setValue(SKIP_WORDS_SCOPE_KEY, self.skip_words_scope)
        self.settings.sync()
        self._update_manga_filename_style_button_text()
        self.update_ui_for_manga_mode(self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False)
        self.is_fetching_only = False
        self.fetched_posts_for_download = []
        self.is_ready_to_download_fetched = False 
        self.fetched_posts_for_batch_update = []
        self.is_ready_to_download_batch_update = False        
        self.allcomic_warning_shown = False 

        self.set_ui_enabled(True)
        self.log_signal.emit("✅ Application fully reset. Ready for new download.")
        self.is_processing_favorites_queue = False
        self.current_processing_favorite_item_info = None
        self.favorite_download_queue.clear()
        self.interrupted_session_data = None
        self.is_restore_pending = False
        self.last_link_input_text_for_queue_sync = ""
        
    def _show_feature_guide (self ):
        steps_content_keys =[
        ("help_guide_step1_title","help_guide_step1_content"),
        ("help_guide_step2_title","help_guide_step2_content"),
        ("help_guide_step3_title","help_guide_step3_content"),
        ("help_guide_step4_title","help_guide_step4_content"),
        ("help_guide_step5_title","help_guide_step5_content"),
        ("help_guide_step6_title","help_guide_step6_content"),
        ("help_guide_step7_title","help_guide_step7_content"),
        ("help_guide_step8_title","help_guide_step8_content"),
        ("help_guide_step9_title","help_guide_step9_content"),
        ("column_header_post_title","Post Title"),
        ("column_header_date_uploaded","Date Uploaded"),
        ]

        steps =[
        ]
        for title_key ,content_key in steps_content_keys :
            title =self ._tr (title_key ,title_key )
            content =self ._tr (content_key ,f"Content for {content_key } not found.")
            steps .append ((title ,content ))

        guide_dialog =HelpGuideDialog (steps ,self )
        guide_dialog .exec_ ()

    def prompt_add_character (self ,character_name ):
        global KNOWN_NAMES 
        reply =QMessageBox .question (self ,"Add Filter Name to Known List?",f"The name '{character_name }' was encountered or used as a filter.\nIt's not in your known names list (used for folder suggestions).\nAdd it now?",QMessageBox .Yes |QMessageBox .No ,QMessageBox .Yes )
        result =(reply ==QMessageBox .Yes )
        if result :
            if self .add_new_character (name_to_add =character_name ,
            is_group_to_add =False ,
            aliases_to_add =[character_name ],
            suppress_similarity_prompt =False ):
                self .log_signal .emit (f"✅ Added '{character_name }' to known names via background prompt.")
            else :result =False ;self .log_signal .emit (f"ℹ️ Adding '{character_name }' via background prompt was declined, failed, or a similar name conflict was not overridden.")
        self .character_prompt_response_signal .emit (result )

    def receive_add_character_result (self ,result ):
        with QMutexLocker (self .prompt_mutex ):self ._add_character_response =result 
        self .log_signal .emit (f"    Main thread received character prompt response: {'Action resulted in addition/confirmation'if result else 'Action resulted in no addition/declined'}")

    def _update_multipart_toggle_button_text(self):
        if hasattr(self, 'multipart_toggle_button'):
            if self.allow_multipart_download_setting:
                scope_text = self.multipart_scope.capitalize()
                self.multipart_toggle_button.setText(self._tr("multipart_on_button_text", f"Multi-part: {scope_text}"))
                self.multipart_toggle_button.setToolTip(self._tr("multipart_on_button_tooltip", f"Multipart download is ON. Applied to: {scope_text} files. Click to change."))
            else:
                self.multipart_toggle_button.setText(self._tr("multipart_off_button_text", "Multi-part: OFF"))
                self.multipart_toggle_button.setToolTip(self._tr("multipart_off_button_tooltip", "Multipart download is OFF. Click to enable and set options."))

    def _update_error_button_count(self):
        """Updates the Error button text to show the count of failed files."""
        if not hasattr(self, 'error_btn'):
            return

        count = len(self.permanently_failed_files_for_dialog)
        base_text = self._tr("error_button_text", "Error")

        if count > 0:
            self.error_btn.setText(f"({count}) {base_text}")
        else:
            self.error_btn.setText(base_text)

    def _toggle_multipart_mode(self):
        """
        Opens the Multipart Scope Dialog and updates settings based on user choice.
        """
        current_scope = self.multipart_scope if self.allow_multipart_download_setting else 'both'
        dialog = MultipartScopeDialog(current_scope, self.multipart_parts_count, self.multipart_min_size_mb, self)
        
        if dialog.exec_() == QDialog.Accepted:
            self.multipart_scope = dialog.get_selected_scope()
            self.multipart_parts_count = dialog.get_selected_parts()
            self.multipart_min_size_mb = dialog.get_selected_min_size()
            self.allow_multipart_download_setting = True
            self.log_signal.emit(f"ℹ️ Multi-part download enabled: Scope='{self.multipart_scope.capitalize()}', Parts={self.multipart_parts_count}, Min Size={self.multipart_min_size_mb} MB")
        else:
            self.allow_multipart_download_setting = False
            self.log_signal.emit("ℹ️ Multi-part download setting remains OFF.")
            
        self._update_multipart_toggle_button_text()
        self.settings.setValue(ALLOW_MULTIPART_DOWNLOAD_KEY, self.allow_multipart_download_setting)

    def _open_known_txt_file (self ):
        if not os .path .exists (self .config_file ):
            QMessageBox .warning (self ,"File Not Found",
            f"The file 'Known.txt' was not found at:\n{self .config_file }\n\n"
            "It will be created automatically when you add a known name or close the application.")
            self .log_signal .emit (f"ℹ️ 'Known.txt' not found at {self .config_file }. It will be created later.")
            return 

        try :
            if sys .platform =="win32":
                os .startfile (self .config_file )
            elif sys .platform =="darwin":
                subprocess .call (['open',self .config_file ])
            else :
                subprocess .call (['xdg-open',self .config_file ])
            self .log_signal .emit (f"ℹ️ Attempted to open '{os .path .basename (self .config_file )}' with the default editor.")
        except FileNotFoundError :
            QMessageBox .critical (self ,"Error",f"Could not find '{os .path .basename (self .config_file )}' at {self .config_file } to open it.")
            self .log_signal .emit (f"❌ Error: '{os .path .basename (self .config_file )}' not found at {self .config_file } when trying to open.")
        except Exception as e :
            QMessageBox .critical (self ,"Error Opening File",f"Could not open '{os .path .basename (self .config_file )}':\n{e }")
            self .log_signal .emit (f"❌ Error opening '{os .path .basename (self .config_file )}': {e }")

    def _show_add_to_filter_dialog (self ):
        global KNOWN_NAMES 
        if not KNOWN_NAMES :
            QMessageBox .information (self ,"No Known Names","Your 'Known.txt' list is empty. Add some names first.")
            return 

        dialog = KnownNamesFilterDialog(KNOWN_NAMES, self)
        if dialog .exec_ ()==QDialog .Accepted :
            selected_entries =dialog .get_selected_entries ()
            if selected_entries :
                self ._add_names_to_character_filter_input (selected_entries )

    def _add_names_to_character_filter_input (self ,selected_entries ):
        """
        Adds the selected known name entries to the character filter input field.
        """
        if not selected_entries :
            return 

        names_to_add_str_list =[]
        for entry in selected_entries :
            if entry .get ("is_group"):
                aliases_str =", ".join (entry .get ("aliases",[]))
                names_to_add_str_list .append (f"({aliases_str })~")
            else :
                names_to_add_str_list .append (entry .get ("name",""))

        names_to_add_str_list =[s for s in names_to_add_str_list if s ]

        if not names_to_add_str_list :
            return 

        current_filter_text =self .character_input .text ().strip ()
        new_text_to_append =", ".join (names_to_add_str_list )

        self .character_input .setText (f"{current_filter_text }, {new_text_to_append }"if current_filter_text else new_text_to_append )
        self .log_signal .emit (f"ℹ️ Added to character filter: {new_text_to_append }")

    def _update_favorite_scope_button_text (self ):
        if not hasattr (self ,'favorite_scope_toggle_button')or not self .favorite_scope_toggle_button :
            return 
        if self .favorite_download_scope ==FAVORITE_SCOPE_SELECTED_LOCATION :
            self .favorite_scope_toggle_button .setText (self ._tr ("favorite_scope_selected_location_text","Scope: Selected Location"))

        elif self .favorite_download_scope ==FAVORITE_SCOPE_ARTIST_FOLDERS :
            self .favorite_scope_toggle_button .setText (self ._tr ("favorite_scope_artist_folders_text","Scope: Artist Folders"))

        else :
            self .favorite_scope_toggle_button .setText (self ._tr ("favorite_scope_unknown_text","Scope: Unknown"))


    def _cycle_favorite_scope (self ):
        if self .favorite_download_scope ==FAVORITE_SCOPE_SELECTED_LOCATION :
            self .favorite_download_scope =FAVORITE_SCOPE_ARTIST_FOLDERS 
        else :
            self .favorite_download_scope =FAVORITE_SCOPE_SELECTED_LOCATION 
        self ._update_favorite_scope_button_text ()
        self .log_signal .emit (f"ℹ️ Favorite download scope changed to: '{self .favorite_download_scope }'")

    def _check_for_updates(self):
        """Phase 1 of Update: Fetches all posts, compares, and prompts the user for confirmation."""
        self.log_signal.emit("🔄 Checking for updates...")
        
        update_url = self.active_update_profile['creator_url'][0]
        processed_ids_from_profile = set(self.active_update_profile['processed_post_ids'])
        self.log_signal.emit(f"   Checking URL: {update_url}")
        
        self.set_ui_enabled(False)
        self.progress_label.setText(self._tr("progress_fetching_all_posts", "Progress: Fetching all post pages..."))
        QCoreApplication.processEvents()

        try:
            post_generator = download_from_api(
                api_url_input=update_url,
                logger=lambda msg: None,
                cancellation_event=self.cancellation_event,
                pause_event=self.pause_event,
                use_cookie=self.use_cookie_checkbox.isChecked(),
                cookie_text=self.cookie_text_input.text(),
                selected_cookie_file=self.selected_cookie_filepath,
                app_base_dir=self.app_base_dir,
                processed_post_ids=processed_ids_from_profile
            )
            all_posts_from_api = [post for batch in post_generator for post in batch]
        except Exception as e:
            self.log_signal.emit(f"❌ Failed to fetch posts during update check: {e}")
            self.download_finished(0, 0, False, [])
            return

        self.log_signal.emit(f"   Fetched a total of {len(all_posts_from_api)} posts from the server.")
        
        self.new_posts_for_update = all_posts_from_api
        
        if not self.new_posts_for_update:
            self.log_signal.emit("✅ Creator is up to date! No new posts found.")
            QMessageBox.information(self, "Up to Date", "No new posts were found for this creator.")
            self._clear_update_selection()
            self.set_ui_enabled(True)
            self.progress_label.setText(self._tr("progress_idle_text", "Progress: Idle"))
            return

        self.log_signal.emit(f"   Found {len(self.new_posts_for_update)} new post(s). Waiting for user confirmation to download.")
        self.progress_label.setText(f"Found {len(self.new_posts_for_update)} new post(s). Ready to download.")
        self._update_button_states_and_connections() 

    def _start_confirmed_update_download(self):
        """Phase 2 of Update: Starts the download of posts found during the check."""
        self.log_signal.emit(f"✅ User confirmed. Starting download for {len(self.new_posts_for_update)} new post(s).")
        self.main_log_output.clear()
        
        update_url = self.active_update_profile['creator_url'][0]
        service, user_id, _ = extract_post_info(update_url)

        base_download_dir_from_ui = self.dir_input.text().strip()
        self.log_signal.emit(f"   Update session will save to base folder: {base_download_dir_from_ui}")

        raw_character_filters_text = self.character_input.text().strip()
        parsed_character_filter_objects, download_commands = self._parse_character_filters(raw_character_filters_text)

        try:
            num_threads_from_gui = int(self.thread_count_input.text().strip())
        except ValueError:
            num_threads_from_gui = 1
        effective_num_file_threads_per_worker = max(1, min(num_threads_from_gui, MAX_FILE_THREADS_PER_POST_OR_WORKER))

        creator_folder_ignore_words_for_run = None
        is_full_creator_download = not self.active_update_profile.get('post_id')
        if is_full_creator_download and not parsed_character_filter_objects:
            creator_folder_ignore_words_for_run = CREATOR_DOWNLOAD_DEFAULT_FOLDER_IGNORE_WORDS

        args_template = {
            'api_url_input': update_url, 
            'download_root': base_download_dir_from_ui,
            'override_output_dir': None,
            'known_names': list(KNOWN_NAMES), 
            'filter_character_list': parsed_character_filter_objects,
            'emitter': self.worker_to_gui_queue, 
            'unwanted_keywords': FOLDER_NAME_STOP_WORDS,
            'filter_mode': self.get_filter_mode(), 
            'skip_zip': self.skip_zip_checkbox.isChecked(),
            'use_subfolders': self.use_subfolders_checkbox.isChecked(),
            'use_post_subfolders': self.use_subfolder_per_post_checkbox.isChecked(),
            'target_post_id_from_initial_url': None, 
            'custom_folder_name': self.custom_folder_input.text().strip(),
            'compress_images': self.compress_images_checkbox.isChecked(),
            'download_thumbnails': self.download_thumbnails_checkbox.isChecked(),
            'service': service, 'user_id': user_id, 'pause_event': self.pause_event,
            'cancellation_event': self.cancellation_event, 
            'downloaded_files': self.downloaded_files,
            'downloaded_file_hashes': self.downloaded_file_hashes,
            'downloaded_files_lock': self.downloaded_files_lock,
            'downloaded_file_hashes_lock': self.downloaded_file_hashes_lock,
            'dynamic_character_filter_holder': self.dynamic_character_filter_holder,
            'skip_words_list': [part.strip().lower() for part in self.skip_words_input.text().strip().split(',') if part.strip() and not part.strip().startswith('[')],
            'skip_file_size_mb': next((int(re.search(r'\[(\d+)\]', part).group(1)) for part in self.skip_words_input.text().strip().split(',') if re.fullmatch(r'\[\d+\]', part.strip())), None),
            'skip_words_scope': self.get_skip_words_scope(), 
            'show_external_links': self.external_links_checkbox.isChecked(),
            'extract_links_only': self.radio_only_links.isChecked(), 
            'skip_current_file_flag': None,
            'manga_mode_active': self.manga_mode_checkbox.isChecked(), 
            'manga_filename_style': self.manga_filename_style,
            'char_filter_scope': self.get_char_filter_scope(),
            'remove_from_filename_words_list': [word.strip() for word in self.remove_from_filename_input.text().strip().split(',') if word.strip()],
            'allow_multipart_download': self.allow_multipart_download_setting, 
            'cookie_text': self.cookie_text_input.text(),
            'use_cookie': self.use_cookie_checkbox.isChecked(),
            'selected_cookie_file': self.selected_cookie_filepath, 
            'app_base_dir': self.app_base_dir,
            'manga_date_prefix': self.manga_date_prefix_input.text().strip(), 
            'manga_date_file_counter_ref': None,
            'scan_content_for_images': self.scan_content_images_checkbox.isChecked(),
            'creator_name_cache': self.creator_name_cache,            
            'creator_download_folder_ignore_words': creator_folder_ignore_words_for_run,
            'num_file_threads_for_worker': effective_num_file_threads_per_worker,
            'multipart_scope': 'files',
            'multipart_parts_count': 8,
            'multipart_min_size_mb': 100,

            'manga_global_file_counter_ref': None,
            'use_date_prefix_for_subfolder': self.date_prefix_checkbox.isChecked(),
            'keep_in_post_duplicates': self.keep_duplicates_checkbox.isChecked(),
            'keep_duplicates_mode': self.keep_duplicates_mode, 
            'keep_duplicates_limit': self.keep_duplicates_limit,
            'downloaded_hash_counts': self.downloaded_hash_counts, 
            'downloaded_hash_counts_lock': self.downloaded_hash_counts_lock,
            'session_file_path': self.session_file_path, 
            'session_lock': self.session_lock,
            'text_only_scope': self.more_filter_scope, 
            'text_export_format': self.text_export_format,
            'single_pdf_mode': self.single_pdf_setting, 
            'project_root_dir': self.app_base_dir,
            'processed_post_ids': list(self.active_update_profile['processed_post_ids']),
            'sfp_threshold': download_commands.get('sfp_threshold'),
            'date_prefix_format': self.date_prefix_format,
            'domain_override': download_commands.get('domain_override'),
            'archive_only_mode': download_commands.get('archive_only', False),
            'manga_custom_filename_format': self.custom_manga_filename_format,
            'manga_custom_date_format': self.manga_custom_date_format,
            'handle_unknown_mode': download_commands.get('handle_unknown', False),
            'download_revisions': self.revisions_checkbox.isChecked() if hasattr(self, 'revisions_checkbox') else False,       
            'visual_sort_active': getattr(self, 'visual_sort_checkbox', None) and self.visual_sort_checkbox.isChecked(),
            'user_data_path': getattr(self, 'user_data_path', "")
        }

        num_threads = int(self.thread_count_input.text()) if self.use_multithreading_checkbox.isChecked() else 1
        self.thread_pool = ThreadPoolExecutor(max_workers=num_threads, thread_name_prefix='UpdateWorker_')
        self.total_posts_to_process = len(self.new_posts_for_update)
        self.processed_posts_count = 0
        self.overall_progress_signal.emit(self.total_posts_to_process, 0)
        
        ppw_expected_keys = list(PostProcessorWorker.__init__.__code__.co_varnames)[1:]
        
        for post_data in self.new_posts_for_update:
            self._submit_post_to_worker_pool(
                post_data, args_template, 1, self.worker_to_gui_queue, ppw_expected_keys, {}
            )
        return True

    def _show_empty_popup (self ):
        """Creates and shows the empty popup dialog."""
        if self.is_restore_pending:
            QMessageBox.information(self, self._tr("restore_pending_title", "Restore Pending"),
                                    self._tr("restore_pending_message_creator_selection",
                                             "Please 'Restore Download' or 'Discard Session' before selecting new creators."))
            return
        dialog = EmptyPopupDialog(self.user_data_path, self)
        if dialog.exec_() == QDialog.Accepted:
            

            if hasattr(dialog, 'update_profiles_list') and dialog.update_profiles_list:
                self.active_update_profiles_list = dialog.update_profiles_list
                load_settings_requested = getattr(dialog, 'load_settings_into_ui_requested', False)
                self.override_update_profile_settings = load_settings_requested 
                
                if load_settings_requested:
                    self.log_signal.emit("ℹ️ User requested to edit settings. Loading profile settings into UI...")
                    first_profile_settings = self.active_update_profiles_list[0]['data'].get('settings', {})
                    self._load_ui_from_settings_dict(first_profile_settings)
                    
                self.log_signal.emit(f"ℹ️ Loaded {len(self.active_update_profiles_list)} creator profile(s). Checking for updates...")
                self.link_input.setText(f"{len(self.active_update_profiles_list)} profiles loaded for update check...")
                
                self._start_batch_update_check(self.active_update_profiles_list)

           
            elif hasattr(dialog, 'selected_creators_for_queue') and dialog.selected_creators_for_queue:
                self.active_update_profile = None
                self.favorite_download_queue.clear()

                for creator_data in dialog.selected_creators_for_queue:
                    service = creator_data.get('service')
                    creator_id = creator_data.get('id')
                    creator_name = creator_data.get('name', 'Unknown Creator')
                    domain = self._get_domain_for_service(service)

                    if service and creator_id:
                        url = f"https://{domain}/{service}/user/{creator_id}"
                        queue_item = {
                            'url': url,
                            'name': creator_name,
                            'name_for_folder': creator_name,
                            'type': 'creator_popup_selection',
                            'scope_from_popup': dialog.current_scope_mode
                        }
                        self.favorite_download_queue.append(queue_item)

                if self.favorite_download_queue:
                    if hasattr(self, 'link_input'):
                        creator_names = [item['name'] for item in self.favorite_download_queue]
                        display_text = ", ".join(creator_names)
                        self.link_input.setText(display_text)
                    
                    self.log_signal.emit(f"ℹ️ {len(self.favorite_download_queue)} creators added to download queue from popup. Click 'Start Download' to process.")
                    if hasattr(self, 'link_input'):
                        self.last_link_input_text_for_queue_sync = self.link_input.text()

                self.update_ui_for_manga_mode(self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False)
    def _load_saved_cookie_settings(self):
        """Loads and applies saved cookie settings on startup."""
        try:
            cookie_content_saved = self.settings.value(COOKIE_TEXT_KEY, "", type=str)

            self.use_cookie_checkbox.setChecked(False)

            if cookie_content_saved:
                self.cookie_text_input.setText(cookie_content_saved)
                
                if os.path.exists(cookie_content_saved):
                    self.selected_cookie_filepath = cookie_content_saved
                    self.cookie_text_input.setReadOnly(True)
                    self._update_cookie_input_placeholders_and_tooltips()
                
                self.log_signal.emit(f"ℹ️ Loaded saved cookie path, but kept 'Use Cookies' unchecked by default.")
        except Exception as e:
            self.log_signal.emit(f"⚠️ Could not load saved cookie settings: {e}")

    def _show_favorite_artists_dialog (self ):
        """
        Opens the popup window where users can browse their saved creators 
        and select which ones to add to the download queue.
        """
        if self ._is_download_active ()or self .is_processing_favorites_queue :
            QMessageBox .warning (self ,"Busy","Another download operation is already in progress.")
            return 

        cookies_config ={
        'use_cookie':self .use_cookie_checkbox .isChecked ()if hasattr (self ,'use_cookie_checkbox')else False ,
        'cookie_text':self .cookie_text_input .text ()if hasattr (self ,'cookie_text_input')else "",
        'selected_cookie_file':self .selected_cookie_filepath ,
        'app_base_dir':self .app_base_dir 
        }

        dialog =FavoriteArtistsDialog (self ,cookies_config )
        if dialog .exec_ ()==QDialog .Accepted :
            selected_artists =dialog .get_selected_artists ()
            if selected_artists :
                if len (selected_artists )>1 and self .link_input :
                    display_names =", ".join ([artist ['name']for artist in selected_artists ])
                    if self .link_input :
                        self .link_input .clear ()
                        self .link_input .setPlaceholderText (f"{len (selected_artists )} favorite artists selected for download queue.")
                    self .log_signal .emit (f"ℹ️ Multiple favorite artists selected. Displaying names: {display_names }")
                elif len (selected_artists )==1 :
                    self .link_input .setText (selected_artists [0 ]['url'])
                    self .log_signal .emit (f"ℹ️ Single favorite artist selected: {selected_artists [0 ]['name']}")

                self .log_signal .emit (f"ℹ️ Queuing {len (selected_artists )} favorite artist(s) for download.")
                for artist_data in selected_artists :
                    self .favorite_download_queue .append ({'url':artist_data ['url'],'name':artist_data ['name'],'name_for_folder':artist_data ['name'],'type':'artist'})

                if not self .is_processing_favorites_queue :
                    self ._process_next_favorite_download ()
            else :
                self .log_signal .emit ("ℹ️ No favorite artists were selected for download.")
                QMessageBox .information (self ,
                self ._tr ("fav_artists_no_selection_title","No Selection"),
                self ._tr ("fav_artists_no_selection_message","Please select at least one artist to download."))
        else :
            self .log_signal .emit ("ℹ️ Favorite artists selection cancelled.")

    def _show_favorite_posts_dialog (self ):
        if self ._is_download_active ()or self .is_processing_favorites_queue :
            QMessageBox .warning (self ,"Busy","Another download operation is already in progress.")
            return 

        cookies_config ={
        'use_cookie':self .use_cookie_checkbox .isChecked ()if hasattr (self ,'use_cookie_checkbox')else False ,
        'cookie_text':self .cookie_text_input .text ()if hasattr (self ,'cookie_text_input')else "",
        'selected_cookie_file':self .selected_cookie_filepath ,
        'app_base_dir':self .app_base_dir 
        }
        global KNOWN_NAMES 

        target_domain_preference_for_fetch =None 

        if cookies_config['use_cookie']:
            self.log_signal.emit("Favorite Posts: 'Use Cookie' is checked. Determining target domain...")
            
            kemono_cookies = prepare_cookies_for_request(
                cookies_config['use_cookie'], cookies_config['cookie_text'], cookies_config['selected_cookie_file'],
                cookies_config['app_base_dir'], lambda msg: self.log_signal.emit(f"[FavPosts Cookie Check] {msg}"),
                target_domain="kemono.cr"
            )
            if not kemono_cookies:
                self.log_signal.emit("  ↳ No cookies for kemono.cr, trying fallback kemono.su...")
                kemono_cookies = prepare_cookies_for_request(
                    cookies_config['use_cookie'], cookies_config['cookie_text'], cookies_config['selected_cookie_file'],
                    cookies_config['app_base_dir'], lambda msg: self.log_signal.emit(f"[FavPosts Cookie Check] {msg}"),
                    target_domain="kemono.su"
                )

            coomer_cookies = prepare_cookies_for_request(
                cookies_config['use_cookie'], cookies_config['cookie_text'], cookies_config['selected_cookie_file'],
                cookies_config['app_base_dir'], lambda msg: self.log_signal.emit(f"[FavPosts Cookie Check] {msg}"),
                target_domain="coomer.st"
            )
            if not coomer_cookies:
                self.log_signal.emit("  ↳ No cookies for coomer.st, trying fallback coomer.su...")
                coomer_cookies = prepare_cookies_for_request(
                    cookies_config['use_cookie'], cookies_config['cookie_text'], cookies_config['selected_cookie_file'],
                    cookies_config['app_base_dir'], lambda msg: self.log_signal.emit(f"[FavPosts Cookie Check] {msg}"),
                    target_domain="coomer.su"
                )

            kemono_ok = bool(kemono_cookies)
            coomer_ok = bool(coomer_cookies)

            if kemono_ok and not coomer_ok:
                target_domain_preference_for_fetch = "kemono.cr"
                self.log_signal.emit("  ↳ Only Kemono cookies loaded. Will fetch favorites from Kemono.cr only.")
            elif coomer_ok and not kemono_ok:
                target_domain_preference_for_fetch = "coomer.st"
                self.log_signal.emit("  ↳ Only Coomer cookies loaded. Will fetch favorites from Coomer.st only.")
            elif kemono_ok and coomer_ok:
                target_domain_preference_for_fetch = None
                self.log_signal.emit("  ↳ Cookies for both Kemono and Coomer loaded. Will attempt to fetch from both.")
            else:
                self.log_signal.emit("  ↳ No valid cookies loaded for Kemono.cr or Coomer.st.")
                cookie_help_dialog = CookieHelpDialog(self, self)
                cookie_help_dialog.exec_()
                return
        else :
            self .log_signal .emit ("Favorite Posts: 'Use Cookie' is NOT checked. Cookies are required.")
            cookie_help_dialog =CookieHelpDialog (self ,self )
            cookie_help_dialog .exec_ ()
            return 

        dialog =FavoritePostsDialog (self ,cookies_config ,KNOWN_NAMES ,target_domain_preference_for_fetch )
        if dialog .exec_ ()==QDialog .Accepted :
            selected_posts =dialog .get_selected_posts ()
            if selected_posts :
                self .log_signal .emit (f"ℹ️ Queuing {len (selected_posts )} favorite post(s) for download.")
                for post_data in selected_posts :
                    domain =self ._get_domain_for_service (post_data ['service'])
                    direct_post_url =f"https://{domain }/{post_data ['service']}/user/{str (post_data ['creator_id'])}/post/{str (post_data ['post_id'])}"

                    queue_item ={
                    'url':direct_post_url ,
                    'name':post_data ['title'],
                    'name_for_folder':post_data ['creator_name_resolved'],
                    'type':'post'
                    }
                    self .favorite_download_queue .append (queue_item )

                if not self .is_processing_favorites_queue :
                    self ._process_next_favorite_download ()
            else :
                self .log_signal .emit ("ℹ️ No favorite posts were selected for download.")
        else :
            self .log_signal .emit ("ℹ️ Favorite posts selection cancelled.")

    def _process_next_favorite_download(self):

        if self.favorite_download_queue and not self.is_processing_favorites_queue:
            manga_mode_is_checked = self.manga_mode_checkbox.isChecked() if self.manga_mode_checkbox else False
            char_filter_is_empty = not self.character_input.text().strip()
            extract_links_only = (self.radio_only_links and self.radio_only_links.isChecked())

        if self ._is_download_active ():
            self .log_signal .emit ("ℹ️ Waiting for current download to finish before starting next favorite.")
            return 
        if not self .favorite_download_queue :
            if self .is_processing_favorites_queue :
                self .is_processing_favorites_queue =False 
                item_type_log ="item"
                if hasattr (self ,'current_processing_favorite_item_info')and self .current_processing_favorite_item_info :
                    item_type_log =self .current_processing_favorite_item_info .get ('type','item')
                self .log_signal .emit (f"✅ All {item_type_log } downloads from favorite queue have been processed.")
                self .set_ui_enabled (True )
            return 
        if not self .is_processing_favorites_queue :
            self .is_processing_favorites_queue =True 
        self .current_processing_favorite_item_info =self .favorite_download_queue .popleft ()
        next_url =self .current_processing_favorite_item_info ['url']
        item_display_name =self .current_processing_favorite_item_info .get ('name','Unknown Item')

        item_type = self.current_processing_favorite_item_info.get('type', 'artist')
        self.log_signal.emit(f"▶️ Processing next favorite from queue ({item_type}): '{item_display_name}' ({next_url})")

        if 'fap-nation.com' in next_url or 'fap-nation.org' in next_url:
            self.log_signal.emit("   (Fap-Nation batch item detected, using dedicated thread)")
            output_dir = self.dir_input.text().strip()
            use_post_subfolder = self.use_subfolder_per_post_checkbox.isChecked()
            self.download_thread = FapNationDownloadThread(
                next_url, 
                output_dir, 
                use_post_subfolder, 
                self.pause_event, 
                self.cancellation_event, 
                self.actual_gui_signals, 
                self
            )
            self.download_thread.progress_signal.connect(self.handle_main_log)
            self.download_thread.file_progress_signal.connect(self.update_file_progress_display)
            self.download_thread.overall_progress_signal.connect(
                lambda total, processed: self.update_progress_display(total, processed, unit="files")
            )
            self.download_thread.finished_signal.connect(
                lambda dl, skip, cancelled: self.download_finished(dl, skip, cancelled, [])
            )
            self.download_thread.start()
            self._update_button_states_and_connections()
            return

        override_dir = None
        item_scope = self.current_processing_favorite_item_info.get('scope_from_popup')
        if item_scope is None:
            item_scope = self.favorite_download_scope

        main_download_dir = self.dir_input.text().strip()

        should_create_artist_folder = False
      

        if item_type == 'creator_popup_selection' and item_scope == EmptyPopupDialog.SCOPE_CREATORS:
            should_create_artist_folder = True 
        elif item_type != 'creator_popup_selection' and self.favorite_download_scope == FAVORITE_SCOPE_ARTIST_FOLDERS:
            should_create_artist_folder = True
        if self.current_processing_favorite_item_info.get('force_artist_folder'):
            should_create_artist_folder = True
       
        if should_create_artist_folder and main_download_dir:
            folder_name_key = self.current_processing_favorite_item_info.get('name_for_folder', 'Unknown_Folder')
            item_specific_folder_name = clean_folder_name(folder_name_key)
            override_dir = os.path.normpath(os.path.join(main_download_dir, item_specific_folder_name))
            self.log_signal.emit(f"    Scope requires artist folder. Target directory: '{override_dir}'")

        success_starting_download = self.start_download(
            direct_api_url=next_url,
            override_output_dir=override_dir,
            is_continuation=True,
            item_type_from_queue=item_type
        )

        if not success_starting_download:
            self.log_signal.emit(f"⚠️ Failed to initiate download for '{item_display_name}'. Skipping and moving to the next item in queue.")
            QTimer.singleShot(100, self._process_next_favorite_download)

class PdfGenerationThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, posts_data, output_filename, font_path, add_info_page, logger_func):
        super().__init__()
        self.posts_data = posts_data
        self.output_filename = output_filename
        self.font_path = font_path
        self.add_info_page = add_info_page
        self.logger_func = logger_func

    def run(self):
        try:
            self.logger_func("📄 Background Task: Generating Single PDF... (This may take a while)")
            
            success = create_single_pdf_from_content(
                self.posts_data,
                self.output_filename,
                self.font_path,
                self.add_info_page,
                logger=self.logger_func
            )
            
            if success:
                self.finished_signal.emit(True, f"PDF Saved: {os.path.basename(self.output_filename)}")
            else:
                self.finished_signal.emit(False, "PDF generation failed.")
                
        except Exception as e:
            self.finished_signal.emit(False, str(e))            