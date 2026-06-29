import cloudscraper
from bs4 import BeautifulSoup
import re
import html

def fetch_rule34video_data(video_url, logger_func, proxies=None):
    """
    Scrapes a rule34video.com page by specifically finding the 'Download' div,
    then selecting the best available quality link.
    
    Args:
        video_url (str): The full URL to the rule34video.com page.
        logger_func (callable): Function to use for logging progress.

    Returns:
        tuple: (video_title, final_video_url, tags_list) or (None, None, None) on failure.
    """
    logger_func(f"   [Rule34Video] Fetching page: {video_url}")
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    
    try:
        main_page_response = scraper.get(video_url, timeout=20)
        main_page_response.raise_for_status()
        
        soup = BeautifulSoup(main_page_response.text, 'html.parser')
        
        page_title_tag = soup.find('title')
        video_title = page_title_tag.text.strip() if page_title_tag else "rule34video_file"

        # Extract tags and models from flashvars
        tags_list = []
        html_text = main_page_response.text
        
        tags_match = re.search(r"video_tags:\s*'([^']+)'", html_text)
        if tags_match:
            tags = tags_match.group(1).split(',')
            tags_list.extend([t.strip() for t in tags if t.strip()])
            
        models_match = re.search(r"video_models:\s*'([^']+)'", html_text)
        if models_match:
            models = models_match.group(1).split(',')
            tags_list.extend([m.strip() for m in models if m.strip()])

        download_label = soup.find('div', class_='label', string='Download')

        if not download_label:
            logger_func("   [Rule34Video] ❌ Could not find the 'Download' label. Unable to locate the correct links div.")
            return None, None, None

        download_div = download_label.parent
        
        link_tags = download_div.find_all('a', class_='tag_item')
        if not link_tags:
            logger_func("   [Rule34Video] ❌ Found the 'Download' div, but no download links were inside it.")
            return None, None, None

        links_by_quality = {}
        quality_pattern = re.compile(r'(\d+p|4k)')

        for tag in link_tags:
            href = tag.get('href')
            if not href:
                continue

            quality = None
            text_match = quality_pattern.search(tag.text)
            if text_match:
                quality = text_match.group(1)
            else:
                href_match = quality_pattern.search(href)
                if href_match:
                    quality = href_match.group(1)

            if quality:
                links_by_quality[quality] = href
        
        if not links_by_quality:
            logger_func("   [Rule34Video] ⚠️ Could not parse specific qualities. Using first available link as a fallback.")
            final_video_url = link_tags[0].get('href')
            if not final_video_url:
                logger_func("   [Rule34Video] ❌ Fallback failed: First link tag had no href attribute.")
                return None, None, None
            
            final_video_url = html.unescape(final_video_url)
            logger_func(f"   [Rule34Video] ✅ Selected first available link as fallback: {final_video_url}")
            return video_title, final_video_url, tags_list
            
        logger_func(f"   [Rule34Video] Found available qualities: {list(links_by_quality.keys())}")

        final_video_url = None
        if '1080p' in links_by_quality:
            final_video_url = links_by_quality['1080p']
            logger_func("   [Rule34Video] ✅ Selected preferred 1080p link.")
        elif '720p' in links_by_quality:
            final_video_url = links_by_quality['720p']
            logger_func("   [Rule34Video] ✅ 1080p not found. Selected fallback 720p link.")
        else:
            fallback_order = ['480p', '360p']
            for quality in fallback_order:
                if quality in links_by_quality:
                    final_video_url = links_by_quality[quality]
                    logger_func(f"   [Rule34Video] ⚠️ 1080p/720p not found. Selected best available fallback: {quality}")
                    break
        
        if not final_video_url:
            logger_func("   [Rule34Video] ❌ Could not find a suitable download link.")
            return None, None, None
            
        final_video_url = html.unescape(final_video_url)
        logger_func(f"   [Rule34Video] ✅ Selected direct download URL: {final_video_url}")
        
        return video_title, final_video_url, tags_list

    except Exception as e:
        logger_func(f"   [Rule34Video] ❌ An error occurred: {e}")
        return None, None, None