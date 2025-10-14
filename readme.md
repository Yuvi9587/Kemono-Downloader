<h1 align="center">Kemono Downloader</h1>

<p>A powerful, feature-rich GUI application for downloading content from a wide array of sites, including <strong>Kemono</strong>, <strong>Coomer</strong>, <strong>Bunkr</strong>, <strong>Erome</strong>, <strong>Saint2.su</strong>, and <strong>nhentai</strong>.</p>
<p>Built with PyQt5, this tool is designed for users who want deep filtering capabilities, customizable folder structures, efficient downloads, and intelligent automation — all within a modern and user-friendly graphical interface.</p>

<div align="center">
    <a href="features.md"><img src="https://img.shields.io/badge/📚%20Full%20Feature%20List-FFD700?style=for-the-badge&logoColor=black&color=FFD700" alt="Full Feature List"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/📝%20License-90EE90?style=for-the-badge&logoColor=black&color=90EE90" alt="License"></a>
</div>

<h2>Core Capabilities Overview</h2>
<h3>High-Performance &amp; Resilient Downloading</h3>
<ul>
  <li><strong>Multi-threading:</strong> Processes multiple posts simultaneously to greatly accelerate downloads from large creator profiles.</li>
  <li><strong>Multi-part Downloading:</strong> Splits large files into chunks and downloads them in parallel to maximize speed.</li>
  <li><strong>Session Management:</strong> Supports pausing, resuming, and <strong>restoring downloads</strong> after crashes or interruptions, so you never lose your progress.</li>
</ul>
<h3>Expanded Site Support</h3>
<ul>
  <li><strong>Direct Downloading:</strong> Full support for Kemono, Coomer, Bunkr, Erome, Saint2.su, and nhentai.</li>
  <li><strong>Batch Mode:</strong> Download hundreds of URLs at once from <code>nhentai.txt</code> or <code>saint2.su.txt</code> files.</li>
  <li><strong>Discord Support:</strong> Download files or save entire channel histories as PDFs directly through the API.</li>
</ul>
<h3>Advanced Filtering &amp; Content Control</h3>
<ul>
  <li><strong>Content Type Filtering:</strong> Select whether to download all files or limit to images, videos, audio, or archives only.</li>
  <li><strong>Keyword Skipping:</strong> Automatically skips posts or files containing certain keywords (e.g., "WIP", "sketch").</li>
  <li><strong>Skip by Size:</strong> Avoid small files by setting a minimum size threshold in MB (e.g., <code>[200]</code>).</li>
  <li><strong>Character Filtering:</strong> Restricts downloads to posts that match specific character or series names, with scope controls for title, filename, or comments.</li>
</ul>
<h3>Intelligent File Organization</h3>
<ul>
  <li><strong>Automated Subfolders:</strong> Automatically organizes downloaded files into subdirectories based on character names or per post.</li>
  <li><strong>Advanced File Renaming:</strong> Flexible renaming options, especially in Manga Mode, including by post title, date, sequential numbering, or post ID.</li>
  <li><strong>Filename Cleaning:</strong> Automatically removes unwanted text from filenames.</li>
</ul>
<h3>Specialized Modes</h3>
<ul>
  <li><strong>Renaming Mode:</strong> Sorts posts chronologically before downloading to ensure pages appear in the correct sequence.</li>
  <li><strong>Favorite Mode:</strong> Connects to your account and downloads from your favorites list (artists or posts).</li>
  <li><strong>Link Extraction Mode:</strong> Extracts external links (Mega, Google Drive) from posts for export or <strong>direct in-app downloading</strong>.</li>
  <li><strong>Text Extraction Mode:</strong> Saves post descriptions or comment sections as <code>PDF</code>, <code>DOCX</code>, or <code>TXT</code> files.</li>
