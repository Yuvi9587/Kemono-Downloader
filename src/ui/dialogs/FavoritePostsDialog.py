import html
import os
import sys
import threading
import time
import traceback
import json
import re
from collections import defaultdict
import cloudscraper
from PySide6.QtCore import QCoreApplication, Qt, Signal, QThread
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QProgressBar,
    QWidget, QCheckBox
)
from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.network_utils import prepare_cookies_for_request
from .CookieHelpDialog import CookieHelpDialog
from ...core.api_client import download_from_api
from ...utils.resolution import get_dark_theme

class FavoritePostsFetcherThread (QThread ):
    """Worker thread to fetch favorite posts and creator names."""
    status_update =Signal (str )
    progress_bar_update =Signal (int ,int )
    finished =Signal (list ,str )

    def __init__ (self ,cookies_config ,parent_logger_func ,target_domain_preference =None ):
        super ().__init__ ()
        self .cookies_config =cookies_config 
        self .parent_logger_func =parent_logger_func 
        self .target_domain_preference =target_domain_preference 
        self .cancellation_event =threading .Event ()
        self .error_key_map ={
        "kemono.cr":"kemono_su",
        "coomer.st":"coomer_su"
        }

    def _logger (self ,message ):
        self .parent_logger_func (f"[FavPostsFetcherThread] {message }")

    def run(self):
        scraper = cloudscraper.create_scraper()

        all_fetched_posts_temp = []
        error_messages_for_summary = []
        fetched_any_successfully = False
        any_cookies_loaded_successfully_for_any_source = False

        self.status_update.emit("key_fetching_fav_post_list_init")
        self.progress_bar_update.emit(0, 0)

        api_sources = [
            {"name": "Kemono.cr", "url": "https://kemono.cr/api/v1/account/favorites?type=post", "domain": "kemono.cr"},
            {"name": "Coomer.st", "url": "https://coomer.st/api/v1/account/favorites?type=post", "domain": "coomer.st"},
            {"name": "Pawchive", "url": "https://pawchive.pw/api/v1/account/favorites?type=post", "domain": "pawchive.pw"}
        ]

        api_sources_to_try =[]
        if self .target_domain_preference :
            self ._logger (f"Targeting specific domain for favorites: {self .target_domain_preference }")
            for source_def in api_sources :
                if source_def ["domain"]==self .target_domain_preference :
                    api_sources_to_try .append (source_def )
                    break 
            if not api_sources_to_try :
                self ._logger (f"Warning: Preferred domain '{self .target_domain_preference }' not a recognized API source. Fetching from all.")
                api_sources_to_try =api_sources 
        else :
            self ._logger ("No specific domain preference, or both domains have cookies. Will attempt to fetch from all sources.")
            api_sources_to_try =api_sources 

        for source in api_sources_to_try :
            if self .cancellation_event .is_set ():
                self .finished .emit ([],"KEY_FETCH_CANCELLED_DURING")
                return 
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

                if not cookies_dict_for_source and fallback_domain:
                    self._logger(f"Warning ({source['name']}): No cookies for '{primary_domain}'. Trying fallback '{fallback_domain}'...")
                    cookies_dict_for_source = prepare_cookies_for_request(
                        True, self.cookies_config['cookie_text'], self.cookies_config['selected_cookie_file'],
                        self.cookies_config['app_base_dir'], self._logger, target_domain=fallback_domain
                    )

                if cookies_dict_for_source:
                    any_cookies_loaded_successfully_for_any_source = True
                else:
                    self._logger(f"Warning ({source['name']}): Cookies enabled but could not be loaded for this domain. Fetch might fail if cookies are required.")

            self ._logger (f"Attempting to fetch favorite posts from: {source ['name']} ({source ['url']})")
            source_key_part =self .error_key_map .get (source ['name'],source ['name'].lower ().replace ('.','_'))
            self .status_update .emit (f"key_fetching_from_source_{source_key_part }")
            QCoreApplication .processEvents ()

            try :
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': f"https://{source['domain']}/favorites",
                    'Accept': 'text/css'
                }

                response = scraper.get(source['url'], headers=headers, cookies=cookies_dict_for_source, timeout=20)

                response .raise_for_status ()
                posts_data_from_api =response .json ()

                if not isinstance (posts_data_from_api ,list ):
                    err_detail =f"Error ({source ['name']}): API did not return a list of posts (got {type (posts_data_from_api )})."
                    self ._logger (err_detail )
                    error_messages_for_summary .append (err_detail )
                    continue 

                processed_posts_from_source =0 
                for post_entry in posts_data_from_api :
                    post_id =post_entry .get ("id")
                    post_title =html .unescape (post_entry .get ("title","Untitled Post").strip ())
                    service =post_entry .get ("service")
                    creator_id =post_entry .get ("user")
                    added_date_str =post_entry .get ("added",post_entry .get ("published",""))

                    if post_id and post_title and service and creator_id :
                        all_fetched_posts_temp .append ({
                        'post_id':post_id ,'title':post_title ,'service':service ,
                        'creator_id':creator_id ,'added_date':added_date_str ,
                        '_source_api':source ['name']
                        })
                        processed_posts_from_source +=1 
                    else :
                        self ._logger (f"Warning ({source ['name']}): Skipping favorite post entry due to missing data: {post_entry }")

                if processed_posts_from_source >0 :
                    fetched_any_successfully =True 
                self ._logger (f"Fetched {processed_posts_from_source } posts from {source ['name']}.")

            except Exception as e :
                err_detail =f"Error fetching favorite posts from {source ['name']}: {e }"
                self ._logger (err_detail )
                error_messages_for_summary .append (err_detail )
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 401:
                    self .finished .emit ([],"KEY_AUTH_FAILED")
                    self ._logger (f"Authorization failed for {source ['name']}, emitting KEY_AUTH_FAILED.")
                    return 

        if self .cancellation_event .is_set ():
            self .finished .emit ([],"KEY_FETCH_CANCELLED_AFTER")
            return 

        if self .cookies_config ['use_cookie']and not any_cookies_loaded_successfully_for_any_source :
            if self .target_domain_preference and not any_cookies_loaded_successfully_for_any_source :
                 domain_key_part =self .error_key_map .get (self .target_domain_preference ,self .target_domain_preference .lower ().replace ('.','_'))
                 self .finished .emit ([],f"KEY_COOKIES_REQUIRED_BUT_NOT_FOUND_FOR_DOMAIN_{domain_key_part }")
                 return 
            self .finished .emit ([],"KEY_COOKIES_REQUIRED_BUT_NOT_FOUND_GENERIC")
            return 

        unique_posts_map ={}
        for post in all_fetched_posts_temp :
            key =(post ['service'].lower (),str (post ['creator_id']).lower (),str (post ['post_id']).lower ())
            if key not in unique_posts_map :
                unique_posts_map [key ]=post 
        all_fetched_posts_temp =list (unique_posts_map .values ())

        all_fetched_posts_temp .sort (key =lambda x :(x .get ('_source_api','').lower (),x .get ('service','').lower (),str (x .get ('creator_id','')).lower (),(x .get ('added_date')or '')),reverse =False )

        if error_messages_for_summary :
            error_summary_str ="; ".join (error_messages_for_summary )
            if not fetched_any_successfully :
                self .finished .emit ([],f"KEY_FETCH_FAILED_GENERIC_{error_summary_str [:50 ]}")
            else :
                 self .finished .emit (all_fetched_posts_temp ,f"KEY_FETCH_PARTIAL_SUCCESS_{error_summary_str [:50 ]}")
        elif not all_fetched_posts_temp and not fetched_any_successfully and not self .target_domain_preference :
            self .finished .emit ([],"KEY_NO_FAVORITES_FOUND_ALL_PLATFORMS")
        else :
            self .finished .emit (all_fetched_posts_temp ,"KEY_FETCH_SUCCESS")

