import os
import sys
import queue
import re
import threading
import time
import traceback
import uuid
import http
import html
import json
from collections import deque, defaultdict
from datetime import datetime
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError, Future
from io import BytesIO
from urllib .parse import urlparse
import requests
import cloudscraper

try:
    from PIL import Image
except ImportError:
    Image = None
try:
    from fpdf import FPDF
    class PDF(FPDF):
        def header(self):
            pass # No header
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, 'Page %s' % self.page_no(), 0, 0, 'C')

except ImportError:
    FPDF = None

try:
    from docx import Document
except ImportError:
    Document = None
from PyQt5 .QtCore import Qt ,QThread ,pyqtSignal ,QMutex ,QMutexLocker ,QObject ,QTimer ,QSettings ,QStandardPaths ,QCoreApplication ,QUrl ,QSize ,QProcess
from .api_client import download_from_api, fetch_post_comments, fetch_single_post_data
from ..services.multipart_downloader import download_file_in_parts, MULTIPART_DOWNLOADER_AVAILABLE
from ..services.drive_downloader import (
    download_mega_file, download_gdrive_file, download_dropbox_file
)
from ..utils.file_utils import (
    is_image, is_video, is_zip, is_rar, is_archive, is_audio, KNOWN_NAMES,
    clean_filename, clean_folder_name
)
from ..utils.network_utils import prepare_cookies_for_request, get_link_platform
from ..utils.text_utils import (
    is_title_match_for_character, is_filename_match_for_character, strip_html_tags,
    extract_folder_name_from_title,
    match_folders_from_title, match_folders_from_filename_enhanced
)
from ..config.constants import *
from ..ui.dialogs.SinglePDF import create_individual_pdf

def robust_clean_name(name):
    """A more robust function to remove illegal characters for filenames and folders."""
    if not name:
        return ""
    illegal_chars_pattern = r'[\x00-\x1f<>:"/\\|?*\']'
    cleaned_name = re.sub(illegal_chars_pattern, '', name)

    cleaned_name = cleaned_name.strip(' .')

    if not cleaned_name:
        return "untitled_folder"
    return cleaned_name

class PostProcessorSignals (QObject ):
    progress_signal =pyqtSignal (str )
    file_download_status_signal =pyqtSignal (bool )
    external_link_signal =pyqtSignal (str ,str ,str ,str ,str )
    file_progress_signal =pyqtSignal (str ,object )
    file_successfully_downloaded_signal =pyqtSignal (dict )
    missed_character_post_signal =pyqtSignal (str ,str )
    worker_finished_signal = pyqtSignal(tuple)

