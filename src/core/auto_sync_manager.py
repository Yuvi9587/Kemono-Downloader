import json
import os
import time
from PySide6.QtCore import QObject, QTimer, Signal, QEvent
from PySide6.QtWidgets import QApplication

class AppEventFilter(QObject):
    def __init__(self):
        super().__init__()
        self.last_activity_time = time.time()
        
    def eventFilter(self, obj, event):
        # We listen to all input events to reset the idle timer
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel):
            self.last_activity_time = time.time()
        return False

class AutoSyncManager(QObject):
    """
    Background daemon that periodically reads the user's Local Subscriptions
    and automatically triggers downloads for them silently.
    """
    
    # Signal to emit the next URL and its JSON settings to download so it runs in the main thread
    trigger_download_signal = Signal(str, str)
    # Signal emitted when the full sync queue is drained
    sync_cycle_complete = Signal()

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        self.has_run_this_session = False
        
        # Idle detection
        self.event_filter = AppEventFilter()
        app = QApplication.instance()
        if app:
            app.installEventFilter(self.event_filter)
            
        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self._check_idle_state)
        
        # We also need a fast timer to process the queue one by one
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self.process_queue)
        
        self.subscription_queue = []
        self.is_processing = False

        # Connect the signal to the slot we will create in main_window
        self.trigger_download_signal.connect(self.main_window._handle_background_sync_download)

        # Load settings and start timer if enabled
        self.check_and_start()

    def check_and_start(self):
        """Checks if auto-sync is enabled in settings and starts the idle checker."""
        if hasattr(self.main_window, 'settings'):
            enabled = self.main_window.settings.value("auto_sync_enabled", False, type=bool)
            if enabled:
                # Start checking for idle every 1 second
                self.idle_check_timer.start(1000) 
            else:
                self.idle_check_timer.stop()

    def _check_idle_state(self):
        if self.has_run_this_session or self.is_processing:
            return
            
        # Get threshold (default 10s)
        idle_threshold = self.main_window.settings.value("auto_sync_idle_threshold", 10, type=int) if hasattr(self.main_window, 'settings') else 10
        
        idle_time = time.time() - self.event_filter.last_activity_time
        
        # If idle enough and NO manual download active
        if idle_time >= idle_threshold:
            if not self.main_window._is_download_active() and not getattr(self.main_window, 'is_processing_favorites_queue', False):
                self.run_sync_cycle()

    def load_subscriptions(self):
        subs = []
        appdata_dir = getattr(self.main_window, 'app_base_dir', '')
        if not appdata_dir:
            return subs
            
        appdata_dir = os.path.join(appdata_dir, "appdata")
        db_dir = os.path.join(appdata_dir, "databases")
        if not os.path.exists(db_dir):
            return subs
            
        from .platform_database import PlatformDatabaseManager
        
        for file in os.listdir(db_dir):
            if file.endswith(".db"):
                platform_name = file.replace(".db", "")
                try:
                    db_manager = PlatformDatabaseManager.get_instance(platform_name, appdata_dir)
                    creators = db_manager.get_all_creators()
                    for c in creators:
                        if c.get('is_synced'):
                            service = c.get('service')
                            creator_id = c.get('creator_id')
                            if not service or not creator_id:
                                continue
                            
                            # Construct URL
                            if platform_name == 'kemono':
                                url = f"https://kemono.su/{service}/user/{creator_id}"
                            elif platform_name == 'pawchive':
                                url = f"https://pawchive.pw/{service}/user/{creator_id}"
                            elif platform_name == 'coomer':
                                url = f"https://coomer.su/{service}/user/{creator_id}"
                            else:
                                url = f"https://{platform_name}.su/{service}/user/{creator_id}" # Fallback
                                
                            subs.append({
                                'url': url,
                                'title': c.get('original_name', 'Unknown'),
                                'sync_settings': c.get('sync_settings') or ""
                            })
                except Exception as e:
                    print(f"AutoSync Error reading DB {file}: {e}")
        return subs

    def run_sync_cycle(self):
        """Called when the app becomes idle to populate the queue with all subscriptions."""
        if self.is_processing or self.has_run_this_session:
            return # Skip if already processing or already ran this session
            
        self.has_run_this_session = True
            
        subs = self.load_subscriptions()
        if not subs:
            return
            
        # Add all subscriptions to the queue
        self.subscription_queue = list(subs)
        self.is_processing = True
        
        # Start checking the queue every 5 seconds
        self.queue_timer.start(5000)

    def process_queue(self):
        """
        Checks if the app is currently busy. If not, it pops the next URL
        from the queue and triggers a download.
        """
        # If the main window is currently downloading something, wait.
        if self.main_window._is_download_active() or getattr(self.main_window, 'is_processing_favorites_queue', False):
            return

        if not self.subscription_queue:
            # Queue is empty — fire completion unconditionally regardless of idle state.
            self.queue_timer.stop()
            self.is_processing = False
            
            # Reset silent flag
            self.main_window.is_silent_background_sync = False
            
            # Notify the active dialog that the full cycle is done
            self.sync_cycle_complete.emit()
            dialog = getattr(self.main_window, 'active_sync_log_dialog', None)
            if dialog is not None:
                try:
                    dialog.on_sync_cycle_complete()
                except Exception:
                    pass
            return

        # Idle check only gates launching the NEXT download.
        # If the user became active, wait until they are idle again.
        idle_threshold = self.main_window.settings.value("auto_sync_idle_threshold", 10, type=int) if hasattr(self.main_window, 'settings') else 10
        idle_time = time.time() - self.event_filter.last_activity_time
        if idle_time < idle_threshold:
            return  # Wait until the user is idle again


            
        # Get the next subscription
        next_sub = self.subscription_queue.pop(0)
        next_url = next_sub.get('url')
        sync_settings_json = next_sub.get('sync_settings', "")
        
        try:
            settings_dict = json.loads(sync_settings_json) if sync_settings_json else {}
            settings_dict['_auto_sync_creator_name'] = next_sub.get('title', 'Unknown')
            sync_settings_json = json.dumps(settings_dict)
        except Exception:
            pass
        
        # We need to tell the main window that this is a silent background sync
        # so it doesn't show popup errors.
        self.main_window.is_silent_background_sync = True
        
        # We trigger the download using a signal to ensure it runs safely on the main thread
        self.trigger_download_signal.emit(next_url, sync_settings_json)
