import os
import re
import traceback
import json
import base64
import time
import zipfile
import struct
import sys
import io
import hashlib  
from contextlib import redirect_stdout
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
import cloudscraper
from requests.adapters import HTTPAdapter      
from urllib3.util.retry import Retry           
from ..utils.file_utils import clean_folder_name

try:
    from Crypto.Cipher import AES
    PYCRYPTODOME_AVAILABLE = True
except ImportError:
    PYCRYPTODOME_AVAILABLE = False

try:
    import gdown
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

MEGA_API_URL = "https://g.api.mega.co.nz"
MIN_SIZE_FOR_MULTIPART_MEGA = 20 * 1024 * 1024
NUM_PARTS_FOR_MEGA = 5

def _get_filename_from_headers(headers):
    cd = headers.get('content-disposition')
    if not cd:
        return None
    fname_match = re.findall('filename="?([^"]+)"?', cd)
    if fname_match:
        sanitized_name = re.sub(r'[<>:"/\\|?*]', '_', fname_match[0].strip())
        return sanitized_name
    return None

def urlb64_to_b64(s):
    s += '=' * (-len(s) % 4)
    return s.replace('-', '+').replace('_', '/')

def b64_to_bytes(s):
    return base64.b64decode(urlb64_to_b64(s))

def bytes_to_b64(b):
    return base64.b64encode(b).decode('utf-8')

def _decrypt_mega_attribute(encrypted_attr_b64, key_bytes):
    if not PYCRYPTODOME_AVAILABLE: return {}
    try:
        attr_bytes = b64_to_bytes(encrypted_attr_b64)
        padded_len = (len(attr_bytes) + 15) & ~15
        padded_attr_bytes = attr_bytes.ljust(padded_len, b'\0')
        iv = b'\0' * 16
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        decrypted_attr = cipher.decrypt(padded_attr_bytes)
        json_str = decrypted_attr.strip(b'\0').decode('utf-8')
        if json_str.startswith('MEGA'):
            return json.loads(json_str[4:])
        return json.loads(json_str)
    except Exception:
        return {}

def _decrypt_mega_key(encrypted_key_b64, master_key_bytes):
    if not PYCRYPTODOME_AVAILABLE: raise Exception("pycryptodome missing")
    key_bytes = b64_to_bytes(encrypted_key_b64)
    iv = b'\0' * 16
    cipher = AES.new(master_key_bytes, AES.MODE_ECB)
    return cipher.decrypt(key_bytes)

