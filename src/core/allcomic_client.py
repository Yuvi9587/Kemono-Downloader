import requests
import re
from bs4 import BeautifulSoup
import time 
import random
from urllib.parse import urlparse

def get_chapter_list(scraper, series_url, logger_func, check_pause_func=None, proxies=None):
    """
    Checks if a URL is a series page and returns a list of all chapter URLs if it is.
    Relies on a passed-in scraper session for connection.
    """
    logger_func(f"   [AllComic] Checking for chapter list at: {series_url}")
    
    headers = {'Referer': 'https://allporncomic.com/'}
    response = None
    max_retries = 8

    req_timeout = (30, 120) if proxies else 30

    for attempt in range(max_retries):
        if check_pause_func and check_pause_func():
            return []

        try:
            response = scraper.get(series_url, headers=headers, timeout=req_timeout, proxies=proxies, verify=False)
            response.raise_for_status()
            logger_func(f"   [AllComic] Successfully connected to series page on attempt {attempt + 1}.")
            break 
        except requests.RequestException as e:
            logger_func(f"   [AllComic] ⚠️ Series page check attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 2)
                logger_func(f"      Retrying in {wait_time:.1f} seconds...")
                
                if check_pause_func:
                    for _ in range(int(wait_time * 10)):
                        if check_pause_func(): return []
                        time.sleep(0.1)
                else:
                    time.sleep(wait_time)
            else:
                logger_func(f"   [AllComic] ❌ All attempts to check series page failed.")
                return [] 
    
    if not response:
        return []

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        chapter_links = soup.select('li.wp-manga-chapter a')
        
        if not chapter_links:
            logger_func("   [AllComic] ℹ️ No chapter list found. Assuming this is a single chapter page.")
            return []

        chapter_urls = [link['href'] for link in chapter_links]
        chapter_urls.reverse() 
        
        logger_func(f"   [AllComic] ✅ Found {len(chapter_urls)} chapters.")
        return chapter_urls
        
    except Exception as e:
        logger_func(f"   [AllComic] ❌ Error parsing chapters after successful connection: {e}")
        return []

def fetch_chapter_data(scraper, chapter_url, logger_func, check_pause_func=None, proxies=None):
    """
    Fetches the comic title, chapter title, and image URLs for a single chapter page.
    Relies on a passed-in scraper session for connection.
    """
    logger_func(f"   [AllComic] Fetching page: {chapter_url}")

    headers = {'Referer': 'https://allporncomic.com/'}
    
    response = None
    max_retries = 8
    
    req_timeout = (30, 120) if proxies else 30

    for attempt in range(max_retries):
        if check_pause_func and check_pause_func():
            return None, None, None

        try:
            response = scraper.get(chapter_url, headers=headers, timeout=req_timeout, proxies=proxies, verify=False)
            response.raise_for_status()
            break
        except requests.RequestException as e:
            logger_func(f"   [AllComic] ⚠️ Chapter page connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 2)
                logger_func(f"      Retrying in {wait_time:.1f} seconds...")
                
                if check_pause_func:
                    for _ in range(int(wait_time * 10)):
                        if check_pause_func(): return None, None, None
                        time.sleep(0.1)
                else:
                    time.sleep(wait_time)
            else:
                logger_func(f"   [AllComic] ❌ All connection attempts failed for chapter: {chapter_url}")
                return None, None, None
    
    if not response:
        return None, None, None

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        
        comic_title = "Unknown Comic"
        title_element = soup.find('h1', class_='post-title')
        if title_element:
            comic_title = title_element.text.strip()
        else:
            try:
                path_parts = urlparse(chapter_url).path.strip('/').split('/')
                if len(path_parts) >= 3 and path_parts[-3] == 'porncomic':
                    comic_slug = path_parts[-2]
                    comic_title = comic_slug.replace('-', ' ').title()
            except Exception:
                pass 

        chapter_slug = chapter_url.strip('/').split('/')[-1]
        chapter_title = chapter_slug.replace('-', ' ').title()
        
        reading_container = soup.find('div', class_='reading-content')
        list_of_image_urls = []
        if reading_container:
            image_elements = reading_container.find_all('img', class_='wp-manga-chapter-img')
            for img in image_elements:
                img_url = (img.get('data-src') or img.get('src', '')).strip()
                if img_url:
                    list_of_image_urls.append(img_url)

        if not list_of_image_urls:
            logger_func(f"   [AllComic] ❌ Could not find any images on the page.")
            return None, None, None

        return comic_title, chapter_title, list_of_image_urls
        
    except Exception as e:
        logger_func(f"   [AllComic] ❌ An unexpected error occurred while parsing the page: {e}")
        return None, None, None