class PostProcessorWorker:
    def __init__(self, post_data, download_root, known_names,
                 filter_character_list, emitter,
                 unwanted_keywords, filter_mode, skip_zip,
                 use_subfolders, use_post_subfolders, target_post_id_from_initial_url, custom_folder_name,
                 compress_images, download_thumbnails, service, user_id, pause_event,
                 api_url_input, cancellation_event,
                 downloaded_files, downloaded_file_hashes, downloaded_files_lock, downloaded_file_hashes_lock,
                 dynamic_character_filter_holder=None, skip_words_list=None,
                 skip_words_scope=SKIP_SCOPE_FILES,
                 show_external_links=False,
                 extract_links_only=False,
                 num_file_threads=4, skip_current_file_flag=None,
                 manga_mode_active=False,
                 manga_filename_style=STYLE_POST_TITLE,
                 char_filter_scope=CHAR_SCOPE_FILES,
                 remove_from_filename_words_list=None,
                 allow_multipart_download=True,
                 cookie_text="",
                 use_cookie=False,
                 override_output_dir=None,
                 selected_cookie_file=None,
                 app_base_dir=None,
                 manga_date_prefix=MANGA_DATE_PREFIX_DEFAULT,
                 manga_date_file_counter_ref=None,
                 scan_content_for_images=False,
                 creator_download_folder_ignore_words=None,
                 manga_global_file_counter_ref=None,
                 use_date_prefix_for_subfolder=False,
                 date_prefix_format="YYYY-MM-DD",
                 keep_in_post_duplicates=False,
                 keep_duplicates_mode=DUPLICATE_HANDLING_HASH,
                 keep_duplicates_limit=0,
                 downloaded_hash_counts=None,
                 downloaded_hash_counts_lock=None,
                 session_file_path=None,
                 session_lock=None,
                 text_only_scope=None,
                 text_export_format='txt',
                 single_pdf_mode=False,
                 project_root_dir=None,
                 processed_post_ids=None,
                 multipart_scope='both',
                 multipart_parts_count=4,
                 multipart_min_size_mb=100,
                 skip_file_size_mb=None,
                 domain_override=None,
                 archive_only_mode=False,
                 manga_custom_filename_format="{published} {title}",
                 manga_custom_date_format="YYYY-MM-DD" ,
                 sfp_threshold=None,
                 handle_unknown_mode=False,
                 creator_name_cache=None,
                 add_info_in_pdf=False

                 ):
        self.post = post_data
        self.download_root = download_root
        self.known_names = known_names
        self.filter_character_list_objects_initial = filter_character_list if filter_character_list else []
        self.dynamic_filter_holder = dynamic_character_filter_holder
        self.unwanted_keywords = unwanted_keywords if unwanted_keywords is not None else set()
        self.filter_mode = filter_mode
        self.skip_zip = skip_zip
        self.use_subfolders = use_subfolders
        self.use_post_subfolders = use_post_subfolders
        self.target_post_id_from_initial_url = target_post_id_from_initial_url
        self.custom_folder_name = custom_folder_name
        self.compress_images = compress_images
        self.download_thumbnails = download_thumbnails
        self.service = service
        self.user_id = user_id
        self.api_url_input = api_url_input
        self.cancellation_event = cancellation_event
        self.pause_event = pause_event
        self.emitter = emitter
        if not self.emitter:
            raise ValueError("PostProcessorWorker requires an emitter (signals object or queue).")
        self.skip_current_file_flag = skip_current_file_flag
        self.downloaded_files = downloaded_files if downloaded_files is not None else set()
        self.downloaded_file_hashes = downloaded_file_hashes if downloaded_file_hashes is not None else set()
        self.downloaded_files_lock = downloaded_files_lock if downloaded_files_lock is not None else threading.Lock()
        self.downloaded_file_hashes_lock = downloaded_file_hashes_lock if downloaded_file_hashes_lock is not None else threading.Lock()
        self.skip_words_list = skip_words_list if skip_words_list is not None else []
        self.skip_words_scope = skip_words_scope
        self.show_external_links = show_external_links
        self.extract_links_only = extract_links_only
        self.num_file_threads = num_file_threads
        self.manga_mode_active = manga_mode_active
        self.manga_filename_style = manga_filename_style
        self.char_filter_scope = char_filter_scope
        self.remove_from_filename_words_list = remove_from_filename_words_list if remove_from_filename_words_list is not None else []
        self.allow_multipart_download = allow_multipart_download
        self.manga_date_file_counter_ref = manga_date_file_counter_ref
        self.selected_cookie_file = selected_cookie_file
        self.app_base_dir = app_base_dir
        self.cookie_text = cookie_text
        self.manga_date_prefix = manga_date_prefix
        self.manga_global_file_counter_ref = manga_global_file_counter_ref
        self.use_cookie = use_cookie
        self.override_output_dir = override_output_dir
        self.scan_content_for_images = scan_content_for_images
        self.creator_download_folder_ignore_words = creator_download_folder_ignore_words
        self.use_date_prefix_for_subfolder = use_date_prefix_for_subfolder
        self.date_prefix_format = date_prefix_format
        self.keep_in_post_duplicates = keep_in_post_duplicates
        self.keep_duplicates_mode = keep_duplicates_mode
        self.keep_duplicates_limit = keep_duplicates_limit
        self.downloaded_hash_counts = downloaded_hash_counts if downloaded_hash_counts is not None else defaultdict(int)
        self.downloaded_hash_counts_lock = downloaded_hash_counts_lock if downloaded_hash_counts_lock is not None else threading.Lock()
        self.session_file_path = session_file_path
        self.session_lock = session_lock
        self.text_only_scope = text_only_scope
        self.text_export_format = text_export_format
        self.single_pdf_mode = single_pdf_mode
        self.project_root_dir = project_root_dir
        self.processed_post_ids = processed_post_ids if processed_post_ids is not None else []
        self.multipart_scope = multipart_scope
        self.multipart_parts_count = multipart_parts_count
        self.multipart_min_size_mb = multipart_min_size_mb
        self.domain_override = domain_override
        self.archive_only_mode = archive_only_mode
        self.skip_file_size_mb = skip_file_size_mb
        self.manga_custom_filename_format = manga_custom_filename_format
        self.manga_custom_date_format = manga_custom_date_format
        self.sfp_threshold = sfp_threshold
        self.handle_unknown_mode = handle_unknown_mode
        self.creator_name_cache = creator_name_cache
        #-- New assign --
        self.add_info_in_pdf = add_info_in_pdf
        #-- New assign --


        if self.compress_images and Image is None:
            self.logger("⚠️ Image compression disabled: Pillow library not found.")
            self.compress_images = False

    def _emit_signal (self ,signal_type_str ,*payload_args ):
        """Helper to emit signal either directly or via queue."""
        if isinstance (self .emitter ,queue .Queue ):
            self .emitter .put ({'type':signal_type_str ,'payload':payload_args })
        elif self .emitter and hasattr (self .emitter ,f"{signal_type_str }_signal"):
            signal_attr =getattr (self .emitter ,f"{signal_type_str }_signal")
            signal_attr .emit (*payload_args )
        else :
            print (f"(Worker Log - Unrecognized Emitter for {signal_type_str }): {payload_args [0 ]if payload_args else ''}")

    def logger (self ,message ):
        self ._emit_signal ('progress',message )
    def check_cancel (self ):
        return self .cancellation_event .is_set ()
    def _check_pause (self ,context_message ="Operation"):
        if self .pause_event and self .pause_event .is_set ():
            while self .pause_event .is_set ():
                if self .check_cancel ():
                    return True
                time .sleep (0.5 )
        return False

    def _get_current_character_filters (self ):
        if self .dynamic_filter_holder :
            return self .dynamic_filter_holder .get_filters ()
        return self .filter_character_list_objects_initial

    def _find_valid_subdomain(self, url: str, max_subdomains: int = 4) -> str:
        """
        Attempts to find a working subdomain for a Kemono/Coomer URL that returned a 403 error.
        Returns the original URL if no other valid subdomain is found.
        """
        parsed_url = urlparse(url)
        original_domain = parsed_url.netloc

        for i in range(1, max_subdomains + 1):
            domain_parts = original_domain.split('.')
            if len(domain_parts) > 1:
                base_domain = ".".join(domain_parts[-2:])
                new_domain = f"n{i}.{base_domain}"
            else:
                continue

            new_url = parsed_url._replace(netloc=new_domain).geturl()

            try:
                with requests.head(new_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5, allow_redirects=True) as resp:
                    if resp.status_code == 200:
                        return new_url
            except requests.RequestException:
                continue

        return url

    def _download_single_file(self, file_info, target_folder_path, post_page_url, original_post_id_for_log, skip_event,
                                post_title="", file_index_in_post=0, num_files_in_this_post=1,
                                manga_date_file_counter_ref=None,
                                forced_filename_override=None,
                                manga_global_file_counter_ref=None, folder_context_name_for_history=None):
        was_original_name_kept_flag = False
        final_filename_saved_for_return = ""
        retry_later_details = None

        # Define and prepare file_url at the top
        file_url = file_info.get('url')
        if self.download_thumbnails and file_url and is_image(file_info.get('name')):
            try:
                parsed = urlparse(file_url)
                new_netloc = re.sub(r'^n\d+\.', 'img.', parsed.netloc)
                new_path = '/thumbnail' + parsed.path if parsed.path.startswith('/data/') else parsed.path
                if new_netloc != parsed.netloc or new_path != parsed.path:
                    file_url = parsed._replace(netloc=new_netloc, path=new_path).geturl()
            except Exception as e:
                self.logger(f"   ⚠️ Could not create thumbnail URL: {e}")

        if self.domain_override and file_url:
            try:
                parsed_url = urlparse(file_url)
                original_netloc_parts = parsed_url.netloc.split('.')
                base_domain_name = original_netloc_parts[-2] if len(original_netloc_parts) >= 2 else original_netloc_parts[0]
                base_override_netloc = f"{base_domain_name}.{self.domain_override}"
                base_override_url = parsed_url._replace(netloc=base_override_netloc).geturl()
                if 'kemono.' in base_override_url or 'coomer.' in base_override_url:
                    file_url = self._find_valid_subdomain(base_override_url)
                else:
                    file_url = base_override_url
            except Exception as e:
                self.logger(f"   ⚠️ Domain Override: Failed to rewrite URL '{file_url}': {e}")

        # Pre-download duplicate check using URL hash
        try:
            parsed_url_for_hash = urlparse(file_url)
            url_hash = os.path.basename(parsed_url_for_hash.path).split('.')[0]
            with self.downloaded_hash_counts_lock:
                current_count = self.downloaded_hash_counts.get(url_hash, 0)
                if self.keep_duplicates_mode == DUPLICATE_HANDLING_HASH and current_count >= 1:
                    self.logger(f"   -> Skip (Content Duplicate by URL Hash): '{file_info.get('name')}' is a duplicate. Skipping download.")
                    return 0, 1, file_info.get('name'), False, FILE_DOWNLOAD_STATUS_SKIPPED, None
                if self.keep_duplicates_mode == DUPLICATE_HANDLING_KEEP_ALL and self.keep_duplicates_limit > 0 and current_count >= self.keep_duplicates_limit:
                    self.logger(f"   -> Skip (Duplicate Limit by URL Hash): Limit of {self.keep_duplicates_limit} for this content has been met. Skipping download.")
                    return 0, 1, file_info.get('name'), False, FILE_DOWNLOAD_STATUS_SKIPPED, None
        except Exception as e:
            self.logger(f"   ⚠️ Could not perform pre-download hash check: {e}. Proceeding with normal download.")

        if self._check_pause(f"File download prep for '{file_info.get('name', 'unknown file')}'"):
            return 0, 1, "", False, FILE_DOWNLOAD_STATUS_SKIPPED, None

        file_download_headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'Referer': post_page_url,
            'Accept': 'text/css'
        }

        cookies_to_use_for_file = None
        if self.use_cookie:
            cookies_to_use_for_file = prepare_cookies_for_request(self.use_cookie, self.cookie_text, self.selected_cookie_file, self.app_base_dir, self.logger)

        if self.skip_file_size_mb is not None:
                api_original_filename_for_size_check = file_info.get('_original_name_for_log', file_info.get('name'))
                try:
                        # Use a stream=True HEAD request to get headers without downloading the body
                        with requests.head(file_url, headers=file_download_headers, timeout=15, cookies=cookies_to_use_for_file, allow_redirects=True) as head_response:
                                head_response.raise_for_status()
                                content_length = head_response.headers.get('Content-Length')
                                if content_length:
                                        file_size_bytes = int(content_length)
                                        file_size_mb = file_size_bytes / (1024 * 1024)
                                        if file_size_mb < self.skip_file_size_mb:
                                                self.logger(f"   -> Skip File (Size): '{api_original_filename_for_size_check}' is {file_size_mb:.2f} MB, which is smaller than the {self.skip_file_size_mb} MB limit.")
                                                return 0, 1, api_original_filename_for_size_check, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
                                else:
                                        self.logger(f"   ⚠️ Could not determine file size for '{api_original_filename_for_size_check}' to check against size limit. Proceeding with download.")
                except requests.RequestException as e:
                        self.logger(f"   ⚠️ Could not fetch file headers to check size for '{api_original_filename_for_size_check}': {e}. Proceeding with download.")

        api_original_filename = file_info.get('_original_name_for_log', file_info.get('name'))
        filename_to_save_in_main_path = ""
        if forced_filename_override:
            filename_to_save_in_main_path = forced_filename_override
            self.logger(f"   Retrying with forced filename: '{filename_to_save_in_main_path}'")
        else:
            if self.skip_words_list and (self.skip_words_scope == SKIP_SCOPE_FILES or self.skip_words_scope == SKIP_SCOPE_BOTH):
                filename_to_check_for_skip_words = api_original_filename.lower()
                for skip_word in self.skip_words_list:
                    if skip_word.lower() in filename_to_check_for_skip_words:
                        self.logger(f"   -> Skip File (Keyword in Original Name '{skip_word}'): '{api_original_filename}'. Scope: {self.skip_words_scope}")
                        return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None

            cleaned_original_api_filename = robust_clean_name(api_original_filename)
            original_filename_cleaned_base, original_ext = os.path.splitext(cleaned_original_api_filename)
            if not original_ext.startswith('.'): original_ext = '.' + original_ext if original_ext else ''

            if self.manga_mode_active:
                if self.manga_filename_style == STYLE_ORIGINAL_NAME:
                    published_date_str = self.post.get('published')
                    added_date_str = self.post.get('added')
                    formatted_date_str = "nodate"
                    date_to_use_str = published_date_str or added_date_str
                    if date_to_use_str:
                        try:
                            formatted_date_str = date_to_use_str.split('T')[0]
                        except Exception:
                            self.logger(f"     ⚠️ Could not parse date '{date_to_use_str}'. Using 'nodate' prefix.")
                    else:
                        self.logger(f"     ⚠️ Post ID {original_post_id_for_log} has no date. Using 'nodate' prefix.")
                    filename_to_save_in_main_path = f"{formatted_date_str}_{cleaned_original_api_filename}"
                    was_original_name_kept_flag = True
                elif self.manga_filename_style == STYLE_POST_TITLE:
                    if post_title and post_title.strip():
                        cleaned_post_title_base = robust_clean_name(post_title.strip())
                        if num_files_in_this_post > 1:
                            if file_index_in_post == 0:
                                filename_to_save_in_main_path = f"{cleaned_post_title_base}{original_ext}"
                            else:
                                filename_to_save_in_main_path = f"{cleaned_post_title_base}_{file_index_in_post}{original_ext}"
                                was_original_name_kept_flag = False
                        else:
                            filename_to_save_in_main_path = f"{cleaned_post_title_base}{original_ext}"
                    else:
                        filename_to_save_in_main_path = cleaned_original_api_filename
                        self.logger(f"⚠️ Renaming Mode (Post Title Style): Post title missing for post {original_post_id_for_log}. Using cleaned original filename '{filename_to_save_in_main_path}'.")
                elif self.manga_filename_style == STYLE_DATE_BASED:
                    if manga_date_file_counter_ref is not None and len(manga_date_file_counter_ref) == 2:
                        counter_val_for_filename = -1
                        counter_lock = manga_date_file_counter_ref[1]
                        with counter_lock:
                            counter_val_for_filename = manga_date_file_counter_ref[0]
                            manga_date_file_counter_ref[0] += 1
                        base_numbered_name = f"{counter_val_for_filename:03d}"
                        if self.manga_date_prefix and self.manga_date_prefix.strip():
                            cleaned_prefix = robust_clean_name(self.manga_date_prefix.strip())
                            if cleaned_prefix:
                                filename_to_save_in_main_path = f"{cleaned_prefix} {base_numbered_name}{original_ext}"
                            else:
                                filename_to_save_in_main_path = f"{base_numbered_name}{original_ext}"; self.logger(f"⚠️ Manga Date Mode: Provided prefix '{self.manga_date_prefix}' was empty after cleaning. Using number only.")
                        else:
                            filename_to_save_in_main_path = f"{base_numbered_name}{original_ext}"
                    else:
                        self.logger(f"⚠️ Manga Date Mode: Counter ref not provided or malformed for '{api_original_filename}'. Using original. Ref: {manga_date_file_counter_ref}")
                        filename_to_save_in_main_path = cleaned_original_api_filename
                elif self.manga_filename_style == STYLE_POST_TITLE_GLOBAL_NUMBERING:
                    if manga_global_file_counter_ref is not None and len(manga_global_file_counter_ref) == 2:
                        counter_val_for_filename = -1
                        counter_lock = manga_global_file_counter_ref[1]
                        with counter_lock:
                            counter_val_for_filename = manga_global_file_counter_ref[0]
                            manga_global_file_counter_ref[0] += 1
                        cleaned_post_title_base_for_global = robust_clean_name(post_title.strip() if post_title and post_title.strip() else "post")
                        filename_to_save_in_main_path = f"{cleaned_post_title_base_for_global}_{counter_val_for_filename:03d}{original_ext}"
                    else:
                        self.logger(f"⚠️ Manga Title+GlobalNum Mode: Counter ref not provided or malformed for '{api_original_filename}'. Using original. Ref: {manga_global_file_counter_ref}")
                        filename_to_save_in_main_path = cleaned_original_api_filename
                        self.logger(f"⚠️ Renaming Mode (Title+GlobalNum Style Fallback): Using cleaned original filename '{filename_to_save_in_main_path}' for post {original_post_id_for_log}.")
                elif self.manga_filename_style == STYLE_POST_ID:
                    if original_post_id_for_log and original_post_id_for_log != 'unknown_id':
                        base_name = str(original_post_id_for_log)
                        filename_to_save_in_main_path = f"{base_name}_{file_index_in_post}{original_ext}"
                    else:
                        self.logger(f"⚠️ Renaming Mode (Post ID Style): Post ID missing. Using cleaned original filename '{cleaned_original_api_filename}'.")
                        filename_to_save_in_main_path = cleaned_original_api_filename

                elif self.manga_filename_style == STYLE_CUSTOM:
                    try:
                        def format_date(date_str):
                            if not date_str or 'NoDate' in date_str:
                                return "NoDate"
                            try:
                                dt_obj = datetime.fromisoformat(date_str)
                                strftime_format = self.manga_custom_date_format.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                                return dt_obj.strftime(strftime_format)
                            except (ValueError, TypeError):
                                return date_str.split('T')[0]

                        service = self.service.lower()
                        user_id = str(self.user_id)

                        # Look up the name in the cache, falling back to the user_id if not found
                        creator_name = user_id # Default to the ID
                        if self.creator_name_cache:
                            creator_name = self.creator_name_cache.get((service, user_id), user_id)

                        added_date = self.post.get('added')
                        published_date = self.post.get('published')
                        edited_date = self.post.get('edited')

                        format_values = {
                            'id': str(self.post.get('id', '')),
                            'user': user_id,
                            'creator_name': creator_name,
                            'service': self.service,
                            'title': str(self.post.get('title', '')),
                            'name': original_filename_cleaned_base,
                            'added': format_date(added_date or published_date),
                            'published': format_date(published_date),
                            'edited': format_date(edited_date or published_date)
                        }

                        custom_base_name = self.manga_custom_filename_format.format(**format_values)
                        cleaned_custom_name = robust_clean_name(custom_base_name)

                        if num_files_in_this_post > 1:
                            filename_to_save_in_main_path = f"{cleaned_custom_name}_{file_index_in_post}{original_ext}"
                        else:
                            filename_to_save_in_main_path = f"{cleaned_custom_name}{original_ext}"

                    except (KeyError, IndexError, ValueError) as e:
                        self.logger(f"⚠️ Custom format error: {e}. Falling back to original filename.")
                        filename_to_save_in_main_path = cleaned_original_api_filename


                elif self.manga_filename_style == STYLE_DATE_POST_TITLE:
                    published_date_str = self.post.get('published')
                    added_date_str = self.post.get('added')
                    formatted_date_str = "nodate"
                    if published_date_str:
                        try:
                            formatted_date_str = published_date_str.split('T')[0]
                        except Exception:
                            self.logger(f"     ⚠️ Could not parse 'published' date '{published_date_str}' for STYLE_DATE_POST_TITLE. Using 'nodate'.")
                    elif added_date_str:
                        try:
                            formatted_date_str = added_date_str.split('T')[0]
                            self.logger(f"     ⚠️ Post ID {original_post_id_for_log} missing 'published' date, using 'added' date '{added_date_str}' for STYLE_DATE_POST_TITLE naming.")
                        except Exception:
                            self.logger(f"     ⚠️ Could not parse 'added' date '{added_date_str}' for STYLE_DATE_POST_TITLE. Using 'nodate'.")
                    else:
                        self.logger(f"     ⚠️ Post ID {original_post_id_for_log} missing both 'published' and 'added' dates for STYLE_DATE_POST_TITLE. Using 'nodate'.")

                    if post_title and post_title.strip():
                        temp_cleaned_title = robust_clean_name(post_title.strip())
                        if not temp_cleaned_title or temp_cleaned_title.startswith("untitled_folder"):
                            self.logger(f"⚠️ Renaming Mode (Date+PostTitle Style): Post title for post {original_post_id_for_log} ('{post_title}') was empty or generic after cleaning. Using 'post' as title part.")
                            cleaned_post_title_for_filename = "post"
                        else:
                            cleaned_post_title_for_filename = temp_cleaned_title
                        base_name_for_style = f"{formatted_date_str}_{cleaned_post_title_for_filename}"
                        if num_files_in_this_post > 1:
                            filename_to_save_in_main_path = f"{base_name_for_style}_{file_index_in_post}{original_ext}" if file_index_in_post > 0 else f"{base_name_for_style}{original_ext}"
                        else:
                            filename_to_save_in_main_path = f"{base_name_for_style}{original_ext}"
                    else:
                        self.logger(f"⚠️ Renaming Mode (Date+PostTitle Style): Post title missing for post {original_post_id_for_log}. Using 'post' as title part with date prefix.")
                        cleaned_post_title_for_filename = "post"
                        base_name_for_style = f"{formatted_date_str}_{cleaned_post_title_for_filename}"
                        if num_files_in_this_post > 1:
                            filename_to_save_in_main_path = f"{base_name_for_style}_{file_index_in_post}{original_ext}" if file_index_in_post > 0 else f"{base_name_for_style}{original_ext}"
                        else:
                            filename_to_save_in_main_path = f"{base_name_for_style}{original_ext}"
                else:
                    self.logger(f"⚠️ Renaming Mode: Unknown filename style '{self.manga_filename_style}'. Defaulting to original filename for '{api_original_filename}'.")
                    filename_to_save_in_main_path = cleaned_original_api_filename

                if not filename_to_save_in_main_path:
                    filename_to_save_in_main_path = f"manga_file_{original_post_id_for_log}_{file_index_in_post + 1}{original_ext}"
                    self.logger(f"⚠️ Renaming Mode: Generated filename was empty. Using generic fallback: '{filename_to_save_in_main_path}'.")
                    was_original_name_kept_flag = False
            else:
                is_url_like = 'http' in api_original_filename.lower()
                is_too_long = len(cleaned_original_api_filename) > 100

                if is_url_like or is_too_long:
                    self.logger(f"   ⚠️ Original filename is a URL or too long. Generating a shorter name.")
                    name_hash = hashlib.md5(api_original_filename.encode()).hexdigest()[:12]
                    _, ext = os.path.splitext(cleaned_original_api_filename)
                    if not ext:
                        try:
                            path = urlparse(api_original_filename).path
                            ext = os.path.splitext(path)[1] or ".file"
                        except Exception:
                            ext = ".file"

                    cleaned_post_title = robust_clean_name(post_title.strip() if post_title else "post")[:40]
                    filename_to_save_in_main_path = f"{cleaned_post_title}_{name_hash}{ext}"
                    was_original_name_kept_flag = False
                else:
                    filename_to_save_in_main_path = cleaned_original_api_filename
                    was_original_name_kept_flag = True

            if self.remove_from_filename_words_list and filename_to_save_in_main_path:
                base_name_for_removal, ext_for_removal = os.path.splitext(filename_to_save_in_main_path)
                modified_base_name = base_name_for_removal
                for word_to_remove in self.remove_from_filename_words_list:
                    if not word_to_remove: continue
                    pattern = re.compile(re.escape(word_to_remove), re.IGNORECASE)
                    modified_base_name = pattern.sub("", modified_base_name)
                modified_base_name = re.sub(r'[_.\s-]+', ' ', modified_base_name)
                modified_base_name = re.sub(r'\s+', ' ', modified_base_name)
                modified_base_name = modified_base_name.strip()
                if modified_base_name and modified_base_name != ext_for_removal.lstrip('.'):
                    filename_to_save_in_main_path = modified_base_name + ext_for_removal
                else:
                    filename_to_save_in_main_path = base_name_for_removal + ext_for_removal


        MAX_PATH_LENGTH = 240

        base_name, extension = os.path.splitext(filename_to_save_in_main_path)

        potential_full_path = os.path.join(target_folder_path, filename_to_save_in_main_path)

        if len(potential_full_path) > MAX_PATH_LENGTH:
            excess_length = len(potential_full_path) - MAX_PATH_LENGTH

            if len(base_name) > excess_length:
                truncated_base_name = base_name[:-excess_length]

                filename_to_save_in_main_path = truncated_base_name.strip() + extension
                self.logger(f"   ⚠️ Path was too long. Truncating filename to: '{filename_to_save_in_main_path}'")
            else:
                name_hash = hashlib.md5(base_name.encode()).hexdigest()[:16]
                filename_to_save_in_main_path = f"{name_hash}{extension}"
                self.logger(f"   ⚠️ Path is extremely long. Hashing filename to: '{filename_to_save_in_main_path}'")

        if not self.download_thumbnails:
            is_img_type = is_image(api_original_filename)
            is_vid_type = is_video(api_original_filename)
            is_archive_type = is_archive(api_original_filename)
            is_audio_type = is_audio(api_original_filename)
            if self.filter_mode == 'archive':
                if not is_archive_type:
                    self.logger(f"   -> Filter Skip (Archive Mode): '{api_original_filename}' (Not an Archive).")
                    return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
            elif self.filter_mode == 'image':
                if not is_img_type:
                    self.logger(f"   -> Filter Skip: '{api_original_filename}' (Not Image).")
                    return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
            elif self.filter_mode == 'video':
                if not is_vid_type:
                    self.logger(f"   -> Filter Skip: '{api_original_filename}' (Not Video).")
                    return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
            elif self.filter_mode == 'audio':
                if not is_audio_type:
                    self.logger(f"   -> Filter Skip: '{api_original_filename}' (Not Audio).")
                    return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
            if (self.skip_zip) and is_archive(api_original_filename):
                self.logger(f"   -> Pref Skip: '{api_original_filename}' (Archive).")
                return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
        try:
            os.makedirs(target_folder_path, exist_ok=True)
        except OSError as e:
            self.logger(f"   ❌ Critical error creating directory '{target_folder_path}': {e}. Skipping file '{api_original_filename}'.")
            return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None

        temp_file_base_for_unique_part, temp_file_ext_for_unique_part = os.path.splitext(filename_to_save_in_main_path if filename_to_save_in_main_path else api_original_filename)
        unique_id_for_part_file = uuid.uuid4().hex[:8]
        unique_part_file_stem_on_disk = f"{temp_file_base_for_unique_part}_{unique_id_for_part_file}"
        max_retries = 3
        if not self.keep_in_post_duplicates:
            final_save_path_check = os.path.join(target_folder_path, filename_to_save_in_main_path)
            if os.path.exists(final_save_path_check):
                try:
                    self.logger(f"   ⚠️ File '{filename_to_save_in_main_path}' exists. Verifying content with URL hash...")

                    parsed_url = urlparse(file_url)
                    hash_from_url = os.path.basename(parsed_url.path).split('.')[0]

                    hash_from_disk = hashlib.sha256()
                    with open(final_save_path_check, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b""): # Use a larger buffer for hashing
                            hash_from_disk.update(chunk)

                    if hash_from_url == hash_from_disk.hexdigest():
                        self.logger(f"   -> Skip (Hash Match): The existing file is a perfect match.")
                        return 0, 1, filename_to_save_in_main_path, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_SKIPPED, None
                    else:
                        # Hashes differ. This is a legitimate collision. Log it and proceed.
                        # The downloader will then save the new file with a numbered suffix (_1, _2, etc.).
                        self.logger(f"   -> Hash Mismatch. Existing file is different content. Proceeding to download new file with a suffix.")

                except Exception as e:
                    self.logger(f"   ⚠️ Could not perform hash check for existing file: {e}. Re-downloading with a suffix to be safe.")

        max_retries = 3
        retry_delay = 5
        downloaded_size_bytes = 0
        calculated_file_hash = None
        downloaded_part_file_path = None
        download_successful_flag = False
        last_exception_for_retry_later = None
        is_permanent_error = False
        data_to_write_io = None

        for attempt_num_single_stream in range(max_retries + 1):
            response = None
            if self._check_pause(f"File download attempt for '{api_original_filename}'"): break
            if self.check_cancel() or (skip_event and skip_event.is_set()): break
            try:
                if attempt_num_single_stream > 0:
                    self.logger(f"   Retrying download for '{api_original_filename}' (Overall Attempt {attempt_num_single_stream + 1}/{max_retries + 1})...")
                    time.sleep(retry_delay * (2 ** (attempt_num_single_stream - 1)))

                self._emit_signal('file_download_status', True)

                current_url_to_try = file_url

                response = requests.get(current_url_to_try, headers=file_download_headers, timeout=(30, 300), stream=True, cookies=cookies_to_use_for_file)

                if response.status_code == 403 and ('kemono.' in current_url_to_try or 'coomer.' in current_url_to_try):
                    self.logger(f"   ⚠️ Got 403 Forbidden for '{api_original_filename}'. Attempting subdomain rotation...")
                    new_url = self._find_valid_subdomain(current_url_to_try)
                    if new_url != current_url_to_try:
                        self.logger(f"   Retrying with new URL: {new_url}")
                        file_url = new_url
                        response.close() # Close the old response
                        response = requests.get(new_url, headers=file_download_headers, timeout=(30, 300), stream=True, cookies=cookies_to_use_for_file)

                response.raise_for_status()

                # --- REVISED AND MOVED SIZE CHECK LOGIC ---
                total_size_bytes = int(response.headers.get('Content-Length', 0))

                if self.skip_file_size_mb is not None:
                    if total_size_bytes > 0:
                        file_size_mb = total_size_bytes / (1024 * 1024)
                        if file_size_mb < self.skip_file_size_mb:
                            self.logger(f"   -> Skip File (Size): '{api_original_filename}' is {file_size_mb:.2f} MB, which is smaller than the {self.skip_file_size_mb} MB limit.")
                            return 0, 1, api_original_filename, False, FILE_DOWNLOAD_STATUS_SKIPPED, None
                    # If Content-Length is missing, we can't check, so we no longer log a warning here and just proceed.
                # --- END OF REVISED LOGIC ---

                num_parts_for_file = min(self.multipart_parts_count, MAX_PARTS_FOR_MULTIPART_DOWNLOAD)

                file_is_eligible_by_scope = False
                if self.multipart_scope == 'videos':
                    if is_video(api_original_filename):
                        file_is_eligible_by_scope = True
                elif self.multipart_scope == 'archives':
                    if is_archive(api_original_filename):
                        file_is_eligible_by_scope = True
                elif self.multipart_scope == 'both':
                    if is_video(api_original_filename) or is_archive(api_original_filename):
                        file_is_eligible_by_scope = True

                min_size_in_bytes = self.multipart_min_size_mb * 1024 * 1024

                attempt_multipart = (self.allow_multipart_download and MULTIPART_DOWNLOADER_AVAILABLE and
                                     file_is_eligible_by_scope and
                                     num_parts_for_file > 1 and total_size_bytes > min_size_in_bytes and
                                     'bytes' in response.headers.get('Accept-Ranges', '').lower())

                if self._check_pause(f"Multipart decision for '{api_original_filename}'"): break

                if attempt_multipart:
                    response.close() # Close the initial connection before starting multipart
                    mp_save_path_for_unique_part_stem_arg = os.path.join(target_folder_path, f"{unique_part_file_stem_on_disk}{temp_file_ext_for_unique_part}")
                    mp_success, mp_bytes, mp_hash, mp_file_handle = download_file_in_parts(
                        file_url, mp_save_path_for_unique_part_stem_arg, total_size_bytes, num_parts_for_file, file_download_headers, api_original_filename,
                        emitter_for_multipart=self.emitter, cookies_for_chunk_session=cookies_to_use_for_file,
                        cancellation_event=self.cancellation_event, skip_event=skip_event, logger_func=self.logger,
                        pause_event=self.pause_event
                    )
                    if mp_success:
                        download_successful_flag = True
                        downloaded_size_bytes = mp_bytes
                        calculated_file_hash = mp_hash
                        downloaded_part_file_path = mp_save_path_for_unique_part_stem_arg
                        if mp_file_handle: mp_file_handle.close()
                        break
                    else:
                        if attempt_num_single_stream < max_retries:
                            self.logger(f"   Multi-part download attempt failed for '{api_original_filename}'. Retrying with single stream.")
                        else:
                            download_successful_flag = False; break
                else:
                    self.logger(f"⬇️ Downloading (Single Stream): '{api_original_filename}' (Size: {total_size_bytes / (1024 * 1024):.2f} MB if known) [Base Name: '{filename_to_save_in_main_path}'] ({response.url})")
                    current_single_stream_part_path = os.path.join(target_folder_path, f"{unique_part_file_stem_on_disk}{temp_file_ext_for_unique_part}.part")
                    current_attempt_downloaded_bytes = 0
                    md5_hasher = hashlib.md5()
                    last_progress_time = time.time()
                    try:
                        with open(current_single_stream_part_path, 'wb') as f_part:
                            for chunk in response.iter_content(chunk_size=1 * 1024 * 1024):
                                if self._check_pause(f"Chunk download for '{api_original_filename}'"): break
                                if self.check_cancel() or (skip_event and skip_event.is_set()): break
                                if chunk:
                                    f_part.write(chunk)
                                    md5_hasher.update(chunk)
                                    current_attempt_downloaded_bytes += len(chunk)
                                    if time.time() - last_progress_time > 1 and total_size_bytes > 0:
                                        self._emit_signal('file_progress', api_original_filename, (current_attempt_downloaded_bytes, total_size_bytes))
                                        last_progress_time = time.time()
                        if self.check_cancel() or (skip_event and skip_event.is_set()) or (self.pause_event and self.pause_event.is_set() and not (current_attempt_downloaded_bytes > 0 or (total_size_bytes == 0 and response.status_code == 200))):
                            if os.path.exists(current_single_stream_part_path): os.remove(current_single_stream_part_path)
                            break
                        attempt_is_complete = False
                        if response.status_code == 200:
                            if total_size_bytes > 0:
                                if current_attempt_downloaded_bytes == total_size_bytes:
                                    attempt_is_complete = True
                                else:
                                    self.logger(f"   ⚠️ Single-stream attempt for '{api_original_filename}' incomplete: received {current_attempt_downloaded_bytes} of {total_size_bytes} bytes.")
                            elif total_size_bytes == 0:
                                if current_attempt_downloaded_bytes > 0:
                                    self.logger(f"   ⚠️ Mismatch for '{api_original_filename}': Server reported 0 bytes, but received {current_attempt_downloaded_bytes} bytes this attempt.")
                                    attempt_is_complete = True
                                else:
                                    attempt_is_complete = True
                        if attempt_is_complete:
                            calculated_file_hash = md5_hasher.hexdigest()
                            downloaded_size_bytes = current_attempt_downloaded_bytes
                            downloaded_part_file_path = current_single_stream_part_path
                            download_successful_flag = True
                            break
                        else:
                            if os.path.exists(current_single_stream_part_path):
                                try:
                                    os.remove(current_single_stream_part_path)
                                except OSError as e_rem_part:
                                    self.logger(f"   -> Failed to remove .part file after failed single stream attempt: {e_rem_part}")
                    except Exception as e_write:
                        self.logger(f"   ❌ Error writing single-stream to disk for '{api_original_filename}': {e_write}")
                        if os.path.exists(current_single_stream_part_path): os.remove(current_single_stream_part_path)
                        raise

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, http.client.IncompleteRead) as e:
                self.logger(f"   ❌ Download Error (Retryable): {api_original_filename}. Error: {e}")
                last_exception_for_retry_later = e
                if isinstance(e, requests.exceptions.ConnectionError) and ("Failed to resolve" in str(e) or "NameResolutionError" in str(e)):
                    self.logger("   💡 This looks like a DNS resolution problem. Please check your internet connection, DNS settings, or VPN.")
            except requests.exceptions.RequestException as e:
                if e.response is not None and e.response.status_code == 403:
                    self.logger(f"   ⚠️ Download Error (403 Forbidden): {api_original_filename}. This often requires valid cookies.")
                    self.logger(f"      Will retry... Check your 'Use Cookie' settings if this persists.")
                    last_exception_for_retry_later = e
                else:
                    self.logger(f"   ❌ Download Error (Non-Retryable): {api_original_filename}. Error: {e}")
                    last_exception_for_retry_later = e
                    is_permanent_error = True
                    break
            except Exception as e:
                self.logger(f"   ❌ Unexpected Download Error: {api_original_filename}: {e}\n{traceback.format_exc(limit=2)}")
                last_exception_for_retry_later = e
                is_permanent_error = True
                break
            finally:
                if response:
                    response.close()
                self._emit_signal('file_download_status', False)

        final_total_for_progress = total_size_bytes if download_successful_flag and total_size_bytes > 0 else downloaded_size_bytes
        self._emit_signal('file_progress', api_original_filename, (downloaded_size_bytes, final_total_for_progress))

        if (not download_successful_flag and
                isinstance(last_exception_for_retry_later, http.client.IncompleteRead) and
                total_size_bytes > 0 and downloaded_part_file_path and os.path.exists(downloaded_part_file_path)):
            try:
                actual_size = os.path.getsize(downloaded_part_file_path)
                if actual_size == total_size_bytes:
                    self.logger(f"   ✅ Rescued '{api_original_filename}': IncompleteRead error occurred, but file size matches. Proceeding with save.")
                    download_successful_flag = True
                    md5_hasher = hashlib.md5()
                    with open(downloaded_part_file_path, 'rb') as f_verify:
                        for chunk in iter(lambda: f_verify.read(8192), b""):
                            md5_hasher.update(chunk)
                    calculated_file_hash = md5_hasher.hexdigest()
            except Exception as rescue_exc:
                self.logger(f"   ⚠️ Failed to rescue file despite matching size. Error: {rescue_exc}")

        if self.check_cancel() or (skip_event and skip_event.is_set()) or (self.pause_event and self.pause_event.is_set() and not download_successful_flag):
            if downloaded_part_file_path and os.path.exists(downloaded_part_file_path):
                try:
                    os.remove(downloaded_part_file_path)
                except OSError:
                    pass
            return 0, 1, filename_to_save_in_main_path, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_SKIPPED, None

        if download_successful_flag:
            if self._check_pause(f"Post-download processing for '{api_original_filename}'"):
                if downloaded_part_file_path and os.path.exists(downloaded_part_file_path):
                    try:
                        os.remove(downloaded_part_file_path)
                    except OSError: pass
                return 0, 1, filename_to_save_in_main_path, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_SKIPPED, None

            if (self.compress_images and downloaded_part_file_path and
                    is_image(api_original_filename) and
                    os.path.getsize(downloaded_part_file_path) > 1.5 * 1024 * 1024):

                self.logger(f"   🔄 Compressing '{api_original_filename}' to WebP...")
                try:
                    with Image.open(downloaded_part_file_path) as img:
                        if img.mode not in ('RGB', 'RGBA'):
                            img = img.convert('RGBA')

                        output_buffer = BytesIO()
                        img.save(output_buffer, format='WebP', quality=85)

                        data_to_write_io = output_buffer

                        base, _ = os.path.splitext(filename_to_save_in_main_path)
                        filename_to_save_in_main_path = f"{base}.webp"
                        self.logger(f"   ✅ Compression successful. New size: {len(data_to_write_io.getvalue()) / (1024*1024):.2f} MB")

                except Exception as e_compress:
                    self.logger(f"   ⚠️ Failed to compress '{api_original_filename}': {e_compress}. Saving original file instead.")
                    data_to_write_io = None

            effective_save_folder = target_folder_path
            base_name, extension = os.path.splitext(filename_to_save_in_main_path)
            counter = 1
            final_filename_on_disk = filename_to_save_in_main_path
            final_save_path = os.path.join(effective_save_folder, final_filename_on_disk)

            while os.path.exists(final_save_path):
                final_filename_on_disk = f"{base_name}_{counter}{extension}"
                final_save_path = os.path.join(effective_save_folder, final_filename_on_disk)
                counter += 1

            if counter > 1:
                self.logger(f"   ⚠️ Filename collision: Saving as '{final_filename_on_disk}' instead.")

            try:
                if data_to_write_io:
                    with open(final_save_path, 'wb') as f_out:
                        f_out.write(data_to_write_io.getvalue())
                    if downloaded_part_file_path and os.path.exists(downloaded_part_file_path):
                        try:
                            os.remove(downloaded_part_file_path)
                        except OSError as e_rem:
                            self.logger(f"  -> Failed to remove .part after compression: {e_rem}")
                else:
                    if downloaded_part_file_path and os.path.exists(downloaded_part_file_path):
                        time.sleep(0.1)
                        os.rename(downloaded_part_file_path, final_save_path)
                    else:
                        raise FileNotFoundError(f"Original .part file not found for saving: {downloaded_part_file_path}")

                try:
                    parsed_url_for_hash = urlparse(file_url)
                    url_hash = os.path.basename(parsed_url_for_hash.path).split('.')[0]
                    with self.downloaded_hash_counts_lock:
                        self.downloaded_hash_counts[url_hash] += 1
                except Exception as e:
                    self.logger(f"   ⚠️ Could not update post-download hash count: {e}")

                final_filename_saved_for_return = final_filename_on_disk
                self.logger(f"✅ Saved: '{final_filename_saved_for_return}' (from '{api_original_filename}', {downloaded_size_bytes / (1024 * 1024):.2f} MB) in '{os.path.basename(effective_save_folder)}'")

                downloaded_file_details = {
                    'disk_filename': final_filename_saved_for_return,
                    'post_title': post_title,
                    'post_id': original_post_id_for_log,
                    'upload_date_str': self.post.get('published') or self.post.get('added') or "N/A",
                    'download_timestamp': time.time(),
                    'download_path': effective_save_folder,
                    'service': self.service,
                    'user_id': self.user_id,
                    'api_original_filename': api_original_filename,
                    'folder_context_name': folder_context_name_for_history or os.path.basename(effective_save_folder)
                }
                self._emit_signal('file_successfully_downloaded', downloaded_file_details)
                time.sleep(0.05)

                return 1, 0, final_filename_saved_for_return, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_SUCCESS, None

            except Exception as save_err:
                self.logger(f"->>Save Fail for '{final_filename_on_disk}': {save_err}")

                if downloaded_part_file_path and os.path.exists(downloaded_part_file_path):
                    try:
                        os.remove(downloaded_part_file_path)
                        self.logger(f"   Cleaned up temporary file after save error: {os.path.basename(downloaded_part_file_path)}")
                    except OSError as e_rem:
                        self.logger(f"   ⚠️ Could not clean up temporary file '{os.path.basename(downloaded_part_file_path)}' after save error: {e_rem}")

                if os.path.exists(final_save_path):
                    try:
                        os.remove(final_save_path)
                    except OSError:
                        self.logger(f"   -> Failed to remove partially saved file: {final_save_path}")

                permanent_failure_details = {
                    'file_info': file_info, 'target_folder_path': target_folder_path, 'headers': file_download_headers,
                    'original_post_id_for_log': original_post_id_for_log, 'post_title': post_title,
                    'file_index_in_post': file_index_in_post, 'num_files_in_this_post': num_files_in_this_post,
                    'forced_filename_override': filename_to_save_in_main_path,
                    'service': self.service,
                    'user_id': self.user_id
                }
                return 0, 1, final_filename_saved_for_return, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_FAILED_PERMANENTLY_THIS_SESSION, permanent_failure_details
            finally:
                if data_to_write_io and hasattr(data_to_write_io, 'close'):
                    data_to_write_io.close()
        else:
            self.logger(f"->>Download Fail for '{api_original_filename}' (Post ID: {original_post_id_for_log}). No successful download after retries.")
            details_for_failure = {
                'file_info': file_info,
                'target_folder_path': target_folder_path,
                'headers': file_download_headers,
                'original_post_id_for_log': original_post_id_for_log,
                'post_title': post_title,
                'file_index_in_post': file_index_in_post,
                'num_files_in_this_post': num_files_in_this_post,
                'forced_filename_override': filename_to_save_in_main_path,
                'added': self.post.get('added'),
                'published': self.post.get('published'),
                'edited': self.post.get('edited')

            }
            if is_permanent_error:
                return 0, 1, filename_to_save_in_main_path, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_FAILED_PERMANENTLY_THIS_SESSION, details_for_failure
            else:
                return 0, 1, filename_to_save_in_main_path, was_original_name_kept_flag, FILE_DOWNLOAD_STATUS_FAILED_RETRYABLE_LATER, details_for_failure

    def _get_manga_style_filename_for_post(self, post_title, original_ext):
        """Generates a filename based on manga style, using post data."""
        if self.manga_filename_style == STYLE_POST_TITLE:
            cleaned_post_title_base = robust_clean_name(post_title.strip() if post_title and post_title.strip() else "post")
            return f"{cleaned_post_title_base}{original_ext}"

        elif self.manga_filename_style == STYLE_CUSTOM:
            try:
                def format_date(date_str):
                    if not date_str or 'NoDate' in date_str:
                        return "NoDate"
                    try:
                        dt_obj = datetime.fromisoformat(date_str)
                        strftime_format = self.manga_custom_date_format.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
                        return dt_obj.strftime(strftime_format)
                    except (ValueError, TypeError):
                        return date_str.split('T')[0]

                service = self.service.lower()
                user_id = str(self.user_id)
                creator_name = self.creator_name_cache.get((service, user_id), user_id)

                added_date = self.post.get('added')
                published_date = self.post.get('published')
                edited_date = self.post.get('edited')

                format_values = {
                    'id': str(self.post.get('id', '')),
                    'user': user_id,
                    'creator_name': creator_name,
                    'service': self.service,
                    'title': str(self.post.get('title', '')),
                    'name': robust_clean_name(post_title), # Use post title as a fallback 'name'
                    'added': format_date(added_date or published_date),
                    'published': format_date(published_date),
                    'edited': format_date(edited_date or published_date)
                }

                custom_base_name = self.manga_custom_filename_format.format(**format_values)
                cleaned_custom_name = robust_clean_name(custom_base_name)

                return f"{cleaned_custom_name}{original_ext}"

            except (KeyError, IndexError, ValueError) as e:
                self.logger(f"⚠️ Custom format error for text export: {e}. Falling back to post title.")
                return f"{robust_clean_name(post_title.strip() or 'untitled_post')}{original_ext}"

        elif self.manga_filename_style == STYLE_DATE_POST_TITLE:
            published_date_str = self.post.get('published')
            added_date_str = self.post.get('added')
            formatted_date_str = "nodate"
            if published_date_str:
                try:
                    formatted_date_str = published_date_str.split('T')[0]
                except Exception:
                    pass
            elif added_date_str:
                try:
                    formatted_date_str = added_date_str.split('T')[0]
                except Exception:
                    pass

            cleaned_post_title_for_filename = robust_clean_name(post_title.strip() or "post")
            base_name_for_style = f"{formatted_date_str}_{cleaned_post_title_for_filename}"
            return f"{base_name_for_style}{original_ext}"

        elif self.manga_filename_style == STYLE_POST_ID:
            post_id = str(self.post.get('id', 'unknown_id'))
            return f"{post_id}{original_ext}"

        elif self.manga_filename_style == STYLE_ORIGINAL_NAME:
            published_date_str = self.post.get('published') or self.post.get('added')
            formatted_date_str = "nodate"
            if published_date_str:
                try:
                    formatted_date_str = published_date_str.split('T')[0]
                except Exception:
                    pass

            # Use post title as the name part, as there is no "original filename" for the text export.
            cleaned_post_title_base = robust_clean_name(post_title.strip() or "untitled_post")
            return f"{formatted_date_str}_{cleaned_post_title_base}{original_ext}"

        # Default fallback
        return f"{robust_clean_name(post_title.strip() or 'untitled_post')}{original_ext}"

    def process(self):
        result_tuple = (0, 0, [], [], [], None, None)
        try:
            if self.service == 'discord':
                post_title = self.post.get('content', '') or f"Message {self.post.get('id', 'N/A')}"
                post_id = self.post.get('id', 'unknown_id')
                post_main_file_info = {}
                post_attachments = self.post.get('attachments', [])
                post_content_html = self.post.get('content', '')
                post_data = self.post
                log_prefix = "Message"
            else:
                post_title = self.post.get('title', '') or 'untitled_post'
                post_id = self.post.get('id', 'unknown_id')
                post_main_file_info = self.post.get('file')
                post_attachments = self.post.get('attachments', [])
                post_content_html = self.post.get('content', '')
                post_data = self.post
                log_prefix = "Post"

            content_is_needed = (
                self.show_external_links or
                self.extract_links_only or
                self.scan_content_for_images or
                (self.filter_mode == 'text_only' and self.text_only_scope == 'content')
            )

            if content_is_needed and self.post.get('content') is None and self.service != 'discord':
                self.logger(f"   Post {post_id} is missing 'content' field, fetching full data...")
                parsed_url = urlparse(self.api_url_input)
                api_domain = parsed_url.netloc
                creator_page_url = f"https://{api_domain}/{self.service}/user/{self.user_id}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                    'Referer': creator_page_url,
                    'Accept': 'text/css'
                    }
                cookies = prepare_cookies_for_request(self.use_cookie, self.cookie_text, self.selected_cookie_file, self.app_base_dir, self.logger, target_domain=api_domain)
                full_post_data = fetch_single_post_data(api_domain, self.service, self.user_id, post_id, headers, self.logger, cookies_dict=cookies)
                if full_post_data:
                    self.logger("   ✅ Full post data fetched successfully.")
                    self.post = full_post_data
                    post_title = self.post.get('title', '') or 'untitled_post'
                    post_main_file_info = self.post.get('file')
                    post_attachments = self.post.get('attachments', [])
                    post_content_html = self.post.get('content', '')
                    post_data = self.post
                else:
                    self.logger(f"   ⚠️ Failed to fetch full content for post {post_id}. Content-dependent features may not work for this post.")

            if self.skip_words_list and (self.skip_words_scope == SKIP_SCOPE_POSTS or self.skip_words_scope == SKIP_SCOPE_BOTH):
                if self._check_pause(f"Skip words (post title) for post {post_id}"):
                    result_tuple = (0, 0, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple
                post_title_lower = post_title.lower()
                for skip_word in self.skip_words_list:
                    if skip_word.lower() in post_title_lower:
                        self.logger(f"   -> Skip Post (Keyword in Title '{skip_word}'): '{post_title[:50]}...'. Scope: {self.skip_words_scope}")
                        # No folder determination or creation happens for skipped posts
                        result_tuple = (0, 0, [], [], [], None, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple

            total_downloaded_this_post = 0
            total_skipped_this_post = 0
            determined_post_save_path_for_history = self.override_output_dir if self.override_output_dir else self.download_root

            if self._check_pause(f"{log_prefix} processing for ID {post_id}"):
                result_tuple = (0, 0, [], [], [], None, None)
                self._emit_signal('worker_finished', result_tuple)
                return result_tuple
            if self.check_cancel():
                result_tuple = (0, 0, [], [], [], None, None)
                self._emit_signal('worker_finished', result_tuple)
                return result_tuple

            current_character_filters = self._get_current_character_filters()
            kept_original_filenames_for_log = []
            retryable_failures_this_post = []
            permanent_failures_this_post = []
            history_data_for_this_post = None
            parsed_api_url = urlparse(self.api_url_input)

            if self.service == 'discord':
                server_id = self.user_id
                channel_id = self.post.get('channel', 'unknown_channel')
                post_page_url = f"https://{parsed_api_url.netloc}/discord/server/{server_id}/{channel_id}"
            else:
                post_page_url = f"https://{parsed_api_url.netloc}/{self.service}/user/{self.user_id}/post/{post_id}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'Referer': post_page_url,
                'Accept': 'text/css'
                }
            link_pattern = re.compile(r"""<a\s+.*?href=["'](https?://[^"']+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
            effective_unwanted_keywords_for_folder_naming = self.unwanted_keywords.copy()
            is_full_creator_download_no_char_filter = not self.target_post_id_from_initial_url and not current_character_filters

            if (self.show_external_links or self.extract_links_only):
                unique_links_data = {}
                links_emitted_count = 0

                embed_data = post_data.get('embed')
                if isinstance(embed_data, dict) and embed_data.get('url'):
                    embed_url = embed_data['url']
                    embed_subject = embed_data.get('subject', embed_url)
                    unique_links_data[embed_url] = embed_subject

                if post_content_html:
                    try:
                        # Stage 2: Find all clickable <a> tag links
                        for match in link_pattern.finditer(post_content_html):
                            link_url = html.unescape(match.group(1).strip())
                            if not any(ext in link_url.lower() for ext in ['.css', '.js', '.ico', '.xml', '.svg']) and not link_url.startswith('javascript:'):
                                clean_link_text = html.unescape(re.sub(r'<.*?>', '', match.group(2))).strip()
                                unique_links_data[link_url] = clean_link_text if clean_link_text else "[Link]"

                        # Stage 3: Find all plain-text URLs
                        plain_text_content = strip_html_tags(post_content_html)
                        plain_text_url_pattern = re.compile(r"""\b(https?://[^\s"'<>\[\]\{\}\|\^\\^~\[\]`]+)""", re.IGNORECASE)
                        for match in plain_text_url_pattern.finditer(plain_text_content):
                            link_url = html.unescape(match.group(1).strip())
                            if link_url not in unique_links_data:
                                unique_links_data[link_url] = "[Plain Text Link]"

                        # Stage 4: Process all unique links found
                        scraped_platforms = {'kemono', 'coomer', 'patreon'}
                        for link_url, link_text in unique_links_data.items():
                            platform = get_link_platform(link_url)
                            decryption_key_found = ""
                            if platform == 'mega':
                                mega_key_pattern = re.compile(r'\b([a-zA-Z0-9_-]{43}|[a-zA-Z0-9_-]{22})\b')
                                parsed_mega_url = urlparse(link_url)
                                if parsed_mega_url.fragment:
                                    potential_key_from_fragment = parsed_mega_url.fragment.split('!')[-1]
                                    if mega_key_pattern.fullmatch(potential_key_from_fragment):
                                        decryption_key_found = potential_key_from_fragment
                                if not decryption_key_found and link_text:
                                    key_match_in_text = mega_key_pattern.search(link_text)
                                    if key_match_in_text:
                                        decryption_key_found = key_match_in_text.group(1)
                                if not decryption_key_found and self.extract_links_only and post_content_html:
                                    key_match_in_content = mega_key_pattern.search(strip_html_tags(post_content_html))
                                    if key_match_in_content:
                                        decryption_key_found = key_match_in_content.group(1)

                            final_link_url_to_emit = link_url
                            if platform == 'mega' and decryption_key_found:
                                parsed_url = urlparse(link_url)
                                if decryption_key_found not in (parsed_url.fragment or ''):
                                    base_url = link_url.split('#')[0]
                                    final_link_url_to_emit = f"{base_url}#{decryption_key_found}"
                                    self.logger(f"   ℹ️ Combined Mega link and key: {final_link_url_to_emit}")

                            if platform not in scraped_platforms:
                                self._emit_signal('external_link', post_title, link_text, final_link_url_to_emit, platform, "")
                                links_emitted_count += 1
                        if links_emitted_count > 0: self.logger(f"   🔗 Found {links_emitted_count} potential external link(s) in post content.")
                    except Exception as e:
                        self.logger(f"⚠️ Error parsing post content for links: {e}\n{traceback.format_exc(limit=2)}")
                elif self.extract_links_only and not unique_links_data:
                     self.logger(f"   ℹ️ Post {post_id} contains no text content to scan for links.")

            if is_full_creator_download_no_char_filter and self.creator_download_folder_ignore_words:
                self.logger(f"   Applying creator download specific folder ignore words ({len(self.creator_download_folder_ignore_words)} words).")
                effective_unwanted_keywords_for_folder_naming.update(self.creator_download_folder_ignore_words)

            if not self.extract_links_only:
                self.logger(f"\n--- Processing {log_prefix} {post_id} ('{post_title[:50]}...') (Thread: {threading.current_thread().name}) ---")

            num_potential_files_in_post = len(post_attachments or []) + (1 if post_main_file_info and post_main_file_info.get('path') else 0)

            post_is_candidate_by_title_char_match = False
            char_filter_that_matched_title = None
            post_is_candidate_by_comment_char_match = False
            post_is_candidate_by_file_char_match_in_comment_scope = False
            char_filter_that_matched_file_in_comment_scope = None
            char_filter_that_matched_comment = None
            effective_use_subfolders = self.use_subfolders

            if current_character_filters and (self.char_filter_scope == CHAR_SCOPE_TITLE or self.char_filter_scope == CHAR_SCOPE_BOTH):
                if self._check_pause(f"Character title filter for post {post_id}"):
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple
                for idx, filter_item_obj in enumerate(current_character_filters):
                    if self.check_cancel(): break
                    terms_to_check_for_title = list(filter_item_obj["aliases"])
                    if filter_item_obj["is_group"]:
                        if filter_item_obj["name"] not in terms_to_check_for_title:
                            terms_to_check_for_title.append(filter_item_obj["name"])
                    unique_terms_for_title_check = list(set(terms_to_check_for_title))
                    for term_to_match in unique_terms_for_title_check:
                        match_found_for_term = is_title_match_for_character(post_title, term_to_match)
                        if match_found_for_term:
                            post_is_candidate_by_title_char_match = True
                            char_filter_that_matched_title = filter_item_obj
                            self.logger(f"   Post title matches char filter term '{term_to_match}' (from group/name '{filter_item_obj['name']}', Scope: {self.char_filter_scope}). Post is candidate.")
                            break
                    if post_is_candidate_by_title_char_match: break

            all_files_from_post_api_for_char_check = []
            api_file_domain_for_char_check = urlparse(self.api_url_input).netloc
            if not api_file_domain_for_char_check or not any(d in api_file_domain_for_char_check.lower() for d in ['kemono.su', 'kemono.party', 'kemono.cr', 'coomer.su', 'coomer.party', 'coomer.st']):
                api_file_domain_for_char_check = "kemono.cr" if "kemono" in self.service.lower() else "coomer.st"
            if post_main_file_info and isinstance(post_main_file_info, dict) and post_main_file_info.get('path'):
                original_api_name = post_main_file_info.get('name') or os.path.basename(post_main_file_info['path'].lstrip('/'))
                if original_api_name:
                    all_files_from_post_api_for_char_check.append({'_original_name_for_log': original_api_name})
            for att_info in post_attachments:
                if isinstance(att_info, dict) and att_info.get('path'):
                    original_api_att_name = att_info.get('name') or os.path.basename(att_info['path'].lstrip('/'))
                    if original_api_att_name:
                        all_files_from_post_api_for_char_check.append({'_original_name_for_log': original_api_att_name})

            if current_character_filters and self.char_filter_scope == CHAR_SCOPE_COMMENTS and self.service != 'discord':
                self.logger(f"   [Char Scope: Comments] Phase 1: Checking post files for matches before comments for post ID '{post_id}'.")
                if self._check_pause(f"File check (comments scope) for post {post_id}"):
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple
                for file_info_item in all_files_from_post_api_for_char_check:
                    if self.check_cancel(): break
                    current_api_original_filename_for_check = file_info_item.get('_original_name_for_log')
                    if not current_api_original_filename_for_check: continue
                    for filter_item_obj in current_character_filters:
                        terms_to_check = list(filter_item_obj["aliases"])
                        if filter_item_obj["is_group"] and filter_item_obj["name"] not in terms_to_check:
                            terms_to_check.append(filter_item_obj["name"])
                        for term_to_match in terms_to_check:
                            if is_filename_match_for_character(current_api_original_filename_for_check, term_to_match):
                                post_is_candidate_by_file_char_match_in_comment_scope = True
                                char_filter_that_matched_file_in_comment_scope = filter_item_obj
                                self.logger(f"     Match Found (File in Comments Scope): File '{current_api_original_filename_for_check}' matches char filter term '{term_to_match}' (from group/name '{filter_item_obj['name']}'). Post is candidate.")
                                break
                        if post_is_candidate_by_file_char_match_in_comment_scope: break
                    if post_is_candidate_by_file_char_match_in_comment_scope: break
                self.logger(f"   [Char Scope: Comments] Phase 1 Result: post_is_candidate_by_file_char_match_in_comment_scope = {post_is_candidate_by_file_char_match_in_comment_scope}")

            if current_character_filters and self.char_filter_scope == CHAR_SCOPE_COMMENTS and self.service != 'discord':
                if not post_is_candidate_by_file_char_match_in_comment_scope:
                    if self._check_pause(f"Comment check for post {post_id}"):
                        result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple
                    self.logger(f"   [Char Scope: Comments] Phase 2: No file match found. Checking post comments for post ID '{post_id}'.")
                    try:
                        parsed_input_url_for_comments = urlparse(self.api_url_input)
                        api_domain_for_comments = parsed_input_url_for_comments.netloc
                        if not any(d in api_domain_for_comments.lower() for d in ['kemono.su', 'kemono.party', 'kemono.cr', 'coomer.su', 'coomer.party', 'coomer.st']):
                            self.logger(f"⚠️ Unrecognized domain '{api_domain_for_comments}' for comment API. Defaulting based on service.")
                            api_domain_for_comments = "kemono.cr" if "kemono" in self.service.lower() else "coomer.st"
                        comments_data = fetch_post_comments(
                            api_domain_for_comments, self.service, self.user_id, post_id,
                            headers, self.logger, self.cancellation_event, self.pause_event,
                            cookies_dict=prepare_cookies_for_request(
                                self.use_cookie, self.cookie_text, self.selected_cookie_file, self.app_base_dir, self.logger
                            )
                        )
                        if comments_data:
                            self.logger(f"     Fetched {len(comments_data)} comments for post {post_id}.")
                            for comment_item_idx, comment_item in enumerate(comments_data):
                                if self.check_cancel(): break
                                raw_comment_content = comment_item.get('content', '')
                                if not raw_comment_content: continue
                                cleaned_comment_text = strip_html_tags(raw_comment_content)
                                if not cleaned_comment_text.strip(): continue
                                for filter_item_obj in current_character_filters:
                                    terms_to_check_comment = list(filter_item_obj["aliases"])
                                    if filter_item_obj["is_group"] and filter_item_obj["name"] not in terms_to_check_comment:
                                        terms_to_check_comment.append(filter_item_obj["name"])
                                    for term_to_match_comment in terms_to_check_comment:
                                        if is_title_match_for_character(cleaned_comment_text, term_to_match_comment):
                                            post_is_candidate_by_comment_char_match = True
                                            char_filter_that_matched_comment = filter_item_obj
                                            self.logger(f"     Match Found (Comment in Comments Scope): Comment in post {post_id} matches char filter term '{term_to_match_comment}' (from group/name '{filter_item_obj['name']}'). Post is candidate.")
                                            self.logger(f"       Matching comment (first 100 chars): '{cleaned_comment_text[:100]}...'")
                                            break
                                    if post_is_candidate_by_comment_char_match: break
                                if post_is_candidate_by_comment_char_match: break
                        else:
                            self.logger(f"     No comments found or fetched for post {post_id} to check against character filters.")
                    except RuntimeError as e_fetch_comment:
                        self.logger(f"   ⚠️ Error fetching or processing comments for post {post_id}: {e_fetch_comment}")
                    except Exception as e_generic_comment:
                        self.logger(f"   ❌ Unexpected error during comment processing for post {post_id}: {e_generic_comment}\n{traceback.format_exc(limit=2)}")
                    self.logger(f"   [Char Scope: Comments] Phase 2 Result: post_is_candidate_by_comment_char_match = {post_is_candidate_by_comment_char_match}")
                else:
                    self.logger(f"   [Char Scope: Comments] Phase 2: Skipped comment check for post ID '{post_id}' because a file match already made it a candidate.")

            if current_character_filters:
                if self.char_filter_scope == CHAR_SCOPE_TITLE and not post_is_candidate_by_title_char_match:
                    self.logger(f"   -> Skip Post (Scope: Title - No Char Match): Title '{post_title[:50]}' does not match character filters.")
                    self._emit_signal('missed_character_post', post_title, "No title match for character filter")
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple
                if self.char_filter_scope == CHAR_SCOPE_COMMENTS and not post_is_candidate_by_file_char_match_in_comment_scope and not post_is_candidate_by_comment_char_match:
                    self.logger(f"   -> Skip Post (Scope: Comments - No Char Match in Comments): Post ID '{post_id}', Title '{post_title[:50]}...'")
                    if self.emitter and hasattr(self.emitter, 'missed_character_post_signal'):
                        self._emit_signal('missed_character_post', post_title, "No character match in files or comments (Comments scope)")
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple

            if self.filter_mode == 'text_only' and not self.extract_links_only:
                self.logger(f"   Mode: Text Only (Scope: {self.text_only_scope})")
                post_title_lower = post_title.lower()

                # --- Skip Words Check ---
                if self.skip_words_list and (self.skip_words_scope == SKIP_SCOPE_POSTS or self.skip_words_scope == SKIP_SCOPE_BOTH):
                    for skip_word in self.skip_words_list:
                        if skip_word.lower() in post_title_lower:
                            self.logger(f"   -> Skip Post (Keyword in Title '{skip_word}'): '{post_title[:50]}...'.")
                            result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                            self._emit_signal('worker_finished', result_tuple)
                            return result_tuple

                if current_character_filters and not post_is_candidate_by_title_char_match and not post_is_candidate_by_comment_char_match and not post_is_candidate_by_file_char_match_in_comment_scope:
                    self.logger(f"   -> Skip Post (No character match for text extraction): '{post_title[:50]}...'.")
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple

                raw_text_content = ""
                comments_data = []
                final_post_data = post_data

                # --- Content Fetching ---
                if self.text_only_scope == 'content' and 'content' not in final_post_data:
                    self.logger(f"   Post {post_id} is missing 'content' field, fetching full data...")
                    parsed_url = urlparse(self.api_url_input)
                    api_domain = parsed_url.netloc
                    cookies = prepare_cookies_for_request(self.use_cookie, self.cookie_text, self.selected_cookie_file, self.app_base_dir, self.logger, target_domain=api_domain)
                    full_data = fetch_single_post_data(api_domain, self.service, self.user_id, post_id, headers, self.logger, cookies_dict=cookies)
                    if full_data:
                        final_post_data = full_data

                if self.text_only_scope == 'content':
                    raw_text_content = final_post_data.get('content', '')
                elif self.text_only_scope == 'comments':
                    try:
                        parsed_url = urlparse(self.api_url_input)
                        api_domain = parsed_url.netloc
                        comments_data = fetch_post_comments(api_domain, self.service, self.user_id, post_id, headers, self.logger, self.cancellation_event, self.pause_event)
                        if comments_data:
                            # For TXT/DOCX export, we format comments here.
                            # For PDF, we pass the raw list to the generator.
                            comment_texts = []
                            for comment in comments_data:
                                user = comment.get('commenter_name', 'Unknown User')
                                timestamp = comment.get('published', 'No Date')
                                body = strip_html_tags(comment.get('content', ''))
                                comment_texts.append(f"--- Comment by {user} on {timestamp} ---\n{body}\n")
                            raw_text_content = "\n".join(comment_texts)
                        else:
                            raw_text_content = ""
                    except Exception as e:
                        self.logger(f"   ❌ Error fetching comments for text-only mode: {e}")

                cleaned_text = ""
                if self.text_only_scope == 'content':
                    if not raw_text_content:
                        cleaned_text = ""
                    else:
                        text_with_newlines = re.sub(r'(?i)</p>|<br\s*/?>', '\n', raw_text_content)
                        just_text = re.sub(r'<.*?>', '', text_with_newlines)
                        cleaned_text = html.unescape(just_text).strip()
                else:
                    cleaned_text = raw_text_content

                cleaned_text = cleaned_text.replace('…', '...')

                if not cleaned_text.strip():
                    self.logger("   -> Skip Saving Text: No content/comments found or fetched.")
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple

                # --- Metadata Preparation ---
                # Prepare all data needed for the info page or JSON dump
                service_str = self.service
                user_id_str = str(self.user_id)
                post_id_str = str(post_id)
                creator_key = (service_str.lower(), user_id_str)

                # Resolve creator name using the cache passed from main_window
                creator_name = user_id_str
                if self.creator_name_cache:
                    creator_name = self.creator_name_cache.get(creator_key, user_id_str)

                common_content_data = {
                    'title': post_title,
                    'published': self.post.get('published') or self.post.get('added'),
                    'service': service_str,
                    'user': user_id_str,
                    'id': post_id_str,
                    'tags': self.post.get('tags'),
                    'original_link': post_page_url,
                    'creator_name': creator_name
                }

                # --- Single PDF Mode (Save Temp JSON) ---
                if self.single_pdf_mode:
                    if self.text_only_scope == 'comments':
                        if not comments_data:
                            result_tuple = (0, 0, [], [], [], None, None)
                            self._emit_signal('worker_finished', result_tuple)
                            return result_tuple
                        common_content_data['comments'] = comments_data
                    else:
                        if not cleaned_text.strip():
                            result_tuple = (0, 0, [], [], [], None, None)
                            self._emit_signal('worker_finished', result_tuple)
                            return result_tuple
                        common_content_data['content'] = cleaned_text

                    temp_dir = os.path.join(self.app_base_dir, "appdata")
                    os.makedirs(temp_dir, exist_ok=True)
                    temp_filename = f"tmp_{post_id}_{uuid.uuid4().hex[:8]}.json"
                    temp_filepath = os.path.join(temp_dir, temp_filename)
                    try:
                        with open(temp_filepath, 'w', encoding='utf-8') as f:
                            json.dump(common_content_data, f, indent=2)
                        self.logger(f"   Saved temporary data for '{post_title}' for single PDF compilation.")
                        result_tuple = (0, 0, [], [], [], None, temp_filepath)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple
                    except Exception as e:
                        self.logger(f"   ❌ Failed to write temporary file for single PDF: {e}")
                        result_tuple = (0, 0, [], [], [], None, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple

                # --- Individual File Mode ---
                else:
                    file_extension = self.text_export_format
                    txt_filename = ""

                    if self.manga_mode_active:
                        txt_filename = self._get_manga_style_filename_for_post(post_title, f".{file_extension}")
                        self.logger(f"   ℹ️ Applying Renaming Mode. Generated filename: '{txt_filename}'")
                    else:
                        txt_filename = clean_filename(post_title) + f".{file_extension}"

                    final_save_path = os.path.join(determined_post_save_path_for_history, txt_filename)

                    try:
                        os.makedirs(determined_post_save_path_for_history, exist_ok=True)
                        base, ext = os.path.splitext(final_save_path)

                        counter = 1
                        while os.path.exists(final_save_path):
                            final_save_path = f"{base}_{counter}{ext}"
                            counter += 1

                        # --- PDF Generation ---
                        if file_extension == 'pdf':
                            # Font setup
                            font_path = ""
                            if self.project_root_dir:
                                font_path = os.path.join(self.project_root_dir, 'data', 'dejavu-sans', 'DejaVuSans.ttf')

                            # Add content specific fields for the generator
                            if self.text_only_scope == 'comments':
                                common_content_data['comments_list_for_pdf'] = comments_data
                            else:
                                common_content_data['content_text_for_pdf'] = cleaned_text

                            # Call the centralized function
                            success = create_individual_pdf(
                                post_data=common_content_data,
                                output_filename=final_save_path,
                                font_path=font_path,
                                add_info_page=self.add_info_in_pdf, # <--- NEW PARAMETER
                                logger=self.logger
                            )

                            if not success:
                                raise Exception("PDF generation failed (check logs)")

                        # --- DOCX Generation ---
                        elif file_extension == 'docx':
                            if Document:
                                self.logger(f"   Converting to DOCX...")
                                document = Document()
                                # Add simple header info if desired, or keep pure text
                                if self.add_info_in_pdf:
                                    document.add_heading(post_title, 0)
                                    document.add_paragraph(f"Date: {common_content_data['published']}")
                                    document.add_paragraph(f"Creator: {common_content_data['creator_name']}")
                                    document.add_paragraph(f"URL: {common_content_data['original_link']}")
                                    document.add_page_break()

                                document.add_paragraph(cleaned_text)
                                document.save(final_save_path)
                            else:
                                self.logger(f"   ⚠️ Cannot create DOCX: 'python-docx' library not installed. Saving as .txt.")
                                final_save_path = os.path.splitext(final_save_path)[0] + ".txt"
                                with open(final_save_path, 'w', encoding='utf-8') as f: f.write(cleaned_text)

                        # --- TXT Generation ---
                        else:
                            content_to_write = cleaned_text
                            # Optional: Add simple text header if "Add Info" is checked
                            if self.add_info_in_pdf:
                                header = (f"Title: {post_title}\n"
                                          f"Date: {common_content_data['published']}\n"
                                          f"Creator: {common_content_data['creator_name']}\n"
                                          f"URL: {common_content_data['original_link']}\n"
                                          f"{'-'*40}\n\n")
                                content_to_write = header + cleaned_text

                            with open(final_save_path, 'w', encoding='utf-8') as f:
                                f.write(content_to_write)

                        self.logger(f"✅ Saved Text: '{os.path.basename(final_save_path)}' in '{os.path.basename(determined_post_save_path_for_history)}'")
                        result_tuple = (1, num_potential_files_in_post, [], [], [], history_data_for_this_post, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple

                    except Exception as e:
                        self.logger(f"   ❌ Critical error saving text file '{txt_filename}': {e}")
                        result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple


            if not self.extract_links_only and self.manga_mode_active and current_character_filters and (self.char_filter_scope == CHAR_SCOPE_TITLE or self.char_filter_scope == CHAR_SCOPE_BOTH) and not post_is_candidate_by_title_char_match:
                 self.logger(f"   -> Skip Post (Renaming Mode with Title/Both Scope - No Title Char Match): Title '{post_title[:50]}' doesn't match filters.")
                 self._emit_signal('missed_character_post', post_title, "Renaming Mode: No title match for character filter (Title/Both scope)")
                 result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                 self._emit_signal('worker_finished', result_tuple)
                 return result_tuple

            if not isinstance(post_attachments, list):
                self.logger(f"⚠️ Corrupt attachment data for post {post_id} (expected list, got {type(post_attachments)}). Skipping attachments.")
                post_attachments = []

            should_create_post_subfolder = self.use_post_subfolders

            if (not self.use_post_subfolders and self.use_subfolders and
                self.sfp_threshold is not None and num_potential_files_in_post >= self.sfp_threshold):

                self.logger(f"   ℹ️ Post has {num_potential_files_in_post} files (≥{self.sfp_threshold}). Activating Subfolder per Post via [sfp] command.")
                should_create_post_subfolder = True

            base_folder_names_for_post_content = []
            determined_post_save_path_for_history = self.override_output_dir if self.override_output_dir else self.download_root
            if not self.extract_links_only and self.use_subfolders:
                if self._check_pause(f"Subfolder determination for post {post_id}"):
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple

                primary_char_filter_for_folder = None
                log_reason_for_folder = ""
                known_name_match_found = False

                if self.char_filter_scope == CHAR_SCOPE_COMMENTS and char_filter_that_matched_comment:
                    if post_is_candidate_by_file_char_match_in_comment_scope and char_filter_that_matched_file_in_comment_scope:
                        primary_char_filter_for_folder = char_filter_that_matched_file_in_comment_scope
                        log_reason_for_folder = "Matched char filter in filename (Comments scope)"
                    elif post_is_candidate_by_comment_char_match and char_filter_that_matched_comment:
                        primary_char_filter_for_folder = char_filter_that_matched_comment
                        log_reason_for_folder = "Matched char filter in comments (Comments scope, no file match)"
                elif (self.char_filter_scope == CHAR_SCOPE_TITLE or self.char_filter_scope == CHAR_SCOPE_BOTH) and char_filter_that_matched_title:
                    primary_char_filter_for_folder = char_filter_that_matched_title
                    log_reason_for_folder = "Matched char filter in title"

                if primary_char_filter_for_folder:
                    known_name_match_found = True
                    cleaned_primary_folder_name = clean_folder_name(primary_char_filter_for_folder["name"])
                    if cleaned_primary_folder_name.lower() in effective_unwanted_keywords_for_folder_naming and cleaned_primary_folder_name.lower() != "untitled_folder":
                        self.logger(f"   ⚠️ Primary char filter folder name '{cleaned_primary_folder_name}' is in ignore list. Using generic name.")
                        base_folder_names_for_post_content = ["Generic Post Content"]
                    else:
                        base_folder_names_for_post_content = [cleaned_primary_folder_name]
                    self.logger(f"   Base folder name(s) for post content ({log_reason_for_folder}): {', '.join(base_folder_names_for_post_content)}")

                elif not current_character_filters:
                    derived_folders_from_title_via_known_txt = match_folders_from_title(
                        post_title, self.known_names, effective_unwanted_keywords_for_folder_naming
                    )
                    valid_derived_folders_from_title_known_txt = [name for name in derived_folders_from_title_via_known_txt if name and name.strip() and name.lower() != "untitled_folder"]

                    if valid_derived_folders_from_title_known_txt:
                        known_name_match_found = True
                        first_match = valid_derived_folders_from_title_known_txt[0]
                        base_folder_names_for_post_content.append(first_match)
                        self.logger(f"   Base folder name for post content (First match from Known.txt & Title): '{first_match}'")

                    elif self.char_filter_scope == CHAR_SCOPE_BOTH:
                        self.logger(f"   -> No folder match from title for post '{post_id}'. Checking filenames (Scope: Both)...")
                        for file_info_for_fallback in all_files_from_post_api_for_char_check:
                            filename_for_fallback = file_info_for_fallback.get('_original_name_for_log')
                            if not filename_for_fallback:
                                continue

                            matched_folders_from_filename = match_folders_from_filename_enhanced(
                                filename_for_fallback, self.known_names, effective_unwanted_keywords_for_folder_naming
                            )

                            if matched_folders_from_filename:
                                known_name_match_found = True
                                first_match = matched_folders_from_filename[0]
                                base_folder_names_for_post_content.append(first_match)
                                self.logger(f"   Base folder name for post content (First match from Known.txt & Filename '{filename_for_fallback}'): '{first_match}'")
                                break

                if self.handle_unknown_mode and not known_name_match_found:
                    self.logger(f"   ℹ️ [unknown] mode: No match in Known.txt. Creating parent folder from post title '{post_title}'.")

                    post_title_as_folder = robust_clean_name(post_title)
                    base_folder_names_for_post_content = [post_title_as_folder]

                    should_create_post_subfolder = False

                else:
                    if not known_name_match_found:
                        extracted_name_from_title_full_ignore = extract_folder_name_from_title(
                            post_title, effective_unwanted_keywords_for_folder_naming
                        )
                        base_folder_names_for_post_content.append(extracted_name_from_title_full_ignore)
                        self.logger(f"   Base folder name(s) for post content (Generic title parsing): {', '.join(base_folder_names_for_post_content)}")

                if base_folder_names_for_post_content:
                    determined_post_save_path_for_history = os.path.join(determined_post_save_path_for_history, base_folder_names_for_post_content[0])

            if not self.extract_links_only and should_create_post_subfolder:
                cleaned_post_title_for_sub = robust_clean_name(post_title)
                max_folder_len = 100
                if len(cleaned_post_title_for_sub) > max_folder_len:
                    cleaned_post_title_for_sub = cleaned_post_title_for_sub[:max_folder_len].strip()
                post_id_for_fallback = self.post.get('id', 'unknown_id')

                if not cleaned_post_title_for_sub or cleaned_post_title_for_sub == "untitled_folder":
                    self.logger(f"   ⚠️ Post title '{post_title}' resulted in a generic subfolder name. Using 'post_{post_id_for_fallback}' as base.")
                    original_cleaned_post_title_for_sub = f"post_{post_id_for_fallback}"
                else:
                    original_cleaned_post_title_for_sub = cleaned_post_title_for_sub

                if self.use_date_prefix_for_subfolder:
                    published_date_str = self.post.get('published') or self.post.get('added')
                    post_id_for_format = str(self.post.get('id', '')) # Get the post ID

                    # Start with the user's format string from settings
                    final_subfolder_name = self.date_prefix_format

                    # 1. Replace date placeholders if a date is available
                    if published_date_str:
                        try:
                            dt_obj = datetime.fromisoformat(published_date_str)
                            final_subfolder_name = final_subfolder_name.replace("YYYY", dt_obj.strftime("%Y"))
                            final_subfolder_name = final_subfolder_name.replace("MM", dt_obj.strftime("%m"))
                            final_subfolder_name = final_subfolder_name.replace("DD", dt_obj.strftime("%d"))
                        except (ValueError, TypeError) as e:
                            self.logger(f"   ⚠️ Could not parse date '{published_date_str}'. Date placeholders will be skipped. Error: {e}")

                    # 2. Perform case-insensitive replacement for {post} and {postid}
                    final_subfolder_name = re.sub(r'{post}', original_cleaned_post_title_for_sub, final_subfolder_name, flags=re.IGNORECASE)
                    final_subfolder_name = re.sub(r'{postid}', post_id_for_format, final_subfolder_name, flags=re.IGNORECASE)

                    # 3. The result of all replacements becomes the new folder name
                    original_cleaned_post_title_for_sub = final_subfolder_name.strip()
                    self.logger(f"   ℹ️ Applying custom subfolder format: '{original_cleaned_post_title_for_sub}'")

                base_path_for_post_subfolder = determined_post_save_path_for_history
                suffix_counter = 0
                final_post_subfolder_name = ""
                suffix_counter = 0
                folder_creation_successful = False
                final_post_subfolder_name = ""
                post_id_for_folder = str(self.post.get('id', 'unknown_id'))

                while not folder_creation_successful:
                    if suffix_counter == 0:
                        name_candidate = original_cleaned_post_title_for_sub
                    else:
                        name_candidate = f"{original_cleaned_post_title_for_sub}_{suffix_counter}"

                    potential_post_subfolder_path = os.path.join(base_path_for_post_subfolder, name_candidate)
                    id_file_path = os.path.join(potential_post_subfolder_path, f".postid_{post_id_for_folder}")

                    if not os.path.isdir(potential_post_subfolder_path):
                        try:
                            os.makedirs(potential_post_subfolder_path)
                            with open(id_file_path, 'w') as f:
                                f.write(post_id_for_folder)

                            final_post_subfolder_name = name_candidate
                            folder_creation_successful = True
                            if suffix_counter > 0:
                                self.logger(f"   Post subfolder name conflict: Using '{final_post_subfolder_name}' to avoid mixing posts.")
                        except OSError as e_mkdir:
                            self.logger(f"   ❌ Error creating directory '{potential_post_subfolder_path}': {e_mkdir}.")
                            final_post_subfolder_name = original_cleaned_post_title_for_sub
                            break
                    else:
                        if os.path.exists(id_file_path):
                            self.logger(f"   ℹ️ Re-using existing post subfolder: '{name_candidate}'")
                            final_post_subfolder_name = name_candidate
                            folder_creation_successful = True
                        else:
                            suffix_counter += 1
                            if suffix_counter > 100: # Safety break
                                self.logger(f"   ⚠️ Exceeded 100 attempts to find unique subfolder for '{original_cleaned_post_title_for_sub}'.")
                                final_post_subfolder_name = f"{original_cleaned_post_title_for_sub}_{uuid.uuid4().hex[:8]}"
                                os.makedirs(os.path.join(base_path_for_post_subfolder, final_post_subfolder_name), exist_ok=True)
                                break
                determined_post_save_path_for_history = os.path.join(base_path_for_post_subfolder, final_post_subfolder_name)

            if self.skip_words_list and (self.skip_words_scope == SKIP_SCOPE_POSTS or self.skip_words_scope == SKIP_SCOPE_BOTH):
                if self._check_pause(f"Skip words (post title) for post {post_id}"):
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    self._emit_signal('worker_finished', result_tuple)
                    return result_tuple
                post_title_lower = post_title.lower()
                for skip_word in self.skip_words_list:
                    if skip_word.lower() in post_title_lower:
                        self.logger(f"   -> Skip Post (Keyword in Title '{skip_word}'): '{post_title[:50]}...'. Scope: {self.skip_words_scope}")
                        history_data_for_skipped_post = {
                            'post_id': post_id, 'service': self.service, 'user_id': self.user_id, 'post_title': post_title,
                            'top_file_name': "N/A (Post Skipped)", 'num_files': num_potential_files_in_post,
                            'upload_date_str': post_data.get('published') or post_data.get('added') or "Unknown",
                            'download_location': determined_post_save_path_for_history
                        }
                        result_tuple = (0, num_potential_files_in_post, [], [], [], history_data_for_skipped_post, None)
                        self._emit_signal('worker_finished', result_tuple)
                        return result_tuple


            if not self.extract_links_only and self.use_subfolders and self.skip_words_list:
                if self._check_pause(f"Folder keyword skip check for post {post_id}"):
                    result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                    return result_tuple
                for folder_name_to_check in base_folder_names_for_post_content:
                    if not folder_name_to_check: continue
                    if any(skip_word.lower() in folder_name_to_check.lower() for skip_word in self.skip_words_list):
                        matched_skip = next((sw for sw in self.skip_words_list if sw.lower() in folder_name_to_check.lower()), "unknown_skip_word")
                        self.logger(f"   -> Skip Post (Folder Keyword): Potential folder '{folder_name_to_check}' contains '{matched_skip}'.")
                        result_tuple = (0, num_potential_files_in_post, [], [], [], None, None)
                        return result_tuple

            if self.extract_links_only:
                self.logger(f"   Extract Links Only mode: Finished processing post {post_id} for links.")
                result_tuple = (0, 0, [], [], [], None, None)
                self._emit_signal('worker_finished', result_tuple)
                return result_tuple

            all_files_from_post_api = []
            api_file_domain = urlparse(self.api_url_input).netloc
            if not api_file_domain or not any(d in api_file_domain.lower() for d in ['kemono.su', 'kemono.party', 'kemono.cr', 'coomer.su', 'coomer.party', 'coomer.st']):
                api_file_domain = "kemono.cr" if "kemono" in self.service.lower() else "coomer.st"
            if post_main_file_info and isinstance(post_main_file_info, dict) and post_main_file_info.get('path'):
                file_path = post_main_file_info['path'].lstrip('/')
                original_api_name = post_main_file_info.get('name') or os.path.basename(file_path)
                if original_api_name:
                    all_files_from_post_api.append({
                        'url': f"https://{api_file_domain}{file_path}" if file_path.startswith('/') else f"https://{api_file_domain}/data/{file_path}",
                        'name': original_api_name,
                        '_original_name_for_log': original_api_name,
                        '_is_thumbnail': is_image(original_api_name)
                    })
                else:
                    self.logger(f"   ⚠️ Skipping main file for post {post_id}: Missing name (Path: {file_path})")

            for idx, att_info in enumerate(post_attachments):
                if isinstance(att_info, dict) and att_info.get('path'):
                    att_path = att_info['path'].lstrip('/')
                    original_api_att_name = att_info.get('name') or os.path.basename(att_path)
                    if original_api_att_name:
                        all_files_from_post_api.append({
                            'url': f"https://{api_file_domain}{att_path}" if att_path.startswith('/') else f"https://{api_file_domain}/data/{att_path}",
                            'name': original_api_att_name,
                            '_original_name_for_log': original_api_att_name,
                            '_is_thumbnail': is_image(original_api_att_name)
                        })
                    else:
                        self.logger(f"   ⚠️ Skipping attachment {idx + 1} for post {post_id}: Missing name (Path: {att_path})")
                else:
                    self.logger(f"   ⚠️ Skipping invalid attachment {idx + 1} for post {post_id}: {str(att_info)[:100]}")

            if self.keep_duplicates_mode == DUPLICATE_HANDLING_HASH:
                unique_files_by_url = {}
                for file_info in all_files_from_post_api:
                    file_url = file_info.get('url')
                    if file_url and file_url not in unique_files_by_url:
                        unique_files_by_url[file_url] = file_info

                original_count = len(all_files_from_post_api)
                all_files_from_post_api = list(unique_files_by_url.values())
                new_count = len(all_files_from_post_api)

                if new_count < original_count:
                    self.logger(f"   De-duplicated file list: Removed {original_count - new_count} redundant entries from the API response.")

            if self.scan_content_for_images and post_content_html and not self.extract_links_only:
                self.logger(f"   Scanning post content for additional image URLs (Post ID: {post_id})...")
                parsed_input_url = urlparse(self.api_url_input)
                base_url_for_relative_paths = f"{parsed_input_url.scheme}://{parsed_input_url.netloc}"
                img_ext_pattern = "|".join(ext.lstrip('.') for ext in IMAGE_EXTENSIONS)
                direct_url_pattern_str = r"""(?i)\b(https?://[^\s"'<>\[\]\{\}\|\^\\^~\[\]`]+\.(?:""" + img_ext_pattern + r"""))\b"""
                img_tag_src_pattern_str = r"""<img\s+[^>]*?src\s*=\s*["']([^"']+)["']"""
                found_image_sources = set()
                for direct_url_match in re.finditer(direct_url_pattern_str, post_content_html):
                    found_image_sources.add(direct_url_match.group(1))
                for img_tag_match in re.finditer(img_tag_src_pattern_str, post_content_html, re.IGNORECASE):
                    src_attr = img_tag_match.group(1).strip()
                    src_attr = html.unescape(src_attr)
                    if not src_attr: continue
                    resolved_src_url = ""
                    if src_attr.startswith(('http://', 'https://')):
                        resolved_src_url = src_attr
                    elif src_attr.startswith('//'):
                        resolved_src_url = f"{parsed_input_url.scheme}:{src_attr}"
                    elif src_attr.startswith('/'):
                        resolved_src_url = f"{base_url_for_relative_paths}{src_attr}"
                    if resolved_src_url:
                        parsed_resolved_url = urlparse(resolved_src_url)
                        if any(parsed_resolved_url.path.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
                            found_image_sources.add(resolved_src_url)
                if found_image_sources:
                    self.logger(f"      Found {len(found_image_sources)} potential image URLs/sources in content.")
                    existing_urls_in_api_list = {f_info['url'] for f_info in all_files_from_post_api}
                    for found_url in found_image_sources:
                        if self.check_cancel(): break
                        if found_url in existing_urls_in_api_list:
                            self.logger(f"         Skipping URL from content (already in API list or previously added from content): {found_url[:70]}...")
                            continue
                        try:
                            parsed_found_url = urlparse(found_url)
                            url_filename = os.path.basename(parsed_found_url.path)
                            if not url_filename or not is_image(url_filename):
                                self.logger(f"         Skipping URL from content (no filename part or not an image extension): {found_url[:70]}...")
                                continue
                            self.logger(f"      Adding image from content: {url_filename} (URL: {found_url[:70]}...)")
                            all_files_from_post_api.append({
                                'url': found_url,
                                'name': url_filename,
                                '_original_name_for_log': url_filename,
                                '_is_thumbnail': False,
                                '_from_content_scan': True
                            })
                            existing_urls_in_api_list.add(found_url)
                        except Exception as e_url_parse:
                            self.logger(f"         Error processing URL from content '{found_url[:70]}...': {e_url_parse}")
                else:
                    self.logger(f"      No additional image URLs found in post content scan for post {post_id}.")

            if self.archive_only_mode and not self.extract_links_only:
                has_archive = any(is_archive(f.get('_original_name_for_log', '')) for f in all_files_from_post_api)

                if has_archive and len(all_files_from_post_api) > 1:
                    self.logger(f"   [AO] Archive found in post {post_id}. Prioritizing archive and skipping other files.")
                    archives_only = [f for f in all_files_from_post_api if is_archive(f.get('_original_name_for_log', ''))]

                    if archives_only:
                        all_files_from_post_api = archives_only
                    else:
                        self.logger(f"   [AO] Warning: has_archive was true, but no archives found after filtering for post {post_id}. This is unexpected.")

            if self.manga_mode_active and self.manga_filename_style == STYLE_DATE_BASED:
                def natural_sort_key_for_files(file_api_info):
                    name = file_api_info.get('_original_name_for_log', '').lower()
                    return [int(text) if text.isdigit() else text for text in re.split('([0-9]+)', name)]
                all_files_from_post_api.sort(key=natural_sort_key_for_files)
                self.logger(f"   Manga Date Mode: Sorted {len(all_files_from_post_api)} files within post {post_id} by original name for sequential numbering.")

            if not all_files_from_post_api:
                self.logger(f"   No files found to download for post {post_id}.")
                if not self.extract_links_only and should_create_post_subfolder:
                    path_to_check_for_emptiness = determined_post_save_path_for_history
                    try:
                        if os.path.isdir(path_to_check_for_emptiness):
                            dir_contents = os.listdir(path_to_check_for_emptiness)
                            # Check if the directory is empty OR only contains our ID file
                            is_effectively_empty = True
                            if dir_contents:
                                if not all(f.startswith('.postid_') for f in dir_contents):
                                    is_effectively_empty = False

                            if is_effectively_empty:
                                self.logger(f"   🗑️ Removing empty post-specific subfolder (post had no files): '{path_to_check_for_emptiness}'")
                                if dir_contents:
                                    for id_file in dir_contents:
                                        if id_file.startswith('.postid_'):
                                            try:
                                                os.remove(os.path.join(path_to_check_for_emptiness, id_file))
                                            except OSError as e_rm_id:
                                                self.logger(f"   ⚠️ Could not remove ID file '{id_file}' during cleanup: {e_rm_id}")
                                os.rmdir(path_to_check_for_emptiness)
                    except OSError as e_rmdir:
                        self.logger(f"   ⚠️ Could not remove effectively empty subfolder (no files) '{path_to_check_for_emptiness}': {e_rmdir}")
                # --- END NEW CLEANUP LOGIC ---

                history_data_for_no_files_post = {
                    'post_title': post_title,
                    'post_id': post_id,
                    'service': self.service,
                    'user_id': self.user_id,
                    'top_file_name': "N/A (No Files)",
                    'num_files': 0,
                    'upload_date_str': post_data.get('published') or post_data.get('added') or "Unknown",
                    'download_location': determined_post_save_path_for_history
                }
                result_tuple = (0, 0, [], [], [], history_data_for_no_files_post, None)
                self._emit_signal('worker_finished', result_tuple)
                return result_tuple

            files_to_download_info_list = []
            processed_original_filenames_in_this_post = set()
            if self.keep_in_post_duplicates:
                files_to_download_info_list.extend(all_files_from_post_api)
                self.logger(f"   ℹ️ 'Keep Duplicates' is on. All {len(all_files_from_post_api)} files from post will be processed.")
            else:
                for file_info in all_files_from_post_api:
                    current_api_original_filename = file_info.get('_original_name_for_log')
                    if current_api_original_filename in processed_original_filenames_in_this_post:
                        self.logger(f"   -> Skip Duplicate Original Name (within post {post_id}): '{current_api_original_filename}' already processed/listed for this post.")
                        total_skipped_this_post += 1
                    else:
                        files_to_download_info_list.append(file_info)
                        if current_api_original_filename:
                            processed_original_filenames_in_this_post.add(current_api_original_filename)

            if not files_to_download_info_list:
                self.logger(f"   All files for post {post_id} were duplicate original names or skipped earlier.")
                result_tuple = (0, total_skipped_this_post, [], [], [], None, None)
                return result_tuple

            self.logger(f"   Identified {len(files_to_download_info_list)} unique original file(s) for potential download from post {post_id}.")
            with ThreadPoolExecutor(max_workers=self.num_file_threads, thread_name_prefix=f'P{post_id}File_') as file_pool:
                futures_list = []
                for file_idx, file_info_to_dl in enumerate(files_to_download_info_list):
                    if self._check_pause(f"File processing loop for post {post_id}, file {file_idx}"): break
                    if self.check_cancel(): break
                    current_api_original_filename = file_info_to_dl.get('_original_name_for_log')
                    file_is_candidate_by_char_filter_scope = False
                    char_filter_info_that_matched_file = None
                    if not current_character_filters:
                        file_is_candidate_by_char_filter_scope = True
                    else:
                        if self.char_filter_scope == CHAR_SCOPE_FILES:
                            for filter_item_obj in current_character_filters:
                                terms_to_check_for_file = list(filter_item_obj["aliases"])
                                if filter_item_obj["is_group"] and filter_item_obj["name"] not in terms_to_check_for_file:
                                    terms_to_check_for_file.append(filter_item_obj["name"])
                                unique_terms_for_file_check = list(set(terms_to_check_for_file))
                                for term_to_match in unique_terms_for_file_check:
                                    if is_filename_match_for_character(current_api_original_filename, term_to_match):
                                        file_is_candidate_by_char_filter_scope = True
                                        char_filter_info_that_matched_file = filter_item_obj
                                        self.logger(f"   File '{current_api_original_filename}' matches char filter term '{term_to_match}' (from '{filter_item_obj['name']}'). Scope: Files.")
                                        break
                                if file_is_candidate_by_char_filter_scope: break
                        elif self.char_filter_scope == CHAR_SCOPE_TITLE:
                            if post_is_candidate_by_title_char_match:
                                file_is_candidate_by_char_filter_scope = True
                                char_filter_info_that_matched_file = char_filter_that_matched_title
                                self.logger(f"   File '{current_api_original_filename}' is candidate because post title matched. Scope: Title.")
                        elif self.char_filter_scope == CHAR_SCOPE_BOTH:
                            if post_is_candidate_by_title_char_match:
                                file_is_candidate_by_char_filter_scope = True
                                char_filter_info_that_matched_file = char_filter_that_matched_title
                                self.logger(f"   File '{current_api_original_filename}' is candidate because post title matched. Scope: Both (Title part).")
                            else:
                                for filter_item_obj_both_file in current_character_filters:
                                    terms_to_check_for_file_both = list(filter_item_obj_both_file["aliases"])
                                    if filter_item_obj_both_file["is_group"] and filter_item_obj_both_file["name"] not in terms_to_check_for_file_both:
                                        terms_to_check_for_file_both.append(filter_item_obj_both_file["name"])
                                    unique_terms_for_file_both_check = list(set(terms_to_check_for_file_both))
                                    for term_to_match in unique_terms_for_file_both_check:
                                        if is_filename_match_for_character(current_api_original_filename, term_to_match):
                                            file_is_candidate_by_char_filter_scope = True
                                            char_filter_info_that_matched_file = filter_item_obj_both_file
                                            self.logger(f"   File '{current_api_original_filename}' matches char filter term '{term_to_match}' (from '{filter_item_obj['name']}'). Scope: Both (File part).")
                                            break
                                    if file_is_candidate_by_char_filter_scope: break
                        elif self.char_filter_scope == CHAR_SCOPE_COMMENTS:
                            if post_is_candidate_by_file_char_match_in_comment_scope:
                                file_is_candidate_by_char_filter_scope = True
                                char_filter_info_that_matched_file = char_filter_that_matched_file_in_comment_scope
                                self.logger(f"   File '{current_api_original_filename}' is candidate because a file in this post matched char filter (Overall Scope: Comments).")
                            elif post_is_candidate_by_comment_char_match:
                                file_is_candidate_by_char_filter_scope = True
                                char_filter_info_that_matched_file = char_filter_that_matched_comment
                                self.logger(f"   File '{current_api_original_filename}' is candidate because post comments matched char filter (Overall Scope: Comments).")
                    if not file_is_candidate_by_char_filter_scope:
                        self.logger(f"   -> Skip File (Char Filter Scope '{self.char_filter_scope}'): '{current_api_original_filename}' no match.")
                        total_skipped_this_post += 1
                        continue

                    base_folder_for_this_file = ""
                    known_name_match_found_for_this_file = False

                    if self.use_subfolders:
                        if char_filter_info_that_matched_file:
                            base_folder_for_this_file = clean_folder_name(char_filter_info_that_matched_file["name"])
                            known_name_match_found_for_this_file = True
                        elif char_filter_that_matched_title:
                            base_folder_for_this_file = clean_folder_name(char_filter_that_matched_title["name"])
                            known_name_match_found_for_this_file = True
                        elif char_filter_that_matched_comment:
                            base_folder_for_this_file = clean_folder_name(char_filter_that_matched_comment["name"])
                            known_name_match_found_for_this_file = True
                        else:
                            title_folders = match_folders_from_title(post_title, self.known_names, effective_unwanted_keywords_for_folder_naming)
                            if title_folders:
                                base_folder_for_this_file = title_folders[0]
                                known_name_match_found_for_this_file = True
                            else:
                                filename_folders = match_folders_from_filename_enhanced(current_api_original_filename, self.known_names, effective_unwanted_keywords_for_folder_naming)
                                if filename_folders:
                                    base_folder_for_this_file = filename_folders[0]
                                    known_name_match_found_for_this_file = True

                        if not known_name_match_found_for_this_file:
                            if self.handle_unknown_mode:
                                self.logger(f"   ℹ️ [unknown] mode: No match in Known.txt for '{current_api_original_filename}'. Using post title for folder.")
                                base_folder_for_this_file = robust_clean_name(post_title)
                            else:
                                base_folder_for_this_file = extract_folder_name_from_title(post_title, effective_unwanted_keywords_for_folder_naming)

                    final_path_for_this_file = self.override_output_dir if self.override_output_dir else self.download_root
                    if self.use_subfolders and base_folder_for_this_file:
                        final_path_for_this_file = os.path.join(final_path_for_this_file, base_folder_for_this_file)

                    effective_spsp = should_create_post_subfolder
                    if self.handle_unknown_mode and not known_name_match_found_for_this_file:
                        effective_spsp = False

                    if effective_spsp:
                        final_path_for_this_file = os.path.join(final_path_for_this_file, final_post_subfolder_name)

                    futures_list.append(file_pool.submit(
                        self._download_single_file,
                        file_info=file_info_to_dl,
                        target_folder_path=final_path_for_this_file,
                        post_page_url=post_page_url,
                        original_post_id_for_log=post_id,
                        skip_event=self.skip_current_file_flag,
                        post_title=post_title,
                        manga_date_file_counter_ref=self.manga_date_file_counter_ref,
                        manga_global_file_counter_ref=self.manga_global_file_counter_ref,
                        folder_context_name_for_history=base_folder_for_this_file,
                        file_index_in_post=file_idx,
                        num_files_in_this_post=len(files_to_download_info_list)
                    ))

                for future in as_completed(futures_list):
                    if self.check_cancel():
                        for f_to_cancel in futures_list:
                            if not f_to_cancel.done():
                                f_to_cancel.cancel()
                        break
                    try:
                        dl_count, skip_count, actual_filename_saved, original_kept_flag, status, details_for_dialog_or_retry = future.result()
                        total_downloaded_this_post += dl_count
                        total_skipped_this_post += skip_count
                        if original_kept_flag and dl_count > 0 and actual_filename_saved:
                            kept_original_filenames_for_log.append(actual_filename_saved)
                        if status == FILE_DOWNLOAD_STATUS_FAILED_RETRYABLE_LATER and details_for_dialog_or_retry:
                            retryable_failures_this_post.append(details_for_dialog_or_retry)
                        elif status == FILE_DOWNLOAD_STATUS_FAILED_PERMANENTLY_THIS_SESSION and details_for_dialog_or_retry:
                            permanent_failures_this_post.append(details_for_dialog_or_retry)
                    except CancelledError:
                        self.logger(f"   File download task for post {post_id} was cancelled.")
                        total_skipped_this_post += 1
                    except Exception as exc_f:
                        self.logger(f"❌ File download task for post {post_id} resulted in error: {exc_f}")
                        total_skipped_this_post += 1
            self._emit_signal('file_progress', "", None)

            if self.session_file_path and self.session_lock:
                try:
                    with self.session_lock:
                        if os.path.exists(self.session_file_path):
                            with open(self.session_file_path, 'r', encoding='utf-8') as f:
                                session_data = json.load(f)

                            if 'download_state' not in session_data:
                                session_data['download_state'] = {}
                            if not isinstance(session_data['download_state'].get('processed_post_ids'), list):
                                session_data['download_state']['processed_post_ids'] = []

                            session_data['download_state']['processed_post_ids'].append(self.post.get('id'))

                            if 'manga_counters' not in session_data['download_state']:
                                session_data['download_state']['manga_counters'] = {}

                            if self.manga_date_file_counter_ref is not None:
                                session_data['download_state']['manga_counters']['date_based'] = self.manga_date_file_counter_ref[0]

                            if self.manga_global_file_counter_ref is not None:
                                session_data['download_state']['manga_counters']['global_numbering'] = self.manga_global_file_counter_ref[0]

                            if permanent_failures_this_post:
                                if not isinstance(session_data['download_state'].get('permanently_failed_files'), list):
                                    session_data['download_state']['permanently_failed_files'] = []
                                existing_failed_urls = {f.get('file_info', {}).get('url') for f in session_data['download_state']['permanently_failed_files']}
                                for failure in permanent_failures_this_post:
                                    if failure.get('file_info', {}).get('url') not in existing_failed_urls:
                                        session_data['download_state']['permanently_failed_files'].append(failure)
                            temp_file_path = self.session_file_path + ".tmp"
                            with open(temp_file_path, 'w', encoding='utf-8') as f_tmp:
                                json.dump(session_data, f_tmp, indent=2)
                            os.replace(temp_file_path, self.session_file_path)
                except Exception as e:
                    self.logger(f"⚠️ Could not update session file for post {post_id}: {e}")

            if not self.extract_links_only and (total_downloaded_this_post > 0 or not (
                    (current_character_filters and (
                        (self.char_filter_scope == CHAR_SCOPE_TITLE and not post_is_candidate_by_title_char_match) or
                        (self.char_filter_scope == CHAR_SCOPE_COMMENTS and not post_is_candidate_by_file_char_match_in_comment_scope and not post_is_candidate_by_comment_char_match)
                    )) or
                    (self.skip_words_list and (self.skip_words_scope == SKIP_SCOPE_POSTS or self.skip_words_scope == SKIP_SCOPE_BOTH) and any(sw.lower() in post_title.lower() for sw in self.skip_words_list))
            )):
                top_file_name_for_history = "N/A"
                if post_main_file_info and post_main_file_info.get('name'):
                    top_file_name_for_history = post_main_file_info['name']
                elif post_attachments and post_attachments[0].get('name'):
                    top_file_name_for_history = post_attachments[0]['name']
                history_data_for_this_post = {
                    'post_title': post_title, 'post_id': post_id,
                    'top_file_name': top_file_name_for_history,
                    'num_files': num_potential_files_in_post,
                    'upload_date_str': post_data.get('published') or post_data.get('added') or "Unknown",
                    'download_location': determined_post_save_path_for_history,
                    'service': self.service, 'user_id': self.user_id,
                }

            if not self.check_cancel():
                self.logger(f"   Post {post_id} Summary: Downloaded={total_downloaded_this_post}, Skipped Files={total_skipped_this_post}")

            if not self.extract_links_only and self.use_post_subfolders and total_downloaded_this_post == 0:
                path_to_check_for_emptiness = determined_post_save_path_for_history
                try:
                    if os.path.isdir(path_to_check_for_emptiness):
                        dir_contents = os.listdir(path_to_check_for_emptiness)
                        # Check if the directory is empty OR only contains our ID file
                        is_effectively_empty = True
                        if dir_contents:
                            # If there are files, check if ALL of them are .postid files
                            if not all(f.startswith('.postid_') for f in dir_contents):
                                is_effectively_empty = False

                        if is_effectively_empty:
                            self.logger(f"   🗑️ Removing empty post-specific subfolder (no files downloaded): '{path_to_check_for_emptiness}'")
                            # We must first remove the ID file(s) before removing the dir
                            if dir_contents:
                                for id_file in dir_contents:
                                    if id_file.startswith('.postid_'):
                                        try:
                                            os.remove(os.path.join(path_to_check_for_emptiness, id_file))
                                        except OSError as e_rm_id:
                                            self.logger(f"   ⚠️ Could not remove ID file '{id_file}' during cleanup: {e_rm_id}")

                            os.rmdir(path_to_check_for_emptiness) # Now the rmdir should work
                except OSError as e_rmdir:
                    self.logger(f"   ⚠️ Could not remove empty post-specific subfolder '{path_to_check_for_emptiness}': {e_rmdir}")

            result_tuple = (total_downloaded_this_post, total_skipped_this_post,
                            kept_original_filenames_for_log, retryable_failures_this_post,
                            permanent_failures_this_post, history_data_for_this_post,
                            None)

            if not self.extract_links_only and self.use_post_subfolders and total_downloaded_this_post == 0:
                path_to_check_for_emptiness = determined_post_save_path_for_history
                try:
                    if os.path.isdir(path_to_check_for_emptiness):
                        dir_contents = os.listdir(path_to_check_for_emptiness)
                        # Check if the directory is empty OR only contains our ID file
                        is_effectively_empty = True
                        if dir_contents:
                            # If there are files, check if ALL of them are .postid files
                            if not all(f.startswith('.postid_') for f in dir_contents):
                                is_effectively_empty = False

                        if is_effectively_empty:
                            self.logger(f"   🗑️ Removing empty post-specific subfolder (no files downloaded): '{path_to_check_for_emptiness}'")
                            # We must first remove the ID file(s) before removing the dir
                            if dir_contents:
                                for id_file in dir_contents:
                                    if id_file.startswith('.postid_'):
                                        try:
                                            os.remove(os.path.join(path_to_check_for_emptiness, id_file))
                                        except OSError as e_rm_id:
                                            self.logger(f"   ⚠️ Could not remove ID file '{id_file}' during cleanup: {e_rm_id}")

                            os.rmdir(path_to_check_for_emptiness) # Now the rmdir should work
                except OSError as e_rmdir:
                    self.logger(f"   ⚠️ Could not remove empty post-specific subfolder '{path_to_check_for_emptiness}': {e_rmdir}")

            self._emit_signal('worker_finished', result_tuple)
            return result_tuple

        except Exception as main_thread_err:
            self.logger(f"\n❌ Critical error within Worker process for {log_prefix} {post_id}: {main_thread_err}")
            self.logger(traceback.format_exc())
            result_tuple = (0, 1, [], [], [{'error': str(main_thread_err)}], None, None)
            self._emit_signal('worker_finished', result_tuple)
            return result_tuple

class DownloadThread(QThread):
    progress_signal = pyqtSignal(str)
    add_character_prompt_signal = pyqtSignal(str)
    file_download_status_signal = pyqtSignal(bool)
    finished_signal = pyqtSignal(int, int, bool, list)
    external_link_signal = pyqtSignal(str, str, str, str, str)
    file_successfully_downloaded_signal = pyqtSignal(dict)
    file_progress_signal = pyqtSignal(str, object)
    retryable_file_failed_signal = pyqtSignal(list)
    missed_character_post_signal = pyqtSignal(str, str)
    post_processed_for_history_signal = pyqtSignal(dict)
    final_history_entries_signal = pyqtSignal(list)
    permanent_file_failed_signal = pyqtSignal(list)

    def __init__(self, api_url_input, output_dir, known_names_copy,
                 cancellation_event,
                 pause_event, filter_character_list=None, dynamic_character_filter_holder=None,
                 filter_mode='all', skip_zip=True,
                 use_subfolders=True, use_post_subfolders=False, custom_folder_name=None, compress_images=False,
                 download_thumbnails=False, service=None, user_id=None,
                 downloaded_files=None, downloaded_file_hashes=None, downloaded_files_lock=None, downloaded_file_hashes_lock=None,
                 skip_words_list=None,
                 skip_words_scope='files',
                 show_external_links=False,
                 extract_links_only=False,
                 num_file_threads_for_worker=1,
                 skip_current_file_flag=None,
                 start_page=None, end_page=None,
                 target_post_id_from_initial_url=None,
                 manga_mode_active=False,
                 unwanted_keywords=None,
                 manga_filename_style='post_title',
                 char_filter_scope='files',
                 remove_from_filename_words_list=None,
                 manga_date_prefix='',
                 allow_multipart_download=True,
                 multipart_parts_count=4,
                 multipart_min_size_mb=100,
                 selected_cookie_file=None,
                 override_output_dir=None,
                 app_base_dir=None,
                 manga_date_file_counter_ref=None,
                 manga_global_file_counter_ref=None,
                 use_cookie=False,
                 scan_content_for_images=False,
                 creator_download_folder_ignore_words=None,
                 use_date_prefix_for_subfolder=False,
                 date_prefix_format="YYYY-MM-DD",
                 keep_in_post_duplicates=False,
                 keep_duplicates_mode='hash',
                 keep_duplicates_limit=0,
                 downloaded_hash_counts=None,
                 downloaded_hash_counts_lock=None,
                 cookie_text="",
                 session_file_path=None,
                 session_lock=None,
                 text_only_scope=None,
                 text_export_format='txt',
                 single_pdf_mode=False,
                 project_root_dir=None,
                 processed_post_ids=None,
                 start_offset=0,
                 fetch_first=False,
                 skip_file_size_mb=None,
                 domain_override=None,
                 archive_only_mode=False,
                 manga_custom_filename_format="{published} {title}",
                 manga_custom_date_format="YYYY-MM-DD" ,
                 sfp_threshold=None,
                 creator_name_cache=None

                 ):
        super().__init__()
        self.api_url_input = api_url_input
        self.output_dir = output_dir
        self.known_names = list(known_names_copy)
        self.cancellation_event = cancellation_event
        self.pause_event = pause_event
        self.skip_current_file_flag = skip_current_file_flag
        self.initial_target_post_id = target_post_id_from_initial_url
        self.filter_character_list_objects_initial = filter_character_list if filter_character_list else []
        self.dynamic_filter_holder = dynamic_character_filter_holder
        self.filter_mode = filter_mode
        self.skip_zip = skip_zip
        self.use_subfolders = use_subfolders
        self.use_post_subfolders = use_post_subfolders
        self.custom_folder_name = custom_folder_name
        self.compress_images = compress_images
        self.download_thumbnails = download_thumbnails
        self.service = service
        self.user_id = user_id
        self.skip_words_list = skip_words_list if skip_words_list is not None else []
        self.skip_words_scope = skip_words_scope
        self.downloaded_files = downloaded_files
        self.downloaded_files_lock = downloaded_files_lock
        self.downloaded_file_hashes = downloaded_file_hashes
        self.downloaded_file_hashes_lock = downloaded_file_hashes_lock
        self._add_character_response = None
        self.prompt_mutex = QMutex()
        self.show_external_links = show_external_links
        self.extract_links_only = extract_links_only
        self.num_file_threads_for_worker = num_file_threads_for_worker
        self.start_page = start_page
        self.end_page = end_page
        self.manga_mode_active = manga_mode_active
        self.unwanted_keywords = unwanted_keywords if unwanted_keywords is not None else {'spicy', 'hd', 'nsfw', '4k', 'preview', 'teaser', 'clip'}
        self.manga_filename_style = manga_filename_style
        self.char_filter_scope = char_filter_scope
        self.remove_from_filename_words_list = remove_from_filename_words_list
        self.manga_date_prefix = manga_date_prefix
        self.allow_multipart_download = allow_multipart_download
        self.multipart_parts_count = multipart_parts_count
        self.multipart_min_size_mb = multipart_min_size_mb
        self.selected_cookie_file = selected_cookie_file
        self.app_base_dir = app_base_dir
        self.cookie_text = cookie_text
        self.use_cookie = use_cookie
        self.override_output_dir = override_output_dir
        self.manga_date_file_counter_ref = manga_date_file_counter_ref
        self.scan_content_for_images = scan_content_for_images
        self.creator_download_folder_ignore_words = creator_download_folder_ignore_words
        self.use_date_prefix_for_subfolder = use_date_prefix_for_subfolder
        self.date_prefix_format = date_prefix_format
        self.keep_in_post_duplicates = keep_in_post_duplicates
        self.keep_duplicates_mode = keep_duplicates_mode
        self.keep_duplicates_limit = keep_duplicates_limit
        self.downloaded_hash_counts = downloaded_hash_counts
        self.downloaded_hash_counts_lock = downloaded_hash_counts_lock
        self.manga_global_file_counter_ref = manga_global_file_counter_ref
        self.session_file_path = session_file_path
        self.session_lock = session_lock
        self.history_candidates_buffer = deque(maxlen=8)
        self.text_only_scope = text_only_scope
        self.text_export_format = text_export_format
        self.single_pdf_mode = single_pdf_mode
        self.project_root_dir = project_root_dir
        self.processed_post_ids_set = set(processed_post_ids) if processed_post_ids is not None else set()
        self.start_offset = start_offset
        self.fetch_first = fetch_first
        self.skip_file_size_mb = skip_file_size_mb
        self.archive_only_mode = archive_only_mode
        self.manga_custom_filename_format = manga_custom_filename_format
        self.manga_custom_date_format = manga_custom_date_format
        self.domain_override = domain_override
        self.sfp_threshold = sfp_threshold
        self.creator_name_cache = creator_name_cache

        if self.compress_images and Image is None:
            self.logger("⚠️ Image compression disabled: Pillow library not found (DownloadThread).")
            self.compress_images = False

    def logger(self, message):
        """Emits a progress signal to be displayed in the log."""
        if hasattr(self, 'progress_signal'):
            self.progress_signal.emit(str(message))

    def run(self):
        """
        The main execution method for the download process.
        This version correctly uses the central `download_from_api` function
        and explicitly maps all arguments to the PostProcessorWorker to prevent TypeErrors.
        """
        grand_total_downloaded_files = 0
        grand_total_skipped_files = 0
        grand_list_of_kept_original_filenames = []
        was_process_cancelled = False

        worker_signals_obj = PostProcessorSignals()
        try:
            worker_signals_obj.progress_signal.connect(self.progress_signal)
            worker_signals_obj.file_download_status_signal.connect(self.file_download_status_signal)
            worker_signals_obj.file_progress_signal.connect(self.file_progress_signal)
            worker_signals_obj.external_link_signal.connect(self.external_link_signal)
            worker_signals_obj.missed_character_post_signal.connect(self.missed_character_post_signal)
            worker_signals_obj.file_successfully_downloaded_signal.connect(self.file_successfully_downloaded_signal)
            worker_signals_obj.worker_finished_signal.connect(lambda result: None)

            self.logger("   Starting post fetch (single-threaded download process)...")

            post_generator = download_from_api(
                self.api_url_input,
                logger=self.logger,
                start_page=self.start_page,
                end_page=self.end_page,
                manga_mode=self.manga_mode_active,
                cancellation_event=self.cancellation_event,
                pause_event=self.pause_event,
                use_cookie=self.use_cookie,
                cookie_text=self.cookie_text,
                selected_cookie_file=self.selected_cookie_file,
                app_base_dir=self.app_base_dir,
                manga_filename_style_for_sort_check=self.manga_filename_style if self.manga_mode_active else None,
                processed_post_ids=self.processed_post_ids_set,
                fetch_all_first=self.fetch_first
            )

            for posts_batch_data in post_generator:
                if self.isInterruptionRequested():
                    was_process_cancelled = True
                    break

                for individual_post_data in posts_batch_data:
                    if self.isInterruptionRequested():
                        was_process_cancelled = True
                        break

                    worker_args = {
                        'post_data': individual_post_data,
                        'emitter': worker_signals_obj,
                        'creator_name_cache': self.creator_name_cache,
                        'download_root': self.output_dir,
                        'known_names': self.known_names,
                        'filter_character_list': self.filter_character_list_objects_initial,
                        'dynamic_character_filter_holder': self.dynamic_filter_holder,
                        'target_post_id_from_initial_url': self.initial_target_post_id,
                        'num_file_threads': self.num_file_threads_for_worker,
                        'processed_post_ids': list(self.processed_post_ids_set),
                        'unwanted_keywords': self.unwanted_keywords,
                        'filter_mode': self.filter_mode,
                        'skip_zip': self.skip_zip,
                        'use_subfolders': self.use_subfolders,
                        'use_post_subfolders': self.use_post_subfolders,
                        'custom_folder_name': self.custom_folder_name,
                        'compress_images': self.compress_images,
                        'download_thumbnails': self.download_thumbnails,
                        'service': self.service,
                        'user_id': self.user_id,
                        'api_url_input': self.api_url_input,
                        'pause_event': self.pause_event,
                        'cancellation_event': self.cancellation_event,
                        'downloaded_files': self.downloaded_files,
                        'downloaded_file_hashes': self.downloaded_file_hashes,
                        'downloaded_files_lock': self.downloaded_files_lock,
                        'downloaded_file_hashes_lock': self.downloaded_file_hashes_lock,
                        'skip_words_list': self.skip_words_list,
                        'skip_words_scope': self.skip_words_scope,
                        'show_external_links': self.show_external_links,
                        'extract_links_only': self.extract_links_only,
                        'skip_current_file_flag': self.skip_current_file_flag,
                        'manga_mode_active': self.manga_mode_active,
                        'manga_filename_style': self.manga_filename_style,
                        'char_filter_scope': self.char_filter_scope,
                        'remove_from_filename_words_list': self.remove_from_filename_words_list,
                        'allow_multipart_download': self.allow_multipart_download,
                        'cookie_text': self.cookie_text,
                        'use_cookie': self.use_cookie,
                        'override_output_dir': self.override_output_dir,
                        'selected_cookie_file': self.selected_cookie_file,
                        'app_base_dir': self.app_base_dir,
                        'manga_date_prefix': self.manga_date_prefix,
                        'manga_date_file_counter_ref': self.manga_date_file_counter_ref,
                        'scan_content_for_images': self.scan_content_for_images,
                        'creator_download_folder_ignore_words': self.creator_download_folder_ignore_words,
                        'manga_global_file_counter_ref': self.manga_global_file_counter_ref,
                        'use_date_prefix_for_subfolder': self.use_date_prefix_for_subfolder,
                        'date_prefix_format': self.date_prefix_format,
                        'keep_in_post_duplicates': self.keep_in_post_duplicates,
                        'keep_duplicates_mode': self.keep_duplicates_mode,
                        'keep_duplicates_limit': self.keep_duplicates_limit,
                        'downloaded_hash_counts': self.downloaded_hash_counts,
                        'downloaded_hash_counts_lock': self.downloaded_hash_counts_lock,
                        'session_file_path': self.session_file_path,
                        'session_lock': self.session_lock,
                        'text_only_scope': self.text_only_scope,
                        'text_export_format': self.text_export_format,
                        'single_pdf_mode': self.single_pdf_mode,
                        'multipart_parts_count': self.multipart_parts_count,
                        'multipart_min_size_mb': self.multipart_min_size_mb,
                        'skip_file_size_mb': self.skip_file_size_mb,
                        'project_root_dir': self.project_root_dir,
                        'domain_override': self.domain_override,
                        'archive_only_mode': self.archive_only_mode,
                        'manga_custom_filename_format': self.manga_custom_filename_format,
                        'manga_custom_date_format': self.manga_custom_date_format,
                        'sfp_threshold': self.sfp_threshold
                    }

                    post_processing_worker = PostProcessorWorker(**worker_args)

                    (dl_count, skip_count, kept_originals_this_post,
                     retryable_failures, permanent_failures,
                     history_data, temp_filepath) = post_processing_worker.process()

                    grand_total_downloaded_files += dl_count
                    grand_total_skipped_files += skip_count
                    if kept_originals_this_post:
                        grand_list_of_kept_original_filenames.extend(kept_originals_this_post)
                    if retryable_failures:
                        self.retryable_file_failed_signal.emit(retryable_failures)
                    if history_data:
                        self.post_processed_for_history_signal.emit(history_data)
                    if permanent_failures:
                        self.permanent_file_failed_signal.emit(permanent_failures)
                    if self.single_pdf_mode and temp_filepath:
                        self.progress_signal.emit(f"TEMP_FILE_PATH:{temp_filepath}")

                if was_process_cancelled:
                    break

            if not was_process_cancelled and not self.isInterruptionRequested():
                self.logger("✅ All posts processed or end of content reached by DownloadThread.")


        except Exception as main_thread_err:
            self.logger(f"\n❌ Critical error within DownloadThread run loop: {main_thread_err}")
            traceback.print_exc()
        finally:
            try:
                if worker_signals_obj:
                    worker_signals_obj.progress_signal.disconnect(self.progress_signal)
                    worker_signals_obj.file_download_status_signal.disconnect(self.file_download_status_signal)
                    worker_signals_obj.external_link_signal.disconnect(self.external_link_signal)
                    worker_signals_obj.file_progress_signal.disconnect(self.file_progress_signal)
                    worker_signals_obj.missed_character_post_signal.disconnect(self.missed_character_post_signal)
                    worker_signals_obj.file_successfully_downloaded_signal.disconnect(self.file_successfully_downloaded_signal)
            except (TypeError, RuntimeError) as e:
                self.logger(f"ℹ️ Note during DownloadThread signal disconnection: {e}")

            self.finished_signal.emit(grand_total_downloaded_files, grand_total_skipped_files, self.isInterruptionRequested(), grand_list_of_kept_original_filenames)

class InterruptedError(Exception):
    """Custom exception for handling cancellations gracefully."""
    pass