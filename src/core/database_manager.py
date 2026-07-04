import os
import sqlite3
import hashlib
import threading

from PyQt5.QtCore import QSettings

class DatabaseManager:
    _shared_lock = threading.Lock()

    def __init__(self):
        import sys 
        try:
            from ..config.constants import CONFIG_ORGANIZATION_NAME, CONFIG_APP_NAME_MAIN, CREATE_DATABASE_KEY
            settings = QSettings(CONFIG_ORGANIZATION_NAME, CONFIG_APP_NAME_MAIN)
            self.enabled = settings.value(CREATE_DATABASE_KEY, True, type=bool)
        except ImportError:
            self.enabled = True
            
        self.lock = DatabaseManager._shared_lock
        if not self.enabled:
            return
            
        if getattr(sys, 'frozen', False):
            app_root = os.path.dirname(sys.executable)
        else:
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            
        self.db_dir = os.path.join(app_root, "appdata")
        os.makedirs(self.db_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.db_dir, 'library.db')
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=20.0)
        with self.lock:
            self._initialize_db()

    def _initialize_db(self):
        cursor = self.conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Images (
                hash TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                phash TEXT
            )
        ''')
        
        try:
            cursor.execute("ALTER TABLE Images ADD COLUMN phash TEXT")
        except sqlite3.OperationalError:
            pass 
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE NOT NULL
            )
        ''')
        
        try:
            cursor.execute("ALTER TABLE Tags ADD COLUMN tag_type TEXT DEFAULT 'general'")
        except sqlite3.OperationalError:
            pass
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ImageTags (
                hash TEXT,
                tag_id INTEGER,
                PRIMARY KEY (hash, tag_id),
                FOREIGN KEY (hash) REFERENCES Images (hash),
                FOREIGN KEY (tag_id) REFERENCES Tags (tag_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS IgnoredPairs (
                hash1 TEXT,
                hash2 TEXT,
                PRIMARY KEY (hash1, hash2)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS TagLess (
                hash TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                phash TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS MangaGalleries (
                gallery_id TEXT PRIMARY KEY,
                site TEXT NOT NULL,
                title TEXT,
                folder_path TEXT,
                artist TEXT
            )
        ''')
        
        try:
            cursor.execute("ALTER TABLE MangaGalleries ADD COLUMN artist TEXT")
        except sqlite3.OperationalError:
            pass
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS MangaTags (
                gallery_id TEXT,
                tag_id INTEGER,
                PRIMARY KEY (gallery_id, tag_id),
                FOREIGN KEY (gallery_id) REFERENCES MangaGalleries (gallery_id),
                FOREIGN KEY (tag_id) REFERENCES Tags (tag_id)
            )
        ''')

        self.conn.commit()

    def generate_md5(self, file_path):
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return None

    def check_exists(self, file_hash):
        if not getattr(self, 'enabled', True):
            return False
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM Images WHERE hash = ?', (file_hash,))
        return cursor.fetchone() is not None

    def record_download(self, file_path, file_name, file_hash=None, tags_list=None, phash=None):
        if not getattr(self, 'enabled', True):
            return True
        if tags_list is None:
            tags_list = []

        if not file_hash:
            file_hash = self.generate_md5(file_path)
            if not file_hash:
                return False

        with self.lock:
            cursor = self.conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO Images (hash, file_path, file_name, phash)
                    VALUES (?, ?, ?, ?)
                ''', (file_hash, file_path, file_name, phash))
            except sqlite3.IntegrityError:
                return False
                
            for tag in tags_list:
                tag_type = 'general'
                clean_tag = tag.strip().lower().replace(' ', '_')
                if not clean_tag:
                    continue
                    
                if ':' in clean_tag:
                    parts = clean_tag.split(':', 1)
                    prefix = parts[0].strip()
                    if prefix in ['character', 'artist', 'series', 'general']:
                        tag_type = prefix
                        clean_tag = parts[1].strip()
                
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO Tags (tag_name, tag_type)
                        VALUES (?, ?)
                    ''', (clean_tag, tag_type))
                except sqlite3.OperationalError:
                    cursor.execute('''
                        INSERT OR IGNORE INTO Tags (tag_name)
                        VALUES (?)
                    ''', (clean_tag,))
                
                cursor.execute('SELECT tag_id FROM Tags WHERE tag_name = ?', (clean_tag,))
                tag_row = cursor.fetchone()
                
                if tag_row:
                    tag_id = tag_row[0]
                    cursor.execute('''
                        INSERT OR IGNORE INTO ImageTags (hash, tag_id)
                        VALUES (?, ?)
                    ''', (file_hash, tag_id))
            
            self.conn.commit()
            return True

    def record_tagless_download(self, file_path, file_name, file_hash=None, phash=None):
        """Records a download from a site without tags into the TagLess table."""
        if not getattr(self, 'enabled', True):
            return True
        if not file_hash:
            file_hash = self.generate_md5(file_path)
            if not file_hash:
                return False

        with self.lock:
            cursor = self.conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO TagLess (hash, file_path, file_name, phash)
                    VALUES (?, ?, ?, ?)
                ''', (file_hash, file_path, file_name, phash))
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def check_manga_exists(self, gallery_id):
        if not getattr(self, 'enabled', True):
            return False
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM MangaGalleries WHERE gallery_id = ?', (gallery_id,))
        return cursor.fetchone() is not None

    def record_manga_download(self, gallery_id, site, title, folder_path, artist=None, tags_list=None):
        if not getattr(self, 'enabled', True):
            return True
        if tags_list is None:
            tags_list = []

        with self.lock:
            cursor = self.conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO MangaGalleries (gallery_id, site, title, folder_path, artist)
                    VALUES (?, ?, ?, ?, ?)
                ''', (gallery_id, site, title, folder_path, artist))
            except sqlite3.IntegrityError:
                return False
                
            for tag in tags_list:
                tag_type = 'general'
                clean_tag = tag.strip().lower().replace(' ', '_')
                if not clean_tag:
                    continue
                    
                if ':' in clean_tag:
                    parts = clean_tag.split(':', 1)
                    prefix = parts[0].strip()
                    if prefix in ['character', 'artist', 'series', 'general']:
                        tag_type = prefix
                        clean_tag = parts[1].strip()
                
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO Tags (tag_name, tag_type)
                        VALUES (?, ?)
                    ''', (clean_tag, tag_type))
                except sqlite3.OperationalError:
                    cursor.execute('''
                        INSERT OR IGNORE INTO Tags (tag_name)
                        VALUES (?)
                    ''', (clean_tag,))
                
                cursor.execute('SELECT tag_id FROM Tags WHERE tag_name = ?', (clean_tag,))
                tag_row = cursor.fetchone()
                
                if tag_row:
                    tag_id = tag_row[0]
                    cursor.execute('''
                        INSERT OR IGNORE INTO MangaTags (gallery_id, tag_id)
                        VALUES (?, ?)
                    ''', (gallery_id, tag_id))
            
            self.conn.commit()
            return True