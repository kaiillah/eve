import re

from config import GOODBYE_KEYWORDS


def normalize_text(t: str) -> str:
    return re.sub(r"[^a-z\s]", " ", t.lower())


def said_goodbye(text: str) -> bool:
    t = normalize_text(text)
    return any(kw in t for kw in GOODBYE_KEYWORDS)
