import re
import os
import time 
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
import queue

def run_hentai2read_download(start_url, output_dir, progress_callback, overall_progress_callback, check_pause_func, proxies=None, export_all_links_mode=False):
    """
    Orchestrates the download process using a producer-consumer model.
    """
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    all_failed_files = []
    
    try:
        progress_callback("   [Hentai2Read] Scraping series page for all metadata...")
        top_level_folder_name, chapters_to_process = _get_series_metadata(start_url, progress_callback, scraper)

        if not chapters_to_process:
            progress_callback("❌ No chapters found to download. Aborting.")
            return 0, 0
        
        total_chapters = len(chapters_to_process)
        overall_progress_callback(total_chapters, 0)
        
        total_downloaded_count = 0
        total_skipped_count = 0

        for idx, chapter in enumerate(chapters_to_process):
            if check_pause_func(): break

            progress_callback(f"\n-- Processing and Downloading Chapter {idx + 1}/{total_chapters}: '{chapter['title']}' --")
            
            series_folder = re.sub(r'[\\/*?:"<>|]', "", top_level_folder_name).strip()
            chapter_folder = re.sub(r'[\\/*?:"<>|]', "", chapter['title']).strip()
            final_save_path = os.path.join(output_dir, series_folder, chapter_folder)
            os.makedirs(final_save_path, exist_ok=True)
            
            dl_count, skip_count, chapter_failures = _process_and_download_chapter(
                chapter_url=chapter['url'],
                save_path=final_save_path,
                scraper=scraper,
                progress_callback=progress_callback,
                check_pause_func=check_pause_func,
                proxies=proxies,
                export_all_links_mode=export_all_links_mode,
                output_dir=output_dir,
                series_title=top_level_folder_name
            )

            total_downloaded_count += dl_count
            total_skipped_count += skip_count
            
            if chapter_failures:
                all_failed_files.extend(chapter_failures)
            
            overall_progress_callback(total_chapters, idx + 1)
            if check_pause_func(): break
        
        if all_failed_files:
            progress_callback("\n" + "="*40)
            progress_callback(f"❌ SUMMARY: {len(all_failed_files)} files failed permanently after 10 retries:")
            for fail_msg in all_failed_files:
                progress_callback(f"   • {fail_msg}")
            progress_callback("="*40 + "\n")
        else:
            progress_callback("\n✅ All chapters processed successfully with no permanent failures.")

        return total_downloaded_count, total_skipped_count

    except Exception as e:
        progress_callback(f"❌ A critical error occurred in the Hentai2Read client: {e}")
        return 0, 0

