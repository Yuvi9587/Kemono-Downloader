import os
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QGroupBox, 
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QLabel, QAbstractItemView, QMessageBox, QFileDialog, QProgressBar, QTextEdit,
    QSpinBox, QFormLayout, QLineEdit, QComboBox
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt, QThread, Signal, Slot
import hashlib
import json
from ...core.platform_database import PlatformDatabaseManager
from ..assets import get_asset_path
import re as _re


class RepairWorker(QThread):
    progress_signal = Signal(int, int)
    log_signal = Signal(str)
    finished_signal = Signal(int, int, int) # healed, deleted, total

    def __init__(self, appdata_dir, scan_path, deep_scan=False):
        super().__init__()
        self.appdata_dir = appdata_dir
        self.scan_path = scan_path
        self.deep_scan = deep_scan
        self.is_cancelled = False

    def run(self):
        self.log_signal.emit(f"🚀 Starting Database Repair Engine...")
        self.log_signal.emit(f"📂 Target Area: {self.scan_path}")
        
        db_dir = os.path.join(self.appdata_dir, "databases")
        if not os.path.exists(db_dir):
            self.log_signal.emit("❌ Database directory not found.")
            return

        all_entries_to_check = []

        # 1. Gather all database entries
        self.log_signal.emit("📊 Analyzing databases...")
        for file in os.listdir(db_dir):
            if not file.endswith(".db"):
                continue
            platform_name = file.replace(".db", "")
            try:
                db_manager = PlatformDatabaseManager.get_instance(platform_name, self.appdata_dir)
                creators = db_manager.get_all_creators()
                for c in creators:
                    table_name = c['sanitized_table_name']
                    creator_id = c['creator_id']
                    service = c['service']
                    
                    sync_settings_json = c.get('sync_settings') or '{}'
                    try:
                        sync_settings = json.loads(sync_settings_json)
                    except json.JSONDecodeError:
                        sync_settings = {}
                        
                    old_output_dir = sync_settings.get('output_dir', '')
                    
                    # We need to make sure the table has the saved_path column, otherwise skip or handle
                    try:
                        db_manager.cursor.execute(f"SELECT hash, original_filename, saved_filename, saved_path FROM {table_name}")
                        rows = db_manager.cursor.fetchall()
                        for row in rows:
                            file_hash, orig_name, saved_name, saved_path = row
                            
                            rel_path = ""
                            if old_output_dir and saved_path and saved_path.startswith(old_output_dir):
                                rel_path = os.path.relpath(saved_path, old_output_dir)
                                
                            all_entries_to_check.append({
                                'platform': platform_name,
                                'table': table_name,
                                'creator_id': creator_id,
                                'service': service,
                                'sync_settings_json': sync_settings_json,
                                'old_output_dir': old_output_dir,
                                'rel_path': rel_path,
                                'hash': file_hash,
                                'orig_name': orig_name,
                                'saved_name': saved_name,
                                'saved_path': saved_path
                            })
                    except Exception as col_err:
                        self.log_signal.emit(f"⚠️ Skipping table {table_name}: {col_err}")
            except Exception as e:
                self.log_signal.emit(f"⚠️ Error reading {file}: {e}")

        total_entries = len(all_entries_to_check)
        self.log_signal.emit(f"✅ Found {total_entries} total downloaded file records.")
        
        # 2. Check which are physically missing
        missing_entries = []
        for i, entry in enumerate(all_entries_to_check):
            if self.is_cancelled:
                return
                
            path = entry['saved_path']
            if not path or not os.path.exists(path):
                missing_entries.append(entry)
                
            if i % 1000 == 0:
                self.progress_signal.emit(i, total_entries)

        self.progress_signal.emit(total_entries, total_entries)
        
        if not missing_entries:
            self.log_signal.emit("🎉 Perfect Database Integrity! No files are missing.")
            self.finished_signal.emit(0, 0, total_entries)
            return

        self.log_signal.emit(f"⚠️ Found {len(missing_entries)} missing files. Initiating physical search...")

        # Build a lookup dictionary for fast matching by filename
        # We index by both original_filename and saved_filename
        missing_lookup = {}
        for entry in missing_entries:
            orig = entry.get('orig_name')
            saved = entry.get('saved_name')
            if orig: missing_lookup.setdefault(orig, []).append(entry)
            if saved: missing_lookup.setdefault(saved, []).append(entry)

        healed_count = 0
        deleted_count = 0
        updated_creators = {}
        
        # 3. Walk the file system
        try:
            for root, _, files in os.walk(self.scan_path):
                if self.is_cancelled:
                    return
                for file_name in files:
                    # Check if this filename is in our missing list
                    if file_name in missing_lookup:
                        full_path = os.path.join(root, file_name)
                        try:
                            # Verify Hash
                            hasher = hashlib.sha256()
                            with open(full_path, "rb") as f:
                                for chunk in iter(lambda: f.read(4096), b""):
                                    hasher.update(chunk)
                                    if self.is_cancelled: return
                            file_hash = hasher.hexdigest()
                            
                            # Check if the hash matches any of the missing entries for this filename
                            candidates = missing_lookup[file_name]
                            for candidate in candidates:
                                if candidate.get('hash') == file_hash:
                                    # We found it! Heal the database
                                    platform_name = candidate['platform']
                                    table = candidate['table']
                                    creator_id = candidate['creator_id']
                                    service = candidate['service']
                                    rel_path = candidate.get('rel_path')
                                    old_output_dir = candidate.get('old_output_dir')
                                    
                                    db_manager = PlatformDatabaseManager.get_instance(platform_name, self.appdata_dir)
                                    db_manager.cursor.execute(f"UPDATE {table} SET saved_path = ? WHERE hash = ?", (full_path, file_hash))
                                    db_manager.conn.commit()
                                    
                                    # Deduce new base folder if we have a valid relative path
                                    if rel_path and full_path.endswith(rel_path):
                                        new_out = full_path[:-len(rel_path)].rstrip('\\/')
                                        if new_out and new_out != old_output_dir:
                                            key = f"{platform_name}_{creator_id}"
                                            if key not in updated_creators:
                                                updated_creators[key] = {
                                                    'platform': platform_name,
                                                    'creator_id': creator_id,
                                                    'service': service,
                                                    'settings_json': candidate.get('sync_settings_json', '{}'),
                                                    'new_output_dir': new_out
                                                }
                                    
                                    self.log_signal.emit(f"✅ HEALED: {file_name}")
                                    healed_count += 1
                                    candidate['healed'] = True
                        except Exception as e:
                            self.log_signal.emit(f"⚠️ Could not verify {file_name}: {e}")
        except Exception as e:
            self.log_signal.emit(f"❌ Critical error during physical search: {e}")

        # 4. Delete entries that are still missing
        self.log_signal.emit("🗑️ Pruning unrecoverable database entries...")
        for entry in missing_entries:
            if self.is_cancelled: return
            if not entry.get('healed'):
                try:
                    platform_name = entry['platform']
                    table = entry['table']
                    file_hash = entry['hash']
                    
                    db_manager = PlatformDatabaseManager.get_instance(platform_name, self.appdata_dir)
                    db_manager.cursor.execute(f"DELETE FROM {table} WHERE hash = ?", (file_hash,))
                    db_manager.conn.commit()
                    deleted_count += 1
                except Exception as e:
                    pass

        # 5. Update creator mappings for deduced output directories
        if updated_creators:
            self.log_signal.emit(f"🔄 Deduced new base folders for {len(updated_creators)} creator(s). Updating sync settings...")
            for key, info in updated_creators.items():
                try:
                    db_manager = PlatformDatabaseManager.get_instance(info['platform'], self.appdata_dir)
                    settings = json.loads(info['settings_json'])
                    settings['output_dir'] = info['new_output_dir']
                    new_settings_str = json.dumps(settings)
                    db_manager.update_sync_settings(info['creator_id'], info['service'], new_settings_str)
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Failed to update sync settings for {info['creator_id']}: {e}")

        self.log_signal.emit(f"🏁 Repair Complete! Healed: {healed_count}. Pruned: {deleted_count}.")
        self.finished_signal.emit(healed_count, deleted_count, total_entries)


