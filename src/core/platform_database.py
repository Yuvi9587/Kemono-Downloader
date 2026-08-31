import os
import sqlite3
import re
import threading
from urllib.parse import urlparse, parse_qs


class PlatformDatabaseManager:
    """
    Manages SQLite databases per platform (e.g., pawchive.db, kemono.db).
    Each database contains a 'creator_mappings' table to map original names to safe table names,
    and individual tables for each creator to track downloaded files.
    """
    _instances = {}
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, platform_name, appdata_dir):
        """Singleton pattern per platform to avoid DB lock issues."""
        with cls._lock:
            key = f"{platform_name}_{appdata_dir}"
            if key not in cls._instances:
                cls._instances[key] = cls(platform_name, appdata_dir)
            return cls._instances[key]

    def __init__(self, platform_name, appdata_dir):
        self.platform_name = platform_name.lower().strip()
        self.db_dir = os.path.join(appdata_dir, "databases")
        os.makedirs(self.db_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.db_dir, f"{self.platform_name}.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.db_lock = threading.Lock()
        
        # Optimize for massive concurrency (Read/Write simultaneous)
        self.cursor.execute('PRAGMA journal_mode=WAL')
        self.cursor.execute('PRAGMA synchronous=NORMAL')
        self.conn.commit()
        
        self._init_core_tables()

    def _init_core_tables(self):
        """Initialize the mapping table that stores original vs sanitized names."""
        with self.db_lock:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS creator_mappings (
                    original_name TEXT,
                    sanitized_table_name TEXT PRIMARY KEY,
                    creator_id TEXT,
                    service TEXT,
                    is_synced BOOLEAN DEFAULT 0,
                    sync_settings TEXT
                )
            ''')
            
            # Safe migration for existing databases
            self.cursor.execute("PRAGMA table_info(creator_mappings)")
            columns = [col[1] for col in self.cursor.fetchall()]
            
            if 'service' not in columns:
                self.cursor.execute("ALTER TABLE creator_mappings ADD COLUMN service TEXT")
                
            if 'is_synced' not in columns:
                self.cursor.execute("ALTER TABLE creator_mappings ADD COLUMN is_synced BOOLEAN DEFAULT 0")
                
            if 'sync_settings' not in columns:
                self.cursor.execute("ALTER TABLE creator_mappings ADD COLUMN sync_settings TEXT")
                
            self.conn.commit()

    def _sanitize_name(self, name):
        """
        Converts a creator's name into a safe SQLite table name.
        Allows only alphanumeric characters, replacing everything else with underscores.
        """
        if not name:
            return "unknown_creator"
            
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())
        safe_name = re.sub(r'_+', '_', safe_name).strip('_')
        
        if not safe_name:
            safe_name = "creator"
            
        # Ensure it doesn't start with a number (SQLite restriction)
        if safe_name[0].isdigit():
            safe_name = f"c_{safe_name}"
            
        return safe_name

    def ensure_creator_table(self, original_creator_name, creator_id=None, service=None):
        """
        Ensures a table exists for the given creator and updates the mapping table.
        Returns the sanitized table name to use for inserts.
        """
        sanitized_name = self._sanitize_name(original_creator_name)
        
        with self.db_lock:
            if creator_id and service:
                # Fetch ALL mappings for this creator to resolve duplicates
                self.cursor.execute("SELECT sanitized_table_name, is_synced, sync_settings FROM creator_mappings WHERE creator_id = ? AND service = ?", (str(creator_id), service))
                existing_rows = self.cursor.fetchall()
                
                has_new_name_row = any(row[0] == sanitized_name for row in existing_rows)
                
                for row in existing_rows:
                    old_table_name = row[0]
                    is_synced = row[1]
                    sync_settings = row[2]
                    
                    if old_table_name != sanitized_name:
                        # Create the new table if it doesn't exist so we can merge data into it
                        self.cursor.execute(f'''
                            CREATE TABLE IF NOT EXISTS {sanitized_name} (
                                hash TEXT, phash TEXT, post_id TEXT, original_filename TEXT, 
                                saved_filename TEXT, creator_id TEXT, saved_path TEXT
                            )
                        ''')
                        
                        # Merge files from old table to new table (ignore duplicates)
                        try:
                            self.cursor.execute(f'''
                                INSERT INTO {sanitized_name} (hash, phash, post_id, original_filename, saved_filename, creator_id, saved_path)
                                SELECT hash, phash, post_id, original_filename, saved_filename, creator_id, saved_path 
                                FROM {old_table_name} 
                                WHERE hash NOT IN (SELECT hash FROM {sanitized_name})
                            ''')
                        except sqlite3.OperationalError:
                            pass # old table might not have saved_path, or might not exist
                            
                        # Delete the old table
                        try:
                            self.cursor.execute(f"DROP TABLE IF EXISTS {old_table_name}")
                        except sqlite3.OperationalError:
                            pass
                            
                        # Delete the old mapping row
                        self.cursor.execute("DELETE FROM creator_mappings WHERE sanitized_table_name = ?", (old_table_name,))
                        
                        # If the new name row doesn't exist yet, we must insert it
                        if not has_new_name_row:
                            self.cursor.execute('''
                                INSERT INTO creator_mappings (original_name, sanitized_table_name, creator_id, service, is_synced, sync_settings)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (original_creator_name, sanitized_name, str(creator_id), service, is_synced, sync_settings))
                            has_new_name_row = True
                        else:
                            # Update existing new name row with sync settings if it lacked them
                            if sync_settings:
                                self.cursor.execute('''
                                    UPDATE creator_mappings 
                                    SET is_synced = COALESCE(NULLIF(is_synced, 0), ?), 
                                        sync_settings = COALESCE(sync_settings, ?)
                                    WHERE sanitized_table_name = ?
                                ''', (is_synced, sync_settings, sanitized_name))
                                
                if not existing_rows:
                    # Absolutely no rows existed
                    self.cursor.execute('''
                        INSERT OR REPLACE INTO creator_mappings (original_name, sanitized_table_name, creator_id, service, is_synced)
                        VALUES (?, ?, ?, ?, 0)
                    ''', (original_creator_name, sanitized_name, creator_id, service))
            else:
                # Fallback if no creator_id provided (legacy)
                self.cursor.execute('''
                    INSERT OR IGNORE INTO creator_mappings (original_name, sanitized_table_name, creator_id, service, is_synced)
                    VALUES (?, ?, ?, ?, 0)
                ''', (original_creator_name, sanitized_name, creator_id, service))

            # Create creator-specific table if it doesn't exist
            self.cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {sanitized_name} (
                    hash TEXT,
                    phash TEXT,
                    post_id TEXT,
                    original_filename TEXT,
                    saved_filename TEXT,
                    creator_id TEXT,
                    saved_path TEXT
                )
            ''')
            
            # Add saved_path to existing tables if missing (migration)
            try:
                self.cursor.execute(f"ALTER TABLE {sanitized_name} ADD COLUMN saved_path TEXT")
            except sqlite3.OperationalError:
                pass # Column already exists
                
            self.conn.commit()
        return sanitized_name

    def record_download(self, creator_name, file_hash, phash, post_id, original_filename, saved_filename, creator_id=None, service=None, saved_path=None):
        """
        Records a successfully downloaded file into the creator's specific table.
        """
        sanitized_name = self.ensure_creator_table(creator_name, creator_id, service)
        
        with self.db_lock:
            self.cursor.execute(f'''
                INSERT INTO {sanitized_name} 
                (hash, phash, post_id, original_filename, saved_filename, creator_id, saved_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (file_hash, phash, post_id, original_filename, saved_filename, creator_id, saved_path))
            self.conn.commit()

    def toggle_sync_status(self, creator_id, is_synced):
        """Updates the is_synced status for a specific creator."""
        with self.db_lock:
            self.cursor.execute('''
                UPDATE creator_mappings SET is_synced = ? WHERE creator_id = ?
            ''', (1 if is_synced else 0, str(creator_id)))
            self.conn.commit()

    def update_sync_settings(self, creator_id, service, settings_json):
        """Updates the JSON configuration string used for auto-syncing this creator."""
        # Ensure creator exists in mappings first (important for Link Only/Text Only modes)
        with self.db_lock:
            self.cursor.execute("SELECT 1 FROM creator_mappings WHERE creator_id = ?", (str(creator_id),))
            if not self.cursor.fetchone():
                # For booru platforms the creator_id is the full search URL.
                # Extract just the tags portion so the Auto Sync Manager shows
                # something readable (e.g. "demon_dog") instead of the full URL.
                booru_platforms = ('rule34', 'gelbooru', 'danbooru', 'safebooru')
                if self.platform_name in booru_platforms:
                    try:
                        parsed = urlparse(str(creator_id))
                        tags_value = parse_qs(parsed.query).get('tags', [''])[0].strip()
                        display_name = tags_value if tags_value else str(creator_id)
                    except Exception:
                        display_name = str(creator_id)
                else:
                    display_name = str(creator_id)

                sanitized_name = self._sanitize_name(display_name)
                self.cursor.execute('''
                    INSERT INTO creator_mappings (original_name, sanitized_table_name, creator_id, service, is_synced)
                    VALUES (?, ?, ?, ?, 0)
                ''', (display_name, sanitized_name, str(creator_id), service))
                
            self.cursor.execute('''
                UPDATE creator_mappings SET sync_settings = ? WHERE creator_id = ?
            ''', (settings_json, str(creator_id)))
            self.conn.commit()


    def get_all_creators(self):
        """Returns a list of all creators mapping data."""
        with self.db_lock:
            self.cursor.execute("SELECT original_name, sanitized_table_name, creator_id, service, is_synced, sync_settings FROM creator_mappings")
            columns = [column[0] for column in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def is_file_downloaded(self, creator_id, file_hash):
        """Checks if a file with the exact hash has already been downloaded for this creator."""
        if not file_hash or not creator_id:
            return False
            
        with self.db_lock:
            self.cursor.execute("SELECT sanitized_table_name FROM creator_mappings WHERE creator_id = ?", (str(creator_id),))
            row = self.cursor.fetchone()
            if not row:
                return False
                
            table_name = row[0]
            try:
                self.cursor.execute(f"SELECT 1 FROM {table_name} WHERE hash = ?", (file_hash,))
                return bool(self.cursor.fetchone())
            except Exception:
                return False

    def delete_creator(self, creator_id):
        """
        Completely removes a creator from the database:
        - Drops their individual file-records table.
        - Removes their row from creator_mappings.
        Returns True on success, False if the creator was not found.
        """
        with self.db_lock:
            self.cursor.execute(
                "SELECT sanitized_table_name FROM creator_mappings WHERE creator_id = ?",
                (str(creator_id),)
            )
            row = self.cursor.fetchone()
            if not row:
                return False

            table_name = row[0]
            try:
                self.cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass  # Table may already be gone

            self.cursor.execute(
                "DELETE FROM creator_mappings WHERE creator_id = ?",
                (str(creator_id),)
            )
            self.conn.commit()
            return True
