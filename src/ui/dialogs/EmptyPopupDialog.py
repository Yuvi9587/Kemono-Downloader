import json
import os
import sys
import threading
import time
import unicodedata
from collections import defaultdict
from urllib.parse import urlparse

import requests

from PySide6.QtCore import Signal, QCoreApplication, QSize, QThread, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QAbstractItemView,
    QSplitter, QProgressBar, QWidget, QFileDialog, QStackedWidget, QCheckBox
)

from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...core.api_client import download_from_api
from ...utils.network_utils import extract_post_info, prepare_cookies_for_request
from ...utils.resolution import get_dark_theme
from .UpdateCheckDialog import UpdateCheckDialog

class CreatorDownloadThread(QThread):
    progress_signal = Signal(int)
    status_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path

    def run(self):
        try:
            os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
            
            response = requests.get(self.url, stream=True, timeout=15)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(self.save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.isInterruptionRequested():
                        break
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            self.progress_signal.emit(progress)
                            self.status_signal.emit(f"Downloading Database... {progress}%")
                        else:
                            mb_downloaded = downloaded / (1024 * 1024)
                            self.status_signal.emit(f"Downloading Database... {mb_downloaded:.1f} MB")
            
            if not self.isInterruptionRequested():
                self.finished_signal.emit(True, "Success")
            else:
                if os.path.exists(self.save_path):
                    os.remove(self.save_path)
                self.finished_signal.emit(False, "Cancelled")
                
        except Exception as e:
            self.finished_signal.emit(False, str(e))

class PostsFetcherThread (QThread ):
    status_update =Signal (str )
    posts_fetched_signal =Signal (object ,list )
    fetch_error_signal =Signal (object ,str )
    finished_signal =Signal ()

    def __init__ (self ,creators_to_fetch ,parent_dialog_ref ):
        super ().__init__ ()
        self .creators_to_fetch =creators_to_fetch 
        self .parent_dialog =parent_dialog_ref 
        self .cancellation_flag =threading .Event ()

    def cancel (self ):
        self .cancellation_flag .set ()
        self .status_update .emit (self .parent_dialog ._tr ("post_fetch_cancelled_status","Post fetching cancellation requested..."))

    def run (self ):
        if not self .creators_to_fetch :
            self .status_update .emit (self .parent_dialog ._tr ("no_creators_to_fetch_status","No creators selected to fetch posts for."))
            self .finished_signal .emit ()
            return 

        for creator_data in self .creators_to_fetch :
            if self .cancellation_flag .is_set ():
                break 

            creator_name =creator_data .get ('name','Unknown Creator')
            service =creator_data .get ('service')
            user_id =creator_data .get ('id')

            print(f"[DEBUG] Fetching posts for: name={creator_name}, service={service}, user_id={user_id}")

            if not service or not user_id :
                self .fetch_error_signal .emit (creator_data ,f"Missing service or ID for {creator_name }")
                continue 

            self .status_update .emit (self .parent_dialog ._tr ("fetching_posts_for_creator_status_all_pages","Fetching all posts for {creator_name} ({service})... This may take a while.").format (creator_name =creator_name ,service =service ))

            domain =self .parent_dialog ._get_domain_for_service (service )
            api_url_base =f"https://{domain }/api/v1/{service }/user/{user_id }"
            print(f"[DEBUG] API URL: {api_url_base}")


            use_cookie_param =False 
            cookie_text_param =""
            selected_cookie_file_param =None 
            app_base_dir_param =None 

            if self .parent_dialog .parent_app :
                app =self .parent_dialog .parent_app 
                use_cookie_param =app .use_cookie_checkbox .isChecked ()
                cookie_text_param =app .cookie_text_input .text ().strip ()
                selected_cookie_file_param =app .selected_cookie_filepath 
                app_base_dir_param =app .app_base_dir 

            all_posts_for_this_creator =[]
            try :
                post_generator =download_from_api (
                api_url_base ,
                logger =lambda msg :self .status_update .emit (f"[API Fetch - {creator_name }] {msg }"),

                use_cookie =use_cookie_param ,
                cookie_text =cookie_text_param ,
                selected_cookie_file =selected_cookie_file_param ,
                app_base_dir =app_base_dir_param ,
                manga_filename_style_for_sort_check =None ,
                cancellation_event =self .cancellation_flag 
                )

                for posts_batch in post_generator :
                    if self .cancellation_flag .is_set ():
                        self .status_update .emit (f"Post fetching for {creator_name } cancelled during pagination.")
                        break 
                    all_posts_for_this_creator .extend (posts_batch )
                    print(f"[DEBUG] Fetched batch: {len(posts_batch)} posts, total so far: {len(all_posts_for_this_creator)}")
                    self .status_update .emit (f"Fetched {len (all_posts_for_this_creator )} posts so far for {creator_name }...")

                print(f"[DEBUG] Finished fetching for {creator_name}: {len(all_posts_for_this_creator)} posts total.")
                if not self .cancellation_flag .is_set ():
                    self .posts_fetched_signal .emit (creator_data ,all_posts_for_this_creator )
                    self .status_update .emit (f"Finished fetching {len (all_posts_for_this_creator )} posts for {creator_name }.")
                else :
                    self .posts_fetched_signal .emit (creator_data ,all_posts_for_this_creator )
                    self .status_update .emit (f"Fetching for {creator_name } cancelled. {len (all_posts_for_this_creator )} posts collected.")

            except RuntimeError as e :
                print(f"[DEBUG] RuntimeError for {creator_name}: {e}")
                if "cancelled by user"in str (e ).lower ()or self .cancellation_flag .is_set ():
                    self .status_update .emit (f"Post fetching for {creator_name } cancelled: {e }")
                    self .posts_fetched_signal .emit (creator_data ,all_posts_for_this_creator )
                else :
                    self .fetch_error_signal .emit (creator_data ,f"Runtime error fetching posts for {creator_name }: {e }")
            except Exception as e :
                print(f"[DEBUG] Exception for {creator_name}: {e}")
                self .fetch_error_signal .emit (creator_data ,f"Error fetching posts for {creator_name }: {e }")

            if self .cancellation_flag .is_set ():
                break 
            QThread .msleep (200 )

        if self .cancellation_flag .is_set ():
            self .status_update .emit (self .parent_dialog ._tr ("post_fetch_cancelled_status_done","Post fetching cancelled."))
        else :
            self .status_update .emit (self .parent_dialog ._tr ("post_fetch_finished_status","Finished fetching posts for selected creators."))
        self .finished_signal .emit ()


class EmptyPopupDialog (QDialog ):
    """A simple empty popup dialog."""
    SCOPE_CHARACTERS ="Characters"
    INITIAL_LOAD_LIMIT =200 
    SCOPE_CREATORS ="Creators"

    def __init__ (self ,user_data_path ,parent_app_ref ,parent =None ):
        super ().__init__ (parent )
        self.parent_app = parent_app_ref

        scale_factor = getattr(self.parent_app, 'scale_factor', 1.0)
        
        self.setMinimumSize(int(400 * scale_factor), int(300 * scale_factor))
        self.current_scope_mode = self.SCOPE_CREATORS
        self.user_data_path = user_data_path

        if hasattr(self.parent_app, 'app_base_dir') and self.parent_app.app_base_dir:
            project_root = self.parent_app.app_base_dir
        else:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        self.creators_file_path = os.path.join(project_root, "data", "creators.json")

        app_icon =get_app_icon_object ()
        if app_icon and not app_icon .isNull ():
            self .setWindowIcon (app_icon )
        
        self.update_profiles_list = None
        self.load_settings_into_ui_requested = False
        
        self.update_profile_data = None
        self.update_creator_name = None
        
        self .selected_creators_for_queue =[]
        self .globally_selected_creators ={}
        self .fetched_posts_data ={}
        self .post_fetch_thread =None 
        self .TITLE_COLUMN_WIDTH_FOR_POSTS =70 
        self .globally_selected_post_ids =set ()
        self ._is_scrolling_titles =False 
        self ._is_scrolling_dates =False 

        dialog_layout = QVBoxLayout(self)
        self.setLayout(dialog_layout)

        self.stacked_widget = QStackedWidget()
        dialog_layout.addWidget(self.stacked_widget)

        self.download_page = QWidget()
        dl_layout = QVBoxLayout(self.download_page)
        
        self.dl_info_label = QLabel("The Creators database (approx. 50MB) is missing.\nWould you like to download it now to enable Creator Selection?")
        self.dl_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dl_info_label.setStyleSheet("font-size: 14px; margin-bottom: 10px;")
        
        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.hide()
        
        self.dl_button = QPushButton("Download Creators.json")
        self.dl_button.setMinimumHeight(40)
        self.dl_button.clicked.connect(self._start_download)
        
        dl_layout.addStretch()
        dl_layout.addWidget(self.dl_info_label)
        dl_layout.addWidget(self.dl_progress)
        dl_layout.addWidget(self.dl_button)
        dl_layout.addStretch()
        self.stacked_widget.addWidget(self.download_page)

        self.normal_page = QWidget()
        normal_layout = QVBoxLayout(self.normal_page)
        normal_layout.setContentsMargins(0, 0, 0, 0)

        self .left_pane_widget =QWidget ()
        left_pane_layout =QVBoxLayout (self .left_pane_widget )

        search_fetch_layout =QHBoxLayout ()
        self .search_input =QLineEdit ()
        self .search_input .textChanged .connect (self ._filter_list )
        search_fetch_layout .addWidget (self .search_input ,1 )
        self .fetch_posts_button =QPushButton ()
        self .fetch_posts_button .setEnabled (False )
        self .fetch_posts_button .clicked .connect (self ._handle_fetch_posts_click )
        search_fetch_layout .addWidget (self .fetch_posts_button )
        left_pane_layout .addLayout (search_fetch_layout )

        self .progress_bar =QProgressBar ()
        self .progress_bar .setRange (0 ,0 )
        self .progress_bar .setTextVisible (False )
        self .progress_bar .setVisible (False )
        left_pane_layout .addWidget (self .progress_bar )

        self .list_widget =QListWidget ()
        self .list_widget .itemChanged .connect (self ._handle_item_check_changed )
        left_pane_layout .addWidget (self .list_widget )

        left_bottom_buttons_layout =QHBoxLayout ()
        self .add_selected_button =QPushButton ()
        self .add_selected_button .setToolTip (
        "Add Selected Creators to URL Input\n\n"
        "Adds the names of all checked creators to the main URL input field,\n"
        "comma-separated, and closes this dialog."
        )
        self .add_selected_button .clicked .connect (self ._handle_add_selected )
        self .add_selected_button .setDefault (True )
        left_bottom_buttons_layout .addWidget (self .add_selected_button )
        self .scope_button =QPushButton ()
        self .scope_button .clicked .connect (self ._toggle_scope_mode )
        left_bottom_buttons_layout .addWidget (self .scope_button )
        
        self.use_pawchive_cb = QCheckBox("Use Pawchive for Kemono")
        self.use_pawchive_cb.setToolTip("When adding Kemono creators to the queue, use pawchive.pw URLs instead.")
        if hasattr(self.parent_app, 'settings'):
            self.use_pawchive_cb.setChecked(self.parent_app.settings.value("popup_use_pawchive", False, type=bool))
            self.use_pawchive_cb.stateChanged.connect(lambda state: self.parent_app.settings.setValue("popup_use_pawchive", bool(state)))
        left_bottom_buttons_layout.addWidget(self.use_pawchive_cb)
        
        left_pane_layout .addLayout (left_bottom_buttons_layout )

        self .right_pane_widget =QWidget ()
        right_pane_layout =QVBoxLayout (self .right_pane_widget )

        self .posts_area_title_label =QLabel ("Fetched Posts")
        self .posts_area_title_label .setAlignment (Qt .AlignCenter )
        right_pane_layout .addWidget (self .posts_area_title_label )

        self .posts_search_input =QLineEdit ()
        self .posts_search_input .setVisible (False )
        self .posts_search_input .textChanged .connect (self ._filter_fetched_posts_list )
        right_pane_layout .addWidget (self .posts_search_input )

        posts_headers_layout =QHBoxLayout ()
        self .posts_title_header_label =QLabel ()
        self .posts_title_header_label .setStyleSheet ("font-weight: bold; padding-left: 20px;")
        posts_headers_layout .addWidget (self .posts_title_header_label ,7 )

        self .posts_date_header_label =QLabel ()
        self .posts_date_header_label .setStyleSheet ("font-weight: bold;")
        posts_headers_layout .addWidget (self .posts_date_header_label ,3 )
        right_pane_layout .addLayout (posts_headers_layout )

        self .posts_content_splitter =QSplitter (Qt .Horizontal )

        self .posts_title_list_widget =QListWidget ()
        self .posts_title_list_widget .itemChanged .connect (self ._handle_post_item_check_changed )
        self .posts_title_list_widget .setAlternatingRowColors (True )
        self .posts_content_splitter .addWidget (self .posts_title_list_widget )

        self .posts_date_list_widget =QListWidget ()
        self .posts_date_list_widget .setSelectionMode (QAbstractItemView .NoSelection )
        self .posts_date_list_widget .setAlternatingRowColors (True )
        self .posts_date_list_widget .setHorizontalScrollBarPolicy (Qt .ScrollBarAlwaysOff )
        self .posts_content_splitter .addWidget (self .posts_date_list_widget )

        right_pane_layout .addWidget (self .posts_content_splitter ,1 )

        posts_buttons_top_layout =QHBoxLayout ()
        self .posts_select_all_button =QPushButton ()
        self .posts_select_all_button .clicked .connect (self ._handle_posts_select_all )
        posts_buttons_top_layout .addWidget (self .posts_select_all_button )

        self .posts_deselect_all_button =QPushButton ()
        self .posts_deselect_all_button .clicked .connect (self ._handle_posts_deselect_all )
        posts_buttons_top_layout .addWidget (self .posts_deselect_all_button )
        right_pane_layout .addLayout (posts_buttons_top_layout )

        posts_buttons_bottom_layout =QHBoxLayout ()
        self .posts_add_selected_button =QPushButton ()
        self .posts_add_selected_button .clicked .connect (self ._handle_posts_add_selected_to_queue )
        posts_buttons_bottom_layout .addWidget (self .posts_add_selected_button )

        self .posts_close_button =QPushButton ()
        self .posts_close_button .clicked .connect (self ._handle_posts_close_view )
        posts_buttons_bottom_layout .addWidget (self .posts_close_button )
        right_pane_layout .addLayout (posts_buttons_bottom_layout )

        self .right_pane_widget .hide ()

        self .main_splitter =QSplitter (Qt .Horizontal )
        self .main_splitter .addWidget (self .left_pane_widget )
        self .main_splitter .addWidget (self .right_pane_widget )
        self .main_splitter .setCollapsible (0 ,False )
        self .main_splitter .setCollapsible (1 ,True )

        self .posts_title_list_widget .verticalScrollBar ().valueChanged .connect (self ._sync_scroll_dates )
        self .posts_date_list_widget .verticalScrollBar ().valueChanged .connect (self ._sync_scroll_titles )
        
        normal_layout.addWidget(self.main_splitter)
        self.stacked_widget.addWidget(self.normal_page)

        self .original_size =self .sizeHint ()
        self .main_splitter .setSizes ([int (self .width ()*scale_factor ),0 ])

        self ._retranslate_ui ()

        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("")

        self .resize (int ((self .original_size .width ()+50 )*scale_factor ),int ((self .original_size .height ()+100 )*scale_factor ))

        QTimer .singleShot (0 ,self ._perform_initial_load )

    def _center_on_screen (self ):
        """Centers the dialog on the parent's screen or the primary screen."""
        if self .parent_app :
            parent_rect =self .parent_app .frameGeometry ()
            self .move (parent_rect .center ()-self .rect ().center ())
        else :
            try :
                screen_geo =QApplication .primaryScreen ().availableGeometry ()
                self .move (screen_geo .center ()-self .rect ().center ())
            except AttributeError :
                pass 


    def _handle_fetch_posts_click (self ):
        selected_creators =list (self .globally_selected_creators .values ())
        print(f"[DEBUG] Selected creators for fetch: {selected_creators}")
        if not selected_creators :
            QMessageBox .information (self ,self ._tr ("no_selection_title","No Selection"),
            "Please select at least one creator to fetch posts for.")
            return 

        if self .parent_app :
            parent_geometry =self .parent_app .geometry ()
            new_width =int (parent_geometry .width ()*0.75 )
            new_height =int (parent_geometry .height ()*0.80 )
            self .resize (new_width ,new_height )
            self ._center_on_screen ()

        self .right_pane_widget .show ()
        QTimer .singleShot (10 ,lambda :self .main_splitter .setSizes ([int (self .width ()*0.3 ),int (self .width ()*0.7 )]))

        QTimer .singleShot (20 ,lambda :self .posts_content_splitter .setSizes ([int (self .posts_content_splitter .width ()*0.7 ),int (self .posts_content_splitter .width ()*0.3 )]))
        self .add_selected_button .setEnabled (False )
        self .globally_selected_post_ids .clear ()
        self .posts_search_input .setVisible (True )
        self .setWindowTitle (self ._tr ("creator_popup_title_fetching","Creator Posts"))

        self .fetch_posts_button .setEnabled (False )
        self .posts_title_list_widget .clear ()
        self .posts_date_list_widget .clear ()
        self .fetched_posts_data .clear ()
        self .posts_area_title_label .setText (self ._tr ("fav_posts_loading_status","Loading favorite posts..."))
        self .posts_title_list_widget .itemChanged .connect (self ._handle_post_item_check_changed )
        self .progress_bar .setVisible (True )

        if self .post_fetch_thread and self .post_fetch_thread .isRunning ():
            self .post_fetch_thread .cancel ()
            self .post_fetch_thread .wait ()
        print(f"[DEBUG] Starting PostsFetcherThread with creators: {selected_creators}")
        self .post_fetch_thread =PostsFetcherThread (selected_creators ,self )
        self .post_fetch_thread .status_update .connect (self ._handle_fetch_status_update )
        self .post_fetch_thread .posts_fetched_signal .connect (self ._handle_posts_fetched )
        self .post_fetch_thread .fetch_error_signal .connect (self ._handle_fetch_error )
        self .post_fetch_thread .finished_signal .connect (self ._handle_fetch_finished )
        self .post_fetch_thread .start ()

    def _tr (self ,key ,default_text =""):
        """Helper to get translation based on current app language."""
        if callable (get_translation )and self .parent_app :
            return get_translation (self .parent_app .current_selected_language ,key ,default_text )
        return default_text 

    def _retranslate_ui (self ):
        self .setWindowTitle (self ._tr ("creator_popup_title","Creator Selection"))
        self .search_input .setPlaceholderText (self ._tr ("creator_popup_search_placeholder","Search by name, service, or paste creator URL..."))
        self .add_selected_button .setText (self ._tr ("creator_popup_add_selected_button","Add Selected"))
        self .fetch_posts_button .setText (self ._tr ("fetch_posts_button_text","Fetch Posts"))
        self ._update_scope_button_text_and_tooltip ()

        self .posts_search_input .setPlaceholderText (self ._tr ("creator_popup_posts_search_placeholder","Search fetched posts by title..."))

        self .posts_title_header_label .setText (self ._tr ("column_header_post_title","Post Title"))
        self .posts_date_header_label .setText (self ._tr ("column_header_date_uploaded","Date Uploaded"))

        self .posts_area_title_label .setText (self ._tr ("creator_popup_posts_area_title","Fetched Posts"))
        self .posts_select_all_button .setText (self ._tr ("select_all_button_text","Select All"))
        self .posts_deselect_all_button .setText (self ._tr ("deselect_all_button_text","Deselect All"))
        self .posts_add_selected_button .setText (self ._tr ("creator_popup_add_posts_to_queue_button","Add Selected Posts to Queue"))
        self .posts_close_button .setText (self ._tr ("fav_posts_cancel_button","Cancel"))

    def _sync_scroll_dates (self ,value ):
        if not self ._is_scrolling_titles :
            self ._is_scrolling_dates =True 
            self .posts_date_list_widget .verticalScrollBar ().setValue (value )
            self ._is_scrolling_dates =False 

    def _sync_scroll_titles (self ,value ):
        if not self ._is_scrolling_dates :
            self ._is_scrolling_titles =True 
            self .posts_title_list_widget .verticalScrollBar ().setValue (value )
            self ._is_scrolling_titles =False 

    def _start_download(self):
        github_raw_url = "https://media.githubusercontent.com/media/Yuvi9587/Kemono-Downloader/main/data/creators.json"
        
        self.dl_button.setEnabled(False)
        self.dl_progress.show()
        self.dl_progress.setRange(0, 0)
        self.dl_info_label.setText("Connecting to GitHub... Please wait.")
        
        self.dl_thread = CreatorDownloadThread(github_raw_url, self.creators_file_path)
        self.dl_thread.progress_signal.connect(self.dl_progress.setValue)
        self.dl_thread.status_signal.connect(self.dl_info_label.setText) 
        self.dl_thread.finished_signal.connect(self._on_download_finished)
        self.dl_thread.start()

    def _on_download_finished(self, success, message):
        if success:
            self.stacked_widget.setCurrentWidget(self.normal_page)
            self._load_creators_from_json() 
        else:
            self.dl_button.setEnabled(True)
            self.dl_progress.hide()
            self.dl_info_label.setText(f"Download failed: {message}\nPlease check your connection and try again.")

    def _perform_initial_load (self ):
        """Called by QTimer to load data after dialog is shown."""
        print(f"[DEBUG] Target DB Path: {self.creators_file_path}")
        if os.path.exists(self.creators_file_path):
            self.stacked_widget.setCurrentWidget(self.normal_page)
            self._load_creators_from_json()
        else:
            self.stacked_widget.setCurrentWidget(self.download_page)

    def _load_creators_from_json (self ):
        """Loads creators from creators.json and populates the list widget."""
        self .list_widget .clear ()

        self .progress_bar .setVisible (True )
        QCoreApplication .processEvents ()
        if not self .isVisible ():return 

        try :
            with open (self.creators_file_path ,'r',encoding ='utf-8')as f :
                data =json .load (f )
            QCoreApplication .processEvents ()
            if not self .isVisible ():return 

            raw_data_list =[]
            if isinstance (data ,list )and len (data )>0 and isinstance (data [0 ],list ):
                raw_data_list =data [0 ]
            elif isinstance (data ,list )and all (isinstance (item ,dict )for item in data ):
                raw_data_list =data 
            else :
                self .list_widget .addItem ("Error: Invalid format in creators.json.")
                self .all_creators_data =[]
                self .progress_bar .setVisible (False );QCoreApplication .processEvents ();return 


            unique_creators_map ={}
            duplicates_skipped_count =0 
            for creator_entry in raw_data_list :
                service =creator_entry .get ('service')
                creator_id =creator_entry .get ('id')
                name_for_log =creator_entry .get ('name','Unknown')

                if service and creator_id :
                    key =(str (service ).lower ().strip (),str (creator_id ).strip ())
                    if key not in unique_creators_map :
                        unique_creators_map [key ]=creator_entry 
                    else :
                        duplicates_skipped_count +=1 
                else :
                    print (f"Warning: Creator entry in creators.json missing service or ID: {name_for_log }")

            self .all_creators_data =list (unique_creators_map .values ())
            if duplicates_skipped_count >0 :
                print (f"INFO (Creator Popup): Skipped {duplicates_skipped_count } duplicate creator entries from creators.json based on (service, id).")

            self .all_creators_data .sort (key =lambda c :(-c .get ('favorited',0 ),c .get ('name','').lower ()))
            QCoreApplication .processEvents ()
            if not self .isVisible ():return 

        except json .JSONDecodeError :
            self .list_widget .addItem ("Error: Could not parse creators.json.")
            self .all_creators_data =[]
            self .progress_bar .setVisible (False );QCoreApplication .processEvents ();return 
        except Exception as e :
            self .list_widget .addItem (f"Error loading creators: {e }")
            self .all_creators_data =[]
            self .progress_bar .setVisible (False );QCoreApplication .processEvents ();return 

        self ._filter_list ()

    def _populate_list_widget (self ,creators_to_display ):
        """Clears and populates the list widget with the given creator data."""
        self .list_widget .blockSignals (True )
        self .list_widget .clear ()

        if not creators_to_display :
            self .list_widget .blockSignals (False )






            return 

        CHUNK_SIZE_POPULATE =100 
        for i in range (0 ,len (creators_to_display ),CHUNK_SIZE_POPULATE ):
            if not self .isVisible ():
                self .list_widget .blockSignals (False )
                return 

            chunk =creators_to_display [i :i +CHUNK_SIZE_POPULATE ]
            for creator in chunk :
                creator_name_raw =creator .get ('name')
                display_creator_name =creator_name_raw .strip ()if isinstance (creator_name_raw ,str )and creator_name_raw .strip ()else "Unknown Creator"
                service_display_name =creator .get ('service','N/A').capitalize ()
                display_text =f"{display_creator_name } ({service_display_name })"
                item =QListWidgetItem (display_text )
                item .setFlags (item .flags ()|Qt .ItemIsUserCheckable )
                item .setData (Qt .UserRole ,creator )
                service =creator .get ('service')
                creator_id =creator .get ('id')
                if service is not None and creator_id is not None :
                    unique_key =(str (service ),str (creator_id ))
                    if unique_key in self .globally_selected_creators :
                        item .setCheckState (Qt .Checked )
                    else :
                        item .setCheckState (Qt .Unchecked )
                else :
                    item .setCheckState (Qt .Unchecked )
                self .list_widget .addItem (item )

            QCoreApplication .processEvents ()

        self .list_widget .blockSignals (False )

    def _filter_list (self ):
        """Filters the list widget based on the search input."""
        raw_search_input =self .search_input .text ()



        check_search_text_for_empty =raw_search_input .lower ().strip ()

        QCoreApplication .processEvents ()
        if not self .isVisible ():return 

        if not check_search_text_for_empty :
            self .progress_bar .setVisible (False )
            creators_to_show =self .all_creators_data [:self .INITIAL_LOAD_LIMIT ]
            self ._populate_list_widget (creators_to_show )
            self .search_input .setToolTip ("Search by name, service, or paste creator URL...")
            QCoreApplication .processEvents ()
        else :
            self .progress_bar .setVisible (True )
            QCoreApplication .processEvents ()
            if not self .isVisible ():return 

            norm_search_casefolded =unicodedata .normalize ('NFKC',raw_search_input ).casefold ().strip ()

            scored_matches =[]

            parsed_service_from_url ,parsed_user_id_from_url ,_ =extract_post_info (raw_search_input )

            if parsed_service_from_url and parsed_user_id_from_url :

                self .search_input .setToolTip (f"Searching for URL: {raw_search_input [:50 ]}...")
                for creator_data in self .all_creators_data :
                    creator_service_lower =creator_data .get ('service','').lower ()

                    creator_id_str_lower =str (creator_data .get ('id','')).lower ()

                    if creator_service_lower ==parsed_service_from_url .lower ()and creator_id_str_lower ==parsed_user_id_from_url .lower ():
                        scored_matches .append ((5 ,creator_data ))

                        break 

            else :


                self .search_input .setToolTip ("Searching by name or service...")
                norm_search_casefolded =unicodedata .normalize ('NFKC',raw_search_input ).casefold ().strip ()

                CHUNK_SIZE_FILTER =500 
                for i in range (0 ,len (self .all_creators_data ),CHUNK_SIZE_FILTER ):
                    if not self .isVisible ():break 
                    chunk =self .all_creators_data [i :i +CHUNK_SIZE_FILTER ]
                    for creator_data in chunk :
                        creator_name_raw =creator_data .get ('name','')
                        creator_service_raw =creator_data .get ('service','')


                        norm_creator_name_casefolded =unicodedata .normalize ('NFKC',creator_name_raw ).casefold ()
                        norm_service_casefolded =unicodedata .normalize ('NFKC',creator_service_raw ).casefold ()

                        current_score =0 

                        if norm_search_casefolded ==norm_creator_name_casefolded :
                            current_score =4 

                        elif norm_creator_name_casefolded .startswith (norm_search_casefolded ):
                            current_score =3 

                        elif norm_search_casefolded in norm_creator_name_casefolded :
                            current_score =2 

                        elif norm_search_casefolded in norm_service_casefolded :
                            current_score =1 

                        if current_score >0 :
                            scored_matches .append ((current_score ,creator_data ))

                    QCoreApplication .processEvents ()



            scored_matches .sort (key =lambda x :(-x [0 ],unicodedata .normalize ('NFKC',x [1 ].get ('name','')).casefold ()))


            final_creators_to_display =[creator_data for score ,creator_data in scored_matches [:20 ]]

            self ._populate_list_widget (final_creators_to_display )
            self .progress_bar .setVisible (False )


            if parsed_service_from_url and parsed_user_id_from_url :
                if final_creators_to_display :
                    self .search_input .setToolTip (f"Found creator by URL: {final_creators_to_display [0 ].get ('name')}")
                else :
                    self .search_input .setToolTip (f"URL parsed, but no matching creator found in your creators.json.")
            else :
                if final_creators_to_display :
                    self .search_input .setToolTip (f"Showing top {len (final_creators_to_display )} match(es) for '{raw_search_input [:30 ]}...'")
                else :
                    self .search_input .setToolTip (f"No matches found for '{raw_search_input [:30 ]}...'")

    def _toggle_scope_mode (self ):
        """Toggles the scope mode and updates the button text."""
        if self .current_scope_mode ==self .SCOPE_CHARACTERS :
            self .current_scope_mode =self .SCOPE_CREATORS 
        else :
            self .current_scope_mode =self .SCOPE_CHARACTERS 
        self ._update_scope_button_text_and_tooltip ()

    def _update_scope_button_text_and_tooltip (self ):
        if self .current_scope_mode ==self .SCOPE_CHARACTERS :
            self .scope_button .setText (self ._tr ("creator_popup_scope_characters_button","Scope: Characters"))
        else :
            self .scope_button .setText (self ._tr ("creator_popup_scope_creators_button","Scope: Creators"))

        self .scope_button .setToolTip (
        f"Current Download Scope: {self .current_scope_mode }\n\n"
        f"Click to toggle between '{self .SCOPE_CHARACTERS }' and '{self .SCOPE_CREATORS }' scopes.\n"
        f"'{self .SCOPE_CHARACTERS }': Downloads into character-named folders directly in the main Download Location (artists mixed).\n"
        f"'{self .SCOPE_CREATORS }': Downloads into artist-named subfolders within the main Download Location, then character folders inside those.")

    def _handle_fetch_status_update (self ,message ):
        if self .parent_app :
            self .parent_app .log_signal .emit (f"[CreatorPopup Fetch] {message }")
        self .posts_area_title_label .setText (message )

    def _handle_posts_fetched (self ,creator_info ,posts_list ):
        creator_key =(creator_info .get ('service'),str (creator_info .get ('id')))

        self .fetched_posts_data [creator_key ]=(creator_info ,posts_list )
        self ._filter_fetched_posts_list ()

    def _filter_fetched_posts_list (self ):
        search_text =self .posts_search_input .text ().lower ().strip ()

        data_for_rebuild ={}

        if not self .fetched_posts_data :
            self .posts_area_title_label .setText (self ._tr ("no_posts_fetched_yet_status","No posts fetched yet."))
        elif not search_text :
            data_for_rebuild =self .fetched_posts_data 

            total_posts_in_view =sum (len (posts_tuple [1 ])for posts_tuple in data_for_rebuild .values ())
            if total_posts_in_view >0 :
                self .posts_area_title_label .setText (self ._tr ("fetched_posts_count_label","Fetched {count} post(s). Select to add to queue.").format (count =total_posts_in_view ))
            else :
                self .posts_area_title_label .setText (self ._tr ("no_posts_found_for_selection","No posts found for selected creator(s)."))
        else :
            for creator_key ,(creator_data_tuple_part ,posts_list_tuple_part )in self .fetched_posts_data .items ():
                matching_posts_for_creator =[
                post for post in posts_list_tuple_part 
                if search_text in post .get ('title','').lower ()
                ]
                if matching_posts_for_creator :

                    data_for_rebuild [creator_key ]=(creator_data_tuple_part ,matching_posts_for_creator )


            total_matching_posts =sum (len (posts_tuple [1 ])for posts_tuple in data_for_rebuild .values ())
            if total_matching_posts >0 :
                self .posts_area_title_label .setText (self ._tr ("fetched_posts_count_label_filtered","Displaying {count} post(s) matching filter.").format (count =total_matching_posts ))
            else :
                self .posts_area_title_label .setText (self ._tr ("no_posts_match_search_filter","No posts match your search filter."))

        self ._rebuild_posts_list_widget (filtered_data_map =data_for_rebuild )

    def _rebuild_posts_list_widget (self ,filtered_data_map ):
        self .posts_title_list_widget .blockSignals (True )
        self .posts_date_list_widget .blockSignals (True )
        self .posts_title_list_widget .clear ()
        self .posts_date_list_widget .clear ()
        data_to_display =filtered_data_map 

        if not data_to_display :
            self .posts_title_list_widget .blockSignals (False )
            self .posts_date_list_widget .blockSignals (False )
            return 


        sorted_creator_keys =sorted (
        data_to_display .keys (),
        key =lambda k :data_to_display [k ][0 ].get ('name','').lower ()
        )

        total_posts_shown =0 
        for creator_key in sorted_creator_keys :

            creator_info_original ,posts_for_this_creator =data_to_display .get (creator_key ,(None ,[]))

            if not creator_info_original or not posts_for_this_creator :
                continue 

            creator_header_item =QListWidgetItem (f"--- {self ._tr ('posts_for_creator_header','Posts for')} {creator_info_original ['name']} ({creator_info_original ['service']}) ---")
            font =creator_header_item .font ()
            font .setBold (True )
            creator_header_item .setFont (font )
            creator_header_item .setFlags (Qt .NoItemFlags )
            self .posts_title_list_widget .addItem (creator_header_item )
            self .posts_date_list_widget .addItem (QListWidgetItem (""))

            for post in posts_for_this_creator :
                post_title =post .get ('title',self ._tr ('untitled_post_placeholder','Untitled Post'))


                date_prefix_str ="[No Date]"
                published_date_str =post .get ('published')
                added_date_str =post .get ('added')

                date_to_use_str =None 
                if published_date_str :
                    date_to_use_str =published_date_str 
                elif added_date_str :
                    date_to_use_str =added_date_str 

                if date_to_use_str :
                    try :

                        formatted_date =date_to_use_str .split ('T')[0 ]
                        date_prefix_str =f"[{formatted_date }]"
                    except Exception :
                        pass 


                date_display_str ="[No Date]"
                published_date_str =post .get ('published')
                added_date_str =post .get ('added')

                date_to_use_str =None 
                if published_date_str :
                    date_to_use_str =published_date_str 
                elif added_date_str :
                    date_to_use_str =added_date_str 

                if date_to_use_str :
                    try :

                        formatted_date =date_to_use_str .split ('T')[0 ]
                        date_display_str =f"[{formatted_date }]"
                    except Exception :
                        pass 


                title_item_text =f"  {post_title }"
                item =QListWidgetItem (title_item_text )
                item .setFlags (item .flags ()|Qt .ItemIsUserCheckable )
                item .setCheckState (Qt .Unchecked )
                item_data ={
                'title':post_title ,
                'id':post .get ('id'),
                'service':creator_info_original ['service'],
                'user_id':creator_info_original ['id'],
                'creator_name':creator_info_original ['name'],
                'full_post_data':post ,
                'date_display_str':date_display_str ,
                'published_date_for_sort':date_to_use_str 
                }
                item .setData (Qt .UserRole ,item_data )
                post_unique_key =(
                item_data ['service'],
                str (item_data ['user_id']),
                str (item_data ['id'])
                )
                if post_unique_key in self .globally_selected_post_ids :
                    item .setCheckState (Qt .Checked )
                else :
                    item .setCheckState (Qt .Unchecked )

                self .posts_title_list_widget .addItem (item )
                total_posts_shown +=1 

                date_item =QListWidgetItem (f"  {date_display_str }")
                date_item .setFlags (Qt .NoItemFlags )
                self .posts_date_list_widget .addItem (date_item )

        self .posts_title_list_widget .blockSignals (False )
        self .posts_date_list_widget .blockSignals (False )

    def _handle_fetch_error (self ,creator_info ,error_message ):
        creator_name =creator_info .get ('name','Unknown Creator')
        if self .parent_app :
            self .parent_app .log_signal .emit (f"[CreatorPopup Fetch ERROR] For {creator_name }: {error_message }")

        self .posts_area_title_label .setText (self ._tr ("fetch_error_for_creator_label","Error fetching for {creator_name}").format (creator_name =creator_name ))


    def _handle_fetch_finished (self ):
        self .fetch_posts_button .setEnabled (True )
        self .progress_bar .setVisible (False )

        if not self .fetched_posts_data :
            if self .post_fetch_thread and self .post_fetch_thread .cancellation_flag .is_set ():
                 self .posts_area_title_label .setText (self ._tr ("post_fetch_cancelled_status_done","Post fetching cancelled."))
            else :
                 self .posts_area_title_label .setText (self ._tr ("failed_to_fetch_or_no_posts_label","Failed to fetch posts or no posts found."))
            self .posts_search_input .setVisible (False )
        elif not self .posts_title_list_widget .count ()and not self .posts_search_input .text ().strip ():
            self .posts_area_title_label .setText (self ._tr ("no_posts_found_for_selection","No posts found for selected creator(s)."))
            self .posts_search_input .setVisible (True )
        else :
            QTimer .singleShot (10 ,lambda :self .posts_content_splitter .setSizes ([int (self .posts_content_splitter .width ()*0.7 ),int (self .posts_content_splitter .width ()*0.3 )]))
            self .posts_search_input .setVisible (True )

    def _handle_posts_select_all (self ):
        self .posts_title_list_widget .blockSignals (True )
        for i in range (self .posts_title_list_widget .count ()):
            item =self .posts_title_list_widget .item (i )
            if item .flags ()&Qt .ItemIsUserCheckable :
                item .setCheckState (Qt .Checked )


                item_data =item .data (Qt .UserRole )
                if item_data :
                    post_unique_key =(
                    item_data ['service'],
                    str (item_data ['user_id']),
                    str (item_data ['id'])
                    )
                    self .globally_selected_post_ids .add (post_unique_key )
        self .posts_title_list_widget .blockSignals (False )

    def _handle_posts_deselect_all (self ):
        self .posts_title_list_widget .blockSignals (True )
        for i in range (self .posts_title_list_widget .count ()):
            item =self .posts_title_list_widget .item (i )
            if item .flags ()&Qt .ItemIsUserCheckable :
                item .setCheckState (Qt .Unchecked )
        self .globally_selected_post_ids .clear ()
        self .posts_title_list_widget .blockSignals (False )

    def _handle_post_item_check_changed (self ,item ):
        if not item or not item .data (Qt .UserRole ):
            return 

        item_data =item .data (Qt .UserRole )
        post_unique_key =(
        item_data ['service'],
        str (item_data ['user_id']),
        str (item_data ['id'])
        )

        if item .checkState ()==Qt .Checked :
            self .globally_selected_post_ids .add (post_unique_key )
        else :
            self .globally_selected_post_ids .discard (post_unique_key )

    def _handle_posts_add_selected_to_queue (self ):
        selected_posts_for_queue =[]
        if not self .globally_selected_post_ids :
            QMessageBox .information (self ,self ._tr ("no_selection_title","No Selection"),
            self ._tr ("select_posts_to_queue_message","Please select at least one post to add to the queue."))
            return 

        for post_key in self .globally_selected_post_ids :
            service ,user_id_str ,post_id_str =post_key 
            post_data_found =None 
            creator_key_for_fetched_data =(service ,user_id_str )


            if creator_key_for_fetched_data in self .fetched_posts_data :
                _unused_creator_info ,posts_in_list_for_creator =self .fetched_posts_data [creator_key_for_fetched_data ]
                for post_in_list in posts_in_list_for_creator :
                    if str (post_in_list .get ('id'))==post_id_str :
                        post_data_found =post_in_list 
                        break 

            if post_data_found :

                creator_info_original ,_unused_posts =self .fetched_posts_data .get (creator_key_for_fetched_data ,({},[]))
                creator_name =creator_info_original .get ('name','Unknown Creator')if creator_info_original else 'Unknown Creator'

                domain =self ._get_domain_for_service (service )
                post_url =f"https://{domain }/{service }/user/{user_id_str }/post/{post_id_str }"
                queue_item ={
                'type':'single_post_from_popup',
                'url':post_url ,
                'name':post_data_found .get ('title',self ._tr ('untitled_post_placeholder','Untitled Post')),
                'name_for_folder':creator_name ,
                'service':service ,
                'user_id':user_id_str ,
                'post_id':post_id_str 
                }
                selected_posts_for_queue .append (queue_item )
            else :




                if self .parent_app and hasattr (self .parent_app ,'log_signal'):
                    self .parent_app .log_signal .emit (f"⚠️ Could not find full post data for selected key: {post_key } when adding to queue.")

                else :
                    domain =self ._get_domain_for_service (service )
                    post_url =f"https://{domain }/{service }/user/{user_id_str }/post/{post_id_str }"
                    queue_item ={
                    'type':'single_post_from_popup',
                    'url':post_url ,
                    'name':f"post id {post_id_str }",
                    'name_for_folder':user_id_str ,
                    'service':service ,
                    'user_id':user_id_str ,
                    'post_id':post_id_str 
                    }
                    selected_posts_for_queue .append (queue_item )

        if selected_posts_for_queue :
            if self .parent_app and hasattr (self .parent_app ,'favorite_download_queue'):
                for qi in selected_posts_for_queue :
                    self .parent_app .favorite_download_queue .append (qi )

                num_just_added_posts =len (selected_posts_for_queue )
                total_in_queue =len (self .parent_app .favorite_download_queue )

                self .parent_app .log_signal .emit (f"ℹ️ Added {num_just_added_posts } selected posts to the download queue. Total in queue: {total_in_queue }.")

                if self .parent_app .link_input :
                    self .parent_app .link_input .setText (
                    self .parent_app ._tr ("popup_posts_selected_text","Posts - {count} selected").format (count =num_just_added_posts )
                    )
                    self .parent_app .link_input .setPlaceholderText (
                    self .parent_app ._tr ("items_in_queue_placeholder","{count} items in queue from popup.").format (count =total_in_queue )
                    )
            
            self.selected_creators_for_queue.clear()
            
            self .accept ()
        else :
            QMessageBox .information (self ,self ._tr ("no_selection_title","No Selection"),
            self ._tr ("select_posts_to_queue_message","Please select at least one post to add to the queue."))

    def _handle_posts_close_view (self ):
        self .right_pane_widget .hide ()
        self .main_splitter .setSizes ([self .width (),0 ])
        
        if hasattr (self ,'_handle_post_item_check_changed'):
            try:
                self .posts_title_list_widget .itemChanged .disconnect (self ._handle_post_item_check_changed )
            except TypeError:
                pass
        
        self .posts_search_input .setVisible (False )
        self .posts_search_input .clear ()
        self .globally_selected_post_ids .clear ()
        self .add_selected_button .setEnabled (True )
        self .setWindowTitle (self ._tr ("creator_popup_title","Creator Selection"))

    def _get_domain_for_service (self ,service_name ):
        """Determines the base domain for a given service."""
        service_lower =service_name .lower ()
        if service_lower in ['onlyfans','fansly']:
            return "coomer.su"
        return "kemono.cr"

    def _handle_add_selected (self ):
        """Gathers globally selected creators and processes them."""
        selected_display_names =[]
        self .selected_creators_for_queue .clear ()
        for creator_data in self .globally_selected_creators .values ():
            creator_name =creator_data .get ('name')
            self .selected_creators_for_queue .append (creator_data )
            if creator_name :
                selected_display_names .append (creator_name )

        if selected_display_names :
            main_app_window =self .parent ()
            if hasattr (main_app_window ,'link_input'):
                main_app_window .link_input .setText (", ".join (selected_display_names ))
            self .accept ()
        else :
            QMessageBox .information (self ,"No Selection","No creators selected to add.")

    def _handle_item_check_changed (self ,item ):
        """Updates the globally_selected_creators dict when an item's check state changes."""
        creator_data =item .data (Qt .UserRole )
        if not isinstance (creator_data ,dict ):
            return 

        service =creator_data .get ('service')
        creator_id =creator_data .get ('id')

        if service is None or creator_id is None :
            print (f"Warning: Creator data in list item missing service or id: {creator_data .get ('name')}")
            return 

        unique_key =(str (service ),str (creator_id ))

        if item .checkState ()==Qt .Checked :
            self .globally_selected_creators [unique_key ]=creator_data 
        else :
            if unique_key in self .globally_selected_creators :
                del self .globally_selected_creators [unique_key ]
        self .fetch_posts_button .setEnabled (bool (self .globally_selected_creators ))
