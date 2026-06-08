import os
import re
from datetime import datetime
from ..config.constants import (
    MAX_FILENAME_COMPONENT_LENGTH, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS,
    ARCHIVE_EXTENSIONS, AUDIO_EXTENSIONS, FOLDER_NAME_STOP_WORDS
)

KNOWN_NAMES = []


def clean_folder_name(name):
    """
    Sanitizes a string to make it a valid folder name.
    Removes invalid characters and trims whitespace.
    """
    if not isinstance(name, str):
        name = str(name)
    
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name)
    cleaned = cleaned.strip()
    
    cleaned = re.sub(r'\s+', ' ', cleaned)

    if not cleaned:
        return "untitled_folder"

    if len(cleaned) > MAX_FILENAME_COMPONENT_LENGTH:
        cleaned = cleaned[:MAX_FILENAME_COMPONENT_LENGTH]

    cleaned = cleaned.rstrip('. ')

    return cleaned if cleaned else "untitled_folder"


def clean_filename(name):
    """
    Sanitizes a string to make it a valid file name.
    """
    if not isinstance(name, str):
        name = str(name)
        
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', name)
    cleaned = cleaned.strip()
    
    if not cleaned:
        return "untitled_file"
        
    base_name, ext = os.path.splitext(cleaned)
    max_base_len = MAX_FILENAME_COMPONENT_LENGTH - len(ext)

    if len(base_name) > max_base_len:
        if max_base_len > 0:
            base_name = base_name[:max_base_len]
        else:
            return cleaned[:MAX_FILENAME_COMPONENT_LENGTH]
    
    return base_name + ext

def format_custom_suffix(suffix_format, file_index):
    """
    Parses a user-defined suffix format (e.g. '001', 'Image1', 'Pg01')
    and returns a formatted string replacing the numeric part with the 
    current file index, preserving zero-padding.
    """
    if not isinstance(suffix_format, str):
        suffix_format = str(suffix_format)
        
    match = re.search(r'(\d+)$', suffix_format)
    if match:
        num_str = match.group(1)
        padding = len(num_str) if num_str.startswith('0') else 0
        prefix = suffix_format[:-len(num_str)]
        formatted_num = str(file_index).zfill(padding) if padding > 0 else str(file_index)
        return prefix + formatted_num
    else:
        return f"{suffix_format}{file_index}"
def is_image(filename):
    if not filename: return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in IMAGE_EXTENSIONS

def is_video(filename):
    if not filename: return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in VIDEO_EXTENSIONS

def is_zip(filename):
    if not filename: return False
    return filename.lower().endswith('.zip')

def is_rar(filename):
    if not filename: return False
    return filename.lower().endswith('.rar')

def is_archive(filename):
    if not filename: return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in ARCHIVE_EXTENSIONS

def is_audio(filename):
    if not filename: return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in AUDIO_EXTENSIONS


def get_known_names(filepath):
    """
    Reads Known.txt and supports both standard lines and (alias) groups.
    The FIRST name in the parentheses becomes the Master Folder Name.
    """
    known_characters = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): 
                    continue
                
                if line.startswith('(') and line.endswith(')'):
                    raw_names = re.split(r'\s*,\s*', line[1:-1])
                    aliases = [name.strip() for name in raw_names if name.strip()]
                    
                    if aliases:
                        known_characters.append({
                            'name': aliases[0], 
                            'aliases': aliases
                        })
                else:
                    known_characters.append({
                        'name': line,
                        'aliases': [line]
                    })
                    
        return known_characters
        
    except FileNotFoundError:
        print(f"Warning: Could not find {filepath}")
        return []

def format_custom_date(date_str, format_string):
    """
    Parses a date string from various formats and formats it according to format_string.
    """
    if not date_str or 'NoDate' in date_str:
        return "NoDate"
        
    clean_str = date_str.split('T')[0]
    dt_obj = None
    
    formats = [
        "%Y-%m-%d", "%d-%m-%Y", 
        "%Y/%m/%d", "%d/%m/%Y",
        "%m-%d-%Y", "%m/%d/%Y",
        "%Y.%m.%d", "%d.%m.%Y"
    ]
    
    for fmt in formats:
        try:
            dt_obj = datetime.strptime(clean_str, fmt)
            break
        except ValueError:
            continue
            
    if not dt_obj:
        try:
            dt_obj = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
            
    if dt_obj:
        strftime_format = format_string.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")
        return dt_obj.strftime(strftime_format)
        
    return clean_str