def _parse_mega_key(key_b64):
    key_bytes = b64_to_bytes(key_b64)
    key_parts = struct.unpack('>' + 'I' * (len(key_bytes) // 4), key_bytes)
    if len(key_parts) == 8:
        final_key = (key_parts[0] ^ key_parts[4], key_parts[1] ^ key_parts[5], key_parts[2] ^ key_parts[6], key_parts[3] ^ key_parts[7])
        iv = (key_parts[4], key_parts[5], 0, 0)
        key_bytes = struct.pack('>' + 'I' * 4, *final_key)
        iv_bytes = struct.pack('>' + 'I' * 4, *iv)
        return key_bytes, iv_bytes, None
    elif len(key_parts) == 4: 
        return key_bytes, None, None
    raise ValueError("Invalid Mega key length")

def _process_file_key(file_key_bytes):
    key_parts = struct.unpack('>' + 'I' * 8, file_key_bytes)
    final_key_parts = (key_parts[0] ^ key_parts[4], key_parts[1] ^ key_parts[5], key_parts[2] ^ key_parts[6], key_parts[3] ^ key_parts[7])
    return struct.pack('>' + 'I' * 4, *final_key_parts)

def _download_and_decrypt_chunk(args):
    url, temp_path, start_byte, end_byte, key, nonce, part_num, progress_data, progress_callback_func, file_name, cancellation_event, pause_event = args
    try:
        headers = {'Range': f'bytes={start_byte}-{end_byte}'}
        initial_counter = start_byte // 16
        cipher = AES.new(key, AES.MODE_CTR, nonce=nonce, initial_value=initial_counter)
        
        with requests.get(url, headers=headers, stream=True, timeout=(15, 300)) as r:
            r.raise_for_status()
            with open(temp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if cancellation_event and cancellation_event.is_set():
                        return False 
                    while pause_event and pause_event.is_set():
                        time.sleep(0.5)
                        if cancellation_event and cancellation_event.is_set():
                            return False 

                    decrypted_chunk = cipher.decrypt(chunk)
                    f.write(decrypted_chunk)
                    with progress_data['lock']:
                        progress_data['downloaded'] += len(chunk)
                        if progress_callback_func and (time.time() - progress_data['last_update'] > 1):
                            progress_callback_func(file_name, (progress_data['downloaded'], progress_data['total_size']))
                            progress_data['last_update'] = time.time()
        return True
    except Exception as e:
        return False

def download_and_decrypt_mega_file(info, download_path, logger_func,
                                   progress_callback_func=None,
                                   cancellation_event=None,
                                   pause_event=None):
    """
    Robust resumable Mega file downloader (single stream, auto-retry).
    """

    file_name = info['file_name']
    file_size = info['file_size']
    dl_url = info['dl_url']
    final_path = os.path.join(download_path, file_name)
    tmp_path = final_path + ".part"

    os.makedirs(download_path, exist_ok=True)

    if os.path.exists(final_path) and os.path.getsize(final_path) == file_size:
        logger_func(f"   [Mega] ℹ️ File '{file_name}' already exists. Skipping.")
        return

    key, iv, _ = _parse_mega_key(urlb64_to_b64(info['file_key']))
    nonce = iv[:8]

    max_retries = 5

    logger_func(f"   [Mega] Downloading '{file_name}' (Resumable)...")

    for attempt in range(max_retries):

        if cancellation_event and cancellation_event.is_set():
            logger_func(f"   [Mega] ❌ Download cancelled for '{file_name}'.")
            return

        try:
            downloaded_bytes = 0

            if os.path.exists(tmp_path):
                downloaded_bytes = os.path.getsize(tmp_path)

            headers = {}
            if downloaded_bytes > 0:
                headers["Range"] = f"bytes={downloaded_bytes}-"
                logger_func(f"   [Mega] Resuming at {downloaded_bytes} bytes...")

            cipher = AES.new(
                key,
                AES.MODE_CTR,
                nonce=nonce,
                initial_value=downloaded_bytes // 16
            )

            with requests.get(dl_url, headers=headers, stream=True, timeout=(60, 900)) as r:
                r.raise_for_status()

                mode = "ab" if downloaded_bytes > 0 else "wb"

                with open(tmp_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=8192):

                        if cancellation_event and cancellation_event.is_set():
                            logger_func(f"   [Mega] ❌ Download cancelled for '{file_name}'.")
                            return

                        while pause_event and pause_event.is_set():
                            time.sleep(0.5)

                        if not chunk:
                            continue

                        decrypted_chunk = cipher.decrypt(chunk)
                        f.write(decrypted_chunk)
                        downloaded_bytes += len(chunk)

                        if progress_callback_func:
                            progress_callback_func(file_name, (downloaded_bytes, file_size))

            break

        except Exception as e:
            if attempt == max_retries - 1:
                logger_func(f"   [Mega] ❌ Download failed for '{file_name}': {e}")
                return

            logger_func(f"   [Mega] ⚠️ Retry {attempt+1}/{max_retries} after error: {e}")
            time.sleep(3)

    if os.path.exists(tmp_path) and os.path.getsize(tmp_path) == file_size:
        os.replace(tmp_path, final_path)
        logger_func(f"   [Mega] ✅ Successfully downloaded '{file_name}'")
    else:
        logger_func(f"   [Mega] ❌ Incomplete download for '{file_name}'.")


def _process_mega_folder(folder_id, folder_key, session, logger_func):
    try:
        master_key_bytes, _, _ = _parse_mega_key(folder_key)
        payload = [{"a": "f", "c": 1, "r": 1}]
        params = {'n': folder_id}
        response = session.post(f"{MEGA_API_URL}/cs", params=params, json=payload, timeout=30)
        response.raise_for_status()
        res_json = response.json()

        if isinstance(res_json, int) or (isinstance(res_json, list) and res_json and isinstance(res_json[0], int)):
            error_code = res_json if isinstance(res_json, int) else res_json[0]
            logger_func(f"   [Mega Folder] ❌ API returned error code: {error_code}. The folder may be invalid or removed.")
            return None, None
        if not isinstance(res_json, list) or not res_json or not isinstance(res_json[0], dict) or 'f' not in res_json[0]:
            logger_func(f"   [Mega Folder] ❌ Invalid folder data received: {str(res_json)[:200]}")
            return None, None

        nodes = res_json[0]['f']
        decrypted_nodes = {}
        for node in nodes:
            try:
                encrypted_key_b64 = node['k'].split(':')[-1]
                decrypted_key_raw = _decrypt_mega_key(encrypted_key_b64, master_key_bytes)
                
                attr_key = _process_file_key(decrypted_key_raw) if node.get('t') == 0 else decrypted_key_raw
                attributes = _decrypt_mega_attribute(node['a'], attr_key)
                name = re.sub(r'[<>:"/\\|?*]', '_', attributes.get('n', f"unknown_{node['h']}"))
                
                decrypted_nodes[node['h']] = {"name": name, "parent": node.get('p'), "type": node.get('t'), "size": node.get('s'), "raw_key_b64": urlb64_to_b64(bytes_to_b64(decrypted_key_raw))}
            except Exception as e:
                logger_func(f"   [Mega Folder] ⚠️ Could not process node {node.get('h')}: {e}")

        root_name = decrypted_nodes.get(folder_id, {}).get("name", "Mega_Folder")
        files_to_download = []
        for handle, node_info in decrypted_nodes.items():
            if node_info.get("type") == 0:
                path_parts = [node_info['name']]
                current_parent_id = node_info.get('parent')
                while current_parent_id in decrypted_nodes:
                    parent_node = decrypted_nodes[current_parent_id]
                    path_parts.insert(0, parent_node['name'])
                    current_parent_id = parent_node.get('parent')
                    if current_parent_id == folder_id:
                        break
                files_to_download.append({'h': handle, 's': node_info['size'], 'key': node_info['raw_key_b64'], 'relative_path': os.path.join(*path_parts)})

        return root_name, files_to_download
    except Exception as e:
        logger_func(f"   [Mega Folder] ❌ Failed to get folder info: {e}")
        return None, None

def download_mega_file(mega_url, download_path, logger_func=print, progress_callback_func=None, overall_progress_callback=None, cancellation_event=None, pause_event=None):
    if not PYCRYPTODOME_AVAILABLE:
        logger_func("❌ Mega download failed: 'pycryptodome' library is not installed.")
        if overall_progress_callback: overall_progress_callback(1, 1)
        return

    logger_func(f"   [Mega] Initializing download for: {mega_url}")
    folder_match = re.search(r'mega(?:\.co)?\.nz/folder/([a-zA-Z0-9]+)#([a-zA-Z0-9_.-]+)', mega_url)
    file_match = re.search(r'mega(?:\.co)?\.nz/(?:file/|#!)?([a-zA-Z0-9]+)(?:#|!)([a-zA-Z0-9_.-]+)', mega_url)
    session = requests.Session()
    session.headers.update({'User-Agent': 'Kemono-Downloader-PyQt/1.0'})

    if folder_match:
        folder_id, folder_key = folder_match.groups()
        logger_func(f"   [Mega] Folder link detected. Starting crawl...")
        root_folder_name, files = _process_mega_folder(folder_id, folder_key, session, logger_func)
        
        if root_folder_name is None or files is None:
            logger_func("   [Mega Folder] ❌ Crawling failed. Aborting.")
            if overall_progress_callback: overall_progress_callback(1, 1)
            return
            
        if not files:
            logger_func("   [Mega Folder] ℹ️ Folder is empty. Nothing to download.")
            if overall_progress_callback: overall_progress_callback(0, 0)
            return

        logger_func("   [Mega Folder] Prioritizing largest files first...")
        files.sort(key=lambda f: f.get('s', 0), reverse=True)

        total_files = len(files)
        logger_func(f"   [Mega Folder] ✅ Crawl complete. Found {total_files} file(s) in folder '{root_folder_name}'.")
        
        if overall_progress_callback: overall_progress_callback(total_files, 0)

        folder_download_path = os.path.join(download_path, root_folder_name)
        os.makedirs(folder_download_path, exist_ok=True)
        
        progress_lock = Lock()
        processed_count = 0
        MAX_WORKERS = 3

        logger_func(f"   [Mega Folder] Starting concurrent download with up to {MAX_WORKERS} workers...")

        def _download_worker(file_data):
            nonlocal processed_count
            try:
                if cancellation_event and cancellation_event.is_set():
                    return

                params = {'n': folder_id}
                payload = [{"a": "g", "g": 1, "n": file_data['h']}]
                response = session.post(f"{MEGA_API_URL}/cs", params=params, json=payload, timeout=20)
                response.raise_for_status()
                res_json = response.json()
                
                if isinstance(res_json, int) or (isinstance(res_json, list) and res_json and isinstance(res_json[0], int)):
                    error_code = res_json if isinstance(res_json, int) else res_json[0]
                    logger_func(f"   [Mega Worker] ❌ API Error {error_code} for '{file_data['relative_path']}'. Skipping.")
                    return

                dl_temp_url = res_json[0]['g']
                file_info = {'file_name': os.path.basename(file_data['relative_path']), 'file_size': file_data['s'], 'dl_url': dl_temp_url, 'file_key': file_data['key']}
                file_specific_path = os.path.dirname(file_data['relative_path'])
                final_download_dir = os.path.join(folder_download_path, file_specific_path)
                
                download_and_decrypt_mega_file(file_info, final_download_dir, logger_func, progress_callback_func, cancellation_event, pause_event)

            except Exception as e:
                if not (cancellation_event and cancellation_event.is_set()):
                    logger_func(f"   [Mega Worker] ❌ Failed to process '{file_data['relative_path']}': {e}")
            finally:
                with progress_lock:
                    processed_count += 1
                    if overall_progress_callback:
                        overall_progress_callback(total_files, processed_count)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(_download_worker, file_data) for file_data in files]
            for future in as_completed(futures):
                if cancellation_event and cancellation_event.is_set():
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                try:
                    future.result()
                except Exception as e:
                    if not (cancellation_event and cancellation_event.is_set()):
                         logger_func(f"   [Mega Folder] A download worker failed with an error: {e}")
        
        logger_func("   [Mega Folder] ✅ All concurrent downloads complete or cancelled.")

    elif file_match:
        if overall_progress_callback: overall_progress_callback(1, 0)
        file_id, file_key = file_match.groups()
        try:
            payload = [{"a": "g", "p": file_id}]
            response = session.post(f"{MEGA_API_URL}/cs", json=payload, timeout=20)
            res_json = response.json()
            if isinstance(res_json, list) and res_json and isinstance(res_json[0], int):
                logger_func(f"   [Mega] ❌ API Error {res_json[0]}. Link may be invalid or removed.")
                if overall_progress_callback: overall_progress_callback(1, 1)
                return

            file_size = res_json[0]['s']
            at_b64 = res_json[0]['at']
            raw_file_key_bytes = b64_to_bytes(file_key)
            attr_key_bytes = _process_file_key(raw_file_key_bytes)
            attrs = _decrypt_mega_attribute(at_b64, attr_key_bytes)
            
            file_name = attrs.get('n', f"unknown_file_{file_id}")
            payload_dl = [{"a": "g", "g": 1, "p": file_id}]
            response_dl = session.post(f"{MEGA_API_URL}/cs", json=payload_dl, timeout=20)
            dl_temp_url = response_dl.json()[0]['g']
            file_info_obj = {'file_name': file_name, 'file_size': file_size, 'dl_url': dl_temp_url, 'file_key': file_key}
            
            download_and_decrypt_mega_file(file_info_obj, download_path, logger_func, progress_callback_func, cancellation_event, pause_event)
            
            if overall_progress_callback: overall_progress_callback(1, 1)
        except Exception as e:
            if not (cancellation_event and cancellation_event.is_set()):
                logger_func(f"   [Mega] ❌ Failed to process single file: {e}")
            if overall_progress_callback: overall_progress_callback(1, 1)
    else:
        logger_func(f"   [Mega] ❌ Error: Invalid or unsupported Mega URL format.")
        if '/folder/' in mega_url and '/file/' in mega_url:
            logger_func("   [Mega] ℹ️ This looks like a link to a file inside a folder. Please use a direct, shareable link to the individual file.")
        if overall_progress_callback: overall_progress_callback(1, 1)

def download_gdrive_file(url, download_path, logger_func=print, progress_callback_func=None, overall_progress_callback=None, use_post_subfolder=False, post_title=None):
    if not GDRIVE_AVAILABLE:
        logger_func("❌ Google Drive download failed: 'gdown' library is not installed.")
        return

    final_download_path = download_path
    if use_post_subfolder and post_title:
        subfolder_name = clean_folder_name(post_title)
        final_download_path = os.path.join(download_path, subfolder_name)
        logger_func(f"   [G-Drive] Using post subfolder: '{subfolder_name}'")
    os.makedirs(final_download_path, exist_ok=True)

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    captured_output_buffer = io.StringIO()
    
    paths = None
    try:
        logger_func(f"   [G-Drive] Starting folder download for: {url}")
        
        sys.stdout = captured_output_buffer
        sys.stderr = captured_output_buffer

        paths = gdown.download_folder(url, output=final_download_path, quiet=False, use_cookies=False, remaining_ok=True)
        
    except Exception as e:
        logger_func(f"   [G-Drive] ❌ An unexpected error occurred: {e}")
        logger_func("   [G-Drive] ℹ️ This can happen if the folder is private, deleted, or you have been rate-limited by Google.")
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    captured_output = captured_output_buffer.getvalue()
    if captured_output:
        processed_files_count = 0
        current_filename = None
        
        if overall_progress_callback:
            overall_progress_callback(-1, 0)

        lines = captured_output.splitlines()
        for i, line in enumerate(lines):
            cleaned_line = line.strip('\r').strip()
            if not cleaned_line:
                continue

            if cleaned_line.startswith("To: "):
                try:
                    if current_filename:
                        logger_func(f"   [G-Drive] ✅ Saved '{current_filename}'")
                    
                    filepath = cleaned_line[4:]
                    current_filename = os.path.basename(filepath)
                    processed_files_count += 1
                    
                    logger_func(f"   [G-Drive] ({processed_files_count}/?) Downloading '{current_filename}'...")
                    if progress_callback_func:
                        progress_callback_func(current_filename, "In Progress...")
                    if overall_progress_callback:
                        overall_progress_callback(-1, processed_files_count -1)

                except Exception:
                    logger_func(f"   [gdown] {cleaned_line}")

        if current_filename:
            logger_func(f"   [G-Drive] ✅ Saved '{current_filename}'")
            if overall_progress_callback:
                overall_progress_callback(-1, processed_files_count)

    if paths and all(os.path.exists(p) for p in paths):
        final_folder_path = os.path.dirname(paths[0]) if paths else final_download_path
        logger_func(f"   [G-Drive] ✅ Finished. Downloaded {len(paths)} file(s) to folder '{final_folder_path}'")
    else:
        logger_func(f"   [G-Drive] ❌ Download failed or folder was empty. Check the log above for details from gdown.")

def download_dropbox_file(dropbox_link, download_path=".", logger_func=print, progress_callback_func=None, use_post_subfolder=False, post_title=None):
    logger_func(f"   [Dropbox] Attempting to download: {dropbox_link}")

    final_download_path = download_path
    if use_post_subfolder and post_title:
        subfolder_name = clean_folder_name(post_title)
        final_download_path = os.path.join(download_path, subfolder_name)
        logger_func(f"   [Dropbox] Using post subfolder: '{subfolder_name}'")

    parsed_url = urlparse(dropbox_link)
    query_params = parse_qs(parsed_url.query)
    query_params['dl'] = ['1']
    new_query = urlencode(query_params, doseq=True)
    direct_download_url = urlunparse(parsed_url._replace(query=new_query))
    logger_func(f"   [Dropbox] Using direct download URL: {direct_download_url}")
    scraper = cloudscraper.create_scraper()
    try:
        os.makedirs(final_download_path, exist_ok=True)
        with scraper.get(direct_download_url, stream=True, allow_redirects=True, timeout=(20, 600)) as r:
            r.raise_for_status()
            filename = _get_filename_from_headers(r.headers) or os.path.basename(parsed_url.path) or "dropbox_download"
            if not os.path.splitext(filename)[1]:
                 filename += ".zip"
            full_save_path = os.path.join(final_download_path, filename)
            logger_func(f"   [Dropbox] Starting download of '{filename}'...")
            total_size = int(r.headers.get('content-length', 0))
            downloaded_bytes = 0
            last_log_time = time.time()
            with open(full_save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    current_time = time.time()
                    if current_time - last_log_time > 1:
                        if progress_callback_func:
                           progress_callback_func(filename, (downloaded_bytes, total_size))
                        last_log_time = current_time
            logger_func(f"   [Dropbox] ✅ Download complete: {full_save_path}")
            if zipfile.is_zipfile(full_save_path):
                logger_func(f"   [Dropbox] ዚ Detected zip file. Attempting to extract...")
                extract_folder_name = os.path.splitext(filename)[0]
                extract_path = os.path.join(final_download_path, extract_folder_name)
                os.makedirs(extract_path, exist_ok=True)
                with zipfile.ZipFile(full_save_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
                logger_func(f"   [Dropbox] ✅ Successfully extracted to folder: '{extract_path}'")
                try:
                    os.remove(full_save_path)
                    logger_func(f"   [Dropbox] 🗑️ Removed original zip file.")
                except OSError as e:
                    logger_func(f"   [Dropbox] ⚠️ Could not remove original zip file: {e}")
    except Exception as e:
        logger_func(f"   [Dropbox] ❌ An error occurred during Dropbox download: {e}")

def download_gofile_folder(
    gofile_url,
    download_path,
    logger_func=print,
    progress_callback_func=None,
    overall_progress_callback=None,
    use_post_subfolder=True
):    
    
    logger_func(f"   [Gofile] Initializing download for: {gofile_url}")

    match = re.search(r"gofile\.io/d/([^/?#]+)", gofile_url)
    if not match:
        logger_func("   [Gofile] ❌ Invalid Gofile folder URL format.")
        if overall_progress_callback:
            overall_progress_callback(1, 1)
        return

    content_id = match.group(1)

    session = requests.Session()
    session.headers.update({
        "Accept-Encoding": "gzip",
        "User-Agent": "Mozilla/5.0",
        "Connection": "keep-alive",
        "Accept": "*/*",
    })

    try:
        logger_func("   [Gofile] Creating temporary guest account for API token...")
        response = session.post("https://api.gofile.io/accounts", timeout=20)
        response.raise_for_status()
        token_data = response.json()

        if token_data.get("status") != "ok":
            logger_func("   [Gofile] ❌ Failed to create guest account.")
            return

        token = token_data["data"]["token"]

        session.cookies.set("accountToken", token)
        session.headers.update({"Authorization": f"Bearer {token}"})

        logger_func("   [Gofile] ✅ Successfully obtained API token.")
    except Exception as e:
        logger_func(f"   [Gofile] ❌ Account creation failed: {e}")
        return

    user_agent = session.headers.get('User-Agent', 'Mozilla/5.0')
    lang = "en-US"
    data = (f"{user_agent}::"
            f"{lang}::"
            f"{token}::"
            f"{int(time.time() / 14400)}::"
            f"5d4f7g8sd45fsd")
    wt_token = hashlib.sha256(data.encode()).hexdigest()

    try:
        api_url = f"https://api.gofile.io/contents/{content_id}?cache=true&sortField=createTime&sortDirection=1"

        logger_func(f"   [Gofile] Fetching folder contents for ID: {content_id}")

        response = session.get(
            api_url,
            headers={
                "X-Website-Token": wt_token,
                "X-BL": lang
            },
            timeout=30
        )
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "ok":
            logger_func(f"   [Gofile] ❌ API Error: {data.get('status')}")
            return

        folder_info = data["data"]

        if folder_info["type"] != "folder":
            logger_func("   [Gofile] ❌ Not a folder.")
            return

        folder_name = clean_folder_name(folder_info["name"])

        if use_post_subfolder:
            final_download_path = os.path.join(download_path, folder_name)
            logger_func(f"   [Gofile] Subfolder per Post is ON. Saving to '{folder_name}'")
        else:
            final_download_path = download_path
            logger_func("   [Gofile] Subfolder per Post is OFF. Saving files directly.")

        os.makedirs(final_download_path, exist_ok=True)
        files = [
            child for child in folder_info["children"].values()
            if child["type"] == "file"
        ]

        if not files:
            logger_func("   [Gofile] ℹ️ No files found.")
            return

        logger_func(f"   [Gofile] Found {len(files)} file(s).")

        if overall_progress_callback:
            overall_progress_callback(len(files), 0)

        for index, file_info in enumerate(files):
            filename = file_info["name"]
            file_url = file_info["link"]
            file_size = file_info.get("size", 0)

            filepath = os.path.join(final_download_path, filename)

            logger_func(f"   [Gofile] ({index+1}/{len(files)}) 🔽 Downloading '{filename}'")

            with session.get(file_url, stream=True, timeout=(30, 600)) as r:
                r.raise_for_status()

                downloaded = 0
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback_func:
                            progress_callback_func(filename, (downloaded, file_size))

            logger_func(f"   [Gofile] ✅ Finished '{filename}'")

            if overall_progress_callback:
                overall_progress_callback(len(files), index + 1)

    except Exception as e:
        logger_func(f"   [Gofile] ❌ Download failed: {e}")