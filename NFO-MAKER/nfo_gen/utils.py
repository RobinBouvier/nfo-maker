"""Shared utility helpers for the NFO generator."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Iterable, Optional


LANG_MAP = {
    "fre": "FR",
    "fra": "FR",
    "fr": "FR",
    "french": "FR",
    "eng": "EN",
    "en": "EN",
    "english": "EN",
    "ger": "DE",
    "deu": "DE",
    "de": "DE",
    "spa": "ES",
    "es": "ES",
    "ita": "IT",
    "it": "IT",
    "jpn": "JA",
    "ja": "JA",
    "chi": "ZH",
    "zho": "ZH",
}


def normalize_language(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if v in LANG_MAP:
        return LANG_MAP[v]
    if len(v) == 2:
        return v.upper()
    return v.upper()


def parse_rational(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                num = float(parts[0])
                den = float(parts[1])
                if den != 0:
                    return num / den
            except ValueError:
                return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value: Optional[object]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value)
    digits = re.findall(r"\d+", s)
    if not digits:
        return None
    return int("".join(digits))


def parse_float(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_bytes(value: Optional[object]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    m = re.search(r"([0-9.]+)\s*([KMGTP]?i?B)", s, re.IGNORECASE)
    if not m:
        return parse_int(s)
    number = float(m.group(1))
    unit = m.group(2).lower()
    factor = 1
    if unit in ("kb", "kib"):
        factor = 1024
    elif unit in ("mb", "mib"):
        factor = 1024 ** 2
    elif unit in ("gb", "gib"):
        factor = 1024 ** 3
    elif unit in ("tb", "tib"):
        factor = 1024 ** 4
    elif unit in ("pb", "pib"):
        factor = 1024 ** 5
    return int(number * factor)


def parse_duration(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 10000:
            return float(value) / 1000.0
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return float(s) / 1000.0
    parts = {"h": 0, "m": 0, "s": 0}
    for key, pattern in (("h", r"(\d+)\s*h"), ("m", r"(\d+)\s*min"), ("s", r"(\d+)\s*s")):
        m = re.search(pattern, s, re.IGNORECASE)
        if m:
            parts[key] = int(m.group(1))
    if any(parts.values()):
        return float(parts["h"] * 3600 + parts["m"] * 60 + parts["s"])
    if ":" in s:
        tokens = s.split(":")
        try:
            nums = [int(t) for t in tokens]
        except ValueError:
            return None
        if len(nums) == 3:
            return float(nums[0] * 3600 + nums[1] * 60 + nums[2])
        if len(nums) == 2:
            return float(nums[0] * 60 + nums[1])
    return None


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "N/A"
    total = int(round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_size(bytes_value: Optional[int]) -> str:
    if bytes_value is None:
        return "N/A"
    gib = bytes_value / (1024 ** 3)
    return f"{gib:.2f} GiB"


def format_bitrate(bits_per_sec: Optional[int]) -> str:
    if bits_per_sec is None:
        return "N/A"
    return f"{int(round(bits_per_sec / 1000.0))} kb/s"


def compute_hash(path: Path, algo: str = "sha1") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def quality_from_resolution(height: Optional[int], width: Optional[int]) -> str:
    if not height and not width:
        return "N/A"
    if height and height >= 2160:
        return "2160p"
    if height and height >= 1440:
        return "1440p"
    if height and height >= 1080:
        return "1080p"
    if width and width >= 3840:
        return "2160p"
    if width and width >= 2560:
        return "1440p"
    if width and width >= 1920:
        return "1080p"
    if height and height >= 720:
        return "720p"
    if width and width >= 1280:
        return "720p"
    if height and height >= 576:
        return "576p"
    return f"{height or width}p"


def first_present(values: Iterable[Optional[str]]) -> Optional[str]:
    for value in values:
        if value:
            return value
    return None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_cache_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    else:
        root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "nfo-gen"


def get_config_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "nfo-gen"