class PostListItemWidget (QWidget ):
    """Custom widget for displaying a single post in the FavoritePostsDialog list."""
    def __init__ (self ,post_data_dict ,parent_dialog_ref ,parent =None ):
        super ().__init__ (parent )
        self .post_data =post_data_dict 
        self .parent_dialog =parent_dialog_ref 

        self .layout =QHBoxLayout (self )
        self .layout .setContentsMargins (5 ,3 ,5 ,3 )
        self .layout .setSpacing (10 )

        self .checkbox =QCheckBox ()
        self .layout .addWidget (self .checkbox )

        self .info_label =QLabel ()
        self .info_label .setWordWrap (True )
        self .info_label .setTextFormat (Qt .RichText )
        self .layout .addWidget (self .info_label ,1 )

        self ._setup_display_text ()
    def _setup_display_text (self ):
        suffix_plain =self .post_data .get ('suffix_for_display',"")
        title_plain =self .post_data .get ('title','Untitled Post')
        escaped_suffix =html .escape (suffix_plain )
        escaped_title =html .escape (title_plain )
        p_style_paragraph ="font-size:10.5pt; margin:0; padding:0;"
        title_span_style ="font-weight:bold; color:#E0E0E0;"
        suffix_span_style ="color:#999999; font-weight:normal; font-size:9.5pt;"

        if escaped_suffix :
            display_html_content =f"<p style='{p_style_paragraph }'><span style='{title_span_style }'>{escaped_title }</span><span style='{suffix_span_style }'>{escaped_suffix }</span></p>"
        else :
            display_html_content =f"<p style='{p_style_paragraph }'><span style='{title_span_style }'>{escaped_title }</span></p>"

        self .info_label .setText (display_html_content )

    def isChecked (self ):return self .checkbox .isChecked ()
    def setCheckState (self ,state ):self .checkbox .setCheckState (state )
    def get_post_data (self ):return self .post_data 

