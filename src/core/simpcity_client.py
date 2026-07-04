try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote, parse_qs
import os
import re
from ..utils.file_utils import clean_folder_name
import urllib.parse
import base64

def fetch_single_simpcity_page(url, logger_func, cookies=None, post_id=None, check_pause_func=None, proxies=None):
    """
    Scrapes a single SimpCity page for images, external links, video tags, and iframes.
    """
    if check_pause_func and check_pause_func():
        return None, [], url, []

    headers = {
        'Referer': 'https://simpcity.cr/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = cffi_requests.get(
            url, 
            timeout=30, 
            headers=headers, 
            cookies=cookies, 
            impersonate="chrome120",
            proxies=proxies
        )

        final_url = response.url
        
        if response.status_code == 404:
            return None, [], final_url, []
            
        if response.status_code == 403:
            logger_func("   [SimpCity] ❌ 403 Forbidden. Your cf_clearance cookie is expired or invalid. Please export a fresh cookies.txt file.")
            
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        album_title = None
        service_labels = []
        title_element = soup.find('h1', class_='p-title-value')
        if title_element:
            for lbl in title_element.find_all('span', class_='label'):
                text = lbl.get_text(strip=True)
                if text: service_labels.append(text)
                lbl.decompose()
            album_title = title_element.get_text(strip=True)
            if album_title.startswith('\xa0'): 
                album_title = album_title.lstrip('\xa0')
        
        search_scope = soup
        if post_id:
            article_container = soup.find('article', id=f'js-post-{post_id}')
            if not article_container:
                article_container = soup.find('div', attrs={'data-lb-id': f'post-{post_id}'})
            if article_container:
                logger_func(f"   [SimpCity] ✅ Isolating search to post content container for ID {post_id}.")
                search_scope = article_container
            else:
                logger_func(f"   [SimpCity] ⚠️ Could not find content container for post ID {post_id}.")

        jobs_on_page = []
        extracted_posts = []

        articles = search_scope.find_all('article', class_=lambda c: c and 'message--post' in c)
        if not articles:
            articles = [search_scope]

        for article in articles:
            current_post_id = None
            lb_container = article.find('div', attrs={'data-lb-id': True}) if hasattr(article, 'find') else None
            if lb_container:
                match = re.search(r'post-(\d+)', lb_container.get('data-lb-id', ''))
                if match: current_post_id = match.group(1)
            
            if not current_post_id and hasattr(article, 'get') and article.get('id'):
                match = re.search(r'js-post-(\d+)', article.get('id', ''))
                if match: current_post_id = match.group(1)
            
            current_post_id = current_post_id or post_id or "unknown"
            
            published_date = "Unknown Date"
            if hasattr(article, 'find'):
                time_tag = article.find('time')
                if time_tag:
                    published_date = time_tag.get('data-date-string') or time_tag.get('title') or time_tag.text.strip()
                elif article.find('span', class_='u-dt'):
                    dt_span = article.find('span', class_='u-dt')
                    published_date = dt_span.get('title') or dt_span.text.strip()
            
            poster_name = "Unknown User"
            if hasattr(article, 'find'):
                name_tag = article.find('h4', class_='message-name')
                if name_tag:
                    poster_name = name_tag.get_text(strip=True)

            content_text = ""
            reply_to_post_id = None
            if hasattr(article, 'find'):
                bb_wrapper = article.find('div', class_='bbWrapper')
                if bb_wrapper:
                    bb_copy = BeautifulSoup(str(bb_wrapper), 'html.parser')
                    
                    blockquotes = bb_copy.find_all('blockquote', class_='bbCodeBlock--quote')
                    for i, bq in enumerate(blockquotes):
                        if i == 0:
                            data_source = bq.get('data-source', '')
                            if data_source.startswith('post: '):
                                reply_to_post_id = data_source.replace('post: ', '').strip()
                        bq.decompose()
                    
                    for a in bb_copy.find_all('a', href=True):
                        a_text = a.get_text(strip=True)
                        href = a['href']
                        
                        if href.startswith('/redirect/?to='):
                            parsed = urlparse(href)
                            qs = parse_qs(parsed.query)
                            if 'to' in qs:
                                try:
                                    # SimpCity base64 encodes the redirect URL
                                    decoded = base64.b64decode(qs['to'][0] + '==').decode('utf-8')
                                    href = decoded
                                except Exception:
                                    href = f"https://simpcity.cr{href}"
                        elif not href.startswith('http'):
                            href = f"https://simpcity.cr{href}"
                            
                        if href not in a_text:
                            a.string = f"\n{a_text}: {href}\n"
                            
                    for iframe in bb_copy.find_all('iframe', src=True):
                        src = iframe['src']
                        new_str = bb_copy.new_string(f"\n[Embedded Link: {src}]\n")
                        iframe.replace_with(new_str)
                        
                    for video in bb_copy.find_all('video'):
                        src_tag = video.find('source')
                        if src_tag and src_tag.get('src'):
                            src = src_tag['src']
                            new_str = bb_copy.new_string(f"\n[Video: {src}]\n")
                            video.replace_with(new_str)
                            
                    content_text = bb_copy.get_text(separator='\n', strip=True)

            post_metadata = {
                'post_id': current_post_id,
                'reply_to_post_id': reply_to_post_id,
                'published': published_date,
                'creator_name': poster_name,
                'thread_title': album_title or "Unknown Thread",
                'service': ", ".join(service_labels) if service_labels else 'Unknown',
                'content': content_text
            }
            
            extracted_posts.append(post_metadata)

            if not hasattr(article, 'find_all'): continue

            start_jobs_len = len(jobs_on_page)

            image_tags = article.find_all('img', class_='bbImage')
            for img_tag in image_tags:
                thumbnail_url = img_tag.get('src')
                if not thumbnail_url or not isinstance(thumbnail_url, str) or re.search(r'(saint2\.(su|pk|cr|to)|turbo\.cr)', thumbnail_url): continue
                full_url = thumbnail_url.replace('.md.', '.')
                filename = img_tag.get('alt', '').replace('.md.', '.') or os.path.basename(unquote(urlparse(full_url).path))
                jobs_on_page.append({'type': 'image', 'filename': filename, 'url': full_url, 'post_metadata': post_metadata})
                
            link_tags = article.find_all('a', href=True)
            for link in link_tags:
                href = link.get('href', '')
                actual_url = href
                if '/misc/goto?url=' in href:
                    try:
                        parsed_href = urlparse(href)
                        query_params = dict(urllib.parse.parse_qsl(parsed_href.query))
                        if 'url' in query_params:
                            actual_url = unquote(query_params['url'])
                    except Exception:
                        actual_url = href
                elif '/redirect/?to=' in href:
                    try:
                        parsed_href = urlparse(href)
                        qs = parse_qs(parsed_href.query)
                        if 'to' in qs:
                            actual_url = base64.b64decode(qs['to'][0] + '==').decode('utf-8')
                    except Exception:
                        pass
                
                if re.search(r'pixeldrain\.com/[lud]/', actual_url): jobs_on_page.append({'type': 'pixeldrain', 'url': actual_url, 'post_metadata': post_metadata})
                elif re.search(r'(saint2\.(su|pk|cr|to)|turbo\.cr)/(?:a|d|embed)/', actual_url): 
                    jobs_on_page.append({'type': 'saint2', 'url': actual_url, 'post_metadata': post_metadata})
                elif re.search(r'bunkr\.(?:cr|si|la|ws|is|ru|su|red|black|media|site|to|ac|ci|fi|pk|ps|sk|ph)|bunkrr\.ru', actual_url): jobs_on_page.append({'type': 'bunkr', 'url': actual_url, 'post_metadata': post_metadata})
                elif re.search(r'mega\.(nz|io)', actual_url): jobs_on_page.append({'type': 'mega', 'url': actual_url, 'post_metadata': post_metadata})

            video_tags = article.find_all('video')
            for video in video_tags:
                source_tag = video.find('source')
                if source_tag and source_tag.get('src'):
                    src_url = source_tag['src']
                    if re.search(r'(saint2\.(su|pk|cr|to)|turbo\.cr)', src_url):
                        jobs_on_page.append({'type': 'saint2_direct', 'url': src_url, 'post_metadata': post_metadata})
            
            iframe_tags = article.find_all('iframe')
            for iframe in iframe_tags:
                src_url = iframe.get('src')
                if src_url and isinstance(src_url, str):
                    if re.search(r'(saint2\.(su|pk|cr|to)|turbo\.cr)/(?:a|d|embed)/', src_url):
                        jobs_on_page.append({'type': 'saint2', 'url': src_url, 'post_metadata': post_metadata})

            for i in range(start_jobs_len, len(jobs_on_page)):
                job = jobs_on_page[i]
                new_meta = dict(job['post_metadata'])
                new_meta['file_index'] = i - start_jobs_len + 1
                job['post_metadata'] = new_meta

        if jobs_on_page or extracted_posts:
            unique_jobs = list({job['url']: job for job in jobs_on_page}.values())
            logger_func(f"   [SimpCity] Scraper found jobs: {[job['type'] for job in unique_jobs]}")
            return album_title, unique_jobs, final_url, extracted_posts

        return album_title, [], final_url, extracted_posts

    except Exception as e:
        logger_func(f"   [SimpCity] ❌ Error fetching page {url}: {e}")
        raise e