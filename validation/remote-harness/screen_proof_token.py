"""Public, readable SSH screen proof: eight independent 5-bit word choices.

The 32-word vocabulary is fixed and never supplied to OCR. Two rows of four
words fit within the existing 21-character echo marker's terminal width.
"""
import re
import secrets


SCREEN_WORDS = tuple('ARCH BARN CAVE DECK DUSK EAST FACT FADE FARM FAST HARD HARP '
                     'HAVE HEAD HEAT HUNT KEPT LAMP LAND LAST LEAF LEFT PART PAST '
                     'PATH RACE RATE SALT SAND SEAT STAR TASK'.split())
LEGACY_TOKEN_PATTERN = r'[ACDEFHJKMNPQRTUVWXY34679]{12}'


def new_screen_token():
    return ' '.join(secrets.choice(SCREEN_WORDS) for _ in range(8))


def token_lines(token):
    """Validate the public canonical token; retain old artifact readability."""
    if not isinstance(token, str):
        raise ValueError('invalid screen token')
    if re.fullmatch(LEGACY_TOKEN_PATTERN, token) is not None:
        return (token,)
    words = token.split(' ')
    if len(words) != 8 or any(word not in SCREEN_WORDS for word in words):
        raise ValueError('invalid screen token')
    return (' '.join(words[:4]), ' '.join(words[4:]))
