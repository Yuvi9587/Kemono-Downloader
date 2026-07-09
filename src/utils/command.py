import re

CMD_ARCHIVE_ONLY = 'ao'
CMD_DOMAIN_OVERRIDE_PREFIX = '.'
CMD_SFP_PREFIX = 'sfp-'
CMD_MIN_FILES_PREFIX = 'min-'
CMD_UNKNOWN = 'unknown'

def parse_commands_from_text(raw_text: str):
    """
    Parses special commands from a text string and returns the cleaned text
    and a dictionary of found commands.

    Commands are in the format [command].
    Example: "Tifa, (Cloud, Zack) [.st] [sfp-10] [unknown]"

    Returns:
        tuple[str, dict]: A tuple containing:
                          - The text string with commands removed.
                          - A dictionary of commands and their values.
    """
    command_pattern = re.compile(r'\[(.*?)\]')
    commands = {}
    
    def command_replacer(match):
        command_str = match.group(1).strip().lower()
        
        if command_str.startswith(CMD_DOMAIN_OVERRIDE_PREFIX):
            tld = command_str[len(CMD_DOMAIN_OVERRIDE_PREFIX):]
            if 'domain_override' not in commands:
                commands['domain_override'] = tld
        elif command_str == CMD_ARCHIVE_ONLY:
            commands['archive_only'] = True
        elif command_str.startswith(CMD_SFP_PREFIX):
            try:
                threshold_str = command_str[len(CMD_SFP_PREFIX):]
                threshold = int(threshold_str)
                if 'sfp_threshold' not in commands:
                    commands['sfp_threshold'] = threshold
            except (ValueError, IndexError):
                pass
        elif command_str.startswith(CMD_MIN_FILES_PREFIX):
            try:
                threshold_str = command_str[len(CMD_MIN_FILES_PREFIX):]
                threshold = int(threshold_str)
                if 'min_files_threshold' not in commands:
                    commands['min_files_threshold'] = threshold
            except (ValueError, IndexError):
                pass
        elif command_str == CMD_UNKNOWN:
            commands['handle_unknown'] = True
            
        return ''

    text_without_commands = command_pattern.sub(command_replacer, raw_text).strip()
    
    return text_without_commands, commands