import os
import time
import json
from PyQt5.QtCore import Qt, QStandardPaths, QTimer
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QVBoxLayout, QSplitter, QWidget, QGroupBox,
    QFileDialog, QMessageBox
)
from ...i18n.translator import get_translation
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme


class DownloadHistoryDialog (QDialog ):
    """Dialog to display download history."""
    def __init__ (self ,last_3_downloaded_entries ,first_processed_entries ,parent_app ,parent =None ):
        super ().__init__ (parent )
        self .parent_app =parent_app 
        self .last_3_downloaded_entries =last_3_downloaded_entries 
        self .first_processed_entries =first_processed_entries 
        self .setModal (True )
        self._apply_theme()
        creator_name_cache = getattr(parent_app, 'creator_name_cache', None)
        if creator_name_cache:
            for entry in self.last_3_downloaded_entries:
                if not entry.get('creator_display_name'):
                    service = entry.get('service', '').lower()
                    user_id = str(entry.get('user_id', ''))
                    key = (service, user_id)
                    entry['creator_display_name'] = creator_name_cache.get(key, entry.get('folder_context_name', 'Unknown Creator/Series'))
            for entry in self.first_processed_entries:
                if not entry.get('creator_name'):
                    service = entry.get('service', '').lower()
                    user_id = str(entry.get('user_id', ''))
                    key = (service, user_id)
                    entry['creator_name'] = creator_name_cache.get(key, entry.get('user_id', 'Unknown'))

        app_icon =get_app_icon_object ()
        if not app_icon .isNull ():
            self .setWindowIcon (app_icon )

        screen_height =QApplication .primaryScreen ().availableGeometry ().height ()if QApplication .primaryScreen ()else 768 
        scale_factor =screen_height /768.0 
        base_min_w ,base_min_h =600 ,450 

        scaled_min_w =int (base_min_w *1.5 *scale_factor )
        scaled_min_h =int (base_min_h *scale_factor )
        self .setMinimumSize (scaled_min_w ,scaled_min_h )

        self .setWindowTitle (self ._tr ("download_history_dialog_title_combined","Download History"))


        dialog_layout =QVBoxLayout (self )
        self .setLayout (dialog_layout )


        self .main_splitter =QSplitter (Qt .Horizontal )
        dialog_layout .addWidget (self .main_splitter )


        left_pane_widget =QWidget ()
        left_layout =QVBoxLayout (left_pane_widget )
        left_header_label =QLabel (self ._tr ("history_last_downloaded_header","Last 3 Files Downloaded:"))
        left_header_label .setAlignment (Qt .AlignCenter )
        left_layout .addWidget (left_header_label )

        left_scroll_area =QScrollArea ()
        left_scroll_area .setWidgetResizable (True )
        left_scroll_content_widget =QWidget ()
        left_scroll_layout =QVBoxLayout (left_scroll_content_widget )

        if not self .last_3_downloaded_entries :
            no_left_history_label =QLabel (self ._tr ("no_download_history_header","No Downloads Yet"))
            no_left_history_label .setAlignment (Qt .AlignCenter )
            left_scroll_layout .addWidget (no_left_history_label )
        else :
            for entry in self .last_3_downloaded_entries :
                group_box =QGroupBox (f"{self ._tr ('history_file_label','File:')} {entry .get ('disk_filename','N/A')}")
                group_layout =QVBoxLayout (group_box )
                details_text =(
                f"<b>{self ._tr ('history_from_post_label','From Post:')}</b> {entry .get ('post_title','N/A')} (ID: {entry .get ('post_id','N/A')})<br>"
                f"<b>{self ._tr ('history_creator_series_label','Creator/Series:')}</b> {entry .get ('creator_display_name','N/A')}<br>"
                f"<b>{self ._tr ('history_post_uploaded_label','Post Uploaded:')}</b> {entry .get ('upload_date_str','N/A')}<br>"
                f"<b>{self ._tr ('history_file_downloaded_label','File Downloaded:')}</b> {time .strftime ('%Y-%m-%d %H:%M:%S',time .localtime (entry .get ('download_timestamp',0 )))}<br>"
                f"<b>{self ._tr ('history_saved_in_folder_label','Saved In Folder:')}</b> {entry .get ('download_path','N/A')}"
                )
                details_label =QLabel (details_text )
                details_label .setWordWrap (True )
                details_label .setTextFormat (Qt .RichText )
                group_layout .addWidget (details_label )
                left_scroll_layout .addWidget (group_box )
        left_scroll_area .setWidget (left_scroll_content_widget )
        left_layout .addWidget (left_scroll_area )
        self .main_splitter .addWidget (left_pane_widget )


        right_pane_widget =QWidget ()
        right_layout =QVBoxLayout (right_pane_widget )
        right_header_label =QLabel (self ._tr ("first_files_processed_header","First {count} Posts Processed This Session:").format (count =len (self .first_processed_entries )))
        right_header_label .setAlignment (Qt .AlignCenter )
        right_layout .addWidget (right_header_label )

        right_scroll_area =QScrollArea ()
        right_scroll_area .setWidgetResizable (True )
        right_scroll_content_widget =QWidget ()
        right_scroll_layout =QVBoxLayout (right_scroll_content_widget )

        if not self .first_processed_entries :
            no_right_history_label =QLabel (self ._tr ("no_processed_history_header","No Posts Processed Yet"))
            no_right_history_label .setAlignment (Qt .AlignCenter )
            right_scroll_layout .addWidget (no_right_history_label )
        else :
            for entry in self .first_processed_entries :

                group_box =QGroupBox (f"{self ._tr ('history_post_label','Post:')} {entry .get ('post_title','N/A')} (ID: {entry .get ('post_id','N/A')})")
                group_layout =QVBoxLayout (group_box )
                details_text =(
                f"<b>{self ._tr ('history_creator_label','Creator:')}</b> {entry .get ('creator_name','N/A')}<br>"
                f"<b>{self ._tr ('history_top_file_label','Top File:')}</b> {entry .get ('top_file_name','N/A')}<br>"
                f"<b>{self ._tr ('history_num_files_label','Num Files in Post:')}</b> {entry .get ('num_files',0 )}<br>"
                f"<b>{self ._tr ('history_post_uploaded_label','Post Uploaded:')}</b> {entry .get ('upload_date_str','N/A')}<br>"
                f"<b>{self ._tr ('history_processed_on_label','Processed On:')}</b> {time .strftime ('%Y-%m-%d %H:%M:%S',time .localtime (entry .get ('download_date_timestamp',0 )))}<br>"
                f"<b>{self ._tr ('history_saved_to_folder_label','Saved To Folder:')}</b> {entry .get ('download_location','N/A')}"
                )
                details_label =QLabel (details_text )
                details_label .setWordWrap (True )
                details_label .setTextFormat (Qt .RichText )
                group_layout .addWidget (details_label )
                right_scroll_layout .addWidget (group_box )
        right_scroll_area .setWidget (right_scroll_content_widget )
        right_layout .addWidget (right_scroll_area )
        self .main_splitter .addWidget (right_pane_widget )


        QTimer .singleShot (0 ,lambda :self .main_splitter .setSizes ([self .width ()//2 ,self .width ()//2 ]))


        bottom_button_layout =QHBoxLayout ()
        self .save_history_button =QPushButton (self ._tr ("history_save_button_text","Save History to .txt"))
        self .save_history_button .clicked .connect (self ._save_history_to_txt )
        bottom_button_layout .addStretch (1 )
        bottom_button_layout .addWidget (self .save_history_button )

        dialog_layout .addLayout (bottom_button_layout )

        if self .parent_app and hasattr (self .parent_app ,'get_dark_theme')and self .parent_app .current_theme =="dark":
            self .setStyleSheet (self .parent_app .get_dark_theme ())

    def _tr (self ,key ,default_text =""):
        if callable (get_translation )and self .parent_app :
            return get_translation (self .parent_app .current_selected_language ,key ,default_text )
        return default_text 

    def _apply_theme(self):
        """Applies the current theme from the parent application."""
        if self.parent_app and self.parent_app.current_theme == "dark":
            scale = getattr(self.parent_app, 'scale_factor', 1)
            self.setStyleSheet(get_dark_theme(scale))
        else:
            self.setStyleSheet("QDialog { background-color: #f0f0f0; }")

    def _save_history_to_txt (self ):
        if not self .last_3_downloaded_entries and not self .first_processed_entries :
            QMessageBox .information (self ,self ._tr ("no_download_history_header","No Downloads Yet"),
            self ._tr ("history_nothing_to_save_message","There is no history to save."))
            return 

        main_download_dir =self .parent_app .dir_input .text ().strip ()
        default_save_dir =""
        if main_download_dir and os .path .isdir (main_download_dir ):
            default_save_dir =main_download_dir 
        else :
            fallback_dir =QStandardPaths .writableLocation (QStandardPaths .DocumentsLocation )
            if fallback_dir and os .path .isdir (fallback_dir ):
                default_save_dir =fallback_dir 
            else :
                default_save_dir =self .parent_app .app_base_dir 

        default_filepath =os .path .join (default_save_dir ,"download_history.txt")

        filepath ,_ =QFileDialog .getSaveFileName (
        self ,self ._tr ("history_save_dialog_title","Save Download History"),
        default_filepath ,"Text Files (*.txt);;All Files (*)"
        )

        if not filepath :
            return 

        history_content =[]
        history_content .append (f"{self ._tr ('history_last_downloaded_header','Last 3 Files Downloaded:')}\n")
        if self .last_3_downloaded_entries :
            for entry in self .last_3_downloaded_entries :
                history_content .append (f"  {self ._tr ('history_file_label','File:')} {entry .get ('disk_filename','N/A')}")
                history_content .append (f"    {self ._tr ('history_from_post_label','From Post:')} {entry .get ('post_title','N/A')} (ID: {entry .get ('post_id','N/A')})")
                history_content .append (f"    {self ._tr ('history_creator_series_label','Creator/Series:')} {entry .get ('creator_display_name','N/A')}")
                history_content .append (f"    {self ._tr ('history_post_uploaded_label','Post Uploaded:')} {entry .get ('upload_date_str','N/A')}")
                history_content .append (f"    {self ._tr ('history_file_downloaded_label','File Downloaded:')} {time .strftime ('%Y-%m-%d %H:%M:%S',time .localtime (entry .get ('download_timestamp',0 )))}")
                history_content .append (f"    {self ._tr ('history_saved_in_folder_label','Saved In Folder:')} {entry .get ('download_path','N/A')}\n")
        else :
            history_content .append (f"  ({self ._tr ('no_download_history_header','No Downloads Yet')})\n")

        history_content .append (f"\n{self ._tr ('first_files_processed_header','First {count} Posts Processed This Session:').format (count =len (self .first_processed_entries ))}\n")
        if self .first_processed_entries :
            for entry in self .first_processed_entries :
                history_content .append (f"  {self ._tr ('history_post_label','Post:')} {entry .get ('post_title','N/A')} (ID: {entry .get ('post_id','N/A')})")
                history_content .append (f"    {self ._tr ('history_creator_label','Creator:')} {entry .get ('creator_name','N/A')}")
                history_content .append (f"    {self ._tr ('history_top_file_label','Top File:')} {entry .get ('top_file_name','N/A')}")
                history_content .append (f"    {self ._tr ('history_num_files_label','Num Files in Post:')} {entry .get ('num_files',0 )}")
                history_content .append (f"    {self ._tr ('history_post_uploaded_label','Post Uploaded:')} {entry .get ('upload_date_str','N/A')}")
                history_content .append (f"    {self ._tr ('history_processed_on_label','Processed On:')} {time .strftime ('%Y-%m-%d %H:%M:%S',time .localtime (entry .get ('download_date_timestamp',0 )))}")
                history_content .append (f"    {self ._tr ('history_saved_to_folder_label','Saved To Folder:')} {entry .get ('download_location','N/A')}\n")
        else :
            history_content .append (f"  ({self ._tr ('no_processed_history_header','No Posts Processed Yet')})\n")

        try :
            with open (filepath ,'w',encoding ='utf-8')as f :
                f .write ("\n".join (history_content ))
            QMessageBox .information (self ,self ._tr ("history_export_success_title","History Export Successful"),
            self ._tr ("history_export_success_message","Successfully exported download history to:\n{filepath}").format (filepath =filepath ))
        except Exception as e :
            QMessageBox .critical (self ,self ._tr ("history_export_error_title","History Export Error"),
            self ._tr ("history_export_error_message","Could not export download history: {error}").format (error =str (e )))