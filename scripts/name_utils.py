"""
Shared name normalization utilities for golf player matching.

Used by merge_odds.py and model.py to match player names across sources.
"""

import re
import unicodedata

# Active nickname mappings - only entries needed for current fields
NICKNAME_MAP = {
    'johnny': 'john',
    'matt': 'matthew',
    'matthias': 'matthew',
    'matti': 'matthew',
    'zach': 'zachary',
}


def last_first_to_first_last(name: str) -> str:
    """Convert 'Last, First' format to 'First Last'."""
    if ',' in name:
        parts = name.split(',', 1)
        if len(parts) == 2:
            return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def normalize_name_base(name: str) -> str:
    """
    Normalize player name WITHOUT nickname mapping.
    Used to detect if nickname mapping was needed for a match.
    """
    # Handle special Nordic characters before normalization
    replacements = {
        'ø': 'o', 'Ø': 'O',
        'æ': 'ae', 'Æ': 'AE',
        'å': 'a', 'Å': 'A',
        'ö': 'o', 'Ö': 'O',
        'ü': 'u', 'Ü': 'U',
        'ñ': 'n', 'Ñ': 'N',
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    # Convert accented characters to ASCII
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Lowercase
    name = name.lower()

    # Strip periods, apostrophes, hyphens
    name = name.replace('.', '').replace("'", '').replace("'", '').replace('-', '')

    # Collapse whitespace
    name = ' '.join(name.split())

    # Strip common suffixes
    suffixes = [' jr', ' sr', ' ii', ' iii', ' iv', ' v']
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]

    # Strip single middle initials (e.g., "jordan l smith" -> "jordan smith")
    name = re.sub(r'\b[a-z]\b', '', name)
    name = ' '.join(name.split())

    return name.strip()


def normalize_name(name: str) -> str:
    """
    Normalize player name WITH nickname mapping.
    """
    name = normalize_name_base(name)

    # Apply nickname mappings to first name
    parts = name.split()
    if parts:
        first = parts[0]
        if first in NICKNAME_MAP:
            parts[0] = NICKNAME_MAP[first]
        name = ' '.join(parts)

    return name.strip()
