import html
import re

import cloudscraper
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object 
from ...utils.network_utils import prepare_cookies_for_request
from .CookieHelpDialog import CookieHelpDialog
from ...utils.resolution import get_dark_theme

class FavoriteArtistsDialog (QDialog ):
    """Dialog to display and select favorite artists."""
    def __init__ (self ,parent_app ,cookies_config ):
        super ().__init__ (parent_app )
        self .parent_app =parent_app 
        self .cookies_config =cookies_config 
        self .all_fetched_artists =[]

        app_icon =get_app_icon_object ()
        if not app_icon .isNull ():
            self .setWindowIcon (app_icon )
        self .selected_artist_urls =[]

        self .setModal (True )
        self .setMinimumSize (500 ,500 )

        self ._init_ui ()
        self ._fetch_favorite_artists ()

    def _get_domain_for_service(self, service_name, source_api=None):
        if source_api and "pawchive" in source_api.lower():
            return "pawchive.pw"
        service_lower = service_name.lower()
        coomer_primary_services = {'onlyfans', 'fansly', 'manyvids', 'candfans'}
        if service_lower in coomer_primary_services:
            return "coomer.st"
        else:
            return "kemono.cr"

    def _tr (self ,key ,default_text =""):
        """Helper to get translation based on current app language."""
        if callable (get_translation )and self .parent_app :
            return get_translation (self .parent_app .current_selected_language ,key ,default_text )
        return default_text 

    def _retranslate_ui (self ):
        self .setWindowTitle (self ._tr ("fav_artists_dialog_title","Favorite Artists"))
        self .status_label .setText (self ._tr ("fav_artists_loading_status","Loading favorite artists..."))
        self .search_input .setPlaceholderText (self ._tr ("fav_artists_search_placeholder","Search artists..."))
        self .select_all_button .setText (self ._tr ("fav_artists_select_all_button","Select All"))
        self .deselect_all_button .setText (self ._tr ("fav_artists_deselect_all_button","Deselect All"))
        self .download_button .setText (self ._tr ("fav_artists_download_selected_button","Download Selected"))
        self .cancel_button .setText (self ._tr ("fav_artists_cancel_button","Cancel"))

    def _init_ui (self ):
        main_layout =QVBoxLayout (self )

        self .status_label =QLabel ()
        self .status_label .setAlignment (Qt .AlignCenter )
        main_layout .addWidget (self .status_label )

        self .search_input =QLineEdit ()
        self .search_input .textChanged .connect (self ._filter_artist_list_display )
        main_layout .addWidget (self .search_input )


        self .artist_list_widget =QListWidget ()
        self .artist_list_widget .setStyleSheet ("""
            QListWidget::item {
                border-bottom: 1px solid #4A4A4A; /* Slightly softer line */
                padding-top: 4px;
                padding-bottom: 4px;
            }""")
        main_layout .addWidget (self .artist_list_widget )
        self .artist_list_widget .setAlternatingRowColors (True )
        self .search_input .setVisible (False )
        self .artist_list_widget .setVisible (False )

        combined_buttons_layout =QHBoxLayout ()

        self .select_all_button =QPushButton ()
        self .select_all_button .clicked .connect (self ._select_all_items )
        combined_buttons_layout .addWidget (self .select_all_button )

        self .deselect_all_button =QPushButton ()
        self .deselect_all_button .clicked .connect (self ._deselect_all_items )
        combined_buttons_layout .addWidget (self .deselect_all_button )


        self .download_button =QPushButton ()
        self .download_button .clicked .connect (self ._accept_selection_action )
        self .download_button .setEnabled (False )
        self .download_button .setDefault (True )
        combined_buttons_layout .addWidget (self .download_button )

        self .cancel_button =QPushButton ()
        self .cancel_button .clicked .connect (self .reject )
        combined_buttons_layout .addWidget (self .cancel_button )

        combined_buttons_layout .addStretch (1 )
        main_layout .addLayout (combined_buttons_layout )

        self ._retranslate_ui ()
        if hasattr (self .parent_app ,'get_dark_theme')and self .parent_app .current_theme =="dark":
            self .setStyleSheet (self .parent_app .get_dark_theme ())


    def _logger (self ,message ):
        """Helper to log messages, either to parent app or console."""
        if hasattr (self .parent_app ,'log_signal')and self .parent_app .log_signal :
            self .parent_app .log_signal .emit (f"[FavArtistsDialog] {message }")
        else :
            print (f"[FavArtistsDialog] {message }")

    def _show_content_elements (self ,show ):
        """Helper to show/hide content-related widgets."""
        self .search_input .setVisible (show )
        self .artist_list_widget .setVisible (show )

    def _fetch_favorite_artists (self ):
        scraper = cloudscraper.create_scraper()

        if self.cookies_config['use_cookie']:
            kemono_cookies = prepare_cookies_for_request(
                True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                self.cookies_config['app_base_dir'], self._logger, target_domain="kemono.cr"
            )
            if not kemono_cookies:
                self._logger("No cookies for kemono.cr, trying fallback kemono.su...")
                kemono_cookies = prepare_cookies_for_request(
                    True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                    self.cookies_config['app_base_dir'], self._logger, target_domain="kemono.su"
                )

            coomer_cookies = prepare_cookies_for_request(
                True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                self.cookies_config['app_base_dir'], self._logger, target_domain="coomer.st"
            )
            if not coomer_cookies:
                self._logger("No cookies for coomer.st, trying fallback coomer.su...")
                coomer_cookies = prepare_cookies_for_request(
                    True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                    self.cookies_config['app_base_dir'], self._logger, target_domain="coomer.su"
                )

            pawchive_cookies = prepare_cookies_for_request(
                True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                self.cookies_config['app_base_dir'], self._logger, target_domain="pawchive.pw"
            )
            if not pawchive_cookies:
                self._logger("No cookies for pawchive.pw, trying fallback pawchive.st...")
                pawchive_cookies = prepare_cookies_for_request(
                    True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                    self.cookies_config['app_base_dir'], self._logger, target_domain="pawchive.st"
                )

            if not kemono_cookies and not coomer_cookies and not pawchive_cookies:
                self.status_label.setText(self._tr("fav_artists_cookies_required_status", "Error: Cookies enabled but could not be loaded for any source."))
                self._logger("Error: Cookies enabled but no valid cookies were loaded. Showing help dialog.")
                cookie_help_dialog = CookieHelpDialog(self.parent_app, self)
                cookie_help_dialog.exec()
                self.download_button.setEnabled(False)
                return

        self .all_fetched_artists =[]
        fetched_any_successfully =False 
        errors_occurred =[]
        any_cookies_loaded_successfully_for_any_source =False 

        api_sources = [
            {"name": "Kemono.cr", "url": "https://kemono.cr/api/v1/account/favorites?type=artist", "domain": "kemono.cr"},
            {"name": "Coomer.st", "url": "https://coomer.st/api/v1/account/favorites?type=artist", "domain": "coomer.st"},
            {"name": "Pawchive", "url": "https://pawchive.pw/api/v1/account/favorites?type=artist", "domain": "pawchive.pw"}
        ]

        for source in api_sources :
            self ._logger (f"Attempting to fetch favorite artists from: {source ['name']} ({source ['url']})")
            self .status_label .setText (self ._tr ("fav_artists_loading_from_source_status","⏳ Loading favorites from {source_name}...").format (source_name =source ['name']))
            QCoreApplication .processEvents ()

            cookies_dict_for_source = None
            if self.cookies_config['use_cookie']:
                primary_domain = source['domain']
                if "kemono" in primary_domain:
                    fallback_domain = "kemono.su"
                elif "coomer" in primary_domain:
                    fallback_domain = "coomer.su"
                elif "pawchive" in primary_domain:
                    fallback_domain = "pawchive.st"
                else:
                    fallback_domain = None

                cookies_dict_for_source = prepare_cookies_for_request(
                    True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                    self.cookies_config['app_base_dir'], self._logger, target_domain=primary_domain
                )
                if not cookies_dict_for_source:
                    self._logger(f"Warning ({source['name']}): No cookies for '{primary_domain}'. Trying fallback '{fallback_domain}'...")
                    cookies_dict_for_source = prepare_cookies_for_request(
                        True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                        self.cookies_config['app_base_dir'], self._logger, target_domain=fallback_domain
                    )
                
                if cookies_dict_for_source:
                    any_cookies_loaded_successfully_for_any_source = True
                else:
                    self._logger(f"Warning ({source['name']}): Cookies enabled but not loaded for this source. Fetch may fail.")
            try :
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': f"https://{source['domain']}/favorites",
                    'Accept': 'text/css'
                }
                
                response = scraper.get(source['url'], headers=headers, cookies=cookies_dict_for_source, timeout=20)

                response .raise_for_status ()
                artists_data_from_api =response .json ()

                if not isinstance (artists_data_from_api ,list ):
                    error_msg =f"Error ({source ['name']}): API did not return a list of artists (got {type (artists_data_from_api )})."
                    self ._logger (error_msg )
                    errors_occurred .append (error_msg )
                    continue 

                processed_artists_from_source =0 
                for artist_entry in artists_data_from_api :
                    artist_id =artist_entry .get ("id")
                    artist_name =html .unescape (artist_entry .get ("name","Unknown Artist").strip ())
                    artist_service_platform =artist_entry .get ("service")

                    if artist_id and artist_name and artist_service_platform :
                        artist_page_domain =self ._get_domain_for_service (artist_service_platform, source['name'])
                        full_url =f"https://{artist_page_domain }/{artist_service_platform }/user/{artist_id }"

                        self .all_fetched_artists .append ({
                        'name':artist_name ,
                        'url':full_url ,
                        'service':artist_service_platform ,
                        'id':artist_id ,
                        '_source_api':source ['name']
                        })
                        processed_artists_from_source +=1 
                    else :
                        self ._logger (f"Warning ({source ['name']}): Skipping favorite artist entry due to missing data: {artist_entry }")

                if processed_artists_from_source >0 :
                    fetched_any_successfully =True 
                self ._logger (f"Fetched {processed_artists_from_source } artists from {source ['name']}.")

            except Exception as e :
                error_msg =f"Error fetching favorites from {source ['name']}: {e }"
                self ._logger (error_msg )
                errors_occurred .append (error_msg )

        if self .cookies_config ['use_cookie']and not any_cookies_loaded_successfully_for_any_source :
            self .status_label .setText (self ._tr ("fav_artists_cookies_required_status","Error: Cookies enabled but could not be loaded for any source."))
            self ._logger ("Error: Cookies enabled but no cookies loaded for any source. Showing help dialog.")
            cookie_help_dialog = CookieHelpDialog(self.parent_app, self)
            cookie_help_dialog .exec_ ()
            self .download_button .setEnabled (False )
            if not fetched_any_successfully :
                 errors_occurred .append ("Cookies enabled but could not be loaded for any API source.")

        unique_artists_map ={}
        for artist in self .all_fetched_artists :
            key =(artist ['service'].lower (),str (artist ['id']).lower ())
            if key not in unique_artists_map :
                unique_artists_map [key ]=artist 
        self .all_fetched_artists =list (unique_artists_map .values ())

        self .all_fetched_artists .sort (key =lambda x :x ['name'].lower ())
        self ._populate_artist_list_widget ()

        if fetched_any_successfully and self .all_fetched_artists :
            self .status_label .setText (self ._tr ("fav_artists_found_status","Found {count} total favorite artist(s).").format (count =len (self .all_fetched_artists )))
            self ._show_content_elements (True )
            self .download_button .setEnabled (True )
        elif not fetched_any_successfully and not errors_occurred :
             self .status_label .setText (self ._tr ("fav_artists_none_found_status","No favorite artists found on Kemono or Coomer."))
             self ._show_content_elements (False )
             self .download_button .setEnabled (False )
        else :
            final_error_message =self ._tr ("fav_artists_failed_status","Failed to fetch favorites.")
            if errors_occurred :
                final_error_message +=" Errors: "+"; ".join (errors_occurred )
            self .status_label .setText (final_error_message )
            self ._show_content_elements (False )
            self .download_button .setEnabled (False )
            if fetched_any_successfully and not self .all_fetched_artists :
                 self .status_label .setText (self ._tr ("fav_artists_no_favorites_after_processing","No favorite artists found after processing."))

    def _populate_artist_list_widget (self ,artists_to_display =None ):
        self .artist_list_widget .clear ()
        source_list =artists_to_display if artists_to_display is not None else self .all_fetched_artists 
        for artist_data in source_list :
            item =QListWidgetItem (f"{artist_data ['name']} ({artist_data .get ('service','N/A').capitalize ()})")
            item .setFlags (item .flags ()|Qt .ItemIsUserCheckable )
            item .setCheckState (Qt .Unchecked )
            item .setData (Qt .UserRole ,artist_data )
            self .artist_list_widget .addItem (item )

    def _filter_artist_list_display (self ):
        search_text =self .search_input .text ().lower ().strip ()
        if not search_text :
            self ._populate_artist_list_widget ()
            return 

        filtered_artists =[
        artist for artist in self .all_fetched_artists 
        if search_text in artist ['name'].lower ()or search_text in artist ['url'].lower ()
        ]
        self ._populate_artist_list_widget (filtered_artists )

    def _select_all_items (self ):
        for i in range (self .artist_list_widget .count ()):
            self .artist_list_widget .item (i ).setCheckState (Qt .Checked )

    def _deselect_all_items (self ):
        for i in range (self .artist_list_widget .count ()):
            self .artist_list_widget .item (i ).setCheckState (Qt .Unchecked )

    def _accept_selection_action (self ):
        self .selected_artists_data =[]
        for i in range (self .artist_list_widget .count ()):
            item =self .artist_list_widget .item (i )
            if item .checkState ()==Qt .Checked :
                self .selected_artists_data .append (item .data (Qt .UserRole ))

        if not self .selected_artists_data :
            QMessageBox .information (self ,"No Selection","Please select at least one artist to download.")
            return 
        self .accept ()

    def get_selected_artists (self ):
        return self .selected_artists_data
