import time
import cloudscraper
import json

def fetch_server_channels(server_id, logger=print, cookies_dict=None, proxies=None):
    """
    Fetches all channels for a given Discord server ID from the API.
    Uses cloudscraper to bypass Cloudflare.
    """
    api_url = f"https://kemono.cr/api/v1/discord/server/{server_id}"
    logger(f"   Fetching channels for server: {api_url}")

    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': f'https://kemono.cr/discord/server/{server_id}',
        'Accept': 'text/css'
    }

    try:
        response = scraper.get(api_url, headers=headers, cookies=cookies_dict, timeout=30)
        response.raise_for_status()
        channels = response.json()
        if isinstance(channels, list):
            logger(f"   ✅ Found {len(channels)} channels for server {server_id}.")
            return channels
        return None
    except Exception as e:
        logger(f"   ❌ Error fetching server channels for {server_id}: {e}")
        return None

def fetch_channel_messages(channel_id, logger=print, cancellation_event=None, pause_event=None, cookies_dict=None, proxies=None):
    """
    A generator that fetches all messages for a specific Discord channel, handling pagination.
    Uses cloudscraper and proper headers to bypass server protection.
    """
    scraper = cloudscraper.create_scraper()
    if proxies:
        scraper.proxies.update(proxies)
    base_url = f"https://kemono.cr/api/v1/discord/channel/{channel_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': f'https://kemono.cr/discord/channel/{channel_id}',
        'Accept': 'text/css'
    }
    
    offset = 0
    page_size = 150 

    while True:
        if cancellation_event and cancellation_event.is_set():
            logger("   Discord message fetching cancelled.")
            break
        if pause_event and pause_event.is_set():
            logger("   Discord message fetching paused...")
            while pause_event.is_set():
                if cancellation_event and cancellation_event.is_set():
                    break
                time.sleep(0.5)
            if not (cancellation_event and cancellation_event.is_set()):
                logger("   Discord message fetching resumed.")

        paginated_url = f"{base_url}?o={offset}"
        logger(f"   Fetching messages from API: page starting at offset {offset}")

        try:
            response = scraper.get(paginated_url, headers=headers, cookies=cookies_dict, timeout=30)
            response.raise_for_status()
            messages_batch = response.json()

            if not messages_batch:
                logger(f"   ✅ Reached end of messages for channel {channel_id}.")
                break
            
            logger(f"   Fetched {len(messages_batch)} messages...")
            yield messages_batch

            if len(messages_batch) < page_size:
                logger(f"   ✅ Last page of messages received for channel {channel_id}.")
                break

            offset += page_size
            time.sleep(0.5)

        except (cloudscraper.exceptions.CloudflareException, json.JSONDecodeError) as e:
            logger(f"   ❌ Error fetching messages at offset {offset}: {e}")
            break
        except Exception as e:
            logger(f"   ❌ An unexpected error occurred while fetching messages: {e}")
            break
