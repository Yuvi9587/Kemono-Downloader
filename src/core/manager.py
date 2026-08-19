import threading
import time
import os
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, CancelledError
from .api_client import download_from_api
from .workers import PostProcessorWorker
from ..config.constants import (
    STYLE_DATE_BASED, STYLE_POST_TITLE_GLOBAL_NUMBERING,
    MAX_THREADS
)
from ..utils.file_utils import clean_folder_name
from ..utils.network_utils import get_link_platform
from .platform_database import PlatformDatabaseManager
from .visual_sorter import VisualSorter

class DownloadManager:
    """
    Manages the entire download lifecycle, acting as a bridge between the UI
    and the backend workers. It handles thread pools, task submission,
    and state management for a download session.
    """

    def __init__(self, progress_queue):
        """
        Initializes the DownloadManager.

        Args:
            progress_queue (queue.Queue): A thread-safe queue for sending
                                          status updates to the UI.
        """
        self.progress_queue = progress_queue
        self.thread_pool = None
        self.active_futures = []
        self.cancellation_event = threading.Event()
        self.pause_event = threading.Event()
        self.is_running = False
        
        self.total_posts = 0
        self.processed_posts = 0
        self.total_downloads = 0
        self.total_skips = 0
        self.all_kept_original_filenames = []
        self.creator_profiles_dir = None
        self.current_creator_name_for_profile = None
        self.current_creator_profile_path = None
        self.session_file_path = None

    def _log(self, message):
        """Puts a progress message into the queue for the UI."""
        self.progress_queue.put({'type': 'progress', 'payload': (message,)})

    def start_session(self, config, restore_data=None):
        """
        Starts a new download session based on the provided configuration.
        This is the main entry point called by the UI.

        Args:
            config (dict): A dictionary containing all settings from the UI.
            restore_data (dict, optional): Data from a previous, interrupted session.
        """
        if self.is_running:
            self._log("❌ Cannot start a new session: A session is already in progress.")
            return

        self.session_file_path = config.get('session_file_path')
        creator_profile_data = self._setup_creator_profile(config)
        
        if self.current_creator_profile_path:
            creator_profile_data['settings'] = config
            creator_profile_data.setdefault('processed_post_ids', [])
            self._save_creator_profile(creator_profile_data)
            self._log(f"✅ Loaded/created profile for '{self.current_creator_name_for_profile}'. Settings saved.")

        self.is_running = True
        self.cancellation_event.clear()
        self.pause_event.clear()
        self.active_futures.clear()
        self.total_posts = 0
        self.processed_posts = 0
        self.total_downloads = 0
        self.total_skips = 0
        self.all_kept_original_filenames = []
        
        is_single_post = bool(config.get('target_post_id_from_initial_url'))
        use_multithreading = config.get('use_multithreading', True)
        
        sequential_styles = [STYLE_DATE_BASED, STYLE_POST_TITLE_GLOBAL_NUMBERING]
        
        is_manga_sequential = (
            config.get('manga_mode_active') and 
            config.get('manga_filename_style') in sequential_styles
        )

        should_use_multithreading_for_posts = use_multithreading and not is_single_post and not is_manga_sequential
        
        if should_use_multithreading_for_posts:
            fetcher_thread = threading.Thread(
                target=self._fetch_and_queue_posts_for_pool,
                args=(config, restore_data, creator_profile_data),
                daemon=True
            )
            fetcher_thread.start()
        else:
            self._log("ℹ️ Manager is handing off to a single-threaded worker (Sequential Mode)...")
            self.is_running = False
            self.progress_queue.put({'type': 'handoff_to_single_thread', 'payload': (config,)})

    def _get_proxies_from_config(self, config):
        """Constructs the proxy dictionary from the config.

        Prefers the pre-built 'proxies' dict that main_window.py assembles,
        because it already uses the correct scheme (http://, socks4://, socks5h://)
        based on the user's selected proxy type. Falls back to building one
        manually (HTTP only) for callers that pass a minimal config without
        the pre-built dict.
        """
        if not config.get('proxy_enabled'):
            return None

        # If main_window already built a correctly-schemed proxies dict, use it.
        if config.get('proxies') is not None:
            return config['proxies']

        # Fallback: build from individual fields (HTTP only).
        host = config.get('proxy_host')
        port = config.get('proxy_port')
        if not host or not port:
            return None

        proxy_type = config.get('proxy_type', 'HTTP').upper()
        if proxy_type == 'SOCKS5':
            scheme = 'socks5h'
        elif proxy_type == 'SOCKS4':
            scheme = 'socks4'
        else:
            scheme = 'http'

        user = config.get('proxy_username')
        password = config.get('proxy_password')
        if user and password:
            proxy_str = f"{scheme}://{user}:{password}@{host}:{port}"
        else:
            proxy_str = f"{scheme}://{host}:{port}"

        return {
            "http": proxy_str,
            "https": proxy_str
        }

    def _fetch_and_queue_posts_for_pool(self, config, restore_data, creator_profile_data):
        """
        Fetches posts from the API in batches and submits them as tasks to a thread pool.
        This method runs in its own dedicated thread to avoid blocking the UI.
        It provides immediate feedback as soon as the first batch of posts is found.
        """
        try:
            num_workers = min(config.get('num_threads', 4), MAX_THREADS)
            self.thread_pool = ThreadPoolExecutor(max_workers=num_workers, thread_name_prefix='PostWorker_')

            session_processed_ids = set(restore_data.get('processed_post_ids', [])) if restore_data else set()
            profile_processed_ids = set(creator_profile_data.get('processed_post_ids', []))
            processed_ids = session_processed_ids.union(profile_processed_ids)
            
            proxies = self._get_proxies_from_config(config)

            if restore_data and 'all_posts_data' in restore_data:
                all_posts = restore_data['all_posts_data']
                posts_to_process = [p for p in all_posts if p.get('id') not in processed_ids]
                self.total_posts = len(all_posts)
                self.processed_posts = len(processed_ids)
                self._log(f"🔄 Restoring session. {len(posts_to_process)} posts remaining.")
                self.progress_queue.put({'type': 'overall_progress', 'payload': (self.total_posts, self.processed_posts)})
                
                if not posts_to_process:
                    self._log("✅ No new posts to process from restored session.")
                    return

                for post_data in posts_to_process:
                    if self.cancellation_event.is_set():
                        break
                    
                    worker_args = self._map_config_to_worker_args(post_data, config)
                    worker_args['proxies'] = proxies
                    
                    worker = PostProcessorWorker(**worker_args)
                    future = self.thread_pool.submit(worker.process)
                    future.add_done_callback(self._handle_future_result)
                    self.active_futures.append(future)
            else:
                if proxies:
                    self._log(f"   🌐 Using Proxy: {config.get('proxy_host')}:{config.get('proxy_port')}")

                post_generator = download_from_api(
                    api_url_input=config['api_url'],
                    logger=self._log,
                    start_page=config.get('start_page'),
                    end_page=config.get('end_page'),
                    cancellation_event=self.cancellation_event,
                    pause_event=self.pause_event,
                    cookies_dict=None,
                    proxies=proxies
                )

                for post_batch in post_generator:
                    if self.cancellation_event.is_set():
                        break
                    
                    if not post_batch:
                        continue

                    new_posts_batch = [p for p in post_batch if p.get('id') not in processed_ids]
                    
                    if not new_posts_batch:
                         continue

                    self.total_posts += len(new_posts_batch) 
                    
                    for post_data in new_posts_batch:
                        if self.cancellation_event.is_set():
                            break
                        
                        worker_args = self._map_config_to_worker_args(post_data, config)
                        worker = PostProcessorWorker(**worker_args)
                        
                        future = self.thread_pool.submit(worker.process)
                        future.add_done_callback(self._handle_future_result)
                        self.active_futures.append(future)
                        
                    time.sleep(0.01)

        except Exception as e:
            self._log(f"❌ Critical Error in Fetcher Thread: {e}")
            traceback.print_exc()
        finally:
            self.is_running = False

    def _map_config_to_worker_args(self, post_data, config):
        """Helper to map the flat config dict to PostProcessorWorker arguments."""
        proxies = self._get_proxies_from_config(config)

        return {
            'post_data': post_data,
            'download_root': config.get('output_dir'),
            'known_names': [],
            'filter_character_list': [],
            'emitter': self.progress_queue,
            'unwanted_keywords': set(),
            'filter_mode': config.get('filter_mode'),
            'skip_zip': config.get('skip_zip'),
            'use_subfolders': config.get('use_subfolders'),
            'use_post_subfolders': config.get('use_post_subfolders'),
            'target_post_id_from_initial_url': config.get('target_post_id_from_initial_url'),
            'custom_folder_name': config.get('custom_folder_name'),
            'compress_images': config.get('compress_images'),
            'download_thumbnails': config.get('download_thumbnails'),
            'service': config.get('service') or 'unknown',
            'user_id': config.get('user_id') or 'unknown',
            'pause_event': self.pause_event,
            'api_url_input': config.get('api_url'),
            'cancellation_event': self.cancellation_event,
            'downloaded_files': None, 
            'downloaded_file_hashes': None,
            'downloaded_files_lock': None,
            'downloaded_file_hashes_lock': None,
            'manga_mode_active': config.get('manga_mode_active'),
            'manga_filename_style': config.get('manga_filename_style'),
            'manga_custom_filename_format': config.get('custom_manga_filename_format', "{published} {title}"),
            'manga_custom_date_format': config.get('manga_custom_date_format', "YYYY-MM-DD"),
            'use_multithreading': config.get('use_multithreading', True),
            'proxies': proxies,
            'download_revisions': config.get('download_revisions', False),
            'visual_sort_active': config.get('visual_sort_active', False),
            'user_data_path': config.get('user_data_path', None)
        }
        
    def _setup_creator_profile(self, config):
        """Prepares the path and loads data for the current creator's profile."""
        self.current_creator_name_for_profile = "Unknown" 
        return {}

    def _save_creator_profile(self, data):
        """(DEPRECATED) Replaced by SQLite PlatformDatabaseManager. Does nothing."""
        return

    def cancel_session(self):
        """Cancels the current running session."""
        if not self.is_running:
            return
        
        if self.cancellation_event.is_set():
            self._log("ℹ️ Cancellation already in progress.")
            return

        self._log("⚠️ Cancellation requested by user...")
        self.cancellation_event.set()

        if self.thread_pool:
            self.thread_pool.shutdown(wait=False, cancel_futures=True)

    def _handle_future_result(self, future):
        """Callback for when a worker task finishes."""
        if self.active_futures:
            try:
                self.active_futures.remove(future)
            except ValueError:
                pass
        
        try:
            result = future.result()
            if result:
                self.total_downloads += result[0]
                self.total_skips += result[1]
                if len(result) > 3 and result[3]:
                    pass
        except CancelledError:
            pass
        except Exception as e:
            self._log(f"❌ Worker Error: {e}")
        
        self.processed_posts += 1
        self.progress_queue.put({'type': 'overall_progress', 'payload': (self.total_posts, self.processed_posts)})

        if not self.active_futures and not self.is_running:
            self._log("✅ All tasks completed.")
            self.progress_queue.put({'type': 'worker_finished', 'payload': (self.total_downloads, self.total_skips, [], [])})