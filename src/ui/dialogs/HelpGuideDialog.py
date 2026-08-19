import os
import sys
from PySide6.QtCore import QUrl, QSize, Qt
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QStackedWidget, QListWidget, QFrame, QWidget, QScrollArea
)
from ..assets import get_app_icon_object
from ...utils.resolution import get_dark_theme

class TourStepWidget(QWidget):
    """
    A custom widget representing a single step or page in the feature guide.
    It neatly formats a title and its corresponding content.
    """
    def __init__(self, title_text, content_text, parent=None, scale=1.0):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title_font_size = int(14 * scale)
        content_font_size = int(11 * scale)

        title_label = QLabel(title_text)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"font-size: {title_font_size}pt; font-weight: bold; color: #87CEEB; padding-bottom: 15px;")
        layout.addWidget(title_label)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("background-color: transparent;")

        content_label = QLabel(content_text)
        content_label.setWordWrap(True)
        content_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content_label.setTextFormat(Qt.TextFormat.RichText)
        content_label.setOpenExternalLinks(True)
        content_label.setStyleSheet(f"font-size: {content_font_size}pt; color: #C8C8C8; line-height: 1.5;")
        scroll_area.setWidget(content_label)
        layout.addWidget(scroll_area, 1)


class HelpGuideDialog(QDialog):
    """A multi-page dialog for displaying the feature guide with a navigation list."""
    
    def __init__(self, steps_data, parent_app, parent=None):
        super().__init__(parent_app) 
        
        self.parent_app = parent_app
        

        self.steps_data = [
            ("Welcome!",
             """
             <p style='font-size: 12pt;'>Welcome to the Kemono Downloader! This guide will walk you through the key features to get you started.</p>
             
             <h3 style='color: #E0E0E0;'>Wide Range of Support</h3>
             <p>This application provides full, direct download support for several popular sites, including:</p>
             <ul>
                 <li>Kemono</li>
                 <li>Coomer</li>
                 <li>Bunkr</li>
                 <li>Erome</li>
                 <li>Saint2.su</li>
                 <li>nhentai.net/</li>
                 <li>fap-nation.org/</li>
                 <li>Discord</li>
                 <li>allporncomic.com</li>
                 <li>hentai2read.com</li>
                 <li>mangadex.org</li>
                 <li>Simpcity</li>
                 <li>gelbooru.com</li>
                 <li>Toonily.com</li>                 
             </ul>
             
             <h3 style='color: #E0E0E0;'>Powerful Batch Mode</h3>
             <p>Save time by downloading hundreds of URLs at once. Simply type <b>nhentai.net</b> or <b>saint2.su</b> into the URL bar. The app will look for a <b>nhentai.txt</b> or <b>saint2.su.txt</b> file in your 'appdata' folder and process all the URLs inside it.</p>
             
             <h3 style='color: #E0E0E0;'>Advanced Discord Support</h3>
             <p>Go beyond simple file downloading. The app can connect directly to the Discord API to:</p>
             <ul>
                 <li>Download all files from a specific channel.</li>
                 <li>Save an entire channel's message history as a fully formatted PDF.</li>
             </ul>
             """),
            
            ("Advanced Filtering",
             """
             <p>Control exactly what content you download, from broad categories to specific keywords.</p>
             
             <h3 style='color: #E0E0E0;'>Content Type Filters</h3>
             <p>These radio buttons let you select the main <i>type</i> of content you want:</p>
             <ul>
                 <li><b>All:</b> Downloads everything (default).</li>
                 <li><b>Images/GIFs:</b> Only downloads static images and GIFs.</li>
                 <li><b>Videos:</b> Only downloads video files (MP4, WEBM, MOV, etc.).</li>
                 <li><b>Only Archives:</b> Exclusively downloads .zip and .rar files.</li>
                 <li><b>Only Links:</b> Extracts external links (Mega, Google Drive) from post descriptions instead of downloading.</li>
                 <li><b>Only Audio:</b> Only downloads audio files (MP3, WAV, etc.).</li>
                 <li><b>More:</b> Opens a dialog to download post descriptions or comments as text/PDF.</li>
             </ul>
             
             <h3 style='color: #E0E0E0;'>Character Filtering</h3>
             <p>The <b>"Filter by Character(s)"</b> input is your most powerful tool for targeting content.</p>
             <ul>
                 <li><b>Basic Use:</b> Enter names, separated by commas (e.g., <code>Tifa, Aerith</code>). This will create folders for "Tifa" and "Aerith" and download posts matching those names.</li>
                 <li><b>Grouped Aliases:</b> Use parentheses to group aliases for a single character (e.g., <code>(Tifa, Lockhart)</code>). This still creates a "Tifa" folder, but it will also match posts that just say "Lockhart".</li>
             </ul>
             <p>The <b>"Filter: [Scope]"</b> button changes <i>what</i> is scanned:</p>
             <ul>
                 <li><b>Filter: Title (Default):</b> Scans only the post's main title.</li>
                 <li><b>Filter: Files:</b> Scans the <i>filenames</i> within the post.</li>
                 <li><b>Filter: Both:</b> Scans both the title and the filenames.</li>
                 <li><b>Filter: Comments (Beta):</b> Scans the post's comment section for the keywords.</li>
             </ul>
             
             <h3 style='color: #E0E0E0;'>Skip Filters (Avoid Content)</h3>
             <p>The <b>"Skip with Words"</b> input lets you avoid content you don't want.</p>
             <p>The <b>"Scope: [Scope]"</b> button changes <i>how</i> it skips:</p>
             <ul>
                 <li><b>Scope: Posts (Default):</b> Skips the <i>entire post</i> if the post's title contains a skip word (e.g., <code>WIP, sketch</code>).</li>
                 <li><b>Scope: Files:</b> Scans and skips <i>individual files</i> if their filename contains a skip word.</li>
                 <li><b>Scope: Both:</b> Skips the post if the title matches, and if not, still checks individual files.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Other Content Options</h3>
             <ul>
                 <li><b>Skip .zip:</b> A quick toggle to ignore all archive files.</li>
                 <li><b>Download Thumbnails Only:</b> Downloads the small preview image instead of the full-resolution file.</li>
                 <li><b>Scan Content for Images:</b> Scans the post's text description for <code>&lt;img&gt;</code> tags. Useful for embedded images not in the post's attachment list.</li>
                 <li><b>Keep Duplicates:</b> By default, the app skips files with identical content (hash). Check this to open a dialog and configure it to keep duplicate files.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Filename Control</h3>
             <p>The <b>"Remove Words from name"</b> input cleans up filenames. Any text you enter here (comma-separated) will be removed from the final saved filename (e.g., <code>patreon, exclusive</code>).</p>
             """),
            
            ("Folder Management (Known.txt)",
             """
             <p>This feature, enabled by the <b>"Separate Folders by Known.txt"</b> checkbox, automatically sorts your downloads. It's designed mainly for <b>Kemono</b>, where creators often tag posts with character names in the title.</p>
             
             <p>When you download from a creator, this feature checks each <b>post title</b> against your `Known.txt` list. If a name matches, a folder is created for that name, and all posts from that creator mentioning the name will be <b>grouped together</b> in that single folder.</p>

             <h3 style='color: #E0E0E0;'>Folder Naming Priority</h3>
             <p>When "Separate Folders" is checked, the app uses this priority to name folders:</p>
             <ol>
                 <li><b>Character Filter:</b> If you use the <b>"Filter by Character(s)"</b> input (e.g., <code>Tifa</code>), that name is <b>always</b> used as the folder name. This overrides all other rules.</li>
                 <li><b>Known.txt (Post Title):</b> If no filter is used, it checks the <b>post's title</b> for a name in `Known.txt`. (This is the most common use case).</li>
                 <li><b>Known.txt (Filename):</b> If the title doesn't match, it checks all <b>filenames</b> in the post for a match in `Known.txt`.</li>
                 <li><b>Fallback:</b> If no match is found, it creates a generic folder from the post's title.</li>
             </ol>
             
             <h3 style='color: #E0E0E0;'>Editing Your Known.txt File</h3>
             <p>You can manage this list using the panel on the right of the main window or by clicking <b>"Open Known.txt"</b> to edit it directly. There are two formats:</p>
             <ul>
                 <li><b>Simple Name:</b><br>
                     <code>Tifa</code><br>
                     This creates a folder named "Tifa" and matches posts/files named "Tifa".
                 </li>
                 <br>
                 <li><b>Grouped Aliases:</b><br>
                     <code>(Tifa, Lockhart)</code><br>
                     This is the most powerful format. It creates a folder named <b>"Tifa Lockhart"</b> and will match posts/files that contain either "Tifa" <i>or</i> "Lockhart". This is perfect for characters with multiple names.
                 </li>
             </ul>
             
             <h3 style='color: #E0E0E0;'>Important Note:</h3>
             <p>This automatic sorting <b>only works if the creator includes the character names or keywords in the post title</b> (or filename). If they don't, the app has no way of knowing how to sort the post, and it will fall back to a generic folder name.</p>
             """),
            
            ("Renaming Mode",
             """
             <p>This mode is designed for downloading comics, manga, or any multi-file post where you need files to be in a specific, sequential order. When active, it downloads posts from <b>oldest to newest</b>.</p>
             
             <p>Activate it by checking the <b>"Renaming Mode"</b> checkbox. This reveals a new button: <b>"Name: [Style]"</b>. Clicking this button cycles through all available naming conventions.</p>
             
             <h3 style='color: #E0E0E0;'>Available Naming Styles</h3>
             <ul>
                 <li><b>Post Title:</b> (Default) Files are named after the post's title, with a number for multi-file posts (e.g., <code>My Comic Page_1.jpg</code>, <code>My Comic Page_2.jpg</code>).</li>
                 
                 <li><b>Date + Original:</b> Prepends the post's date to the original filename (e.g., <code>2025-11-16_original_file_name.jpg</code>).</li>
                 
                 <li><b>Date + Title:</b> Prepends the date to the post title (e.g., <code>2025-11-16_My Comic Page_1.jpg</code>).</li>

                 <li><b>Post ID:</b> Names files using the post's unique ID and the file index (e.g., <code>9876543_0.jpg</code>, <code>9876543_1.jpg</code>).</li>

                 <li><b>Date Based:</b> Renames all files to a simple, sequential number (e.g., <code>001.jpg</code>, <code>002.jpg</code>). You can add a prefix in the text box that appears (e.g., "Chapter 1 " to get <code>Chapter 1 001.jpg</code>).
                 <br><b style='color: #f0ad4e;'>Note: This mode disables multithreading to guarantee correct file order.</b></li>

                 <li><b>Title + G.Num (Global Numbering):</b> Names files by title, but with a *global* counter (e.g., <code>Post A_001.jpg</code>, <code>Post B_002.jpg</code>).
                 <br><b style='color: #f0ad4e;'>Note: This mode also disables multithreading.</b></li>
                 
                 <li><b>Custom:</b> Lets you design your own filename using a format string. A <b>"..."</b> button will appear to open the custom format dialog.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Custom Format Placeholders</h3>
             <p>When using the "Custom" style, you can use these placeholders (click the buttons in the dialog to add them):</p>
             <ul>
                <li><code>{id}</code> - The unique ID of the post.</li>
                <li><code>{creator_name}</code> - The creator's name.</li>
                <li><code>{service}</code> - The service (e.g., Patreon, Pixiv Fanbox, etc).</li>
                <li><code>{title}</code> - The title of the post.</li>
                <li><code>{added}</code> - Date the post was added.</li>
                <li><code>{published}</code> - Date the post was published.</li>
                <li><code>{edited}</code> - Date the post was last edited.</li>
                <li><code>{name}</code> - The original name of the file.</li>
             </ul>
             <p>You can also set a custom <b>Date Format</b> (e.g., <code>YYYY-MM-DD</code>) that will apply to the {added}, {published}, and {edited} placeholders.</p>
             """),

            ("Batch Downloading",
             """
             <p>This feature allows you to download hundreds of URLs from a text file, which is much faster than queuing them one by one.</p>
             
             <h3 style='color: #E0E0E0;'>How It Works (Step-by-Step)</h3>
             <ol>
                 <li><b>Find your 'appdata' folder:</b> This is in the same directory as the downloader's <code>.exe</code> file.</li>
                 <li><b>Create a .txt file:</b> Inside the 'appdata' folder, create a text file for the site you want to batch from. The name must be exact. (eg.. nhentai.txt, hentai2read.txt, etc.. )</li>
                 <li><b>Add URLs:</b> Open the <code>.txt</code> file and paste one download URL on each line. Save the file.</li>
                 <li><b>Start the Batch:</b> In the downloader's main URL bar, type the <b>site's domain name</b> (e.g., <code>nhentai.net</code>) and click "Start Download".</li>
             </ol>
             <p>The app will automatically find your text file, read all the URLs, and download them sequentially.</p>

             <h3 style='color: #E0E0E0;'>Supported Sites and Filenames</h3>
             <p>The <code>.txt</code> file name must match the site you are triggering:</p>
             <ul>
                 <li><b>To trigger, type:</b> <code>allporncomic.com</code><br>
                     <b>Text file name:</b> <code>allporncomic.txt</code></li>
                 
                 <li><b>To trigger, type:</b> <code>nhentai.net</code><br>
                     <b>Text file name:</b> <code>nhentai.txt</code></li>
                 
                 <li><b>To trigger, type:</b> <code>fap-nation.com</code> or <code>fap-nation.org</code><br>
                     <b>Text file name:</b> <code>fap-nation.txt</code></li>
                 
                 <li><b>To trigger, type:</b> <code>saint2.su</code><br>
                     <b>Text file name:</b> <code>saint2.su.txt</code></li>
                 
                 <li><b>To trigger, type:</b> <code>hentai2read.com</code><br>
                     <b>Text file name:</b> <code>hentai2read.txt</code></li>
                 
                 <li><b>To trigger, type:</b> <code>rule34video.com</code><br>
                     <b>Text file name:</b> <code>rule34video.txt</code></li>
             </ul>
             """),

            ("Special Modes: Text & Links",
             """
             <p>These two modes completely change the downloader's function from downloading files to extracting information.</p>
             
             <h3 style='color: #E0E0E0;'>🔗 Only Links Mode</h3>
             <p>When you select this, the app <b>stops downloading files</b>. Instead, it scans the post's description for any external URLs (like Mega, Google Drive, Dropbox, etc.) and lists them in the main log.</p>
             <p>This mode also reveals a new set of tools above the log:</p>
             <ul>
                 <li><b>Search Bar:</b> Lets you filter the extracted links by keyword (e.g., "mega", "part 1").</li>
                 <li><b>Export Links Button:</b> Opens a dialog to save all the found links to a <code>.txt</code> file.</li>
                 <li><b>Download Button:</b> Opens a new dialog that lets you selectively download from the supported links (Mega, Google Drive, Dropbox) that were found.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>📄 More (Text Export Mode)</h3>
             <p>This mode downloads the <b>text content</b> from posts instead of the files. When you select it, a dialog appears asking for more details:</p>
             <ul>
                 <li><b>Scope:</b>
                     <ul>
                         <li><b>Description/Content:</b> Saves the text from the post's main body.</li>
                         <li><b>Comments:</b> Fetches and saves all the comments from the post.</li>
                     </ul>
                 </li>
                 <li><b>Export as:</b> You can choose to save the text as a <b>PDF</b>, <b>DOCX</b>, or <b>TXT</b> file.</li>
                 <li><b>Single PDF:</b> (Only available for PDF format) This powerful option stops the app from saving individual PDF files. Instead, it collects the text from <i>all</i> matching posts, sorts them by date, and compiles them into <b>one single, large PDF file</b> at the end of the download session.</li>
             </ul>
             """),

            ("Add to Queue",
             """
             <p>This feature allows you to queue up multiple distinct downloads with different settings and run them all sequentially.</p>

             <h3 style='color: #E0E0E0;'>Step 1: Prepare the Download</h3>
             <p>Before clicking add, configure the download exactly how you want it processed for this specific link:</p>
             <ul>
                 <li><b>Select Directory:</b> Choose where you want the files to go.</li>
                 <li><b>Configure Options:</b> Check/uncheck boxes (e.g., "Separate Folders", "Use Cookie", "Manga Mode").</li>
                 <li><b>Paste URL:</b> Enter the link for the creator or post you want to download.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Step 2: Add to Queue</h3>
             <ol>
                 <li>Click the <b>Add to Queue</b> button (located near the Start Download).</li>
                 <li><b>Confirmation:</b> You will see a popup message and the log will print <code>✅ Job added to queue</code>.</li>
                 <li>The URL box will clear, allowing you to immediately paste the next link.</li>
             </ol>

             <h3 style='color: #E0E0E0;'>Step 3: Repeat & Start</h3>
             <p>You can repeat steps 1 and 2 as many times as you like. You can even change settings (like the download folder) between adds; the queue remembers the specific settings for each individual link.</p>
             <p>To start processing the queue:</p>
             <ol>
                 <li>In the Link Input box, type exactly: <code>start queue</code></li>
                 <li>The main "Start Download" button will change to <b>"Execute Queue"</b>.</li>
                 <li>Click that button to begin.</li>
             </ol>

             <h3 style='color: #E0E0E0;'>Processing Behavior</h3>
             <p>Once started, the app will lock the UI, load the first job, download it until finished, and automatically move to the next until the queue is empty.</p>

             <h3 style='color: #E0E0E0;'>Special Case: Creator Selection Popup</h3>
             <p>If you use the <b>Creator Selection</b> popup (the 🎨 button):</p>
             <ul>
                 <li>Select multiple creators in that popup and click <b>"Queue Selected"</b>.</li>
                 <li>The app internally adds them to a temporary list.</li>
                 <li>When you click the main <b>"Add to Queue"</b> button on the main window, it will detect that list and automatically bulk-create job files for all the creators you selected.</li>
             </ul>
             """),

            ("Special Commands",
             """
             <p>You can add special commands to the <b>"Filter by Character(s)"</b> input field to change download behavior for a single task. Commands are keywords wrapped in square brackets <code>[]</code>.</p>
             <p><b>Example:</b> <code>Tifa, (Cloud, Zack) [ao] [sfp-10]</code></p>
             
             <h3 style='color: #E0E0E0;'>Filter Commands (in "Filter by Character(s)" input)</h3>
             <ul>
                 <li><b><code>[ao]</code> (Archive Only Priority)</b><br>
                 This command prioritizes archives.
                 <ul>
                    <li>If a post contains <b>only images/videos</b>, it will download them normally.</li>
                    <li>If a post contains <b>both archives AND images/videos</b>, this command tells the app to <b>only download the archives</b> and skip the other files for that post.</li>
                 </ul>
                 </li>
                 <br>
                 <li><b><code>[sfp-N]</code> (Subfolder Per Post Threshold)</b><br>
                 This is an override for when "Subfolder per Post" is <b>OFF</b> (and "Separate Folders by Known.txt" is <b>ON</b>).<br>
                 For example, if you set <code>[sfp-10]</code>:
                 <ul>
                    <li>Posts with <b>less than 10 files</b> will download normally into the main folder (e.g., <code>/ArtistName/</code>).</li>
                    <li>When a post with <b>10 or more files</b> is found, this command will <b>force a subfolder to be created for that one post</b> (e.g., <code>/ArtistName/Comic_Title/</code>) to keep its files grouped together.</li>
                 </ul>
                 </li>
                 <br>
                 <li><b><code>[unknown]</code> (Handle Unknown)</b><br>
                 Changes how sorting works when "Separate Folders by Known.txt" is on. If a post title doesn't match any name in your <code>Known.txt</code> list, this command will create a folder using the post's title instead of a generic fallback folder.
                 </li>
                 <br>
                 <li><b><code>[.domain]</code> (Domain Override)</b><br>
                 An advanced command. For example, <code>[.st]</code> forces the app to download from <code>coomer.st</code>, and <code>[.cr]</code> forces it to download from <code>kemono.cr</code>. This can be useful if one domain is blocked or slow.
                 </li>
             </ul>

             <h3 style='color: #E0E0E0;'>Skip Command (in "Skip with Words" input)</h3>
             <p>This command is different and goes into the <b>"Skip with Words"</b> input field, along with any other skip words.</p>
             <ul>
                 <li><b><code>[N]</code> (Skip File by Size)</b><br>
                 This command skips any file that is <b>smaller</b> than <code>N</code> megabytes (MB).<br>
                 <b>Example:</b> Entering <code>WIP, sketch, [200]</code> into the "Skip with Words" input will skip files with "WIP" or "sketch" in their name, AND it will also skip any file smaller than 200MB.
                 </li>
             </ul>
             """),

            ("Cloud Storage & Direct Links",
             """
             <p>The downloader has built-in support for popular cloud storage and direct-link sites. You can use this in two main ways.</p>
             
             <h3 style='color: #E0E0E0;'>Method 1: Direct URL Download</h3>
             <p>You can paste a direct link from these services into the main URL bar and hit "Start Download" just like a Kemono link.</p>
             <ul>
                 <li><b>Pixeldrain:</b> Supports single files (<code>/u/...</code>), albums (<code>/l/...</code>), and folders (<code>/d/...</code>).</li>
                 <li><b>Mega.nz:</b> Supports both single file links (<code>/file/...</code>) and folder links (<code>/folder/...</code>).</li>
                 <li><b>Gofile.io:</b> Supports folder links (<code>/d/...</code>).</li>
                 <li><b>Google Drive:</b> Supports shared folder links.</li>
                 <li><b>Dropbox:</b> Supports shared <code>.zip</code> file links. It will automatically download, extract, and delete the <code>.zip</code> file.</li>
             </ul>
             
             <h3 style='color: #E0E0E0;'>Method 2: "Only Links" Mode Downloader</h3>
             <p>This is a two-step process for handling posts that have many cloud links in their description.</p>
             <ol>
                 <li><b>Step 1: Extract Links</b><br>
                 Select the <b>"🔗 Only Links"</b> radio button and run a download on a creator or post page. The app will scan all posts and list the external links (Mega, GDrive, etc.) it finds in the log.
                 </li>
                 <br>
                 <li><b>Step 2: Download Links</b><br>
                 After extraction, a <b>"Download"</b> button (next to "Export Links") will become active. This opens a new window where you can selectively download from the supported links (Mega, Google Drive, Dropbox) that were found.
                 </li>
             </ol>

             <h3 style='color: #E0E0E0;'>Note: SimpCity Integration</h3>
             <p>SimpCity support relies heavily on this feature. When you download from a SimpCity thread, the app <b>automatically</b> scans the page for links to services like <b>Pixeldrain, Bunkr, Saint2, Mega, and Gofile</b> and then downloads them just as if you had put in those links directly. You can control which of these services are downloaded from the checkboxes in the "SimpCity Settings" section of the main window.</p>
             """), 

            ("Creator Selection & Updates",
             """
             <p>Clicking the <b>🎨 button</b> (next to the URL bar) opens the <b>Creator Selection</b> dialog. This is your control for managing creators you've already downloaded from.</p>

             <h3 style='color: #E0E0E0;'>Main List & Searching</h3>
             <p>The main list shows all creators from your <code>creators.json</code> file. You can:</p>
             <ul>
                 <li><b>Search:</b> The top search bar filters your creators by name, service, or even a direct URL.</li>
                 <li><b>Select:</b> Check the boxes next to creators to select them for an action.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Action Buttons</h3>
             
             <p><b>Check for Updates</b></p>
             <p>This button opens a new window, "Check for Updates," which lists all your <b>Creator Profiles</b> (the <code>.json</code> files saved in your <code>appdata/creator_profiles</code> folder). These profiles are created automatically when you download a full creator page.</p>
             <p>From this dialog, you can check multiple creators at once. The app will scan all of them and then show a final "Start Download" button on the main window to download <i>only</i> the new posts, using the same settings you used for each creator last time.</p>
             
             <p><b>Add Selected</b></p>
             <p>This is the simplest action. It takes all the creators you've checked, puts their names in the main URL bar, and closes the dialog. This is a quick way to add multiple creators to the download queue for a download.</p>
             
             <p><b>Fetch Posts</b></p>
             <p>This is a powerful tool for finding specific posts. When you click it:</p>
             <ol>
                <li>The dialog expands, and a new panel appears on the right.</li>
                <li>The app fetches <i>every single post</i> from all the creators you selected. This may take time.</li>
                <li>The right panel fills with a list of all posts, grouped by creator.</li>
                <li>You can now search this list and check the boxes next to the <i>individual posts</i> you want.</li>
                <li>Clicking <b>"Add Selected Posts to Queue"</b> adds only those specific posts to the download queue.</li>
             </ol>
             """),

            ("⭐ Favorite Mode",
             """
             <p>This mode is a powerful feature for downloading directly from your personal <b>Kemono</b> and <b>Coomer</b> favorites lists. It requires you to be logged in on your browser and to provide your cookies to the app.</p>
             
             <p><b style='color: #f0ad4e;'>Important:</b> You <b>must</b> check the <b>"Use Cookie"</b> box and provide a valid cookie for this mode to work. If cookies are missing or invalid, the app will show you a help dialog.</p>

             <h3 style='color: #E0E0E0;'>How to Use Favorite Mode</h3>
             <ol>
                 <li>Check the <b>"⭐ Favorite Mode"</b> checkbox on the main window. This will lock the URL bar and show two new buttons.</li>
                 <li>Click either <b>"🖼️ Favorite Artists"</b> or <b>"📄 Favorite Posts"</b>.</li>
                 <li>A new dialog will open and begin fetching all your favorites from both Kemono and Coomer at the same time.</li>
                 <li>Once loaded, you can search, filter, and select the artists or posts you want to download.</li>
                 <li>Click "Download Selected" to add them to the main download queue and begin processing.</li>
             </ol>
             
             <h3 style='color: #E0E0E0;'>Favorite Artists</h3>
             <p>The <b>"Favorite Artists"</b> dialog will load your list of followed creators. When you download from here, the app treats it as a full creator download, just as if you had pasted in that artist's URL.</p>
             
             <h3 style='color: #E0E0E0;'>Favorite Posts</h3>
             <p>The <b>"Favorite Posts"</b> dialog loads a list of every individual post you have favorited. This dialog has some extra features:</p>
             <ul>
                 <li><b>Creator Name Resolution:</b> It attempts to match the post's creator ID with the names in your <code>creators.json</code> file to show you a recognizable name.</li>
                 <li><b>Known.txt Matching:</b> It highlights posts by showing <code>[Known - Tifa]</code> in the title if the post title matches an entry in your <code>Known.txt</code> list, helping you find specific content.</li>
                 <li><b>Grouping:</b> Posts are automatically grouped by creator to keep the list organized.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Download Scope (Artist Folders)</h3>
             <p>In Favorite Mode, the <b>"Scope: [Location]"</b> button becomes very important. It controls <i>where</i> your favorited items are saved:</p>
             <ul>
                 <li><b>Scope: Selected Location (Default):</b> Downloads all selected items directly into the main "Download Location" folder you have set.</li>
                 <li><b>Scope: Artist Folders:</b> This automatically creates a new subfolder for each artist inside your main "Download Location" (e.g., <code>/Downloads/ArtistName/</code>). This is the best way to keep your favorites organized.</li>
             </ul>
             """),

            ("File & Download Options",
             """
             <p>These checkboxes give you fine-grained control over which files are downloaded and how they are processed.</p>
             
             <h3 style='color: #E0E0E0;'>File Type & Content</h3>
             <ul>
                 <li><b>Skip .zip:</b> A simple toggle. When checked, the downloader will skip all <code>.zip</code> and <code>.rar</code> archive files it finds.</li>
                 <br>
                 <li><b>Scan Content for Images:</b> This is a powerful feature for posts where images are embedded in the description (<code>&lt;img&gt;</code> tags) but not listed as attachments. When checked, the app will scan the post's HTML content and try to find and download these embedded images.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Image Processing</h3>
             <ul>
                 <li><b>Download Thumbnails Only:</b> Saves bandwidth and time by downloading the small preview/thumbnail version of an image instead of the full-resolution file.</li>
                 <br>
                 <li><b>Compress to WebP:</b> If an image is over 1.5MB, this option will automatically convert it to the <code>.webp</code> format during the download, which significantly reduces file size while maintaining high quality.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Duplicate Handling</h3>
             <ul>
                 <li><b>Keep Duplicates:</b> By default, the app checks the <i>content</i> (hash) of a file and will not re-download a file it already has. Checking this box opens a dialog with more options:
                    <ul>
                        <li><b>Hash (Default):</b> The standard behavior.</li>
                        <li><b>Keep Everything:</b> Disables all duplicate checks and downloads every file from the API, even if you already have it.</li>
                        <li><b>Limit:</b> Lets you set a limit (e.g., 2) to how many times a file with the same content can be downloaded.</li>
                    </ul>
                 </li>
             </ul>
             """),

            ("Utility & Advanced Options",
             """
             <p>These features provide advanced control over your downloads, sessions, and application settings.</p>

             <h3 style='color: #E0E0E0;'>🛡️ Proxy Support </h3>
             <p>You can now configure a proxy to bypass region blocks or ISP restrictions (e.g., for AllComic or Nhentai).</p>
             <p>Go to <b>Settings ⚙️ > Proxy Tab</b> to set it up:</p>
             <ul>
                 <li><b>Protocols:</b> Full support for <b>HTTP</b>, <b>SOCKS4</b>, and <b>SOCKS5</b>.</li>
                 <li><b>Authentication:</b> Supports username and password for private proxies.</li>
                 <li><b>Global Effect:</b> Once enabled, all app connections (including API fetches and file downloads) will route through this proxy.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Use Cookie</h3>
             <p>This is essential for downloading from sites that require a login (like <b>SimpCity</b> or accessing your <b>favorites</b> on Kemono/Coomer). You can either:</p>
             <ul>
                 <li><b>Paste a cookie string:</b> Copy the "cookie" value from your browser's developer tools and paste it into the text field.</li>
                 <li><b>Use a file:</b> Click the "Browse" button to select a <code>cookies.txt</code> file exported from your browser.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Page Range</h3>
             <p>When downloading from a creator's main page (not a single post), these "Start" and "End" fields let you limit the download. For example, entering <code>Start: 1</code> and <code>End: 5</code> will only download posts from the first five pages.</p>
             
             <h3 style='color: #E0E0E0;'>Multi-part Download</h3>
             <p>Clicking the <b>"Multi-part: OFF"</b> button opens a dialog to enable high-speed downloads for large files. It will split a large file into multiple parts and download them at the same time. You can choose to apply this to videos, archives, or both, and set the minimum file size to trigger it.</p>
             
             <h3 style='color: #E0E0E0;'>Download History</h3>
             <p>The <b>"History"</b> button opens a dialog showing two lists:</p>
             <ul>
                 <li><b>Last 3 Files:</b> The last 3 individual files you successfully downloaded.</li>
                 <li><b>First 3 Posts:</b> The first 3 posts Processed from your *most recent* download session.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Settings (Gear Icon)</h3>
             <p>The <b>Gear</b> icon ⚙️ opens the main application settings, which is now organized into tabs:</p>
             <ul>
                 <li><b>Display Tab:</b> Change the app's <b>Theme</b> (Light/Dark), <b>Language</b>, <b>UI Scale</b>, and default <b>Window Size</b>.</li>
                 <li><b>Downloads Tab:</b>
                     <ul>
                         <li>Save your current <b>Download Path</b>, <b>Cookie</b>, and <b>Discord Token</b> for future sessions using the "Save Path + Cookie + Token" button.</li>
                         <li>Set an <b>Action After Download</b> (e.g., Notify, Sleep, Shutdown).</li>
                         <li>Customize the <b>Post Subfolder Format</b> for when the date prefix is used (e.g., <code>YYYY-MM-DD {post}</code>).</li>
                         <li>Toggle <b>"Save Creator.json file"</b> (which enables the "Check for Updates" feature).</li>
                         <li>Toggle <b>"Fetch First"</b> (to find all posts from a creator before starting any downloads).</li>
                     </ul>
                 </li>
                 <li><b>Proxy Tab:</b> Configure HTTP/SOCKS proxies and authentication.</li>
                 <li><b>Updates Tab:</b> Check for and install new application updates.</li>
             </ul>

             <h3 style='color: #E0E0E0;'>Reset Button</h3> 
             <p>The <b>"Reset"</b> button (bottom right) is a soft reset. It clears all input fields (except your Download Location), clears the logs, and resets all download options and filters back to their default state. It does <b>not</b> clear your Download History or saved Settings.</p>
             """)        
             ]

        scale = self.parent_app.scale_factor if hasattr(self.parent_app, 'scale_factor') else 1.0

        app_icon = get_app_icon_object()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.setModal(True)
        self.resize(int(800 * scale), int(650 * scale))

        dialog_font_size = int(11 * scale)
        
        current_theme_style = ""
        if hasattr(self.parent_app, 'current_theme') and self.parent_app.current_theme == "dark":
            base_style = get_dark_theme(scale)

            list_widget_style = f"""
                QListWidget {{
                    background-color: #2E2E2E;
                    border: 1px solid #4A4A4A;
                    border-radius: 4px;
                    font-size: {int(11 * scale)}pt;
                    color: #DCDCDC;
                }}
                QListWidget::item {{
                    padding: 10px;
                    border-bottom: 1px solid #4A4A4A;
                }}
                QListWidget::item:selected {{
                    background-color: #87CEEB;
                    color: #1E1E1E;
                    font-weight: bold;
                }}
                QListWidget::item:hover:!selected {{
                    background-color: #3A3A3A;
                }}
                
                /* Style for the TourStepWidget content */
                TourStepWidget QLabel {{
                    color: #DCDCDC;
                }}
                TourStepWidget QScrollArea {{
                    background-color: transparent;
                }}
            """
            current_theme_style = base_style + list_widget_style
        else:
            current_theme_style = f"""
                QDialog {{ background-color: #F0F0F0; border: 1px solid #B0B0B0; }}
                QLabel {{ color: #1E1E1E; }}
                QPushButton {{ 
                    background-color: #E1E1E1; 
                    color: #1E1E1E; 
                    border: 1px solid #ADADAD; 
                    padding: {int(8*scale)}px {int(15*scale)}px; 
                    border-radius: 4px; 
                    min-height: {int(25*scale)}px; 
                    font-size: {dialog_font_size}pt; 
                }}
                QPushButton:hover {{ background-color: #CACACA; }}
                QPushButton:pressed {{ background-color: #B0B0B0; }}
                QListWidget {{
                    background-color: #FFFFFF;
                    border: 1px solid #C0C0C0;
                    border-radius: 4px;
                    font-size: {int(11 * scale)}pt;
                    color: #1E1E1E;
                }}
                QListWidget::item {{
                    padding: 10px;
                    border-bottom: 1px solid #E0E0E0;
                }}
                QListWidget::item:selected {{
                    background-color: #0078D7;
                    color: #FFFFFF;
                    font-weight: bold;
                }}
                QListWidget::item:hover:!selected {{
                    background-color: #F0F0F0;
                }}
                TourStepWidget QLabel {{
                    color: #1E1E1E;
                }}
                TourStepWidget h3 {{
                    color: #005A9E;
                }}
            """

        self.setStyleSheet(current_theme_style)
        self._init_ui()
        
        if self.parent_app:
            self.move(self.parent_app.geometry().center() - self.rect().center())

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        title_label = QLabel("Kemono Downloader - Feature Guide")
        scale = getattr(self.parent_app, 'scale_factor', 1.0)
        title_font_size = int(16 * scale)
        title_label.setStyleSheet(f"font-size: {title_font_size}pt; font-weight: bold; color: #87CEEB;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout, 1)

        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(int(280 * scale))
        content_layout.addWidget(self.nav_list)

        self.stacked_widget = QStackedWidget()
        content_layout.addWidget(self.stacked_widget)

        for title, content in self.steps_data:
            self.nav_list.addItem(title)
            step_widget = TourStepWidget(title, content, scale=scale)
            self.stacked_widget.addWidget(step_widget)

        self.nav_list.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        if self.nav_list.count() > 0:
            self.nav_list.setCurrentRow(0)

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 10, 0, 0)
        
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            assets_base_dir = sys._MEIPASS
        else:
            assets_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

        github_icon_path = os.path.join(assets_base_dir, "assets", "github.png")
        instagram_icon_path = os.path.join(assets_base_dir, "assets", "instagram.png")
        discord_icon_path = os.path.join(assets_base_dir, "assets", "discord.png")

        self.github_button = QPushButton(QIcon(github_icon_path), "")
        self.instagram_button = QPushButton(QIcon(instagram_icon_path), "")
        self.discord_button = QPushButton(QIcon(discord_icon_path), "")

        icon_dim = int(24 * scale)
        icon_size = QSize(icon_dim, icon_dim)
        
        tooltip_map = {
            "help_guide_github_tooltip": "Visit the project on GitHub",
            "help_guide_instagram_tooltip": "Follow the developer on Instagram",
            "help_guide_discord_tooltip": "Join the official Discord server"
        }

        for button, tooltip_key, url in [
            (self.github_button, "help_guide_github_tooltip", "https://github.com/Yuvi63771/Kemono-Downloader"),
            (self.instagram_button, "help_guide_instagram_tooltip", "https://www.instagram.com/uvi.arts/"),
            (self.discord_button, "help_guide_discord_tooltip", "https://discord.gg/BqP64XTdJN")
        ]:
            button.setIconSize(icon_size)
            button.setToolTip(tooltip_map.get(tooltip_key, ""))
            button.setFixedSize(icon_size.width() + 8, icon_size.height() + 8)
            button.setStyleSheet("background-color: transparent; border: none;")
            button.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            footer_layout.addWidget(button)

        footer_layout.addStretch(1)

        self.finish_button = QPushButton("Finish")
        self.finish_button.clicked.connect(self.accept)
        footer_layout.addWidget(self.finish_button)

        main_layout.addLayout(footer_layout)