def _get_series_metadata(start_url, progress_callback, scraper):
    """
    Scrapes the main series page to get the Artist Name, Series Title, and chapter list.
    """
    max_retries = 4
    last_exception = None
    soup = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                progress_callback(f"   [Hentai2Read] ⚠️ Retrying connection (Attempt {attempt + 1}/{max_retries})...")
            
            response = scraper.get(start_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            last_exception = None
            break

        except Exception as e:
            last_exception = e
            progress_callback(f"   [Hentai2Read] ⚠️ Connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
            continue

    if last_exception:
        progress_callback(f"   [Hentai2Read] ❌ Error getting series metadata after {max_retries} attempts: {last_exception}")
        return "Unknown Series", []

    try:
        series_title = "Unknown Series"
        artist_name = None

        title_tag = soup.select_one("h3.block-title a")
        if title_tag:
            series_title = title_tag.get_text(strip=True)
        else:
            meta_title = soup.select_one("meta[property='og:title']")
            if meta_title:
                series_title = meta_title.get("content", "Unknown Series").replace(" - Hentai2Read", "")

        metadata_list = soup.select_one("ul.list.list-simple-mini")
        if metadata_list:
            for b_tag in metadata_list.find_all('b'):
                label = b_tag.get_text(strip=True)
                if "Artist" in label or "Author" in label:
                    a_tag = b_tag.find_next_sibling('a')
                    if a_tag:
                        artist_name = a_tag.get_text(strip=True)
                        break
        
        if not artist_name:
            artist_link = soup.find('a', href=re.compile(r'/hentai-list/artist/'))
            if artist_link:
                artist_name = artist_link.get_text(strip=True)

        if artist_name:
            top_level_folder_name = f"{artist_name} - {series_title}"
        else:
            top_level_folder_name = series_title
        
        chapter_links = soup.select("div.media a.pull-left.font-w600")
        if not chapter_links:
            chapters_to_process = [{'url': start_url, 'title': series_title}]
        else:
            chapters_to_process = [
                {'url': urljoin(start_url, link['href']), 'title': " ".join(link.stripped_strings)} 
                for link in chapter_links
            ]
            chapters_to_process.reverse()

        progress_callback(f"   [Hentai2Read] ✅ Found Metadata: '{top_level_folder_name}'")
        progress_callback(f"   [Hentai2Read] ✅ Found {len(chapters_to_process)} chapters to process.")
        
        return top_level_folder_name, chapters_to_process

    except Exception as e:
        progress_callback(f"   [Hentai2Read] ❌ Error parsing metadata after successful connection: {e}")
        return "Unknown Series", []

def _process_and_download_chapter(chapter_url, save_path, scraper, progress_callback, check_pause_func, proxies=None, export_all_links_mode=False, output_dir=None, series_title=None):
    """
    Uses a producer-consumer pattern to download a chapter.
    Includes RETRY LOGIC and ACTIVE LOGGING.
    """
    task_queue = queue.Queue()
    num_download_threads = 8
    
    download_stats = {'downloaded': 0, 'skipped': 0}
    failed_files_list = [] 

    def downloader_worker():
        worker_scraper = cloudscraper.create_scraper()
        if proxies:
            worker_scraper.proxies.update(proxies)
        while True:
            task = task_queue.get()
            if task is None:
                task_queue.task_done()
                break
            
            filepath, img_url = task
            filename = os.path.basename(filepath)
            
            if os.path.exists(filepath):
                progress_callback(f"   -> Skip (Exists): '{filename}'")
                download_stats['skipped'] += 1
                task_queue.task_done()
                continue

            success = False
            progress_callback(f"   Downloading: '{filename}'...")
            
            for attempt in range(10):
                try:
                    if attempt > 0:
                        progress_callback(f"   ⚠️ Retrying '{filename}' (Attempt {attempt+1}/10)...")
                        time.sleep(2) 

                    response = worker_scraper.get(img_url, stream=True, timeout=60, headers={'Referer': chapter_url})
                    response.raise_for_status()
                    
                    with open(filepath, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    download_stats['downloaded'] += 1
                    success = True
                    progress_callback(f"   ✅ Downloaded: '{filename}'")
                    break 

                except Exception as e:
                    if attempt == 9:
                        progress_callback(f"   ❌ Failed '{filename}' after 10 attempts: {e}")
            
            if not success:
                failed_files_list.append(f"{filename} (Chapter: {os.path.basename(save_path)})")
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError: pass

            task_queue.task_done()

    executor = ThreadPoolExecutor(max_workers=num_download_threads, thread_name_prefix='H2R_Downloader')
    for _ in range(num_download_threads):
        executor.submit(downloader_worker)

    page_number = 1
    progress_callback("   [Hentai2Read] Scanning pages...")
    
    while True:
        if check_pause_func(): break
        if page_number > 300: 
            progress_callback("   [Hentai2Read] ⚠️ Safety break: Reached 300 pages.")
            break
        
        if page_number % 10 == 0:
             progress_callback(f"   [Hentai2Read] Scanned {page_number} pages so far...")

        page_url_to_check = f"{chapter_url}{page_number}/"
        try:
            page_response = None
            page_last_exception = None
            for page_attempt in range(3): 
                try:
                    page_response = scraper.get(page_url_to_check, timeout=30)
                    page_last_exception = None
                    break
                except Exception as e:
                    page_last_exception = e
                    time.sleep(1)
            
            if page_last_exception:
                raise page_last_exception

            if page_response.history or page_response.status_code != 200:
                progress_callback(f"   [Hentai2Read] End of chapter detected on page {page_number}.")
                break

            soup = BeautifulSoup(page_response.text, 'html.parser')
            img_tag = soup.select_one("img#arf-reader")
            img_src = img_tag.get("src") if img_tag else None

            if not img_tag or img_src == "https://static.hentai.direct/hentai":
                progress_callback(f"   [Hentai2Read] End of chapter detected (Last page reached at {page_number}).")
                break
            
            normalized_img_src = urljoin(page_response.url, img_src)
            ext = os.path.splitext(normalized_img_src.split('/')[-1])[-1] or ".jpg"
            filename = f"{page_number:03d}{ext}"
            filepath = os.path.join(save_path, filename)
            
            if export_all_links_mode:
                export_file_path = os.path.join(output_dir, "all_file_links.txt")
                try:
                    with open(export_file_path, "a", encoding="utf-8") as f:
                        if page_number == 1:
                            f.write(f"\n# Hentai2Read: {series_title} - {os.path.basename(save_path)}\n")
                        f.write(normalized_img_src + "\n")
                    download_stats['downloaded'] += 1
                except Exception as e:
                    pass
            else:
                task_queue.put((filepath, normalized_img_src))
            
            page_number += 1
            time.sleep(0.1) 
        except Exception as e:
            progress_callback(f"   [Hentai2Read] ❌ Error while scraping page {page_number}: {e}")
            break
            
    for _ in range(num_download_threads):
        task_queue.put(None)
    
    task_queue.join()
    executor.shutdown(wait=True)
    
    progress_callback(f"   Chapter complete. Processed {page_number - 1} images.")
    
    return download_stats['downloaded'], download_stats['skipped'], failed_files_list