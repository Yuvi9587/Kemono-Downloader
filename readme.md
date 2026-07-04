<h1 align="center">Kemono Downloader</h1>

<p>A desktop application for downloading content from various sites, including Kemono, Coomer, Pawchive, Bunkr, Erome, Saint2.su, and nhentai.</p>
<p>Built with PyQt5, this tool provides filtering options, customizable folder structures, and automated downloads to help you organize content easily.</p>

<div align="center">
    <a href="features.md"><img src="https://img.shields.io/badge/📚%20Feature%20List-FFD700?style=for-the-badge&logoColor=black&color=FFD700" alt="Full Feature List"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/📝%20License-90EE90?style=for-the-badge&logoColor=black&color=90EE90" alt="License"></a>
</div>

<h2>Features</h2>

<h3>Downloading</h3>
<ul>
  <li><strong>Multi-threading:</strong> Download multiple posts at the same time.</li>
  <li><strong>Multi-part Downloading:</strong> Download large files in smaller chunks to improve speed.</li>
  <li><strong>Session Management:</strong> Pause, resume, and restore your downloads if they get interrupted.</li>
</ul>

<h3>Site Support</h3>
<ul>
  <li><strong>Supported Sites:</strong> Download from Kemono, Coomer, Pawchive, Bunkr, Erome, Saint2.su, and nhentai.</li>
  <li><strong>Batch Mode:</strong> Download multiple URLs at once using text files.</li>
  <li><strong>Discord Support:</strong> Download attachments or save channel histories as PDFs.</li>
</ul>

<h3>Filtering &amp; Controls</h3>
<ul>
  <li><strong>Content Types:</strong> Choose to download only images, videos, audio, or archives.</li>
  <li><strong>Keyword Skipping:</strong> Skip posts or files that contain specific keywords.</li>
  <li><strong>Size Limits:</strong> Set a minimum file size to skip smaller files.</li>
  <li><strong>Character Filtering:</strong> Only download posts that match specific character or series names.</li>
</ul>

<h3>File Organization</h3>
<ul>
  <li><strong>Subfolders:</strong> Automatically organize files into subdirectories by character or post.</li>
  <li><strong>File Renaming:</strong> Rename files by post title, date, sequential number, or post ID.</li>
  <li><strong>Filename Cleaning:</strong> Automatically clean up messy filenames.</li>
</ul>

<h3>Download Modes</h3>
<ul>
  <li><strong>Manga Mode:</strong> Sort posts chronologically to keep pages in order.</li>
  <li><strong>Favorites Mode:</strong> Download directly from your account's favorites list.</li>
  <li><strong>Export Links:</strong> Extract external links (like Mega or Google Drive) and save them to a file.</li>
  <li><strong>Text Extraction:</strong> Save post descriptions or comments as PDF, DOCX, or TXT.</li>
</ul>

<h3>Other Features</h3>
<ul>
  <li><strong>In-App Updater:</strong> Check for and install new updates from the settings.</li>
  <li><strong>Cookie Support:</strong> Access content that requires a login by using browser cookies.</li>
  <li><strong>Duplicate Detection:</strong> Avoid saving files you've already downloaded.</li>
  <li><strong>Image Compression:</strong> Optionally convert images to <code>.webp</code> to save disk space.</li>
  <li><strong>Creator Profiles:</strong> Keep track of creators and easily check for new posts.</li>
  <li><strong>Error Handling:</strong> Track failed downloads and retry them later.</li>
</ul>

<section aria-labelledby="supported-sites">
  <h2 id="supported-sites">Supported Sites</h2>

  <h3>Main Platforms</h3>
  <ul>
    <li>
      <strong>Kemono, Coomer, &amp; Pawchive</strong> — Download posts and files from creators on services like Patreon, Fanbox, OnlyFans, and Fansly.
    </li>
    <li>
      <strong>Discord</strong> — Download files or save the message history as a PDF.
    </li>
  </ul>

  <hr>

  <h3>Specialized Sites</h3>
  <p>Paste a link from any of these sites to download automatically:</p>
  <details>
    <summary>Click to expand</summary>
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

  <h3>File Hosts</h3>
  <p>You can paste direct links from these file hosts:</p>
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
<pre><code>Required: pip install PyQt5 requests packaging cloudscraper bs4 pycryptodome
</code></pre>

<pre><code>Optional: pip install gdown pillow fpdf python-docx 
</code></pre>

<h3>Running the Application</h3>
<p>Open your terminal, navigate to the folder, and run:</p>
<pre><code>python main.py
</code></pre>

<h2>Contributing</h2>
<p>Feel free to fork this repo and submit pull requests for bug fixes, new features, or UI improvements.</p>

<h2>License</h2>
<p>This project is licensed under the MIT License.</p>

<h3>Included Third-Party Tools</h3>
<p>This project includes a pre-compiled binary of <code>yt-dlp</code> for handling certain video downloads. <code>yt-dlp</code> is in the public domain. For more info, check the official <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp GitHub repository</a>.</p>

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
