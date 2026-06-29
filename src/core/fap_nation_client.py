import re
import os
import cloudscraper
from urllib.parse import urlparse, urljoin
from ..utils.file_utils import clean_folder_name

def fetch_fap_nation_data(album_url, logger_func, proxies=None):
    """
    Scrapes a fap-nation page by prioritizing HLS streams first, then falling
    back to direct download links. Selects the highest quality available.
    """
    logger_func(f"   [Fap-Nation] Fetching album data from: {album_url}")
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    
    try:
        response = scraper.get(album_url, timeout=45)
        response.raise_for_status()
        html_content = response.text
        
        title_match = re.search(r'<h1[^>]*itemprop="name"[^>]*>(.*?)</h1>', html_content, re.IGNORECASE)
        album_slug = clean_folder_name(os.path.basename(urlparse(album_url).path.strip('/')))
        album_title = clean_folder_name(title_match.group(1).strip()) if title_match else album_slug

        files_to_download = []
        final_url = None
        link_type = None
        filename_from_video_tag = None

        video_tag_title_match = re.search(r'data-plyr-config=.*?&quot;title&quot;:.*?&quot;([^&]+?\.mp4)&quot;', html_content, re.IGNORECASE)
        if video_tag_title_match:
            filename_from_video_tag = clean_folder_name(video_tag_title_match.group(1))
            logger_func(f"   [Fap-Nation] Found high-quality filename in video tag: {filename_from_video_tag}")


        logger_func("   [Fap-Nation] Priority 1: Searching for HLS stream...")
        iframe_match = re.search(r'<iframe[^>]+src="([^"]+mediadelivery\.net[^"]+)"', html_content, re.IGNORECASE)
        
        if iframe_match:
            iframe_url = iframe_match.group(1)
            logger_func(f"   [Fap-Nation] Found video iframe. Visiting: {iframe_url}")
            try:
                iframe_response = scraper.get(iframe_url, timeout=30)
                iframe_response.raise_for_status()
                iframe_html = iframe_response.text
                
                playlist_match = re.search(r'<source[^>]+src="([^"]+\.m3u8)"', iframe_html, re.IGNORECASE)
                if playlist_match:
                    final_url = playlist_match.group(1)
                    link_type = 'hls'
                    logger_func(f"   [Fap-Nation] Found embedded HLS stream in iframe: {final_url}")
            except Exception as e:
                logger_func(f"   [Fap-Nation] ⚠️ Error fetching or parsing iframe content: {e}")
        
        if not final_url:
            logger_func("   [Fap-Nation] No stream found in iframe. Checking main page content as a last resort...")
            js_var_match = re.search(r'"(https?://[^"]+\.m3u8)"', html_content, re.IGNORECASE)
            if js_var_match:
                final_url = js_var_match.group(1)
                link_type = 'hls'
                logger_func(f"   [Fap-Nation] Found HLS stream on main page: {final_url}")

        if not final_url:
            logger_func("   [Fap-Nation] No HLS stream found. Priority 2 (Fallback): Searching for direct download links...")
            direct_link_pattern = r'<a\s+[^>]*href="([^"]+\.(?:mp4|webm|mkv|mov))"[^>]*>'
            direct_links_found = re.findall(direct_link_pattern, html_content, re.IGNORECASE)

            if direct_links_found:
                logger_func(f"   [Fap-Nation] Found {len(direct_links_found)} direct media link(s). Selecting the best quality...")
                best_link = None
                qualities_to_check = ['1080p', '720p', '480p', '360p']
                
                for quality in qualities_to_check:
                    for link in direct_links_found:
                        if quality in link.lower():
                            best_link = link
                            logger_func(f"   [Fap-Nation] Found '{quality}' link: {best_link}")
                            break
                    if best_link:
                        break

                if not best_link:
                    best_link = direct_links_found[0]
                    logger_func(f"   [Fap-Nation] ⚠️ No quality tags (1080p, 720p, etc.) found in links. Defaulting to first link: {best_link}")

                final_url = best_link
                link_type = 'direct'
                logger_func(f"   [Fap-Nation] Identified direct media link: {final_url}")
        if not final_url:
            logger_func("   [Fap-Nation] ❌ Stage 1 Failed: Could not find any HLS stream or direct link.")
            return None, []

        if link_type == 'hls' and final_url:
            logger_func("   [Fap-Nation] HLS stream found. Checking for higher quality variants...")
            try:
                master_playlist_response = scraper.get(final_url, timeout=20)
                master_playlist_response.raise_for_status()
                playlist_content = master_playlist_response.text

                streams = re.findall(r'#EXT-X-STREAM-INF:.*?RESOLUTION=(\d+)x(\d+).*?\n(.*?)\s', playlist_content)
                
                if streams:
                    best_stream = max(streams, key=lambda s: int(s[0]) * int(s[1]))
                    height = best_stream[1]
                    relative_path = best_stream[2]
                    new_final_url = urljoin(final_url, relative_path)
                    
                    logger_func(f"   [Fap-Nation] ✅ Best quality found: {height}p. Updating URL to: {new_final_url}")
                    final_url = new_final_url
                else:
                    logger_func("   [Fap-Nation] ℹ️ No alternate quality streams found in playlist. Using original.")
            except Exception as e:
                logger_func(f"   [Fap-Nation] ⚠️ Could not parse HLS master playlist for quality selection: {e}. Using original URL.")

        if final_url and link_type:
            if filename_from_video_tag:
                base_name, _ = os.path.splitext(filename_from_video_tag)
                new_filename = f"{base_name}.mp4"
            else:
                new_filename = f"{album_slug}.mp4"
            
            files_to_download.append({'url': final_url, 'filename': new_filename, 'type': link_type})
            logger_func(f"   [Fap-Nation] ✅ Ready to download '{new_filename}' ({link_type} method).")
            return album_title, files_to_download
        
        logger_func(f"   [Fap-Nation] ❌ Could not determine a valid download link.")
        return None, []
        
    except Exception as e:
        logger_func(f"   [Fap-Nation] ❌ Error fetching Fap-Nation data: {e}")
        return None, []