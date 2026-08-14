<h1 align="center">Kemono Downloader</h1>

<p align="center">A simple desktop application for downloading media from various supported sites.</p>

<div align="center">
    <a href="features.md"><img src="https://img.shields.io/badge/📚%20Features-FFD700?style=for-the-badge&logoColor=black&color=FFD700" alt="Features"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/📝%20License-90EE90?style=for-the-badge&logoColor=black&color=90EE90" alt="License"></a>
</div>

## What is it?

Kemono Downloader is a Python-based desktop tool built with PyQt5 that helps you download images, videos, audio, and archives from several platforms. It focuses on making it easier to save and organize content locally with filtering and folder structuring options.

## Features at a Glance

- **Multi-threading:** Download multiple items simultaneously.
- **Session Management:** Pause and resume downloads.
- **Filtering:** Filter downloads by file type (images, videos, etc.), minimum file size, or specific keywords.
- **Organization:** Automatically save files into folders organized by creator or post.
- **Manga Mode:** Download and rename images chronologically for easier reading.
- **Export Links:** Extract direct file URLs into a text file instead of downloading them.

## Supported Sites

You can paste links from the following platforms to download content:

- Kemono, Coomer, & Pawchive
- Discord (Save attachments or export chat history)
- AllPornComic, Bunkr, Erome, Fap-Nation
- Hentai2Read, nhentai, Pixeldrain, Saint2, Toonily
- File hosts: Dropbox, Gofile, Google Drive, Mega

## Installation

You will need Python 3.6 or newer installed on your system.

### 1. Install Dependencies
```bash
pip install PyQt5 requests packaging cloudscraper bs4 pycryptodome
```
Optional dependencies (for features like PDF generation and image compression):
```bash
pip install gdown pillow fpdf python-docx
```

### 2. Run the App
```bash
python main.py
```

## Contributing
If you'd like to help improve the app, feel free to fork the repository and submit a pull request. Bug fixes and quality-of-life improvements are always welcome!

## License
This project is available under the MIT License.

*Note: This project includes a pre-compiled version of `yt-dlp` (public domain) to help with downloading certain videos. See their [repository](https://github.com/yt-dlp/yt-dlp) for details.*
