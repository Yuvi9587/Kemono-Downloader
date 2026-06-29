import cloudscraper
from bs4 import BeautifulSoup
import time

def get_chapter_list(series_url, logger_func, proxies=None):
    logger_func(f"   [Toonily] Scraping series page for chapter list: {series_url}")
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://toonily.com/'
    }
    
    try:
        response = scraper.get(series_url, timeout=30, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        chapter_links = soup.select('li.wp-manga-chapter > a')

        if not chapter_links:
            logger_func("   [Toonily] ❌ Could not find any chapter links on the page.")
            return []

        urls = [link['href'] for link in chapter_links]
        urls.reverse() 
        logger_func(f"   [Toonily] Found {len(urls)} chapters.")
        return urls

    except Exception as e:
        logger_func(f"   [Toonily] ❌ Error getting chapter list: {e}")
        return []


def fetch_chapter_data(chapter_url, logger_func, scraper_session, proxies=None):
    """
    Scrapes a single Toonily.com chapter page for its title and image URLs.
    """
    main_series_url = chapter_url.rsplit('/', 2)[0] + '/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': main_series_url
    }
    
    try:
        response = scraper_session.get(chapter_url, timeout=30, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        title_element = soup.select_one('h1#chapter-heading')
        image_container = soup.select_one('div.reading-content')
        
        if not title_element or not image_container:
            logger_func("   [Toonily] ❌ Page structure invalid. Could not find title or image container.")
            return None, None, []

        full_chapter_title = title_element.text.strip()
        
        if " - Chapter" in full_chapter_title:
            series_title = full_chapter_title.split(" - Chapter")[0].strip()
        else:
            series_title = full_chapter_title.strip()

        chapter_title = full_chapter_title
        
        image_elements = image_container.select('img')
        image_urls = [img.get('data-src', img.get('src')).strip() for img in image_elements if img.get('data-src') or img.get('src')]
        
        return series_title, chapter_title, image_urls

    except Exception as e:
        logger_func(f"   [Toonily] ❌ An error occurred scraping chapter '{chapter_url}': {e}")
        return None, None, []