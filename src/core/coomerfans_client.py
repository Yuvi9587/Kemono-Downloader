import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

class CoomerfansClient:
    def __init__(self, proxies=None):
        self.base_url = "https://coomerfans.com"
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }

    def get_posts_from_page(self, page_url):
        """Scrapes the <div class='post'> elements to find all post info."""
        try:
            response = self.session.get(page_url, headers=self.headers, timeout=15)
            if response.status_code != 200:
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            post_items = []
            
            posts = soup.find_all('div', class_='post')
            for post in posts:
                a_tag = post.find('a', class_='view-post')
                if a_tag and 'href' in a_tag.attrs:
                    href = a_tag['href']
                    full_link = urljoin(self.base_url, href)
                    
                    parts = href.split('/')
                    post_id = parts[2] if len(parts) > 2 else ""
                    
                    title = ""
                    h3 = post.find('h3')
                    if h3 and h3.find('a'):
                        title = h3.find('a').text.strip()
                        
                    post_items.append({
                        'url': full_link,
                        'id': post_id,
                        'title': title
                    })
                    
            return post_items
        except Exception:
            return []

    def get_media_from_post(self, post_url):
        """Scrapes the post page to find high-res images and direct mp4 links. Returns (media_urls, title, date)."""
        media_urls = []
        page_title = ""
        post_date = ""
        try:
            response = self.session.get(post_url, headers=self.headers, timeout=15)
            if response.status_code != 200:
                return media_urls, page_title, post_date
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract title and date from post-wrap
            post_wrap = soup.find('div', class_='post-wrap')
            if post_wrap:
                h1 = post_wrap.find('h1')
                if h1 and h1.text:
                    page_title = h1.text.strip()
                    
                date_span = post_wrap.find('span', class_='post-date')
                if date_span and date_span.text:
                    raw_date = date_span.text.replace('Added', '').strip()
                    post_date = raw_date.split(' ')[0]
            
            if not page_title and soup.title and soup.title.string:
                page_title = soup.title.string.split('-')[0].strip()
            
            post_body = soup.find('div', class_='post-body')
            if post_body:
                images = post_body.find_all('img')
                for img in images:
                    if 'src' in img.attrs:
                        media_urls.append(img['src'])
                        
            players = soup.find_all('div', class_='player')
            for player in players:
                source = player.find('source')
                if source and 'src' in source.attrs:
                    media_urls.append(source['src'])
                    
            return media_urls, page_title, post_date
        except Exception:
            return media_urls, page_title, post_date