</ul>
<h3>Utility &amp; Advanced Features</h3>
<ul>
  <li><strong>In-App Updater:</strong> Check for new versions directly from the settings menu.</li>
  <li><strong>Cookie Support:</strong> Enables access to subscriber-only content via browser session cookies.</li>
  <li><strong>Duplicate Detection:</strong> Prevents saving duplicate files using content-based comparison, with configurable limits.</li>
  <li><strong>Image Compression:</strong> Automatically converts large images to <code>.webp</code> to reduce disk usage.</li>
  <li><strong>Creator Management:</strong> Built-in creator browser and update checker for downloading only new posts from saved profiles.</li>
  <li><strong>Error Handling:</strong> Tracks failed downloads and provides a retry dialog with options to export or redownload missing files.</li>
</ul>
<section aria-labelledby="supported-sites">
  <h2 id="supported-sites">Supported Sites</h2>

  <h3>Main Platforms</h3>
  <p>
    The downloader is primarily built to archive content from the platforms below.
  </p>
  <ul>
    <li>
      <strong>Kemono &amp; Coomer</strong> — Core supported sites; download posts and files from creators on services such as
      <em>Patreon, Fanbox, OnlyFans, Fansly</em>, and similar platforms.
    </li>
    <li>
      <strong>Discord</strong> — Two modes for a channel URL:
      <ul>
        <li>Download all files and attachments.</li>
        <li>Save the entire message history as a formatted PDF.</li>
      </ul>
    </li>
  </ul>

  <hr>

  <h3>Specialized Site Support</h3>
  <p>Paste a link from any of the following and the app will handle the download automatically:</p>

  <details>
    <summary>Supported specialized sites (click to expand)</summary>
    <ul>
      <li>AllPornComic</li>
      <li>Bunkr</li>
      <li>Erome</li>
      <li>Fap-Nation</li>
      <li>Hentai2Read</li>
      <li>nhentai</li>
      <li>Pixeldrain</li>
      <li>Saint2</li>
      <li>Toonily</li>
    </ul>
  </details>

  <hr>

  <h3>Direct File Hosting</h3>
  <p>
    You may paste direct links from these file hosting services to download contents without using the
    <code>&quot;Only Links&quot;</code> mode:
  </p>
  <ul>
    <li>Dropbox</li>
    <li>Gofile</li>
    <li>Google Drive</li>
    <li>Mega</li>
  </ul>
</section>

<h2>💻 Installation</h2>
<h3>Requirements</h3>
<ul>
  <li>Python 3.6 or higher</li>
  <li>pip (Python package installer)</li>
</ul>
<h3>Install Dependencies</h3>
<pre><code>Required - pip install PyQt5 requests packaging cloudscraper bs4 pycryptodome
</code></pre>

<pre><code>Optional - pip install gdown pillow fpdf python-docx 
</code></pre>

<h3>Running the Application</h3>
<p>Navigate to the application's directory in your terminal and run:</p>
<pre><code>python main.py
</code></pre>
<h2>Contribution</h2>
<p>Feel free to fork this repo and submit pull requests for bug fixes, new features, or UI improvements!</p>
<h2>License</h2>
<p>This project is under the MIT Licence</p>
<h2>Included Third-Party Tools</h2>

This project includes a pre-compiled binary of `yt-dlp` for handling certain video downloads. `yt-dlp` is in the public domain. For more information or to get the latest version, please visit the official [yt-dlp GitHub repository](https://github.com/yt-dlp/yt-dlp).

<h2>Star History</h2>
<table align="center" style="border-collapse: collapse; border: none; margin-left: auto; margin-right: auto;">
  <tbody>
    <tr>
      <td align="center" valign="middle" style="padding: 10px; border: none;">
        <a href="https://www.star-history.com/#Yuvi9587/Kemono-Downloader&amp;Date">
          <img src="https://api.star-history.com/svg?repos=Yuvi9587/Kemono-Downloader&amp;type=Date" alt="Star History Chart" width="650">
        </a>
      </td>
    </tr>
  </tbody>
</table>

<p align="center">
  <a href="https://buymeacoffee.com/yuvi9587">
    <img src="https://img.shields.io/badge/🍺%20Buy%20Me%20a%20Coffee-FFCCCB?style=for-the-badge&amp;logoColor=black&amp;color=FFDD00" alt="Buy Me a Coffee">
  </a>
</p>
