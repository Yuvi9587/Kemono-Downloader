import re
import requests
from urllib.parse import urlparse

from ...utils.network_utils import prepare_cookies_for_request
from ...utils.file_utils import clean_folder_name 

from .allcomic_downloader_thread import AllcomicDownloadThread
from .booru_downloader_thread import BooruDownloadThread
from .bunkr_downloader_thread import BunkrDownloadThread
from .discord_downloader_thread import DiscordDownloadThread
from .drive_downloader_thread import DriveDownloadThread
from .erome_downloader_thread import EromeDownloadThread
from .external_link_downloader_thread import ExternalLinkDownloadThread
from .fap_nation_downloader_thread import FapNationDownloadThread
from .hentai2read_downloader_thread import Hentai2readDownloadThread
from .kemono_discord_downloader_thread import KemonoDiscordDownloadThread
from .mangadex_downloader_thread import MangaDexDownloadThread
from .nhentai_downloader_thread import NhentaiDownloadThread
from .pixeldrain_downloader_thread import PixeldrainDownloadThread
from .rule34video_downloader_thread import Rule34VideoDownloadThread
from .saint2_downloader_thread import Saint2DownloadThread
from .simp_city_downloader_thread import SimpCityDownloadThread
from .toonily_downloader_thread import ToonilyDownloadThread
from .deviantart_downloader_thread import DeviantArtDownloadThread
from .hentaifox_downloader_thread import HentaiFoxDownloadThread
from .rule34_downloader_thread import Rule34DownloadThread
from .hotleaks_thread import HotleaksThread  
from .coomerfans_thread import CoomerfansThread
from .cumst_downloader_thread import CumStDownloadThread