class FavoritePostsDialog (QDialog ):
    """Dialog to display and select favorite posts."""
    def __init__ (self ,parent_app ,cookies_config ,known_names_list_ref ,target_domain_preference =None ):
        super ().__init__ (parent_app )
        self .parent_app =parent_app 
        self .cookies_config =cookies_config 
        self .all_fetched_posts =[]
        self .selected_posts_data =[]
        self .known_names_list_ref =known_names_list_ref 
        self .target_domain_preference_for_this_fetch =target_domain_preference 
        self .creator_name_cache ={}
        self .displayable_grouped_posts ={}
        self .fetcher_thread =None 

        app_icon =get_app_icon_object ()
        if not app_icon .isNull ():
            self .setWindowIcon (app_icon )

        self .setModal (True )
        self .setMinimumSize (600 ,600 )
        if hasattr (self .parent_app ,'get_dark_theme'):
            self .setStyleSheet (self .parent_app .get_dark_theme ())

        self ._init_ui ()
        self ._load_creator_names_from_file ()
        self ._retranslate_ui ()
        self ._start_fetching_favorite_posts ()

    def _update_status_label_from_key (self ,status_key ):
        """Translates a status key and updates the status label."""

        translated_status =self ._tr (status_key .lower (),status_key )
        self .status_label .setText (translated_status )

    def _init_ui (self ):
        main_layout =QVBoxLayout (self )

        self .status_label =QLabel ()
        self .status_label .setAlignment (Qt .AlignCenter )
        main_layout .addWidget (self .status_label )

        self .progress_bar =QProgressBar ()
        self .progress_bar .setTextVisible (False )
        self .progress_bar .setVisible (False )
        main_layout .addWidget (self .progress_bar )

        self .search_input =QLineEdit ()

        self .search_input .textChanged .connect (self ._filter_post_list_display )
        main_layout .addWidget (self .search_input )

        self .post_list_widget =QListWidget ()
        self .post_list_widget .setStyleSheet ("""
            QListWidget::item {
                border-bottom: 1px solid #4A4A4A;
                padding-top: 4px;
                padding-bottom: 4px;
            }""")
        self .post_list_widget .setAlternatingRowColors (True )
        main_layout .addWidget (self .post_list_widget )

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

    def _tr (self ,key ,default_text =""):
        """Helper to get translation based on current app language."""
        if callable (get_translation )and self .parent_app :
            return get_translation (self .parent_app .current_selected_language ,key ,default_text )
        return default_text 

    def _retranslate_ui (self ):
        self .setWindowTitle (self ._tr ("fav_posts_dialog_title","Favorite Posts"))
        self .status_label .setText (self ._tr ("fav_posts_loading_status","Loading favorite posts..."))
        self .search_input .setPlaceholderText (self ._tr ("fav_posts_search_placeholder","Search posts (title, creator name, ID, service)..."))
        self .select_all_button .setText (self ._tr ("fav_posts_select_all_button","Select All"))
        self .deselect_all_button .setText (self ._tr ("fav_posts_deselect_all_button","Deselect All"))
        self .download_button .setText (self ._tr ("fav_posts_download_selected_button","Download Selected"))
        self .cancel_button .setText (self ._tr ("fav_posts_cancel_button","Cancel"))

    def _logger (self ,message ):
        if hasattr (self .parent_app ,'log_signal')and self .parent_app .log_signal :
            self .parent_app .log_signal .emit (f"[FavPostsDialog] {message }")
        else :
            print (f"[FavPostsDialog] {message }")

    def _load_creator_names_from_file (self ):
        """Loads creator id-name-service mappings from creators.txt."""
        self ._logger ("Attempting to load creators.json for Favorite Posts Dialog.")
         
        if getattr (sys ,'frozen',False )and hasattr (sys ,'_MEIPASS'):
            base_path_for_creators =sys ._MEIPASS 
            self ._logger (f"  Running bundled. Using _MEIPASS: {base_path_for_creators }")
        else :
            base_path_for_creators =self .parent_app .app_base_dir 
            self ._logger (f"  Not bundled or _MEIPASS unavailable. Using app_base_dir: {base_path_for_creators }")
        creators_file_path = os.path.join(base_path_for_creators, "data", "creators.json")
        self ._logger (f"Full path to creators.json: {creators_file_path }")

        if not os .path .exists (creators_file_path ):
            self ._logger (f"Warning: 'creators.json' not found at {creators_file_path }. Creator names will not be displayed.")
            return 

        try :
            with open (creators_file_path ,'r',encoding ='utf-8')as f :
                loaded_data =json .load (f )

                if isinstance (loaded_data ,list )and len (loaded_data )>0 and isinstance (loaded_data [0 ],list ):
                    creators_list =loaded_data [0 ]
                elif isinstance (loaded_data ,list )and all (isinstance (item ,dict )for item in loaded_data ):
                    creators_list =loaded_data 
                else :
                    self ._logger (f"Warning: 'creators.json' has an unexpected format. Expected a list of lists or a flat list of creator objects.")
                    return 

                for creator_data in creators_list :
                    creator_id =creator_data .get ("id")
                    name =creator_data .get ("name")
                    service =creator_data .get ("service")
                    if creator_id and name and service :
                        self .creator_name_cache [(service .lower (),str (creator_id ))]=name 
            self ._logger (f"Successfully loaded {len (self .creator_name_cache )} creator names from 'creators.json'.")
        except Exception as e :
            self ._logger (f"Error loading 'creators.json': {e }")

    def _start_fetching_favorite_posts (self ):
        self .download_button .setEnabled (False )
        self .status_label .setText ("Initializing favorite posts fetch...")

        self .fetcher_thread =FavoritePostsFetcherThread (
        self .cookies_config ,
        self .parent_app .log_signal .emit ,
        target_domain_preference =self .target_domain_preference_for_this_fetch 
        )
        self .fetcher_thread .status_update .connect (self ._update_status_label_from_key )
        self .fetcher_thread .finished .connect (self ._on_fetch_completed )
        self .fetcher_thread .progress_bar_update .connect (self ._set_progress_bar_value )
        self .progress_bar .setVisible (True )
        self .fetcher_thread .start ()

    def _set_progress_bar_value (self ,value ,maximum ):
        if maximum ==0 :
            self .progress_bar .setRange (0 ,0 )
            self .progress_bar .setValue (0 )
        else :
            self .progress_bar .setRange (0 ,maximum )
            self .progress_bar .setValue (value )

    def _on_fetch_completed (self ,fetched_posts_list ,status_key ):
        self .progress_bar .setVisible (False )

        proceed_to_display_posts =False 
        show_error_message_box =False 
        message_box_title_key ="fav_posts_fetch_error_title"
        message_box_text_key ="fav_posts_fetch_error_message"
        message_box_params ={'domain':self .target_domain_preference_for_this_fetch or "platform",'error_message_part':""}
        status_label_text_key =None 

        if status_key =="KEY_FETCH_SUCCESS":
            proceed_to_display_posts =True 
        elif status_key and status_key .startswith ("KEY_FETCH_PARTIAL_SUCCESS_")and fetched_posts_list :
            displayable_detail =status_key .replace ("KEY_FETCH_PARTIAL_SUCCESS_","").replace ("_"," ")
            self ._logger (f"Partial success with posts: {status_key } -> {displayable_detail }")


            proceed_to_display_posts =True 
        elif status_key :
            specific_domain_msg_part =f" for {self .target_domain_preference_for_this_fetch }"if self .target_domain_preference_for_this_fetch else ""

            if status_key .startswith ("KEY_COOKIES_REQUIRED_BUT_NOT_FOUND_FOR_DOMAIN_")or status_key =="KEY_COOKIES_REQUIRED_BUT_NOT_FOUND_GENERIC":
                status_label_text_key ="fav_posts_cookies_required_error"
                self ._logger (f"Cookie error: {status_key }. Showing help dialog.")
                cookie_help_dialog = CookieHelpDialog(self.parent_app, self)
                cookie_help_dialog .exec_ ()
            elif status_key =="KEY_AUTH_FAILED":
                status_label_text_key ="fav_posts_auth_failed_title"
                self ._logger (f"Auth error: {status_key }. Showing help dialog.")
                QMessageBox .warning (self ,self ._tr ("fav_posts_auth_failed_title","Authorization Failed (Posts)"),
                self ._tr ("fav_posts_auth_failed_message_generic","...").format (domain_specific_part =specific_domain_msg_part ))
                cookie_help_dialog = CookieHelpDialog(self.parent_app, self)
                cookie_help_dialog .exec_ ()
            elif status_key =="KEY_NO_FAVORITES_FOUND_ALL_PLATFORMS":
                status_label_text_key ="fav_posts_no_posts_found_status"
                self ._logger (status_key )
            elif status_key .startswith ("KEY_FETCH_CANCELLED"):
                status_label_text_key ="fav_posts_fetch_cancelled_status"
                self ._logger (status_key )
            else :
                displayable_error_detail =status_key 
                if status_key .startswith ("KEY_FETCH_FAILED_GENERIC_"):
                    displayable_error_detail =status_key .replace ("KEY_FETCH_FAILED_GENERIC_","").replace ("_"," ")
                elif status_key .startswith ("KEY_FETCH_PARTIAL_SUCCESS_"):
                    displayable_error_detail =status_key .replace ("KEY_FETCH_PARTIAL_SUCCESS_","Partial success but no posts: ").replace ("_"," ")

                message_box_params ['error_message_part']=f":\n\n{displayable_error_detail }"if displayable_error_detail else ""
                status_label_text_key ="fav_posts_fetch_error_message"
                show_error_message_box =True 
                self ._logger (f"Fetch error: {status_key } -> {displayable_error_detail }")

            if status_label_text_key :
                 self .status_label .setText (self ._tr (status_label_text_key ,status_label_text_key ).format (**message_box_params ))
            if show_error_message_box :
                 QMessageBox .critical (self ,self ._tr (message_box_title_key ),self ._tr (message_box_text_key ).format (**message_box_params ))

            self .download_button .setEnabled (False )
            return 


        if not proceed_to_display_posts :
            if not status_label_text_key :
                self .status_label .setText (self ._tr ("fav_posts_cookies_required_error","Error: Cookies are required for favorite posts but could not be loaded."))
            self .download_button .setEnabled (False )
            return 

        if not self .creator_name_cache :
            self ._logger ("Warning: Creator name cache is empty. Names will not be resolved from creators.json. Displaying IDs instead.")
        else :
            self ._logger (f"Creator name cache has {len (self .creator_name_cache )} entries. Attempting to resolve names...")
            sample_keys =list (self .creator_name_cache .keys ())[:3 ]
            if sample_keys :
                self ._logger (f"Sample keys from creator_name_cache: {sample_keys }")


        processed_one_missing_log =False 
        for post_entry in fetched_posts_list :
            service_from_post =post_entry .get ('service','')
            creator_id_from_post =post_entry .get ('creator_id','')

            lookup_key_service =service_from_post .lower ()
            lookup_key_id =str (creator_id_from_post )
            lookup_key_tuple =(lookup_key_service ,lookup_key_id )

            resolved_name =self .creator_name_cache .get (lookup_key_tuple )

            if resolved_name :
                post_entry ['creator_name_resolved']=resolved_name 
            else :
                post_entry ['creator_name_resolved']=str (creator_id_from_post )
                if not processed_one_missing_log and self .creator_name_cache :
                    self ._logger (f"Debug: Name not found for key {lookup_key_tuple }. Using ID '{creator_id_from_post }'.")
                    processed_one_missing_log =True 

        self .all_fetched_posts =fetched_posts_list 

        if not self .all_fetched_posts :
            self .status_label .setText (self ._tr ("fav_posts_no_posts_found_status","No favorite posts found."))
            self .download_button .setEnabled (False )
            return 

        try :
            self ._populate_post_list_widget ()
            self .status_label .setText (self ._tr ("fav_posts_found_status","{count} favorite post(s) found.").format (count =len (self .all_fetched_posts )))
            self .download_button .setEnabled (True )
        except Exception as e :
            self .status_label .setText (self ._tr ("fav_posts_display_error_status","Error displaying posts: {error}").format (error =str (e )))
            self ._logger (f"Error during _populate_post_list_widget: {e }\n{traceback .format_exc (limit =3 )}")
            QMessageBox .critical (self ,self ._tr ("fav_posts_ui_error_title","UI Error"),self ._tr ("fav_posts_ui_error_message","Could not display favorite posts: {error}").format (error =str (e )))
            self .download_button .setEnabled (False )


    def _find_best_known_name_match_in_title (self ,title_raw ):
        if not title_raw or not self .known_names_list_ref :
            return None 

        title_lower =title_raw .lower ()
        best_match_known_name_primary =None 
        longest_match_len =0 

        for known_entry in self .known_names_list_ref :
            aliases_to_check =set ()
            for alias_val in known_entry .get ("aliases",[]):
                aliases_to_check .add (alias_val )
            if not known_entry .get ("is_group",False ):
                aliases_to_check .add (known_entry ["name"])
            sorted_aliases_for_entry =sorted (list (aliases_to_check ),key =len ,reverse =True )

            for alias in sorted_aliases_for_entry :
                alias_lower =alias .lower ()
                if not alias_lower :
                    continue 
                if re .search (r'\b'+re .escape (alias_lower )+r'\b',title_lower ):
                    if len (alias_lower )>longest_match_len :
                        longest_match_len =len (alias_lower )
                        best_match_known_name_primary =known_entry ["name"]
                    break 
        return best_match_known_name_primary 

    def _populate_post_list_widget (self ,posts_to_display =None ):
        self .post_list_widget .clear ()

        source_list_for_grouping =posts_to_display if posts_to_display is not None else self .all_fetched_posts 
        grouped_posts ={}
        for post in source_list_for_grouping :
            service =post .get ('service','unknown_service')
            creator_id =post .get ('creator_id','unknown_id')
            group_key =(service ,creator_id )
            if group_key not in grouped_posts :
                grouped_posts [group_key ]=[]
            grouped_posts [group_key ].append (post )

        sorted_group_keys =sorted (grouped_posts .keys (),key =lambda x :(x [0 ].lower (),x [1 ].lower ()))

        self .displayable_grouped_posts ={
        key :sorted (grouped_posts [key ],key =lambda p :(p .get ('added_date')or ''),reverse =True )
        for key in sorted_group_keys 
        }
        for service ,creator_id_val in sorted_group_keys :
            creator_name_display =self .creator_name_cache .get (
            (service .lower (),str (creator_id_val )),
            str (creator_id_val )
            )
            artist_header_display_text =f"{creator_name_display } ({service .capitalize ()} / {creator_id_val })"
            artist_header_item =QListWidgetItem (f"🎨 {artist_header_display_text }")
            artist_header_item .setFlags (Qt .NoItemFlags )
            font =artist_header_item .font ()
            font .setBold (True )
            font .setPointSize (font .pointSize ()+1 )
            artist_header_item .setFont (font )
            artist_header_item .setForeground (Qt .cyan )
            self .post_list_widget .addItem (artist_header_item )
            for post_data in self .displayable_grouped_posts [(service ,creator_id_val )]:
                post_title_raw =post_data .get ('title','Untitled Post')
                found_known_name_primary =self ._find_best_known_name_match_in_title (post_title_raw )

                plain_text_title_for_list_item =post_title_raw 
                if found_known_name_primary :
                    suffix_text =f" [Known - {found_known_name_primary }]"
                    post_data ['suffix_for_display']=suffix_text 
                    plain_text_title_for_list_item =post_title_raw +suffix_text 
                else :
                    post_data .pop ('suffix_for_display',None )

                list_item =QListWidgetItem (self .post_list_widget )
                list_item .setText (plain_text_title_for_list_item )
                list_item .setFlags (list_item .flags ()|Qt .ItemIsUserCheckable )
                list_item .setCheckState (Qt .Unchecked )
                list_item .setData (Qt .UserRole ,post_data )
                self .post_list_widget .addItem (list_item )

    def _filter_post_list_display (self ):
        search_text =self .search_input .text ().lower ().strip ()
        if not search_text :
            self ._populate_post_list_widget (self .all_fetched_posts )
            return 

        filtered_posts_to_group =[]
        for post in self .all_fetched_posts :
            matches_post_title =search_text in post .get ('title','').lower ()
            matches_creator_name =search_text in post .get ('creator_name_resolved','').lower ()
            matches_creator_id =search_text in post .get ('creator_id','').lower ()
            matches_service =search_text in post ['service'].lower ()

            if matches_post_title or matches_creator_name or matches_creator_id or matches_service :
                filtered_posts_to_group .append (post )

        self ._populate_post_list_widget (filtered_posts_to_group )

    def _select_all_items (self ):
        for i in range (self .post_list_widget .count ()):
            item =self .post_list_widget .item (i )
            if item and item .flags ()&Qt .ItemIsUserCheckable :
                item .setCheckState (Qt .Checked )

    def _deselect_all_items (self ):
        for i in range (self .post_list_widget .count ()):
            item =self .post_list_widget .item (i )
            if item and item .flags ()&Qt .ItemIsUserCheckable :
                item .setCheckState (Qt .Unchecked )

    def _accept_selection_action (self ):
        self .selected_posts_data =[]
        for i in range (self .post_list_widget .count ()):
            item =self .post_list_widget .item (i )
            if item and item .checkState ()==Qt .Checked :
                post_data_for_download =item .data (Qt .UserRole )
                self .selected_posts_data .append (post_data_for_download )

        if not self .selected_posts_data :
            QMessageBox .information (self ,self ._tr ("fav_posts_no_selection_title","No Selection"),self ._tr ("fav_posts_no_selection_message","Please select at least one post to download."))
            return 
        self .accept ()

    def get_selected_posts (self ):
        return self .selected_posts_data 