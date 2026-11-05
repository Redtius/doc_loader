"""Text normalisation shared by all formats."""

import re
import unicodedata

# Control characters other than tab and newline.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def normalize(text: str) -> str:
    """NFKC (ligatures "ﬁ" -> "fi", odd spaces), no control characters, single spaces."""
    text = _CONTROL.sub("", unicodedata.normalize("NFKC", text))
    return " ".join(text.split())