def create_downloader_thread(main_app, api_url, service, id1, id2, effective_output_dir_for_run, export_all_links_mode=False):
    """
    Factory function to create and configure the correct QThread for a given URL.
    Returns a configured QThread instance, a specific error string ("COOKIE_ERROR", "FETCH_ERROR"),
    or None if no special handler is found (indicating fallback to generic BackendDownloadThread).
    """


    if service in ['danbooru', 'gelbooru']:
        api_key, user_id = main_app.get_booru_credentials()
        return BooruDownloadThread(
            url=api_url, output_dir=effective_output_dir_for_run,
            api_key=api_key, user_id=user_id, parent=main_app
        )

    platform = None
    if 'mega.nz' in api_url or 'mega.io' in api_url: platform = 'mega'
    elif 'drive.google.com' in api_url: platform = 'gdrive'
    elif 'dropbox.com' in api_url: platform = 'dropbox'
    elif 'gofile.io' in api_url: platform = 'gofile'
    if platform:
        use_post_subfolder = main_app.use_subfolder_per_post_checkbox.isChecked()
        return DriveDownloadThread(
            api_url, effective_output_dir_for_run, platform, use_post_subfolder,
            main_app.cancellation_event, main_app.pause_event, main_app.log_signal.emit,
            parent=main_app
        )

    if 'erome.com' in api_url:
        return EromeDownloadThread(api_url, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    if service == 'rule34':
        main_app.log_signal.emit("ℹ️ Rule34 URL detected. Starting dedicated downloader.")
        
        api_key, user_id = main_app.get_booru_credentials()
        
        return Rule34DownloadThread(api_url, effective_output_dir_for_run, api_key, user_id, main_app, export_all_links_mode=export_all_links_mode)
    if 'mangadex.org' in api_url:
        return MangaDexDownloadThread(api_url, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    is_saint2_url = service == 'saint2' or 'saint2.su' in api_url or 'saint2.pk' in api_url
    if is_saint2_url and api_url.strip().lower() != 'saint2.su':
        return Saint2DownloadThread(api_url, effective_output_dir_for_run, main_app)

    if service == 'simpcity':
        cookies = prepare_cookies_for_request(
            use_cookie_flag=True,
            cookie_text_input=main_app.cookie_text_input.text(),
            selected_cookie_file_path=main_app.selected_cookie_filepath,
            app_base_dir=main_app.app_base_dir,
            logger_func=main_app.log_signal.emit,
            target_domain='simpcity.cr'
        )
        if not cookies:
            main_app.log_signal.emit("❌ SimpCity requires valid cookies. Please provide them.")
            return "COOKIE_ERROR"
        return SimpCityDownloadThread(api_url, id2, effective_output_dir_for_run, cookies, main_app)

    if service == 'rule34video':
        main_app.log_signal.emit("ℹ️ Rule34Video.com URL detected. Starting dedicated downloader.")
        return Rule34VideoDownloadThread(api_url, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    elif service == 'discord' and any(domain in api_url for domain in ['kemono.cr', 'kemono.su', 'kemono.party', 'pawchive.st', 'pawchive.pw']):
        main_app.log_signal.emit("ℹ️ Kemono Discord URL detected. Starting dedicated downloader.")
        cookies = prepare_cookies_for_request(
            use_cookie_flag=main_app.use_cookie_checkbox.isChecked(),
            cookie_text_input=main_app.cookie_text_input.text(),
            selected_cookie_file_path=main_app.selected_cookie_filepath,
            app_base_dir=main_app.app_base_dir,
            logger_func=main_app.log_signal.emit,
            target_domain='kemono.cr'
        )
        return KemonoDiscordDownloadThread(
            server_id=id1,
            channel_id=id2,
            output_dir=effective_output_dir_for_run,
            cookies_dict=cookies,
            parent=main_app
        )

    elif service == 'discord' and 'discord.com' in api_url:
        main_app.log_signal.emit("ℹ️ Official Discord URL detected. Starting dedicated downloader.")
        token = main_app.remove_from_filename_input.text().strip()
        if not token:
             main_app.log_signal.emit("❌ Official Discord requires an Authorization Token in the 'Remove Words' field.")
             return None

        limit_text = main_app.discord_message_limit_input.text().strip()
        message_limit = int(limit_text) if limit_text.isdigit() else None
        mode = main_app.discord_download_scope

        return DiscordDownloadThread(
            mode=mode,
            session=requests.Session(),
            token=token,
            output_dir=effective_output_dir_for_run,
            server_id=id1,
            channel_id=id2,
            url=api_url,
            app_base_dir=main_app.app_base_dir,
            limit=message_limit,
            parent=main_app
        )

    if service == 'allcomic' or 'allcomic.com' in api_url or 'allporncomic.com' in api_url:
        return AllcomicDownloadThread(api_url, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    if service == 'hentai2read' or 'hentai2read.com' in api_url:
        return Hentai2readDownloadThread(api_url, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    if service == 'fap-nation' or 'fap-nation.com' in api_url or 'fap-nation.org' in api_url:
        use_post_subfolder = main_app.use_subfolder_per_post_checkbox.isChecked()
        return FapNationDownloadThread(
            api_url, effective_output_dir_for_run, use_post_subfolder,
            main_app.pause_event, main_app.cancellation_event, main_app.actual_gui_signals, main_app,
            export_all_links_mode=export_all_links_mode
        )

    if service == 'coomerfans' or 'coomerfans.com' in api_url:
        main_app.log_signal.emit("🔎 Coomerfans URL detected. Starting dedicated scraper.")
        return CoomerfansThread(
            url=api_url, 
            save_directory=effective_output_dir_for_run,
            main_app=main_app
        )

    if service == 'pixeldrain' or 'pixeldrain.com' in api_url:
        return PixeldrainDownloadThread(api_url, effective_output_dir_for_run, main_app)

    if service == 'nhentai':
        from ...core.nhentai_client import fetch_nhentai_gallery
        main_app.log_signal.emit(f"ℹ️ nHentai gallery ID {id1} detected. Fetching gallery data...")
        gallery_data = fetch_nhentai_gallery(id1, main_app.log_signal.emit)
        if not gallery_data:
            main_app.log_signal.emit(f"❌ Failed to fetch nHentai gallery data for ID {id1}.")
            return "FETCH_ERROR"
        return NhentaiDownloadThread(gallery_data, effective_output_dir_for_run, main_app, export_all_links_mode=export_all_links_mode)

    if service == 'toonily' or 'toonily.com' in api_url:
        return ToonilyDownloadThread(api_url, effective_output_dir_for_run, main_app)

    if service == 'bunkr':
        return BunkrDownloadThread(id1, effective_output_dir_for_run, main_app)

    if service == 'deviantart':
        main_app.log_signal.emit(f"ℹ️ DeviantArt URL detected. Starting dedicated downloader.")
        return DeviantArtDownloadThread(
            url=api_url,
            output_dir=effective_output_dir_for_run,
            pause_event=main_app.pause_event,
            cancellation_event=main_app.cancellation_event,
            parent=main_app,
            export_all_links_mode=export_all_links_mode
        )

    if 'hentaifox.com' in api_url or service == 'hentaifox':
        main_app.log_signal.emit("🦊 HentaiFox URL detected.")
        return HentaiFoxDownloadThread(
            url_or_id=api_url,
            output_dir=effective_output_dir_for_run,
            parent=main_app,
            export_all_links_mode=export_all_links_mode
        )    
    
    if service == 'hotleaks' or 'hotleaks.tv' in api_url or 'hotleaks.vip' in api_url:
        main_app.log_signal.emit("🔥 Hotleaks URL detected. Starting dedicated downloader.")
        return HotleaksThread(
            url=api_url, 
            save_directory=effective_output_dir_for_run,
            main_app=main_app,
            export_all_links_mode=export_all_links_mode
        )

    if 'cum.st' in api_url:
        main_app.log_signal.emit("🔞 cum.st URL detected. Starting dedicated downloader.")
        return CumStDownloadThread(
            url=api_url,
            save_directory=effective_output_dir_for_run,
            main_app=main_app,
            export_all_links_mode=export_all_links_mode
        )
        
    main_app.log_signal.emit(f"ℹ️ No specialized downloader found for service '{service}' and URL '{api_url[:50]}...'. Using generic downloader.")
    return None