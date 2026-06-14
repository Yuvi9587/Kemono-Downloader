import time
import traceback
from urllib.parse import urlparse
import json
import requests
import cloudscraper 
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from ..utils.network_utils import extract_post_info, prepare_cookies_for_request
from ..config.constants import (
    STYLE_DATE_POST_TITLE,
    STYLE_DATE_BASED,
    STYLE_POST_TITLE_GLOBAL_NUMBERING
)

_last_429_warning_time = 0

class CustomSSLAdapter(HTTPAdapter):
    """
    A custom HTTPAdapter that forces check_hostname=False when using SSL.
    This prevents the 'Cannot set verify_mode to CERT_NONE' error.
    """
    def init_poolmanager(self, connections, maxsize, block=False):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx
        )

def fetch_posts_paginated(api_url_base, headers, offset, logger, cancellation_event=None, pause_event=None, cookies_dict=None, proxies=None):
    """
    Fetches a single page of posts from the API with robust retry logic.
    """
    if cancellation_event and cancellation_event.is_set():
        raise RuntimeError("Fetch operation cancelled by user.")
    if pause_event and pause_event.is_set():
        logger("   Post fetching paused...")
        while pause_event.is_set():
            if cancellation_event and cancellation_event.is_set():
                raise RuntimeError("Fetch operation cancelled by user while paused.")
            time.sleep(0.5)
        logger("   Post fetching resumed.")
    fields_to_request = "id,user,service,title,shared_file,added,published,edited,file,attachments,tags,content"
    paginated_url = f'{api_url_base}?o={offset}&fields={fields_to_request}'
    
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        if cancellation_event and cancellation_event.is_set():
            raise RuntimeError("Fetch operation cancelled by user during retry loop.")

        log_message = f"   Fetching post list: {api_url_base} (Page approx. {offset // 50 + 1})"
        if attempt > 0:
            log_message += f" (Attempt {attempt + 1}/{max_retries})"
        logger(log_message)

        request_timeout = (30, 120) if proxies else (15, 60)
        
        try:
            with requests.get(paginated_url, headers=headers, timeout=request_timeout, cookies=cookies_dict, proxies=proxies, verify=False) as response:
              
                response.raise_for_status()
                response.encoding = 'utf-8'  
                return response.json()

        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 403 and offset == 0:
                logger("   ❌ Access Denied (403 Forbidden) on the first page.")
                logger("      This is likely a rate limit or a Cloudflare block.")
                logger("      💡 SOLUTION: Wait a while, use a VPN, or provide a valid session cookie.")
                return []

            if e.response is not None and e.response.status_code == 400:
                logger(f"   ✅ Reached end of posts (API returned 400 Bad Request for offset {offset}).")
                return []

            logger(f"   ⚠️ Retryable network error on page fetch (Attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)
                logger(f"      Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger(f"   ❌ Failed to fetch page after {max_retries} attempts.")
                raise RuntimeError(f"Network error fetching offset {offset}")
        except json.JSONDecodeError as e:
            logger(f"   ❌ Failed to decode JSON on page fetch (Attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                delay = retry_delay * (2 ** attempt)
                logger(f"      Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                raise RuntimeError(f"JSONDecodeError fetching offset {offset}")

    raise RuntimeError(f"Failed to fetch page {paginated_url} after all attempts.")

def fetch_single_post_data(api_domain, service, user_id, post_id, headers, logger, cookies_dict=None, proxies=None):
    """
    Fetches the full data, including the 'content' field, for a single post using cloudscraper.
    Includes RETRY logic for 429 Rate Limit errors.
    """
    post_api_url = f"https://{api_domain}/api/v1/{service}/user/{user_id}/post/{post_id}"
    logger(f"      Fetching full content for post ID {post_id}...")

    max_retries = 4
    
    for attempt in range(max_retries + 1):
        scraper = None
        try:
            scraper = cloudscraper.create_scraper()
            
            adapter = CustomSSLAdapter()
            scraper.mount("https://", adapter)

            request_timeout = (30, 300) if proxies else (15, 300)
            
            response = scraper.get(post_api_url, headers=headers, timeout=request_timeout, cookies=cookies_dict, proxies=proxies, verify=False)
        
            
            if response.status_code == 429:
                wait_time = 20 + (attempt * 10)
                
                global _last_429_warning_time 
                current_time = time.time()
                
                if current_time - _last_429_warning_time > 60:
                    logger(f"      ⚠️ Rate Limited (429). API is throttling requests. Pausing {wait_time}s (will continue automatically)...")
                    _last_429_warning_time = current_time
                
                time.sleep(wait_time)
                continue
           

            response.raise_for_status()

            full_post_data = response.json()

            if isinstance(full_post_data, list) and full_post_data:
                return full_post_data[0] 
            if isinstance(full_post_data, dict) and 'post' in full_post_data:
                return full_post_data['post'] 
            return full_post_data 

        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if attempt < max_retries:
                    wait_time = 20 + (attempt * 10)
                    logger(f"      ⚠️ Rate Limit Error caught: {e}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            if attempt == max_retries:
                logger(f"      ❌ Failed to fetch full content for post {post_id} after {max_retries} retries: {e}")
                return None
        finally:
            if scraper:
                scraper.close()
    return None
        
def fetch_post_comments(api_domain, service, user_id, post_id, headers, logger, cancellation_event=None, pause_event=None, cookies_dict=None, proxies=None):
    """Fetches all comments for a specific post."""
    if cancellation_event and cancellation_event.is_set():
        raise RuntimeError("Comment fetch operation cancelled by user.")

    comments_api_url = f"https://{api_domain}/api/v1/{service}/user/{user_id}/post/{post_id}/comments"
    logger(f"   Fetching comments: {comments_api_url}")
    
    try:
        request_timeout = (30, 60) if proxies else (10, 30)
        
        with requests.get(comments_api_url, headers=headers, timeout=request_timeout, cookies=cookies_dict, proxies=proxies, verify=False) as response:
            response.raise_for_status()
            response.encoding = 'utf-8'          
            return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error fetching comments for post {post_id}: {e}")
    except ValueError as e:
        raise RuntimeError(f"Error decoding JSON from comments API for post {post_id}: {e}")

def fetch_post_revisions(api_domain, service, user_id, post_id, headers, logger, cookies_dict=None, proxies=None):
    """
    Fetches the revision history for a specific post.
    Endpoint: /v1/{service}/user/{creator_id}/post/{post_id}/revisions
    """
    url = f"https://{api_domain}/api/v1/{service}/user/{user_id}/post/{post_id}/revisions"

    try:
        request_timeout = (10, 30)
        response = requests.get(url, headers=headers, timeout=request_timeout, cookies=cookies_dict, proxies=proxies, verify=False)
        
        if response.status_code == 404:
            return []
            
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger(f"   ⚠️ Failed to fetch revisions for post {post_id}: {e}")
        return []

def download_from_api(
    api_url_input,
    logger=print,
    start_page=None,
    end_page=None,
    manga_mode=False,
    cancellation_event=None,
    pause_event=None,
    use_cookie=False,
    cookie_text="",
    selected_cookie_file=None,
    app_base_dir=None,
    manga_filename_style_for_sort_check=None,
    processed_post_ids=None,
    fetch_all_first=False,
    proxies=None,
    **kwargs
    ):
    parsed_input_url_for_domain = urlparse(api_url_input)
    api_domain = parsed_input_url_for_domain.netloc

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        'Referer': f'https://{api_domain}/',
        'Accept': 'text/css'
    }

    if processed_post_ids is None:
        processed_post_ids = set()
    else:
        processed_post_ids = set(processed_post_ids)

    service, user_id, target_post_id = extract_post_info(api_url_input)

    if cancellation_event and cancellation_event.is_set():
        logger("   Download_from_api cancelled at start.")
        return
    
    if not any(d in api_domain.lower() for d in ['kemono.su', 'kemono.party', 'kemono.cr', 'pawchive.st', 'coomer.su', 'coomer.party', 'coomer.st']):
        logger(f"⚠️ Unrecognized domain '{api_domain}' from input URL. Defaulting to kemono.cr for API calls.")
        api_domain = "kemono.cr"
        
    cookies_for_api = None
    if use_cookie and app_base_dir:
        cookies_for_api = prepare_cookies_for_request(use_cookie, cookie_text, selected_cookie_file, app_base_dir, logger, target_domain=api_domain)
  

    if target_post_id:
        if target_post_id in processed_post_ids:
            logger(f"   Skipping already processed target post ID: {target_post_id}")
            return
        direct_post_api_url = f"https://{api_domain}/api/v1/{service}/user/{user_id}/post/{target_post_id}"
        logger(f"   Attempting direct fetch for target post: {direct_post_api_url}")
        try:
            request_timeout = (30, 60) if proxies else (10, 30)
            
            with requests.get(direct_post_api_url, headers=headers, timeout=request_timeout, cookies=cookies_for_api, proxies=proxies, verify=False) as direct_response:
                direct_response.raise_for_status()
                direct_response.encoding = 'utf-8' 
                direct_post_data = direct_response.json()
            
            if isinstance(direct_post_data, list) and direct_post_data:
                direct_post_data = direct_post_data[0]
            if isinstance(direct_post_data, dict) and 'post' in direct_post_data and isinstance(direct_post_data['post'], dict):
                direct_post_data = direct_post_data['post']

            if isinstance(direct_post_data, dict) and direct_post_data.get('id') == target_post_id:
                if kwargs.get('download_revisions') and service != 'discord':
                    logger(f"   Checking historical revisions for direct post {target_post_id}...")
                    revisions = fetch_post_revisions(api_domain, service, user_id, target_post_id, headers, logger, cookies_dict=cookies_for_api, proxies=proxies)
                    
                    if revisions:
                        existing_paths = set()
                        if direct_post_data.get('file') and 'path' in direct_post_data['file']:
                            existing_paths.add(direct_post_data['file']['path'])
                        
                        attachments = direct_post_data.setdefault('attachments', [])
                        for att in attachments:
                            if 'path' in att: existing_paths.add(att['path'])
                        
                        found_rev_files = 0
                        for rev in revisions:
                            if rev.get('file') and rev['file'].get('path'):
                                if rev['file']['path'] not in existing_paths:
                                    attachments.append(rev['file'])
                                    existing_paths.add(rev['file']['path'])
                                    found_rev_files += 1
                            for att in rev.get('attachments', []):
                                if att.get('path') and att['path'] not in existing_paths:
                                    attachments.append(att)
                                    existing_paths.add(att['path'])
                                    found_rev_files += 1
                        
                        if found_rev_files > 0:
                            logger(f"   ✅ Recovered {found_rev_files} file(s) from post history.")

                logger(f"   ✅ Direct fetch successful for post {target_post_id}.")
                yield [direct_post_data]
                return

      
        except Exception as e:
            logger(f"   ⚠️ Unexpected error during direct fetch for post {target_post_id}: {e}. Falling back to pagination.")
    if not service or not user_id:
        logger(f"❌ Invalid URL or could not extract service/user: {api_url_input}")
        return
    if target_post_id and (start_page or end_page):
        logger("⚠️ Page range (start/end page) is ignored when a specific post URL is provided (searching all pages for the post).")


    styles_requiring_fetch_all = [STYLE_DATE_BASED, STYLE_POST_TITLE_GLOBAL_NUMBERING]

    is_manga_mode_fetch_all_and_sort_oldest_first = (
        manga_mode and 
        (manga_filename_style_for_sort_check in styles_requiring_fetch_all) and 
        not target_post_id
    )

    should_fetch_all = fetch_all_first or is_manga_mode_fetch_all_and_sort_oldest_first  
    api_base_url = f"https://{api_domain}/api/v1/{service}/user/{user_id}/posts"
    page_size = 50
    
    if is_manga_mode_fetch_all_and_sort_oldest_first:
        logger(f"   Manga Mode (Style: {manga_filename_style_for_sort_check} - Oldest First Sort Active): Fetching all posts to sort by date...")
        all_posts_for_manga_mode = []
        current_offset_manga = 0
        if start_page and start_page > 1:
            current_offset_manga = (start_page - 1) * page_size
            logger(f"   Manga Mode: Starting fetch from page {start_page} (offset {current_offset_manga}).")
        elif start_page:
            logger(f"   Manga Mode: Starting fetch from page 1 (offset 0).")
        if end_page:
            logger(f"   Manga Mode: Will fetch up to page {end_page}.")
        while True:
            if pause_event and pause_event.is_set():
                logger("   Manga mode post fetching paused...")
                while pause_event.is_set():
                    if cancellation_event and cancellation_event.is_set():
                        logger("   Manga mode post fetching cancelled while paused.")
                        break
                    time.sleep(0.5)
                if not (cancellation_event and cancellation_event.is_set()): logger("   Manga mode post fetching resumed.")
            if cancellation_event and cancellation_event.is_set():
                logger("   Manga mode post fetching cancelled.")
                break
            current_page_num_manga = (current_offset_manga // page_size) + 1
            if end_page and current_page_num_manga > end_page:
                logger(f"   Manga Mode: Reached specified end page ({end_page}). Stopping post fetch.")
                break
            try:
                logger(f"   🔎 [Manga Mode] Scanning page {current_page_num_manga} (Posts {current_offset_manga} to {current_offset_manga + page_size})... Sorting...")
                time.sleep(0.1)
                
                posts_batch_manga = fetch_posts_paginated(api_base_url, headers, current_offset_manga, logger, cancellation_event, pause_event, cookies_dict=cookies_for_api, proxies=proxies)

                if not isinstance(posts_batch_manga, list):
                    logger(f"❌ API Error (Manga Mode): Expected list of posts, got {type(posts_batch_manga)}.")
                    break
                if not posts_batch_manga:
                    logger("✅ Reached end of posts (Manga Mode fetch all).")
                    if start_page and not end_page and current_page_num_manga < start_page:
                        logger(f"   Manga Mode: No posts found on or after specified start page {start_page}.")
                    elif end_page and current_page_num_manga <= end_page and not all_posts_for_manga_mode:
                        logger(f"   Manga Mode: No posts found within the specified page range ({start_page or 1}-{end_page}).")
                    break
                all_posts_for_manga_mode.extend(posts_batch_manga)
                
                logger(f"RENAMING_MODE_FETCH_PROGRESS:{len(all_posts_for_manga_mode)}:{current_page_num_manga}")

                current_offset_manga += page_size
                time.sleep(0.6)
            except RuntimeError as e:
                if "cancelled by user" in str(e).lower():
                    logger(f"ℹ️ Manga mode pagination stopped due to cancellation: {e}")
                else:
                    logger(f"❌ {e}\n   Aborting manga mode pagination.")
                break
            except Exception as e:
                logger(f"❌ Unexpected error during manga mode fetch: {e}")
                traceback.print_exc()
                break
        
        if cancellation_event and cancellation_event.is_set(): return
        
        if all_posts_for_manga_mode:
            logger(f"RENAMING_MODE_FETCH_COMPLETE:{len(all_posts_for_manga_mode)}")

        if all_posts_for_manga_mode:
            if processed_post_ids:
                original_count = len(all_posts_for_manga_mode)
                all_posts_for_manga_mode = [post for post in all_posts_for_manga_mode if post.get('id') not in processed_post_ids]
                skipped_count = original_count - len(all_posts_for_manga_mode)
                if skipped_count > 0:
                    logger(f"   Manga Mode: Skipped {skipped_count} already processed post(s) before sorting.")

            logger(f"   Manga Mode: Fetched {len(all_posts_for_manga_mode)} total posts. Sorting by publication date (oldest first)...")
            def sort_key_tuple(post):
                published_date_str = post.get('published')
                added_date_str = post.get('added')
                post_id_str = post.get('id', "0")
                primary_sort_val = "0000-00-00T00:00:00"
                if published_date_str:
                    primary_sort_val = published_date_str
                elif added_date_str:
                    logger(f"    ⚠️ Post ID {post_id_str} missing 'published' date, using 'added' date '{added_date_str}' for primary sorting.")
                    primary_sort_val = added_date_str
                else:
                    logger(f"    ⚠️ Post ID {post_id_str} missing both 'published' and 'added' dates. Placing at start of sort (using default earliest date).")
                secondary_sort_val = 0
                try:
                    secondary_sort_val = int(post_id_str)
                except ValueError:
                    logger(f"    ⚠️ Post ID '{post_id_str}' is not a valid integer for secondary sorting, using 0.")
                return (primary_sort_val, secondary_sort_val)
            all_posts_for_manga_mode.sort(key=sort_key_tuple)
            for i in range(0, len(all_posts_for_manga_mode), page_size):
                if cancellation_event and cancellation_event.is_set():
                    logger("   Manga mode post yielding cancelled.")
                    break
                yield all_posts_for_manga_mode[i:i + page_size]
        return

    if manga_mode and not target_post_id and (manga_filename_style_for_sort_check not in styles_requiring_fetch_all):
        logger(f"   Renaming Mode (Style: {manga_filename_style_for_sort_check}): Processing posts in default API order (Streaming).")

    current_page_num = 1
    current_offset = 0
    processed_target_post_flag = False
    if start_page and start_page > 1 and not target_post_id:
        current_offset = (start_page - 1) * page_size
        current_page_num = start_page
        logger(f"   Starting from page {current_page_num} (calculated offset {current_offset}).")
    
    while True:
        if pause_event and pause_event.is_set():
            logger("   Post fetching loop paused...")
            while pause_event.is_set():
                if cancellation_event and cancellation_event.is_set():
                    logger("   Post fetching loop cancelled while paused.")
                    break
                time.sleep(0.5)
            if not (cancellation_event and cancellation_event.is_set()): logger("   Post fetching loop resumed.")
        
        if cancellation_event and cancellation_event.is_set():
            logger("   Post fetching loop cancelled.")
            break
            
        if target_post_id and processed_target_post_flag:
            break
            
        if not target_post_id and end_page and current_page_num > end_page:
            logger(f"✅ Reached specified end page ({end_page}) for creator feed. Stopping.")
            break
            
        try:
            logger(f"   🔎 Fetching API page {current_page_num} (Posts {current_offset} to {current_offset + page_size})...")
            time.sleep(1.0)
            
            raw_posts_batch = fetch_posts_paginated(api_base_url, headers, current_offset, logger, cancellation_event, pause_event, cookies_dict=cookies_for_api, proxies=proxies)
            if not isinstance(raw_posts_batch, list):
                logger(f"❌ API Error: Expected list of posts, got {type(raw_posts_batch)} at page {current_page_num} (offset {current_offset}).")
                break
        except RuntimeError as e:
            if "cancelled by user" in str(e).lower():
                logger(f"ℹ️ Pagination stopped due to cancellation: {e}")
            else:
                logger(f"❌ {e}\n   Aborting pagination at page {current_page_num} (offset {current_offset}).")
            break
        except Exception as e:
            logger(f"❌ Unexpected error fetching page {current_page_num} (offset {current_offset}): {e}")
            traceback.print_exc()
            break

        if not raw_posts_batch:
            if target_post_id and not processed_target_post_flag:
                logger(f"❌ Target post {target_post_id} not found after checking all available pages (API returned no more posts at offset {current_offset}).")
            elif not target_post_id:
                if current_page_num == (start_page or 1):
                    logger(f"😕 No posts found on the first page checked (page {current_page_num}, offset {current_offset}).")
                else:
                    logger(f"✅ Reached end of posts (no more content from API at offset {current_offset}).")
            break

        posts_batch_to_yield = raw_posts_batch
        original_count = len(raw_posts_batch)
        
        if processed_post_ids:
            posts_batch_to_yield = [post for post in raw_posts_batch if post.get('id') not in processed_post_ids]
            skipped_count = original_count - len(posts_batch_to_yield)
            if skipped_count > 0:
                logger(f"   Skipped {skipped_count} already processed post(s) from page {current_page_num}.")

        if target_post_id and not processed_target_post_flag:
            matching_post = next((p for p in posts_batch_to_yield if str(p.get('id')) == str(target_post_id)), None)
            if matching_post:
                logger(f"🎯 Found target post {target_post_id} on page {current_page_num} (offset {current_offset}).")
                yield [matching_post]
                processed_target_post_flag = True
        elif not target_post_id:
            if posts_batch_to_yield:
                yield posts_batch_to_yield
            elif original_count > 0:
                logger(f"   No new posts found on page {current_page_num}. Checking next page...")

        if processed_target_post_flag:
            break
            
        current_offset += page_size
        current_page_num += 1
        time.sleep(0.6)
        
    if target_post_id and not processed_target_post_flag and not (cancellation_event and cancellation_event.is_set()):
        logger(f"❌ Target post {target_post_id} could not be found after checking all relevant pages (final check after loop).")