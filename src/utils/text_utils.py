import re
import html

from .file_utils import clean_folder_name
from ..config.constants import FOLDER_NAME_STOP_WORDS


KNOWN_TXT_MATCH_CLEANUP_PATTERNS = [
    r'\bcum\b',
    r'\bnsfw\b',
    r'\bsfw\b',
    r'\bweb\b',
    r'\bhd\b',
    r'\bhi\s*res\b',
    r'\bhigh\s*res\b',
    r'\b\d+p\b',
    r'\b\d+k\b',
    r'\[OC\]',
    r'\[Request(?:s)?\]',
    r'\bCommission\b',
    r'\bComm\b',
    r'\bPreview\b',
]

cjk_pattern = re.compile(r'[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uffef\u4e00-\u9fff\uac00-\ud7af]')

def contains_cjk(text):
    """Checks if the text contains any CJK characters."""
    return bool(cjk_pattern.search(text))


def is_title_match_for_character(post_title, character_name_filter):
    """
    Checks if a post title contains a specific character name as a whole word.
    Case-insensitive.
    """
    if not post_title or not character_name_filter:
        return False

    pattern = r"(?i)\b" + re.escape(str(character_name_filter).strip()) + r"\b"
    return bool(re.search(pattern, post_title))


def is_filename_match_for_character(filename, character_name_filter):
    """
    Checks if a filename contains a character name using smart length-based boundaries.
    """
    if not filename or not character_name_filter:
        return False

    filename_lower = filename.lower()
    alias_lower = str(character_name_filter).strip().lower()

    if contains_cjk(alias_lower) or contains_cjk(filename_lower):
        return alias_lower in filename_lower

    strict_pattern = r'(?:^|[\s_+-])' + re.escape(alias_lower) + r'(?:[\s_+-]|$)'
    if re.search(strict_pattern, filename_lower):
        return True

    if len(alias_lower) >= 4:
        relaxed_pattern = r'(?:^|[\s_+-])' + re.escape(alias_lower)
        if re.search(relaxed_pattern, filename_lower):
            return True

    return False


def strip_html_tags(html_text):
    """
    Removes HTML tags from a string and cleans up resulting whitespace.
    """
    if not html_text:
        return ""
    text = html.unescape(str(html_text))
    text_after_tag_removal = re.sub(r'<[^>]+>', ' ', text)
    cleaned_text = re.sub(r'\s+', ' ', text_after_tag_removal).strip()
    return cleaned_text


def extract_folder_name_from_title(title, unwanted_keywords):
    """
    Extracts a plausible folder name from a post title by finding the first
    significant word that isn't a stop-word.
    """
    if not title:
        return 'Uncategorized'

    title_lower = title.lower()
    tokens = re.findall(r'\b[\w\-]+\b', title_lower)

    for token in tokens:
        clean_token = clean_folder_name(token)
        if clean_token and clean_token.lower() not in unwanted_keywords:
            return clean_token

    cleaned_full_title = clean_folder_name(title)
    return cleaned_full_title if cleaned_full_title else 'Uncategorized'

def match_folders_from_title(title, names_to_match, unwanted_keywords):
    """
    Matches folder names from a title based on a list of known name objects.
    Finds ALL non-overlapping characters in the title.
    """
    if not title or not names_to_match:
        return []

    cleaned_title = title
    for pat_str in KNOWN_TXT_MATCH_CLEANUP_PATTERNS:
        cleaned_title = re.sub(pat_str, ' ', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()
    
    title_lower = cleaned_title.lower()

    alias_map_to_primary = []
    for name_obj in names_to_match:
        primary_name = name_obj.get("name")
        if not primary_name: continue

        cleaned_primary_name = clean_folder_name(primary_name)
        if not cleaned_primary_name or cleaned_primary_name.lower() in unwanted_keywords:
            continue

        for alias in name_obj.get("aliases", []):
            if alias and alias.lower(): 
                alias_map_to_primary.append((alias.lower(), cleaned_primary_name))

    alias_map_to_primary.sort(key=lambda x: len(x[0]), reverse=True)

    matched_intervals = []
    candidate_list = []
    candidate_set = set()

    for alias_lower, primary_name_for_alias in alias_map_to_primary:
        try:
            if contains_cjk(alias_lower):
                matches = list(re.finditer(re.escape(alias_lower), title_lower))
            else:
                pattern = r'\b' + re.escape(alias_lower) + r'\b'
                matches = list(re.finditer(pattern, title_lower))
            
            for match in matches:
                start, end = match.span()
                overlap = any(s < end and e > start and (s != start or e != end) for s, e in matched_intervals)
                if not overlap:
                    matched_intervals.append((start, end))
                    if primary_name_for_alias not in candidate_set:
                        candidate_set.add(primary_name_for_alias)
                        candidate_list.append(primary_name_for_alias)
        except re.error:
            continue

    unique_matches_count = len(set(matched_intervals))
    return candidate_list, unique_matches_count


def match_folders_from_filename_enhanced(filename, names_to_match, unwanted_keywords, post_title=""):
    """
    Matches folder names from a filename, collecting ALL non-overlapping characters.
    """
    if not filename or not names_to_match:
        return []

    filename_lower = filename.lower()
    alias_map_to_primary = []
    for name_obj in names_to_match:
        primary_name = name_obj.get("name")
        if not primary_name: continue

        cleaned_primary_name = clean_folder_name(primary_name)
        if not cleaned_primary_name or cleaned_primary_name.lower() in unwanted_keywords:
            continue

        for alias in name_obj.get("aliases", []):
            if alias and alias.lower(): 
                alias_map_to_primary.append((alias.lower(), cleaned_primary_name))

    alias_map_to_primary.sort(key=lambda x: len(x[0]), reverse=True)

    matched_intervals = []
    candidate_list = []
    candidate_set = set()

    for alias_lower, primary_name_for_alias in alias_map_to_primary:
        matches = []
        try:
            strict_pattern = r'(?:^|[\s_+.-])' + re.escape(alias_lower) + r'(?:[\s_+.-]|$)'
            matches = list(re.finditer(strict_pattern, filename_lower))
            
            if not matches and len(alias_lower) >= 4:
                relaxed_pattern = r'(?:^|[\s_+.-])' + re.escape(alias_lower)
                matches = list(re.finditer(relaxed_pattern, filename_lower))
            
            if not matches and (contains_cjk(alias_lower) or contains_cjk(filename_lower)):
                matches = list(re.finditer(re.escape(alias_lower), filename_lower))

            for match in matches:
                start, end = match.span()
                overlap = any(s < end and e > start and (s != start or e != end) for s, e in matched_intervals)
                if not overlap:
                    matched_intervals.append((start, end))
                    if primary_name_for_alias not in candidate_set:
                        candidate_set.add(primary_name_for_alias)
                        candidate_list.append(primary_name_for_alias)
        except re.error:
            continue

    unique_matches_count = len(set(matched_intervals))

    if len(candidate_list) > 1 and post_title:
        title_matches, _ = match_folders_from_title(post_title, names_to_match, unwanted_keywords)
        intersection = [name for name in candidate_list if name in title_matches]
        if len(intersection) == 1:
            return [intersection[0]], 1
        elif len(intersection) > 1:
            return intersection, unique_matches_count
            
    return candidate_list, unique_matches_count