class AutoSyncDialog(QDialog):
    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.setWindowTitle("Auto-Sync Hub")
        self.resize(800, 600)
        self.repair_worker = None
        
        # Per-session sync statistics (reset each time a new cycle starts)
        self._sync_stats = {}
        self._current_sync_creator = None
        
        self._setup_ui()
        self._load_auto_sync_settings()
        self._populate_sync_table()
        
        # Register this dialog as the active sync log target on the parent app
        self.parent_app.active_sync_log_dialog = self

    def closeEvent(self, event):
        # Unregister when dialog is closed
        if getattr(self.parent_app, 'active_sync_log_dialog', None) is self:
            self.parent_app.active_sync_log_dialog = None
        super().closeEvent(event)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        self.sync_tab = QWidget()
        self.repair_tab = QWidget()
        self.activity_tab = QWidget()
        
        self.tab_widget.addTab(self.sync_tab, "Monitored Creators")
        self.tab_widget.addTab(self.activity_tab, "Activity Log")
        self.tab_widget.addTab(self.repair_tab, "Database Repair")
        
        self.advanced_tab = QWidget()
        self.tab_widget.addTab(self.advanced_tab, "Advanced Settings")
        
        self._setup_sync_tab()
        self._setup_activity_tab()
        self._setup_repair_tab()
        self._setup_advanced_tab()
        
        # Close Button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _setup_sync_tab(self):
        layout = QVBoxLayout(self.sync_tab)
        
        # Status
        desc = QLabel("Check the box next to any creator to automatically download their new posts in the background.\nThe app must be left open (or minimized to the system tray) for the daemon to run.")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Table
        self.sync_table = QTableWidget(0, 5)
        self.sync_table.setHorizontalHeaderLabels(["Sync", "Creator Name", "Platform", "Service", "Output Directory"])
        self.sync_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sync_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.sync_table.verticalHeader().setVisible(False)
        self.sync_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sync_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sync_table.setShowGrid(False)
        self.sync_table.setAlternatingRowColors(True)
        self.sync_table.itemChanged.connect(self._on_sync_item_changed)
        layout.addWidget(self.sync_table)
        
        refresh_btn = QPushButton("Refresh Creator List")
        refresh_btn.clicked.connect(self._populate_sync_table)
        layout.addWidget(refresh_btn)
        
        # Settings
        settings_group = QGroupBox("Daemon Settings")
        settings_layout = QVBoxLayout(settings_group)
        
        self.enable_sync_cb = QCheckBox("Enable Background Auto-Sync (Set & Forget)")
        self.enable_sync_cb.stateChanged.connect(self._save_auto_sync_settings)
        settings_layout.addWidget(self.enable_sync_cb)
        
        self.minimize_to_tray_cb = QCheckBox("Minimize to System Tray instead of closing")
        self.minimize_to_tray_cb.stateChanged.connect(self._save_auto_sync_settings)
        settings_layout.addWidget(self.minimize_to_tray_cb)
        
        layout.addWidget(settings_group)

    def _setup_activity_tab(self):
        layout = QVBoxLayout(self.activity_tab)
        
        desc = QLabel(
            "<b>Auto-Sync Activity Log</b><br><br>"
            "When the background daemon is running, its activity is displayed here instead of in the main log, "
            "so your main log stays clean. Keep this dialog open to monitor live progress."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        btn_layout = QHBoxLayout()
        
        self.pause_sync_btn = QPushButton("Pause Sync")
        self.pause_sync_btn.clicked.connect(self._toggle_pause)
        btn_layout.addWidget(self.pause_sync_btn)
        
        self.cancel_sync_btn = QPushButton("Cancel Sync")
        self.cancel_sync_btn.clicked.connect(self._cancel_sync)
        btn_layout.addWidget(self.cancel_sync_btn)
        
        btn_layout.addStretch()
        
        self.show_summary_btn = QPushButton("Show Summary")
        self.show_summary_btn.setEnabled(False)
        self.show_summary_btn.setToolTip("Available after all monitored creators have been synced.")
        self.show_summary_btn.clicked.connect(self._show_sync_summary)
        btn_layout.addWidget(self.show_summary_btn)
        
        self.clear_activity_log_btn = QPushButton("Clear Log")
        self.clear_activity_log_btn.clicked.connect(self._clear_activity_log)
        btn_layout.addWidget(self.clear_activity_log_btn)
        
        layout.addLayout(btn_layout)
        
        self.activity_log_output = QTextEdit()
        self.activity_log_output.setReadOnly(True)
        self.activity_log_output.setLineWrapMode(QTextEdit.NoWrap)
        self.activity_log_output.setPlaceholderText(
            "Auto-Sync activity will appear here when the background daemon runs..."
        )
        layout.addWidget(self.activity_log_output)

    def _setup_repair_tab(self):
        layout = QVBoxLayout(self.repair_tab)
        
        desc = QLabel(
            "<b>Self-Healing Database Engine</b><br><br>"
            "If you move, rename, or delete files on your hard drive, the database will eventually lose track of them. "
            "This tool scans your drives, matches files by name, and verifies their hash to 'heal' the database. "
            "If a file is completely missing, it deletes the database entry so it can be re-downloaded naturally."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # Controls
        ctrl_layout = QHBoxLayout()
        self.target_folder_btn = QPushButton("Scan Target Folder (Fast)")
        self.target_folder_btn.clicked.connect(self._scan_target)
        
        self.deep_scan_btn = QPushButton("Deep Scan Entire Drive (Slow)")
        self.deep_scan_btn.clicked.connect(self._deep_scan)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_repair)
        
        ctrl_layout.addWidget(self.target_folder_btn)
        ctrl_layout.addWidget(self.deep_scan_btn)
        ctrl_layout.addWidget(self.stop_btn)
        layout.addLayout(ctrl_layout)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Log
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    def _setup_advanced_tab(self):
        layout = QVBoxLayout(self.advanced_tab)
        
        # Trigger Options
        trigger_group = QGroupBox("Daemon Trigger Options")
        trigger_layout = QFormLayout(trigger_group)
        
        self.idle_threshold_spin = QSpinBox()
        self.idle_threshold_spin.setRange(1, 3600)
        self.idle_threshold_spin.setValue(10)
        self.idle_threshold_spin.setToolTip("Seconds of user inactivity before auto-sync triggers (runs once per startup).")
        self.idle_threshold_spin.valueChanged.connect(self._save_auto_sync_settings)
        trigger_layout.addRow("Start Auto-Sync after app is idle for (seconds):", self.idle_threshold_spin)
        
        layout.addWidget(trigger_group)
        
        # Scan Optimization Group
        scan_group = QGroupBox("Scan Optimization")
        scan_layout = QFormLayout(scan_group)
        
        self.enable_early_stop_cb = QCheckBox("Enable Early Stop (Stop scanning when old posts are found)")
        self.enable_early_stop_cb.setChecked(True)
        self.enable_early_stop_cb.stateChanged.connect(self._save_auto_sync_settings)
        scan_layout.addRow(self.enable_early_stop_cb)
        
        self.early_stop_threshold_spin = QSpinBox()
        self.early_stop_threshold_spin.setRange(0, 100)
        self.early_stop_threshold_spin.setValue(0)
        self.early_stop_threshold_spin.setToolTip("0 = Disabled")
        self.early_stop_threshold_spin.valueChanged.connect(self._save_auto_sync_settings)
        scan_layout.addRow("Stop after X consecutive skipped posts (0 = disabled):", self.early_stop_threshold_spin)
        
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(0, 1000)
        self.max_pages_spin.setValue(1)
        self.max_pages_spin.setToolTip("0 = Unlimited")
        self.max_pages_spin.valueChanged.connect(self._save_auto_sync_settings)
        scan_layout.addRow("Max pages to scan per creator (0 = unlimited):", self.max_pages_spin)
        
        layout.addWidget(scan_group)
        
        # Error Handling Group
        error_group = QGroupBox("Error Handling")
        error_layout = QVBoxLayout(error_group)
        
        self.retry_404_cb = QCheckBox("Retry 404 Not Found errors on next sync")
        self.retry_404_cb.setToolTip("If unchecked, 404 errors (files not on server) are silently skipped.")
        self.retry_404_cb.stateChanged.connect(self._save_auto_sync_settings)
        error_layout.addWidget(self.retry_404_cb)
        
        layout.addWidget(error_group)
        
        # Network Group
        network_group = QGroupBox("Network Settings (Auto Sync Only)")
        network_layout = QFormLayout(network_group)
        
        self.proxy_override_cb = QCheckBox("Override global proxy settings during Auto Sync")
        self.proxy_override_cb.setToolTip("If enabled, Auto Sync will use the proxy settings defined below instead of your global settings. If you want Auto Sync to run WITHOUT a proxy, check this and leave 'Enable Proxy' unchecked.")
        self.proxy_override_cb.stateChanged.connect(self._save_auto_sync_settings)
        network_layout.addRow(self.proxy_override_cb)
        
        self.use_proxy_cb = QCheckBox("Enable Proxy for Auto Sync")
        self.use_proxy_cb.stateChanged.connect(self._save_auto_sync_settings)
        network_layout.addRow(self.use_proxy_cb)
        
        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["HTTP", "SOCKS4", "SOCKS5"])
        self.proxy_type_combo.currentIndexChanged.connect(self._save_auto_sync_settings)
        network_layout.addRow("Proxy Type:", self.proxy_type_combo)
        
        self.proxy_host_input = QLineEdit()
        self.proxy_host_input.editingFinished.connect(self._save_auto_sync_settings)
        network_layout.addRow("Proxy Host:", self.proxy_host_input)
        
        self.proxy_port_input = QLineEdit()
        self.proxy_port_input.editingFinished.connect(self._save_auto_sync_settings)
        network_layout.addRow("Proxy Port:", self.proxy_port_input)
        
        self.proxy_user_input = QLineEdit()
        self.proxy_user_input.editingFinished.connect(self._save_auto_sync_settings)
        network_layout.addRow("Proxy Username (Optional):", self.proxy_user_input)
        
        self.proxy_pass_input = QLineEdit()
        self.proxy_pass_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.proxy_pass_input.editingFinished.connect(self._save_auto_sync_settings)
        network_layout.addRow("Proxy Password (Optional):", self.proxy_pass_input)
        
        # Disable sub-settings if override is unchecked
        self.proxy_override_cb.toggled.connect(
            lambda checked: [
                self.use_proxy_cb.setEnabled(checked),
                self.proxy_type_combo.setEnabled(checked),
                self.proxy_host_input.setEnabled(checked),
                self.proxy_port_input.setEnabled(checked),
                self.proxy_user_input.setEnabled(checked),
                self.proxy_pass_input.setEnabled(checked)
            ]
        )
        
        layout.addWidget(network_group)
        layout.addStretch()

    @Slot(str)
    def append_sync_log(self, message):
        """
        Receives a log message from the main window during a background sync
        and appends a simplified, clean version to the Activity Log tab.
        Noisy/verbose debug lines are filtered out automatically.
        """
        # Filter out internal debug / verbose lines that clutter the log
        _noise_prefixes = (
            "--- DEBUG:",
            "==> Returning:",
            "single_thread_active:",
            "is_fetcher_thread_running:",
            "is_fetching_only:",
            "RENAMING_MODE_FETCH",
            "TEMP_FILE_PATH:",
            "   ->",          # hash skip verbose lines
        )
        _noise_substrings = (
            "shiboken6",
            "libpyside",
        )
        msg_stripped = message.strip()
        if not msg_stripped:
            return
        if any(msg_stripped.startswith(p) for p in _noise_prefixes):
            return
        if any(s in msg_stripped for s in _noise_substrings):
            return

        # --- Stat parsing ---
        import re as _re
        # Detect which creator is being synced
        _creator_match = _re.search(r'triggering download for:\s*(.+)', msg_stripped)
        if _creator_match:
            url_part = _creator_match.group(1).strip()
            if " | Creator: " in url_part:
                url, creator_label = url_part.split(" | Creator: ", 1)
            else:
                url = url_part
                # Derive a short label from the URL
                _tags = _re.search(r'tags=([^&\s]+)', url)
                if _tags:
                    creator_label = _tags.group(1)
                else:
                    creator_label = url.rstrip('/').split('/')[-1]
            self._current_sync_creator = creator_label
            if creator_label not in self._sync_stats:
                self._sync_stats[creator_label] = {'downloaded': 0, 'skipped': 0, 'failed': 0}

        if self._current_sync_creator:
            key = self._current_sync_creator
            if key not in self._sync_stats:
                self._sync_stats[key] = {'downloaded': 0, 'skipped': 0, 'failed': 0}
            _dl_match = _re.search(r'Download complete.*?(\d+)\s+downloaded.*?(\d+)\s+skipped', msg_stripped, _re.IGNORECASE)
            if _dl_match:
                self._sync_stats[key]['downloaded'] += int(_dl_match.group(1))
                self._sync_stats[key]['skipped'] += int(_dl_match.group(2))
            if _re.search(r'\u274c|failed|error', msg_stripped, _re.IGNORECASE):
                self._sync_stats[key]['failed'] += 1

        # Switch to the Activity tab and flash it if the user is on a different tab
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.activity_log_output.append(f"[{timestamp}] {msg_stripped}")
            
            # Auto-scroll
            scrollbar = self.activity_log_output.verticalScrollBar()
            if scrollbar.value() >= scrollbar.maximum() - 30:
                scrollbar.setValue(scrollbar.maximum())
                
            # Highlight the Activity tab if not currently selected
            activity_tab_index = self.tab_widget.indexOf(self.activity_tab)
            if self.tab_widget.currentIndex() != activity_tab_index:
                self.tab_widget.setTabText(activity_tab_index, "Activity Log \u2022")
        except Exception:
            pass

    def _clear_activity_log(self):
        self.activity_log_output.clear()
        self._sync_stats = {}
        self._current_sync_creator = None
        self.show_summary_btn.setEnabled(False)
        activity_tab_index = self.tab_widget.indexOf(self.activity_tab)
        self.tab_widget.setTabText(activity_tab_index, "Activity Log")

    def on_sync_cycle_complete(self):
        """Called by AutoSyncManager when all monitored creators have been processed."""
        try:
            self.show_summary_btn.setEnabled(True)
            self.show_summary_btn.setToolTip("Click to view the full sync summary in the log.")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.activity_log_output.append(f"[{timestamp}] --- All monitored creators have been synced. Click 'Show Summary' for details. ---")
            scrollbar = self.activity_log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    def _show_sync_summary(self):
        """Appends a formatted summary table to the activity log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        lines = []
        lines.append(f"[{timestamp}] " + "=" * 55)
        lines.append(f"[{timestamp}]   AUTO-SYNC SESSION SUMMARY")
        lines.append(f"[{timestamp}] " + "=" * 55)

        if not self._sync_stats:
            lines.append(f"[{timestamp}]   No data collected for this session.")
        else:
            total_dl = total_sk = total_fail = 0
            col_w = 28
            lines.append(f"[{timestamp}]   {'Creator':<{col_w}} {'Downloaded':>12} {'Skipped':>9} {'Failed':>8}")
            lines.append(f"[{timestamp}]   {'-' * col_w} {'----------':>12} {'-------':>9} {'------':>8}")
            for creator, stats in self._sync_stats.items():
                dl = stats['downloaded']
                sk = stats['skipped']
                fl = stats['failed']
                total_dl += dl; total_sk += sk; total_fail += fl
                label = (creator[:col_w - 2] + '..') if len(creator) > col_w else creator
                lines.append(f"[{timestamp}]   {label:<{col_w}} {dl:>12} {sk:>9} {fl:>8}")
            lines.append(f"[{timestamp}]   {'-' * col_w} {'----------':>12} {'-------':>9} {'------':>8}")
            lines.append(f"[{timestamp}]   {'TOTAL':<{col_w}} {total_dl:>12} {total_sk:>9} {total_fail:>8}")
        lines.append(f"[{timestamp}] " + "=" * 55)

        for line in lines:
            self.activity_log_output.append(line)
        scrollbar = self.activity_log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.show_summary_btn.setEnabled(False)

    def _toggle_pause(self):
        if hasattr(self.parent_app, 'pause_download'):
            self.parent_app.pause_download()
            
            # Update button text based on parent state
            if getattr(self.parent_app, 'is_paused', False):
                self.pause_sync_btn.setText("Resume Sync")
            else:
                self.pause_sync_btn.setText("Pause Sync")

    def _cancel_sync(self):
        if hasattr(self.parent_app, 'cancel_download'):
            reply = QMessageBox.question(
                self, "Cancel Auto-Sync", 
                "Are you sure you want to stop the current background auto-sync?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.parent_app.cancel_download()
                self._log("🛑 Auto-Sync cancelled by user.")

    def _populate_sync_table(self):
        self.sync_table.blockSignals(True)
        self.sync_table.setRowCount(0)
        appdata_dir = getattr(self.parent_app, 'app_base_dir', '')
        if not appdata_dir:
            return
        
        appdata_dir = os.path.join(appdata_dir, "appdata")
        db_dir = os.path.join(appdata_dir, "databases")
        if not os.path.exists(db_dir):
            return
            
        all_creators = []
        for file in os.listdir(db_dir):
            if file.endswith(".db"):
                platform_name = file.replace(".db", "")
                try:
                    db_manager = PlatformDatabaseManager.get_instance(platform_name, appdata_dir)
                    creators = db_manager.get_all_creators()
                    for c in creators:
                        c['platform'] = platform_name
                        all_creators.append(c)
                except Exception as e:
                    print(f"Error reading DB {file}: {e}")
                    
        all_creators.sort(key=lambda x: (not x.get('is_synced', False), x.get('platform', ''), x.get('original_name', '')))
        
        self.sync_table.setRowCount(len(all_creators))
        for row, c in enumerate(all_creators):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if c.get('is_synced') else Qt.Unchecked)
            chk.setData(Qt.UserRole, (c['platform'], c['creator_id']))
            self.sync_table.setItem(row, 0, chk)
            
            self.sync_table.setItem(row, 1, QTableWidgetItem(c.get('original_name', 'Unknown')))
            self.sync_table.setItem(row, 2, QTableWidgetItem(c.get('platform', '').capitalize()))
            self.sync_table.setItem(row, 3, QTableWidgetItem(c.get('service', '') or 'Unknown'))
            
            # Setup Output Directory column widget
            sync_settings = {}
            if c.get('sync_settings'):
                try:
                    sync_settings = json.loads(c['sync_settings'])
                except json.JSONDecodeError:
                    pass
            current_out_dir = sync_settings.get('output_dir', '')
            
            out_widget = QWidget()
            out_layout = QHBoxLayout(out_widget)
            out_layout.setContentsMargins(2, 2, 2, 2)
            out_layout.setSpacing(5)
            
            line_edit = QLineEdit(current_out_dir)
            
            btn = QPushButton()
            btn.setIcon(QIcon(get_asset_path("assets/Svg/folder.svg")))
            btn.setFixedSize(24, 24)
            btn.setToolTip("Browse for new download location")
            
            out_layout.addWidget(line_edit)
            out_layout.addWidget(btn)
            
            self.sync_table.setCellWidget(row, 4, out_widget)
            
            platform = c.get('platform')
            creator_id = c.get('creator_id')
            service = c.get('service')
            
            btn.clicked.connect(lambda checked=False, p=platform, cid=creator_id, s=service, le=line_edit: self._browse_creator_dir(p, cid, s, le))
            line_edit.editingFinished.connect(lambda p=platform, cid=creator_id, s=service, le=line_edit: self._update_creator_dir(p, cid, s, le.text()))
            
        self.sync_table.blockSignals(False)

    def _on_sync_item_changed(self, item):
        if item.column() == 0:
            platform_id_data = item.data(Qt.UserRole)
            if platform_id_data:
                platform_name, creator_id = platform_id_data
                is_synced = item.checkState() == Qt.Checked
                appdata_dir = os.path.join(getattr(self.parent_app, 'app_base_dir', ''), "appdata")
                db_manager = PlatformDatabaseManager.get_instance(platform_name, appdata_dir)
                db_manager.toggle_sync_status(creator_id, is_synced)

    def _browse_creator_dir(self, platform, creator_id, service, line_edit):
        start_dir = line_edit.text() if os.path.isdir(line_edit.text()) else ""
        new_dir = QFileDialog.getExistingDirectory(self, "Select New Download Location", start_dir)
        if new_dir:
            new_dir = os.path.normpath(new_dir)
            line_edit.setText(new_dir)
            self._update_creator_dir(platform, creator_id, service, new_dir)
            
    def _update_creator_dir(self, platform, creator_id, service, new_path):
        if not new_path:
            return
        appdata_dir = os.path.join(getattr(self.parent_app, 'app_base_dir', ''), "appdata")
        db_manager = PlatformDatabaseManager.get_instance(platform, appdata_dir)
        
        # We need to fetch the existing settings first to only update output_dir
        db_manager.cursor.execute("SELECT sync_settings FROM creator_mappings WHERE creator_id = ?", (str(creator_id),))
        row = db_manager.cursor.fetchone()
        if row:
            settings_json = row[0] or '{}'
            try:
                settings = json.loads(settings_json)
            except json.JSONDecodeError:
                settings = {}
                
            settings['output_dir'] = new_path
            db_manager.update_sync_settings(creator_id, service, json.dumps(settings))
            self._log(f"✅ Updated download location for {creator_id} to: {new_path}")

    def _load_auto_sync_settings(self):
        if hasattr(self.parent_app, 'settings'):
            self.enable_sync_cb.setChecked(self.parent_app.settings.value("auto_sync_enabled", False, type=bool))
            self.minimize_to_tray_cb.setChecked(self.parent_app.settings.value("minimize_to_tray", False, type=bool))
            
            # Advanced settings
            self.idle_threshold_spin.setValue(self.parent_app.settings.value("auto_sync_idle_threshold", 10, type=int))
            self.enable_early_stop_cb.setChecked(self.parent_app.settings.value("auto_sync_enable_early_stop", True, type=bool))
            self.early_stop_threshold_spin.setValue(self.parent_app.settings.value("auto_sync_early_stop_threshold", 0, type=int))
            self.max_pages_spin.setValue(self.parent_app.settings.value("auto_sync_max_pages", 1, type=int))
            self.retry_404_cb.setChecked(self.parent_app.settings.value("auto_sync_retry_404", False, type=bool))
            
            # Load proxy settings
            self.proxy_override_cb.setChecked(self.parent_app.settings.value("auto_sync_proxy_override", True, type=bool))
            self.use_proxy_cb.setChecked(self.parent_app.settings.value("auto_sync_proxy_enabled", False, type=bool))
            self.proxy_type_combo.setCurrentText(self.parent_app.settings.value("auto_sync_proxy_type", "HTTP", type=str))
            self.proxy_host_input.setText(self.parent_app.settings.value("auto_sync_proxy_host", "", type=str))
            self.proxy_port_input.setText(self.parent_app.settings.value("auto_sync_proxy_port", "", type=str))
            self.proxy_user_input.setText(self.parent_app.settings.value("auto_sync_proxy_username", "", type=str))
            self.proxy_pass_input.setText(self.parent_app.settings.value("auto_sync_proxy_password", "", type=str))
            
            # Initial state setup
            checked = self.proxy_override_cb.isChecked()
            self.use_proxy_cb.setEnabled(checked)
            self.proxy_type_combo.setEnabled(checked)
            self.proxy_host_input.setEnabled(checked)
            self.proxy_port_input.setEnabled(checked)
            self.proxy_user_input.setEnabled(checked)
            self.proxy_pass_input.setEnabled(checked)

    def _save_auto_sync_settings(self):
        if hasattr(self.parent_app, 'settings'):
            self.parent_app.settings.setValue("auto_sync_enabled", self.enable_sync_cb.isChecked())
            self.parent_app.settings.setValue("minimize_to_tray", self.minimize_to_tray_cb.isChecked())
            
            # Advanced settings
            self.parent_app.settings.setValue("auto_sync_idle_threshold", self.idle_threshold_spin.value())
            self.parent_app.settings.setValue("auto_sync_enable_early_stop", self.enable_early_stop_cb.isChecked())
            self.parent_app.settings.setValue("auto_sync_early_stop_threshold", self.early_stop_threshold_spin.value())
            self.parent_app.settings.setValue("auto_sync_max_pages", self.max_pages_spin.value())
            self.parent_app.settings.setValue("auto_sync_retry_404", self.retry_404_cb.isChecked())
            
            self.parent_app.settings.setValue("auto_sync_proxy_override", self.proxy_override_cb.isChecked())
            self.parent_app.settings.setValue("auto_sync_proxy_enabled", self.use_proxy_cb.isChecked())
            self.parent_app.settings.setValue("auto_sync_proxy_type", self.proxy_type_combo.currentText())
            self.parent_app.settings.setValue("auto_sync_proxy_host", self.proxy_host_input.text())
            self.parent_app.settings.setValue("auto_sync_proxy_port", self.proxy_port_input.text())
            self.parent_app.settings.setValue("auto_sync_proxy_username", self.proxy_user_input.text())
            self.parent_app.settings.setValue("auto_sync_proxy_password", self.proxy_pass_input.text())
            
            self.parent_app.settings.sync()

    def _log(self, text):
        self.log_area.append(text)

    def _update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_repair_finished(self, healed, deleted, total):
        self.target_folder_btn.setEnabled(True)
        self.deep_scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())
        QMessageBox.information(self, "Repair Complete", f"Database Repair Complete!\n\nTotal records checked: {total}\nHealed entries: {healed}\nDeleted (Missing) entries: {deleted}")

    def _scan_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Scan for Missing Files")
        if folder:
            self._start_repair(folder, False)

    def _deep_scan(self):
        # We prompt the user for the root of the drive
        folder = QFileDialog.getExistingDirectory(self, "Select Drive Root to Deep Scan (e.g. D:\\)")
        if folder:
            reply = QMessageBox.question(self, "Deep Scan Warning", "Deep Scans can take a very long time depending on the size of the drive. Do you wish to proceed?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._start_repair(folder, True)

    def _start_repair(self, scan_path, deep_scan):
        self.target_folder_btn.setEnabled(False)
        self.deep_scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_area.clear()
        self.progress_bar.setValue(0)
        
        appdata_dir = os.path.join(getattr(self.parent_app, 'app_base_dir', ''), "appdata")
        
        self.repair_worker = RepairWorker(appdata_dir, scan_path, deep_scan)
        self.repair_worker.log_signal.connect(self._log)
        self.repair_worker.progress_signal.connect(self._update_progress)
        self.repair_worker.finished_signal.connect(self._on_repair_finished)
        self.repair_worker.start()

    def _stop_repair(self):
        if self.repair_worker:
            self.repair_worker.is_cancelled = True
            self.repair_worker.wait()
            self._log("🛑 Repair cancelled by user.")
            self._on_repair_finished(0, 0, 0)
