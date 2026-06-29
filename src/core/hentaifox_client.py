import requests
import re
from bs4 import BeautifulSoup 


BASE_URL = "https://hentaifox.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://hentaifox.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

def get_gallery_id(url_or_id):
    """Extracts numbers from URL or returns the ID string."""
    match = re.search(r"(\d+)", str(url_or_id))
    return match.group(1) if match else None

def get_gallery_metadata(gallery_id, proxies=None):
    """
    Fetches the main gallery page to get the Title, Total Pages, Tags, and Artists.
    """
    req_timeout = 30 if proxies else 15
    url = f"{BASE_URL}/gallery/{gallery_id}/"
    response = requests.get(url, headers=HEADERS, proxies=proxies, timeout=req_timeout)
    response.raise_for_status()
    html = response.text
    
    soup = BeautifulSoup(html, "html.parser")

    title_match = re.search(r'<title>(.*?)</title>', html)
    title = title_match.group(1).replace(" - HentaiFox", "").strip() if title_match else f"Gallery {gallery_id}"

    pages_match = re.search(r'Pages: (\d+)', html)
    if not pages_match:
        raise ValueError("Could not find total pages count.")
    
    total_pages = int(pages_match.group(1))
    
    tags_list = []
    tags_ul = soup.find('ul', class_='tags')
    if tags_ul:
        for a_tag in tags_ul.find_all('a', class_='tag_btn'):
            strings = list(a_tag.stripped_strings)
            if strings:
                tags_list.append(strings[0])
                
    artist_list = []
    artists_ul = soup.find('ul', class_='artists')
    if artists_ul:
        for a_tag in artists_ul.find_all('a', class_='tag_btn'):
            strings = list(a_tag.stripped_strings)
            if strings:
                artist_list.append(strings[0])
                
    artist_string = ", ".join(artist_list) if artist_list else None
    
    return {
        "id": gallery_id,
        "title": title,
        "total_pages": total_pages,
        "tags": tags_list,
        "artist": artist_string
    }

def get_image_link_for_page(gallery_id, page_num, proxies=None):
    """
    Fetches the specific reader page to find the actual image URL.
    Equivalent to the loop in the 'hentaifox' function:
    url="https://hentaifox.com/g/${id}/${i}/"
    """
    req_timeout = 30 if proxies else 15
    url = f"{BASE_URL}/g/{gallery_id}/{page_num}/"
    response = requests.get(url, headers=HEADERS, proxies=proxies, timeout=req_timeout)
    
    match = re.search(r'data-src="(https://[^"]+)"', response.text)
    
    if match:
        return match.group(1)
    return None