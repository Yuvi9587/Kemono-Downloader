import sys
import os
import requests
import subprocess
import zipfile
import shutil
from packaging.version import parse as parse_version
from PyQt5.QtCore import QThread, pyqtSignal

GITHUB_REPO_URL = "https://api.github.com/repos/Yuvi9587/Kemono-Downloader/releases/latest"
EXE_NAME = "Kemono.Downloader.exe"

class UpdateChecker(QThread):
    """Checks for a new version on GitHub in a background thread."""
    update_available = pyqtSignal(str, str)
    up_to_date = pyqtSignal(str)
    update_error = pyqtSignal(str)

    def __init__(self, current_version):
        super().__init__()
        self.current_version_str = current_version.lstrip('v')

    def run(self):
        try:
            response = requests.get(GITHUB_REPO_URL, timeout=15)
            response.raise_for_status()
            data = response.json()

            latest_version_str = data['tag_name'].lstrip('v')
            current_version = parse_version(self.current_version_str)
            latest_version = parse_version(latest_version_str)

            if latest_version > current_version:
                for asset in data.get('assets', []):
                    if asset['name'].endswith('.zip'):
                        self.update_available.emit(latest_version_str, asset['browser_download_url'])
                        return
                self.update_error.emit(f"Update found, but no '.zip' release asset was found.")
            else:
                self.up_to_date.emit("You are on the latest version.")

        except requests.exceptions.RequestException as e:
            self.update_error.emit(f"Network error: {e}")
        except Exception as e:
            self.update_error.emit(f"An error occurred: {e}")


class UpdateDownloader(QThread):
    """
    Downloads the new executable and runs an updater script that kills the old process,
    replaces the file, and displays a message in the terminal.
    """
    download_finished = pyqtSignal()
    download_error = pyqtSignal(str)

    def __init__(self, download_url, parent_app):
        super().__init__()
        self.download_url = download_url
        self.parent_app = parent_app

    def run(self):
        try:
            app_path = sys.executable
            app_dir = os.path.dirname(app_path)
            zip_path = os.path.join(app_dir, "update.zip")
            extract_dir = os.path.join(app_dir, "update_extracted")
            updater_script_path = os.path.join(app_dir, "updater.bat")
            
            pid_file_path = os.path.join(app_dir, "updater.pid")

            with requests.get(self.download_url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            # Extract the zip file
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            os.makedirs(extract_dir, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
                
            # Find the directory containing _internal
            update_source_dir = extract_dir
            for root, dirs, files in os.walk(extract_dir):
                if '_internal' in dirs:
                    update_source_dir = root
                    break

            with open(pid_file_path, "w") as f:
                f.write(str(os.getpid()))

            # Create a batch script to replace files and launch the new executable
            # We use xcopy to move everything from update_source_dir to app_dir
            # Then we find the new executable to launch
            script_content = rf"""
@echo off
SETLOCAL EnableDelayedExpansion

echo.
echo Reading process information...
set /p PID=<{pid_file_path}

echo Closing the old application (PID: %PID%)...
taskkill /F /PID %PID%

echo Waiting for files to unlock...
timeout /t 2 /nobreak > nul

echo Replacing application files...
:: Remove old _internal directory
if exist "{app_dir}\_internal" rmdir /S /Q "{app_dir}\_internal"
:: Remove old executables (app, yt-dlp, etc.)
del /F /Q "{app_dir}\*.exe"

:: Copy new files
xcopy /E /Y /I "{update_source_dir}\*" "{app_dir}\"

:: Find the new application executable to launch (excluding known helpers)
set "NEW_EXE="
for %%F in ("{app_dir}\*.exe") do (
    if /I not "%%~nxF"=="yt-dlp.exe" if /I not "%%~nxF"=="ffmpeg.exe" (
        set "NEW_EXE=%%~nxF"
    )
)

echo.
echo ============================================================
echo      Update Complete!
echo ============================================================
echo.
timeout /t 2 > nul

echo Cleaning up helper files...
rmdir /S /Q "{extract_dir}"
del /F /Q "{zip_path}"
del /F /Q "{pid_file_path}"

if defined NEW_EXE (
    echo Starting !NEW_EXE!...
    start "" "{app_dir}\!NEW_EXE!"
) else (
    echo Could not find the new executable to start automatically.
    pause
)

del "%~f0"
ENDLOCAL
"""
            with open(updater_script_path, "w") as f:
                f.write(script_content)

            os.startfile(updater_script_path)
            
            self.download_finished.emit()

        except Exception as e:
            self.download_error.emit(f"Failed to download or run updater: {e}")

# --- Patch Updater System ---
PATCH_JSON_URL = "https://huggingface.co/Yuvi9587/Kemono-Downloader-Patches/raw/main/patch.json"

class PatchUpdateChecker(QThread):
    """Checks for a lightweight EXE patch update on Hugging Face."""
    patch_available = pyqtSignal(str, str)
    up_to_date = pyqtSignal()
    
    def __init__(self, current_version):
        super().__init__()
        self.current_version_str = current_version.lstrip('v')
        
    def run(self):
        try:
            response = requests.get(PATCH_JSON_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            patch_version_str = data.get('version', '').lstrip('v')
            download_url = data.get('download_url', '')
            
            if not patch_version_str or not download_url:
                return
                
            current_v = parse_version(self.current_version_str)
            patch_v = parse_version(patch_version_str)
            
            if patch_v > current_v:
                self.patch_available.emit(patch_version_str, download_url)
            else:
                self.up_to_date.emit()
        except Exception:
            pass # Silent failure for background check

class PatchDownloader(QThread):
    """Downloads a raw .exe patch and swaps it with the current one."""
    download_finished = pyqtSignal()
    download_error = pyqtSignal(str)

    def __init__(self, download_url):
        super().__init__()
        self.download_url = download_url

    def run(self):
        try:
            app_path = sys.executable
            app_dir = os.path.dirname(app_path)
            new_exe_path = os.path.join(app_dir, "update_patch.exe")
            updater_script_path = os.path.join(app_dir, "patch_updater.bat")
            pid_file_path = os.path.join(app_dir, "updater.pid")

            with requests.get(self.download_url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(new_exe_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            with open(pid_file_path, "w") as f:
                f.write(str(os.getpid()))

            script_content = rf"""
@echo off
SETLOCAL EnableDelayedExpansion

echo.
echo Reading process information...
set /p PID=<{pid_file_path}

echo Closing the old application (PID: %PID%)...
taskkill /F /PID %PID%

echo Waiting for files to unlock...
timeout /t 2 /nobreak > nul

echo Applying Patch...
move /Y "{new_exe_path}" "{app_path}"

echo.
echo ============================================================
echo      Patch Update Complete!
echo ============================================================
echo.
timeout /t 2 > nul

echo Cleaning up...
del /F /Q "{pid_file_path}"

echo Starting application...
start "" "{app_path}"

del "%~f0"
ENDLOCAL
"""
            with open(updater_script_path, "w") as f:
                f.write(script_content)

            os.startfile(updater_script_path)
            self.download_finished.emit()

        except Exception as e:
            self.download_error.emit(f"Failed to download or run patch updater: {e}")
