import os
import threading
import time
import datetime
import json
import sqlite3
import re
import html
from urllib.parse import urlparse
import cloudscraper
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    imagehash = None
    IMAGEHASH_AVAILABLE = False
from PyQt5.QtCore import QThread, pyqtSignal

from PIL import Image

from ...core.booru_client import fetch_booru_data, BooruClientException
from ...utils.file_utils import clean_folder_name
from ...core.database_manager import DatabaseManager
from ...utils.proxy_utils import get_proxies_from_settings

_ff_ver = (datetime.date.today().toordinal() - 735506) // 28
USERAGENT_FIREFOX = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; "
                     f"rv:{_ff_ver}.0) Gecko/20100101 Firefox/{_ff_ver}.0")

class BooruDownloadThread(QThread):
    """A dedicated QThread for handling Gelbooru/Danbooru with Rule34 DB & Filters."""
    progress_signal = pyqtSignal(str)
    overall_progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(int, int, bool)

    def __init__(self, url, output_dir, api_key, user_id, parent=None):
        super().__init__(parent)
        self.booru_url = url
        self.output_dir = output_dir
        self.api_key = api_key
        self.user_id = user_id
        self.main_app = parent
        self.is_cancelled = False
        self.pause_event = parent.pause_event if hasattr(parent, 'pause_event') else threading.Event()
        
        self.db = DatabaseManager()
        self.tag_count_cache = {}
        self.proxies = get_proxies_from_settings(parent.settings) if hasattr(parent, 'settings') else None
        
        settings = self.main_app.settings
        
        custom_bl = str(settings.value("r34_custom_blacklist", ""))
        self.active_blacklist = [word.strip().lower() for word in custom_bl.split(',') if word.strip()]
        
        whitelist_str = str(settings.value("r34_whitelist", ""))
        self.active_whitelist = [word.strip().lower() for word in whitelist_str.split(',') if word.strip()]
        
        if settings.value("r34_exclude_gore", False, type=bool):
            self.active_blacklist.extend(['ryona', 'guro', 'amputat', 'decapitat', 'disembowel', 'mutilat', 'impal', 'torture', 'prolapse', 'viscera', 'autopsy', 'vivisection'])
        if settings.value("r34_exclude_scat", False, type=bool):
            self.active_blacklist.extend(['scat', 'feces', 'urine', 'watersports', 'vomit', 'puke', 'copro', 'defecat', 'smegma', 'gaper', "fart"])
        if settings.value("r34_exclude_furry", False, type=bool):
            self.active_blacklist.extend(['bestiality', 'zoophil', 'feral', 'animal_genitalia', 'animal_penis', 'animal_sex', 'furry', 'anthro'])
        if settings.value("r34_exclude_loli", False, type=bool):
            self.active_blacklist.extend(['loli', 'shota', 'underage', 'toddler', 'infant', 'pedoph', 'cub'])
        if settings.value("r34_exclude_vore", False, type=bool):
            self.active_blacklist.extend(['vore', 'cannibalism', 'unbirth', 'absorption', 'digestion'])
        if settings.value("r34_exclude_insects", False, type=bool):
            self.active_blacklist.extend(['insects', 'bugs', 'arachnid', 'spider', 'parasite', 'worms', 'maggots', 'infestation'])
        if settings.value("r34_exclude_necro", False, type=bool):
            self.active_blacklist.extend(['necrophilia', 'dead', 'corpse', 'zombie', 'rotting', 'decay'])
            
        if settings.value("r34_exclude_custom", False, type=bool):
            custom_safety_tags = str(settings.value("r34_custom_safety_tags", ""))
            self.active_blacklist.extend([t.strip().lower() for t in custom_safety_tags.split(',') if t.strip()])
            
        self.rating_filter = int(settings.value("r34_rating_filter", 0))
        self.min_score = int(settings.value("r34_min_score", 0))
        self.max_downloads = int(settings.value("r34_max_downloads", 0))

        self.dl_images = settings.value("r34_download_images", True, type=bool)
        self.dl_videos = settings.value("r34_download_videos", True, type=bool)

        self.favorites_only = settings.value("r34_favorites_only", False, type=bool)
        self.use_scene_sort = settings.value("r34_use_scene_sort", False, type=bool)
        
        scene_tags_str = settings.value("r34_scene_tags", "1girl,bikini,beach")
        self.ordered_scene_tags = [t.strip().lower() for t in scene_tags_str.split(',') if t.strip()]

        alias_str = settings.value("r34_tag_aliases", "1girl = solo, single, women")
        self.alias_map = {}
        for line in alias_str.split('||'):
            if '=' in line:
                master, aliases = line.split('=', 1)
                master = master.strip().lower()
                for a in aliases.split(','):
                    self.alias_map[a.strip().lower()] = master

        self.smart_sort = settings.value("r34_smart_sort", False, type=bool)
        self.known_characters_exact = set()
        self.known_characters_base = {} 
        self.known_characters_unordered = {} 
        self.favorite_characters = set() 
        self.known_franchises = set()
        self.dynamic_penalized_tags = set()

        if self.smart_sort:
            char_db_path = os.path.join(self.main_app.user_data_path, "Database", "AllTags.db")
            if os.path.exists(char_db_path):
                try:
                    with sqlite3.connect(char_db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM CharacterTags")
                        for row in cursor.fetchall():
                            self._process_character_tag(row[0], is_favorite=False)
                except Exception as e:
                    pass

        self.hash_db_path = os.path.join(self.main_app.user_data_path, "downloaded_hashes.json")
        self.hash_db = {}
        self.all_known_hashes = set()
        
        if os.path.exists(self.hash_db_path):
            try:
                with open(self.hash_db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.hash_db = {"Legacy_Migrations": data}
                        self.all_known_hashes = set(data)
                    elif isinstance(data, dict):
                        self.hash_db = data
                        for hash_list in data.values():
                            self.all_known_hashes.update(hash_list)
            except Exception: pass

    def _process_character_tag(self, tag, is_favorite):
        if '=' in tag:
            master_part, aliases_part = tag.split('=', 1)
            clean_master = re.sub(r'_+', '_', re.sub(r'\s+', '_', html.unescape(master_part.strip()).lower()))
            for alias in aliases_part.split(','):
                clean_alias = re.sub(r'_+', '_', re.sub(r'\s+', '_', html.unescape(alias.strip()).lower()))
                if clean_alias: self.alias_map[clean_alias] = clean_master
            tag = master_part

        is_penalized = '*' in tag
        if is_penalized: tag = tag.replace('*', '')
            
        clean_tag = re.sub(r'_+', '_', re.sub(r'\s+', '_', html.unescape(tag.strip()).lower()))
        self.known_characters_exact.add(clean_tag)
        
        match = re.search(r'^(.*?)_\(([^)]+)\)$', clean_tag)
        if match:
            base_name, franchise = match.group(1), match.group(2)
            self.known_franchises.add(franchise.replace('_', ' '))
            if base_name not in self.known_characters_base:
                self.known_characters_base[base_name] = set()
            self.known_characters_base[base_name].add(franchise)
        else:
            base_name = clean_tag
        
        fingerprint_parts = [p for p in base_name.split('_') if p]
        self.known_characters_unordered[tuple(sorted(fingerprint_parts))] = base_name
        
        if is_penalized: self.dynamic_penalized_tags.add(base_name.replace('_', ' '))
        if is_favorite: self.favorite_characters.add(base_name.replace('_', ' '))

    def is_safe_to_download(self, tags_string):
        if not self.active_blacklist: return True, "normal", ""
        image_tags = tags_string.lower().split()
        for tag in image_tags:
            if tag in self.active_whitelist: return True, "vip", tag
        for tag in image_tags:
            if tag.startswith('not_'): continue 
            for bad_word in self.active_blacklist:
                if '*' in bad_word:
                    if bad_word.replace('*', '') in tag: return False, "wildcard", bad_word
                else:
                    if tag == bad_word: return False, "blacklist", bad_word
        return True, "normal", ""

    def get_tag_count(self, tag_name):
        original_tag = tag_name.lower().strip().replace(' ', '_').replace(':', '')
        if original_tag in self.tag_count_cache: return self.tag_count_cache[original_tag]
        try:
            r = requests.get(f"https://api.rule34.xxx/index.php?page=dapi&s=tag&q=index&name={original_tag}", timeout=5)
            if r.status_code == 200:
                match = re.search(r'count="(\d+)"', r.text)
                if match:
                    cnt = int(match.group(1))
                    self.tag_count_cache[original_tag] = cnt
                    return cnt
        except Exception: pass
        return 0

    def calculate_phash_safe(self, file_path):
        valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        if os.path.splitext(file_path)[1].lower() not in valid_exts: return None, ""
        try:
            return str(imagehash.phash(Image.open(file_path), hash_size=16)), ""
        except Exception as e:
            return None, f"pHash error: {e}"

    def run(self):
        download_count = 0
        skip_count = 0
        processed_count = 0
        cumulative_total = 0
        
        def logger(msg): self.progress_signal.emit(str(msg))

        try:
            self.progress_signal.emit("=" * 40)
            self.progress_signal.emit(f"🚀 Starting Booru Download w/ Rule34 DB Integration: {self.booru_url}")
            
            item_generator = fetch_booru_data(self.booru_url, self.api_key, self.user_id, logger, proxies=self.proxies)
            scraper = cloudscraper.create_scraper()
            if self.proxies:
                scraper.proxies.update(self.proxies)
            download_headers = { "User-Agent": USERAGENT_FIREFOX, "Referer": "https://gelbooru.com/" }

            for item in item_generator:
                if self.is_cancelled: break
                
                if self.max_downloads > 0 and download_count >= self.max_downloads:
                    self.progress_signal.emit(f"🛑 Maximum download limit ({self.max_downloads}) reached. Stopping.")
                    break

                if isinstance(item, tuple) and item[0] == 'PAGE_UPDATE':
                    newly_found = item[1]
                    cumulative_total += newly_found
                    self.overall_progress_signal.emit(cumulative_total, processed_count)
                    continue

                post_data = item
                processed_count += 1

                if int(post_data.get('score', 0)) < self.min_score:
                    skip_count += 1
                    continue
                
                post_rating = str(post_data.get('rating', 'q')).lower()
                rating_char = post_rating[0] if post_rating else 'q'
                if self.rating_filter == 1 and rating_char != 's': continue 
                elif self.rating_filter == 2 and rating_char == 'e': continue 
                elif self.rating_filter == 3 and rating_char != 'e': continue 

                raw_tags_list = post_data.get('tags', '').lower().split()
                translated_tags_list = [self.alias_map.get(t, t) for t in raw_tags_list]
                post_tags_list = [t.replace('_(series)', '') for t in translated_tags_list]
                tags_string = " ".join(post_tags_list)
                
                is_safe, _, _ = self.is_safe_to_download(tags_string)
                if not is_safe:
                    skip_count += 1
                    continue 
                
                file_url = post_data.get('file_url')
                if not file_url: continue

                ext = post_data.get('extension', 'jpg').lower()
                if not ext.startswith('.'): ext = '.' + ext
                is_video = ext in ['.mp4', '.webm', '.mov', '.mkv']
                if is_video and not self.dl_videos: continue 
                if not is_video and not self.dl_images: continue 

                file_hash = post_data.get('md5', post_data.get('hash', ''))
                post_id = post_data.get('id', 'Unknown')
                search_category = post_data.get('search_tags', 'booru_download')
                
                if search_category not in self.hash_db: self.hash_db[search_category] = []
                if file_hash and file_hash in self.all_known_hashes:
                    self.progress_signal.emit(f"   -> Skip Post {post_id}: MD5 Hash already in local DB.")
                    skip_count += 1
                    continue

                char_folders = [] 
                scene_folder_name = ""

                if self.smart_sort and self.known_characters_exact:
                    found_chars = []
                    ignored_chars = {'monochrome', 'anonymous', 'unknown'}
                    post_tags_set = set(post_tags_list)
                    
                    for t in post_tags_list:
                        if t in ignored_chars: continue
                        if t in self.known_characters_exact:
                            found_chars.append(t.replace('_', ' '))
                            continue
                            
                        base_t = re.sub(r'_\([^)]+\)$', '', t)
                        if base_t in ignored_chars: continue
                        if base_t != t and (base_t in self.known_characters_base or base_t in self.known_characters_exact):
                            found_chars.append(base_t.replace('_', ' '))
                            continue 
                            
                        if t in self.known_characters_base:
                            if any(franchise in post_tags_set for franchise in self.known_characters_base[t]):
                                found_chars.append(t.replace('_', ' '))
                                continue

                        name_fingerprint = tuple(sorted([p for p in base_t.split('_') if p]))
                        if name_fingerprint in self.known_characters_unordered:
                            correct_base_name = self.known_characters_unordered[name_fingerprint]
                            found_chars.append(correct_base_name.replace('_', ' '))

                    found_chars = list(dict.fromkeys(found_chars))
                    if len(found_chars) > 1:
                        safe_chars = [c for c in found_chars if c.lower() not in self.known_franchises]
                        if safe_chars: found_chars = safe_chars

                    if found_chars:
                        def get_most_popular_char(char_list):
                            if len(char_list) == 1: return char_list[0]
                            best_char, highest_score = char_list[0], -1
                            for c in char_list:
                                score = self.get_tag_count(c)
                                if c.lower() in self.dynamic_penalized_tags: score = score // 1000
                                if score > highest_score:
                                    highest_score, best_char = score, c
                            return best_char

                        if self.favorites_only:
                            matched_favs = [c for c in found_chars if c in self.favorite_characters]
                            char_folders.append(get_most_popular_char(matched_favs).title() if matched_favs else "Unknown")
                        else:
                            char_folders.append(get_most_popular_char(found_chars).title())
                    else:
                        if self.favorites_only: char_folders.append("Unknown")

                if self.use_scene_sort:
                    for p_scene in self.ordered_scene_tags:
                        if p_scene.replace(' ', '_') in post_tags_set or p_scene in tags_string:
                            scene_folder_name = p_scene.title()
                            break 

                final_output_dir = self.output_dir
                if not char_folders and scene_folder_name: final_output_dir = os.path.join(final_output_dir, "~Scenes")
                for folder in char_folders: final_output_dir = os.path.join(final_output_dir, clean_folder_name(folder))
                if scene_folder_name: final_output_dir = os.path.join(final_output_dir, clean_folder_name(scene_folder_name))
                
                os.makedirs(final_output_dir, exist_ok=True)
                final_filename = f"{post_data.get('category', 'booru')}_{post_id}_{file_hash or post_data.get('filename', 'img')}{ext}"
                filepath = os.path.join(final_output_dir, final_filename)

                if os.path.exists(filepath):
                    skip_count += 1
                    continue

                if self.pause_event.is_set():
                    while self.pause_event.is_set() and not self.is_cancelled: time.sleep(0.5)

                try:
                    self.progress_signal.emit(f"   Downloading: '{final_filename}'...")
                    response = scraper.get(file_url, headers=download_headers, stream=True, timeout=60)
                    
                    if response.status_code == 200:
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if self.is_cancelled: break
                                if self.pause_event.is_set():
                                    while self.pause_event.is_set() and not self.is_cancelled: time.sleep(0.5)
                                f.write(chunk)
                        
                        if not self.is_cancelled:
                            download_count += 1
                            calc_phash, _ = self.calculate_phash_safe(filepath)
                            
                            if file_hash:
                                if file_hash not in self.hash_db[search_category]: self.hash_db[search_category].append(file_hash)
                                self.all_known_hashes.add(file_hash)
                            
                            self.db.record_download(
                                file_path=filepath,
                                file_name=final_filename,
                                file_hash=file_hash,
                                tags_list=post_tags_list,
                                phash=calc_phash
                            )
                            
                            if download_count % 20 == 0:
                                try:
                                    with open(self.hash_db_path, 'w', encoding='utf-8') as f:
                                        json.dump(self.hash_db, f, indent=4)
                                except Exception: pass
                        else:
                            if os.path.exists(filepath): os.remove(filepath)
                            skip_count += 1
                    else:
                        skip_count += 1
                except Exception as e:
                    skip_count += 1
                
                self.overall_progress_signal.emit(cumulative_total, processed_count)
                time.sleep(0.2)

        except BooruClientException as e:
            self.progress_signal.emit(f"❌ A Booru client error occurred: {e}")
        except Exception as e:
            self.progress_signal.emit(f"❌ An unexpected error occurred in Booru thread: {e}")
        finally:
            try:
                with open(self.hash_db_path, 'w', encoding='utf-8') as f:
                    json.dump(self.hash_db, f, indent=4)
            except Exception: pass
            
            self.finished_signal.emit(download_count, skip_count, self.is_cancelled)

    def cancel(self):
        self.is_cancelled = True
        self.progress_signal.emit("   Cancellation signal received by Booru thread.")