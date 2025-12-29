"""Filename parsing helpers for movie title/year/language extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import List, Optional


TAG_TOKENS = {
    "1080p",
    "2160p",
    "720p",
    "480p",
    "4k",
    "uhd",
    "hdr",
    "hdr10",
    "hdr10plus",
    "dv",
    "dovi",
    "bluray",
    "bdrip",
    "brrip",
    "remux",
    "web",
    "webdl",
    "web-dl",
    "webrip",
    "hdrip",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "avc",
    "av1",
    "aac",
    "ac3",
    "eac3",
    "ddp",
    "dts",
    "dtshd",
    "truehd",
    "atmos",
    "5.1",
    "7.1",
    "2.0",
    "10bit",
    "8bit",
    "proper",
    "repack",
    "limited",
    "multi",
    "vostfr",
    "vfi",
    "vf",
    "vff",
}

LANG_TOKENS = {
    "fr": "FR",
    "french": "FR",
    "en": "EN",
    "eng": "EN",
    "english": "EN",
    "es": "ES",
    "spa": "ES",
    "de": "DE",
    "ger": "DE",
    "ita": "IT",
    "it": "IT",
    "multi": "MULTI",
}

YEAR_RE = re.compile(r"^(19|20)\d{2}$")
RESOLUTION_RE = re.compile(r"^\d{3,4}p$")


@dataclass
class ParsedName:
    title: str
    year: Optional[int]
    languages: List[str]
    raw: str


def parse_filename(filename: str) -> ParsedName:
    base = Path(filename).stem
    base = base.replace(".", " ").replace("_", " ")
    base = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", base)
    base = re.sub(r"\s*-\s*[^-]+$", " ", base)
    tokens = [t for t in base.split() if t]

    year = None
    languages: List[str] = []
    cleaned: List[str] = []

    for token in tokens:
        lower = token.lower()
        if YEAR_RE.match(lower) and year is None:
            year = int(lower)
            continue
        if lower in LANG_TOKENS:
            lang = LANG_TOKENS[lower]
            if lang not in languages:
                languages.append(lang)
            continue
        if lower in TAG_TOKENS:
            continue
        if RESOLUTION_RE.match(lower):
            continue
        cleaned.append(token)

    title = " ".join(cleaned).strip()
    if not title:
        title = Path(filename).stem
    return ParsedName(title=title, year=year, languages=languages, raw=filename)
