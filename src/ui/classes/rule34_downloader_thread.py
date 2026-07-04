import os
import json
import sqlite3
import requests
import html
import re
import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs
from PyQt5.QtCore import QThread, pyqtSignal
from ...config.constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

from PIL import Image
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    imagehash = None
    IMAGEHASH_AVAILABLE = False
from ...core.database_manager import DatabaseManager

class Rule34DownloadThread(QThread):
    finished_signal = pyqtSignal(int, int, bool)

    def __init__(self, url, output_dir, api_key="", user_id="", parent=None, export_all_links_mode=False):
        super().__init__(parent)
        self.export_all_links_mode = export_all_links_mode
        self.url = url
        self.output_dir = output_dir
        self.api_key = api_key
        self.user_id = user_id
        self.main_app = parent
        self.session = requests.Session()
        
        self.db_lock = threading.Lock()
        self.max_workers = 4 
        
        self.db = DatabaseManager()
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        self.tag_count_cache = {}

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
            
        self.active_blacklist.extend([
            'rape', 'gore', 
            'literal_spitroast', 'scaphism', 'what_the_fuck', 'itt', 
            'where_is_your_god_now', 'what_has_science_done', 'abortion_mark'
        ])
        
        self.rating_filter = int(settings.value("r34_rating_filter", 0))
        self.min_score = int(settings.value("r34_min_score", 0))
        self.max_downloads = int(settings.value("r34_max_downloads", 0))

        self.dl_images = settings.value("r34_download_images", True, type=bool)
        self.dl_videos = settings.value("r34_download_videos", True, type=bool)

        if not self.api_key or not self.user_id:
            self.api_key = str(settings.value("r34_api_key", "")).strip()
            self.user_id = str(settings.value("r34_user_id", "")).strip()

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
                        rows = cursor.fetchall()
                        
                        for row in rows:
                            self._process_character_tag(row[0], is_favorite=False)
                except Exception as e:
                    self.main_app.log_signal.emit(f"[WARN] Failed to read AllTags.db: {e}")

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
            except Exception as e:
                self.main_app.log_signal.emit(f"[WARN] Failed to read hash database: {e}")

    def _process_character_tag(self, tag, is_favorite):
        if '=' in tag:
            master_part, aliases_part = tag.split('=', 1)
            
            clean_master = html.unescape(master_part.strip()).lower()
            clean_master = re.sub(r'\s+', '_', clean_master)
            clean_master = re.sub(r'_+', '_', clean_master)
            
            for alias in aliases_part.split(','):
                clean_alias = html.unescape(alias.strip()).lower()
                clean_alias = re.sub(r'\s+', '_', clean_alias)
                clean_alias = re.sub(r'_+', '_', clean_alias)
                if clean_alias:
                    self.alias_map[clean_alias] = clean_master
                    
            tag = master_part

        is_penalized = '*' in tag
        if is_penalized:
            tag = tag.replace('*', '')
            
        tag = tag.strip()
        clean_tag = html.unescape(tag).lower()
        clean_tag = re.sub(r'\s+', '_', clean_tag)
        clean_tag = re.sub(r'_+', '_', clean_tag)
        
        self.known_characters_exact.add(clean_tag)
        
        match = re.search(r'^(.*?)_\(([^)]+)\)$', clean_tag)
        if match:
            base_name = match.group(1)
            franchise = match.group(2)
            self.known_franchises.add(franchise.replace('_', ' '))
            
            if base_name not in self.known_characters_base:
                self.known_characters_base[base_name] = set()
            self.known_characters_base[base_name].add(franchise)
        else:
            base_name = clean_tag
        
        fingerprint_parts = [p for p in base_name.split('_') if p]
        name_fingerprint = tuple(sorted(fingerprint_parts))
        self.known_characters_unordered[name_fingerprint] = base_name
        
        if is_penalized:
            self.dynamic_penalized_tags.add(base_name.replace('_', ' '))
            
        if is_favorite:
            self.favorite_characters.add(base_name.replace('_', ' '))

    def is_safe_to_download(self, tags_string):
        if not self.active_blacklist:
            return True, "normal", ""
            
        image_tags = tags_string.lower().split()
        
        for tag in image_tags:
            if tag in self.active_whitelist: 
                return True, "vip", tag

        for tag in image_tags:
            if tag.startswith('not_'): 
                continue 
                
            for bad_word in self.active_blacklist:
                if '*' in bad_word:
                    clean_pattern = bad_word.replace('*', '')
                    if clean_pattern in tag:
                        return False, "wildcard", bad_word
                else:
                    if tag == bad_word:
                        return False, "blacklist", bad_word
                        
        return True, "normal", ""

    def get_tag_count(self, tag_name):
        original_tag = tag_name.lower().strip().replace(' ', '_').replace(':', '')
        
        def fetch_count(search_name):
            if search_name in self.tag_count_cache:
                return self.tag_count_cache[search_name]
            try:
                api_url = "https://api.rule34.xxx/index.php"
                params = {
                    'page': 'dapi',
                    's': 'tag',
                    'q': 'index',
                    'name': search_name
                }
                
                if self.api_key and self.user_id:
                    params['api_key'] = self.api_key
                    params['user_id'] = self.user_id
                    
                time.sleep(0.1)  # Throttle to prevent triggering rate limits
                response = self.session.get(api_url, params=params, timeout=(10, 15))
                
                if response.status_code == 200 and response.text.strip():
                    match = re.search(r'count="(\d+)"', response.text)
                    if match:
                        count = int(match.group(1))
                        if count > 0:
                            self.tag_count_cache[search_name] = count
                            return count
            except Exception as e:
                self.main_app.log_signal.emit(f"[DEBUG] fetch_count failed for {search_name}: {e}")
            return 0

        count = fetch_count(original_tag)
        
        if count == 0 and "_(" in original_tag:
            base_name = original_tag.split('_(')[0]
            count = fetch_count(base_name)
            
            if count > 0:
                self.tag_count_cache[original_tag] = count

        return count

    def _execute_download_task(self, file_url, save_path, file_hash, post_tags_list, search_category, post, log_folder_path, safe_type, trigger_word, original_tags):
        """Runs concurrently in the background without touching the main UI directly."""
        if self.main_app.cancellation_event.is_set(): 
            return False, ""

        if self.download_file(file_url, save_path):
            calculated_phash, hash_warn = self.calculate_phash_safe(save_path)
            
            post_id = post.get('id')
            categorized_tags = []
            if post_id:
                post_view_url = f"https://rule34.xxx/index.php?page=post&s=view&id={post_id}"
                try:
                    from bs4 import BeautifulSoup
                    post_response = self.session.get(post_view_url, timeout=(10, 15))
                    if post_response.status_code == 200:
                        soup = BeautifulSoup(post_response.text, 'html.parser')
                        tag_sidebar = soup.find('ul', id='tag-sidebar')
                        if tag_sidebar:
                            for li in tag_sidebar.find_all('li', class_='tag'):
                                classes = li.get('class', [])
                                tag_type = 'general'
                                for c in classes:
                                    if c.startswith('tag-type-'):
                                        category = c.replace('tag-type-', '')
                                        if category == 'copyright':
                                            tag_type = 'series'
                                        elif category in ['character', 'artist']:
                                            tag_type = category
                                        else:
                                            tag_type = 'general'
                                
                                tag_link = li.find('a', href=lambda h: h and 'tags=' in h)
                                if tag_link:
                                    tag_name = tag_link.text.strip().lower().replace(' ', '_')
                                    tag_name = self.alias_map.get(tag_name, tag_name)
                                    tag_name = tag_name.replace('_(series)', '')
                                    if tag_name:
                                        categorized_tags.append(f"{tag_type}:{tag_name}")
                except Exception:
                    pass

            if not categorized_tags:
                categorized_tags = [f"general:{t}" for t in post_tags_list]

            with self.db_lock:
                if file_hash:
                    if file_hash not in self.hash_db[search_category]:
                        self.hash_db[search_category].append(file_hash)
                    self.all_known_hashes.add(file_hash)
                
                self.db.record_download(
                    file_path=save_path,
                    file_name=os.path.basename(save_path),
                    file_hash=file_hash,
                    tags_list=categorized_tags,
                    phash=calculated_phash
                )

            score_val = post.get('score', '0')
            rating_val = post.get('rating', 'q').upper()
            res = f"{post.get('width', '?')}x{post.get('height', '?')}"
            
            log_lines = [f"\n[+] POST {post.get('id', 'Unknown')}"]
            log_lines.append(f"    Stats   : Score {score_val} | Rating {rating_val} | Res {res}")
            
            if safe_type == "vip":
                if trigger_word not in original_tags.lower():
                    log_lines.append(f"    Bypass  : Whitelist triggered by '{trigger_word}'")
                
            log_lines.append(f"    File    : {os.path.basename(save_path)}")
            log_lines.append(f"    Path    : [{' / '.join(log_folder_path)}]")
            
            if hash_warn:
                log_lines.append(f"    {hash_warn}")
                    
            return True, "\n".join(log_lines)
            
        return False, ""

    def run(self):
        parsed_url = urlparse(self.url)
        query_params = parse_qs(parsed_url.query)
        tags = query_params.get('tags', [''])[0]
        
        if not tags: return

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rating_map = ["All Ratings", "Safe Only", "Questionable & Safe", "Explicit Only"]
        rating_str = rating_map[self.rating_filter] if 0 <= self.rating_filter <= 3 else "Unknown"
        media_str = []
        if self.dl_images: media_str.append("Images")
        if self.dl_videos: media_str.append("Videos")
        
        start_msg = f"""
┌───────────────────────────────────────────────────────────────────────
│ ⚡ TURBO DOWNLOAD SEQUENCE INITIATED ({self.max_workers} Workers)
├───────────────────────────────────────────────────────────────────────
│ Timestamp   : {now}
│ Query Tags  : {tags}
│ Target Dir  : {self.output_dir}
│ Media Types : {' & '.join(media_str)}
│ Filter      : {rating_str} | Min Score: {self.min_score}
│ Constraint  : {'Unlimited' if self.max_downloads == 0 else self.max_downloads}
│ Routing     : Char Sorting ({'ON' if self.smart_sort else 'OFF'}) | Scenes ({'ON' if self.use_scene_sort else 'OFF'})
└───────────────────────────────────────────────────────────────────────"""
        self.main_app.log_signal.emit(start_msg)

        pid = 0
        limit = 1000
        total_count = 0

        while True:
            if self.main_app.cancellation_event.is_set(): break

            api_url = f"https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&tags={tags}&json=1&limit={limit}&pid={pid}"
            if self.user_id and self.api_key: api_url += f"&user_id={self.user_id}&api_key={self.api_key}"
            
            max_retries = 3
            for attempt in range(max_retries):
                if self.main_app.cancellation_event.is_set(): break
                try:
                    response = self.session.get(api_url, timeout=(10, 20))
                    response.raise_for_status()
                    break # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.main_app.log_signal.emit(f"\n[WARN] API connection dropped (Attempt {attempt + 1}/{max_retries}). Retrying in {2 ** attempt}s...")
                        time.sleep(2 ** attempt)
                    else:
                        self.main_app.log_signal.emit(f"\n[ERROR] API communication failure on page {pid + 1} after {max_retries} attempts: {e}")
                        response = None # Mark as failed

            if not response or not response.text.strip(): break

            try:
                posts = response.json()
                if isinstance(posts, str):
                    try: posts = json.loads(posts)
                    except json.JSONDecodeError: break

                if isinstance(posts, dict): posts = posts.get('post', [])
                if not isinstance(posts, list) or len(posts) == 0: break

                self.main_app.log_signal.emit(f"\n[NETWORK] Fetching Page {pid + 1} | Retrieved {len(posts)} indices...")

                download_tasks = []

                for post in posts:
                    if self.main_app.cancellation_event.is_set(): break
                    if not isinstance(post, dict): continue

                    if self.max_downloads > 0 and (total_count + len(download_tasks)) >= self.max_downloads:
                        self.main_app.log_signal.emit(f"\n[CONSTRAINT] Maximum download limit ({self.max_downloads}) reached on queue. Terminating sequence.")
                        break

                    if int(post.get('score', 0)) < self.min_score: continue
                        
                    post_rating = post.get('rating', 'q')
                    if self.rating_filter == 1 and post_rating != 's': continue 
                    elif self.rating_filter == 2 and post_rating == 'e': continue 
                    elif self.rating_filter == 3 and post_rating != 'e': continue 

                    raw_tags_string = post.get('tags', '')
                    raw_tags_list = raw_tags_string.lower().split()
                    
                    translated_tags_list = [self.alias_map.get(t, t) for t in raw_tags_list]
                    
                    post_tags_list = [t.replace('_(series)', '') for t in translated_tags_list]
                    
                    tags_string = " ".join(post_tags_list)
                    post_tags_set = set(post_tags_list) 
                    
                    is_safe, safe_type, trigger_word = self.is_safe_to_download(tags_string)
                    if not is_safe: continue 

                    file_url = post.get('file_url')
                    if not file_url: continue

                    ext = os.path.splitext(urlparse(file_url).path)[1].lower()
                    is_video = ext in VIDEO_EXTENSIONS
                    is_image = ext in IMAGE_EXTENSIONS
                    if is_video and not self.dl_videos: continue
                    if is_image and not self.dl_images: continue
                    if not is_video and not is_image: continue  # skip audio/archive/unknown

                    if getattr(self, 'export_all_links_mode', False):
                        download_tasks.append((file_url, None, None, None, None, None, None, None, None, None))
                        continue

                    file_hash = post.get('hash', '')
                    post_id = post.get('id', 'Unknown')
                    
                    search_category = tags.strip()
                    if search_category not in self.hash_db:
                        self.hash_db[search_category] = []

                    if file_hash and file_hash in self.all_known_hashes:
                        self.main_app.log_signal.emit(f"[SKIP] Post {post_id} | Reason: MD5 Hash present in local JSON database.")
                        continue

                    filename = f"{post_id}{ext}"

                    char_folders = [] 
                    scene_folder_name = ""

                    if self.smart_sort and self.known_characters_exact:
                        found_chars = []
                        ignored_chars = {'monochrome', 'anonymous', 'unknown'}
                        
                        for t in post_tags_list:
                            if t in ignored_chars: continue
                            
                            if t in self.known_characters_exact:
                                found_chars.append(t.replace('_', ' '))
                                continue
                                
                            base_t = re.sub(r'_\([^)]+\)$', '', t)
                            if base_t in ignored_chars: continue
                            
                            if base_t != t: 
                                if base_t in self.known_characters_base or base_t in self.known_characters_exact:
                                    found_chars.append(base_t.replace('_', ' '))
                                    continue 
                                
                            if t in self.known_characters_base:
                                required_franchises = self.known_characters_base[t]
                                if any(franchise in post_tags_set for franchise in required_franchises):
                                    found_chars.append(t.replace('_', ' '))
                                    continue
                                elif t in self.known_characters_exact:
                                    found_chars.append(t.replace('_', ' '))
                                    continue

                            fingerprint_parts = [p for p in base_t.split('_') if p]
                            name_fingerprint = tuple(sorted(fingerprint_parts))
                            
                            if name_fingerprint in self.known_characters_unordered:
                                correct_base_name = self.known_characters_unordered[name_fingerprint]
                                if correct_base_name in self.known_characters_base:
                                    required_franchises = self.known_characters_base[correct_base_name]
                                    
                                    if any(franchise in post_tags_set for franchise in required_franchises):
                                        found_chars.append(correct_base_name.replace('_', ' '))
                                    elif correct_base_name in self.known_characters_exact:
                                        found_chars.append(correct_base_name.replace('_', ' '))
                                else:
                                    found_chars.append(correct_base_name.replace('_', ' '))

                        found_chars = list(dict.fromkeys(found_chars))

                        if len(found_chars) > 1:
                            safe_chars = [c for c in found_chars if c.lower() not in self.known_franchises]
                            if safe_chars:
                                found_chars = safe_chars

                        if found_chars:
                            def get_most_popular_char(char_list):
                                if len(char_list) == 1:
                                    return char_list[0]
                                    
                                best_char = char_list[0]
                                highest_score = -1
                                
                                all_penalized_tags = self.dynamic_penalized_tags
                                
                                if not hasattr(self, 'logged_matchups'):
                                    self.logged_matchups = set()
                                    
                                matchup_key = tuple(sorted(char_list))
                                should_log = False
                                
                                if matchup_key not in self.logged_matchups:
                                    should_log = True
                                    self.logged_matchups.add(matchup_key)
                                    log_lines = ["\n[EVALUATION] Character Prominence Analysis:"]
                                
                                for c in char_list:
                                    count = self.get_tag_count(c)
                                    score = count
                                    
                                    if c.lower() in all_penalized_tags:
                                        score = count // 1000
                                        if should_log:
                                            log_lines.append(f"  :: {c.title():<25} | {count:,} posts (FRANCHISE PENALTY APPLIED)")
                                    else:
                                        if should_log:
                                            log_lines.append(f"  :: {c.title():<25} | {count:,} posts")
                                        
                                    if score > highest_score:
                                        highest_score = score
                                        best_char = c
                                        
                                if should_log:
                                    if len(char_list) > 1:
                                        log_lines.append(f"  >> Primary Routing Assigned : {best_char.title()}")
                                    self.main_app.log_signal.emit("\n".join(log_lines))
                                        
                                return best_char

                            if self.favorites_only:
                                matched_favs = [c for c in found_chars if c in self.favorite_characters]
                                if matched_favs:
                                    char_folders.append(get_most_popular_char(matched_favs).title())
                                else:
                                    char_folders.append("Unknown")
                                    char_folders.append(get_most_popular_char(found_chars).title())
                            else:
                                char_folders.append(get_most_popular_char(found_chars).title())
                        else:
                            if self.favorites_only:
                                char_folders.append("Unknown")

                    if self.use_scene_sort:
                        for priority_scene in self.ordered_scene_tags:
                            p_scene_ul = priority_scene.replace(' ', '_')
                            if p_scene_ul in post_tags_set or priority_scene in tags_string.lower():
                                scene_folder_name = priority_scene.title()
                                break 

                    final_output_dir = self.output_dir
                    log_folder_path = []

                    if not char_folders and scene_folder_name:
                        final_output_dir = os.path.join(final_output_dir, "~Scenes")
                        log_folder_path.append("~Scenes")

                    for folder in char_folders:
                        clean_folder = re.sub(r'[\\/*?:"<>|]', "", folder)
                        final_output_dir = os.path.join(final_output_dir, clean_folder)
                        log_folder_path.append(clean_folder)
                        
                    if scene_folder_name:
                        clean_scene = re.sub(r'[\\/*?:"<>|]', "", scene_folder_name)
                        final_output_dir = os.path.join(final_output_dir, clean_scene)
                        log_folder_path.append(clean_scene)
                        
                    if not log_folder_path:
                        log_folder_path = ["Root"]

                    os.makedirs(final_output_dir, exist_ok=True)
                    save_path = os.path.join(final_output_dir, filename)

                    if not os.path.exists(save_path):
                        download_tasks.append((file_url, save_path, file_hash, post_tags_list, search_category, post, log_folder_path, safe_type, trigger_word, tags))

                if download_tasks:
                    if getattr(self, 'export_all_links_mode', False):
                        self.main_app.log_signal.emit(f"\n[📋 EXPORT] Exporting {len(download_tasks)} links...")
                        export_file_path = os.path.join(self.output_dir, "all_file_links.txt")
                        try:
                            with open(export_file_path, "a", encoding="utf-8") as f:
                                f.write(f"\n# Rule34 Query: {tags}\n")
                                for task in download_tasks:
                                    f.write(task[0] + "\n")
                                    total_count += 1
                            self.main_app.log_signal.emit(f"[✅] Exported {len(download_tasks)} links to {export_file_path}")
                        except Exception as e:
                            self.main_app.log_signal.emit(f"[❌] Failed to export links: {e}")
                        
                        if self.max_downloads > 0 and total_count >= self.max_downloads:
                            break
                        pid += 1
                        continue

                    self.main_app.log_signal.emit(f"\n[⚡ TURBO] Firing up {self.max_workers} concurrent workers for {len(download_tasks)} files...")
                    
                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        futures = {executor.submit(self._execute_download_task, *task): task for task in download_tasks}
                        
                        for future in as_completed(futures):
                            if self.main_app.cancellation_event.is_set():
                                break
                                
                            success, log_text = future.result()
                            if success:
                                total_count += 1
                                
                                if log_text:
                                    self.main_app.log_signal.emit(log_text)
                                
                                if total_count % 50 == 0:
                                    with self.db_lock:
                                        try:
                                            with open(self.hash_db_path, 'w', encoding='utf-8') as f:
                                                json.dump(self.hash_db, f, indent=4)
                                        except Exception: pass

                if self.max_downloads > 0 and total_count >= self.max_downloads:
                    break

                pid += 1

            except Exception as e:
                self.main_app.log_signal.emit(f"\n[ERROR] API communication failure on page {pid + 1}: {e}")
                break

        if not getattr(self, 'export_all_links_mode', False):
            try:
                with open(self.hash_db_path, 'w', encoding='utf-8') as f:
                    json.dump(self.hash_db, f, indent=4)
            except Exception as e:
                self.main_app.log_signal.emit(f"[ERROR] Could not commit hash database to disk: {e}")

        finish_msg = f"""
┌───────────────────────────────────────────────────────────────────────
│ DOWNLOAD SEQUENCE COMPLETED
├───────────────────────────────────────────────────────────────────────
│ Total files acquired : {total_count}
└───────────────────────────────────────────────────────────────────────"""
        self.main_app.log_signal.emit(finish_msg)
        self.finished_signal.emit(total_count, 0, self.main_app.cancellation_event.is_set())

    def calculate_phash_safe(self, file_path):
        """Generates a 256-bit Perceptual Hash. Returns (hash, warning_message)."""
        valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext not in valid_exts: return None, ""
            
        try:
            img = Image.open(file_path)
            img_hash = imagehash.phash(img, hash_size=16) 
            return str(img_hash), ""
        except Exception as e:
            return None, f"[WARN] Failed to calculate pHash for {os.path.basename(file_path)}: {e}"

    def calculate_phash(self, file_path):
        """Legacy fallback just in case other files still call this directly."""
        hash_val, _ = self.calculate_phash_safe(file_path)
        return hash_val

    def download_file(self, url, save_path):
        try:
            with self.session.get(url, stream=True, timeout=(10, 15)) as response:
                response.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.main_app.cancellation_event.is_set():
                            # Close early to safely clean up file
                            f.close()
                            if os.path.exists(save_path): os.remove(save_path)
                            return False
                        if chunk: f.write(chunk)
                return True
        except Exception:
            # If download fails midway, don't leave corrupted partial files
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except OSError: pass
            return False