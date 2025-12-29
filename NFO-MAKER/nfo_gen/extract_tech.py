"""MediaInfo/ffprobe technical extraction."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import (
    first_present,
    normalize_language,
    parse_bytes,
    parse_duration,
    parse_float,
    parse_int,
    parse_rational,
)


def _run_cmd(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _mi_value(track: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for key in keys:
        if key in track:
            value = track.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _mi_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in ("yes", "true", "1"):
        return True
    if v in ("no", "false", "0"):
        return False
    return None


def _mi_hdr(track: Dict[str, Any]) -> Optional[str]:
    hdr = _mi_value(
        track,
        [
            "HDR_Format",
            "HDR_Format_Commercial",
            "HDR_Format_String",
            "HDR_Format_Compatibility",
        ],
    )
    return hdr


def _parse_mediainfo(data: Dict[str, Any], filename: str) -> Dict[str, Any]:
    tracks = data.get("media", {}).get("track", [])
    general: Dict[str, Any] = {"filename": filename}
    videos: List[Dict[str, Any]] = []
    audios: List[Dict[str, Any]] = []
    subtitles: List[Dict[str, Any]] = []

    for track in tracks:
        ttype = track.get("@type")
        if ttype == "General":
            general["extension"] = _mi_value(track, ["FileExtension"])
            general["size_bytes"] = parse_bytes(
                _mi_value(track, ["FileSize", "FileSize_String3", "FileSize_String"])
            )
            general["duration_sec"] = parse_duration(
                _mi_value(
                    track,
                    [
                        "Duration",
                        "Duration_String3",
                        "Duration_String2",
                        "Duration_String1",
                    ],
                )
            )
            general["overall_bitrate"] = parse_int(
                _mi_value(track, ["OverallBitRate", "OverallBitRate_String"])
            )
            general["container"] = _mi_value(track, ["Format"])
            general["encoded_date"] = _mi_value(track, ["Encoded_Date", "EncodedDate"])
            general["writing_app"] = _mi_value(track, ["WritingApplication"])
            general["writing_library"] = _mi_value(track, ["WritingLibrary"])
        elif ttype == "Video":
            videos.append(
                {
                    "codec": _mi_value(track, ["Format", "Format_Commercial"]),
                    "profile": _mi_value(track, ["Format_Profile"]),
                    "bitrate": parse_int(_mi_value(track, ["BitRate", "BitRate_String"])),
                    "width": parse_int(_mi_value(track, ["Width"])),
                    "height": parse_int(_mi_value(track, ["Height"])),
                    "aspect_ratio": _mi_value(track, ["DisplayAspectRatio", "DisplayAspectRatio_String"]),
                    "frame_rate": parse_float(_mi_value(track, ["FrameRate"])),
                    "scan_type": _mi_value(track, ["ScanType"]),
                    "bit_depth": parse_int(_mi_value(track, ["BitDepth"])),
                    "chroma": _mi_value(track, ["ChromaSubsampling", "ChromaSubsampling_String"]),
                    "color_primaries": _mi_value(track, ["ColorPrimaries"]),
                    "color_transfer": _mi_value(track, ["TransferCharacteristics"]),
                    "color_matrix": _mi_value(track, ["MatrixCoefficients"]),
                    "hdr": _mi_hdr(track),
                }
            )
        elif ttype == "Audio":
            audios.append(
                {
                    "codec": _mi_value(track, ["Format", "Format_Commercial"]),
                    "bitrate": parse_int(_mi_value(track, ["BitRate", "BitRate_String"])),
                    "channels": parse_int(_mi_value(track, ["Channels"])),
                    "channel_layout": _mi_value(track, ["ChannelLayout", "ChannelLayout_String"]),
                    "sample_rate": parse_int(_mi_value(track, ["SamplingRate"])),
                    "language": normalize_language(_mi_value(track, ["Language"])),
                    "title": _mi_value(track, ["Title"]),
                    "default": _mi_bool(_mi_value(track, ["Default"])),
                    "forced": _mi_bool(_mi_value(track, ["Forced"])),
                    "delay_ms": parse_int(_mi_value(track, ["DelayRelativeToVideo"])),
                }
            )
        elif ttype in ("Text", "Subtitle"):
            subtitles.append(
                {
                    "format": _mi_value(track, ["Format", "CodecID"]),
                    "language": normalize_language(_mi_value(track, ["Language"])),
                    "title": _mi_value(track, ["Title"]),
                    "default": _mi_bool(_mi_value(track, ["Default"])),
                    "forced": _mi_bool(_mi_value(track, ["Forced"])),
                }
            )

    return {
        "general": general,
        "videos": videos,
        "audios": audios,
        "subtitles": subtitles,
        "tool": "mediainfo",
    }


def _parse_chroma_from_pix_fmt(pix_fmt: Optional[str]) -> Optional[str]:
    if not pix_fmt:
        return None
    m = None
    if "yuv" in pix_fmt:
        m = pix_fmt.split("yuv")[-1]
    if not m:
        return None
    digits = "".join(ch for ch in m if ch.isdigit())
    if len(digits) >= 3:
        return f"{digits[0]}:{digits[1]}:{digits[2]}"
    return None


def _parse_ffprobe(data: Dict[str, Any], filename: str) -> Dict[str, Any]:
    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) if isinstance(fmt, dict) else {}
    general: Dict[str, Any] = {
        "filename": filename,
        "extension": Path(filename).suffix.lstrip("."),
        "size_bytes": parse_int(fmt.get("size")),
        "duration_sec": parse_float(fmt.get("duration")),
        "overall_bitrate": parse_int(fmt.get("bit_rate")),
        "container": first_present(
            [fmt.get("format_long_name"), fmt.get("format_name")]
        ),
        "encoded_date": first_present(
            [
                tags.get("ENCODED_DATE"),
                tags.get("encoded_date"),
                tags.get("DATE"),
            ]
        ),
        "writing_app": first_present(
            [tags.get("WRITING_APPLICATION"), tags.get("writing_application")]
        ),
        "writing_library": first_present(
            [tags.get("WRITING_LIBRARY"), tags.get("writing_library")]
        ),
    }

    videos: List[Dict[str, Any]] = []
    audios: List[Dict[str, Any]] = []
    subtitles: List[Dict[str, Any]] = []

    for stream in data.get("streams", []):
        stype = stream.get("codec_type")
        if stype == "video":
            hdr = None
            transfer = stream.get("color_transfer") or stream.get("color_trc")
            if transfer == "smpte2084":
                hdr = "HDR10"
            elif transfer == "arib-std-b67":
                hdr = "HLG"
            for side_data in stream.get("side_data_list", []) or []:
                if "Dolby Vision" in str(side_data.get("side_data_type", "")):
                    hdr = "Dolby Vision"
            videos.append(
                {
                    "codec": stream.get("codec_name"),
                    "profile": stream.get("profile"),
                    "bitrate": parse_int(stream.get("bit_rate")),
                    "width": parse_int(stream.get("width")),
                    "height": parse_int(stream.get("height")),
                    "aspect_ratio": stream.get("display_aspect_ratio"),
                    "frame_rate": parse_rational(
                        first_present([stream.get("avg_frame_rate"), stream.get("r_frame_rate")])
                    ),
                    "scan_type": stream.get("field_order"),
                    "bit_depth": parse_int(stream.get("bits_per_raw_sample")),
                    "chroma": _parse_chroma_from_pix_fmt(stream.get("pix_fmt")),
                    "color_primaries": stream.get("color_primaries"),
                    "color_transfer": transfer,
                    "color_matrix": stream.get("color_space"),
                    "hdr": hdr,
                }
            )
        elif stype == "audio":
            tags = stream.get("tags", {}) if isinstance(stream, dict) else {}
            audios.append(
                {
                    "codec": stream.get("codec_name"),
                    "bitrate": parse_int(stream.get("bit_rate")),
                    "channels": parse_int(stream.get("channels")),
                    "channel_layout": stream.get("channel_layout"),
                    "sample_rate": parse_int(stream.get("sample_rate")),
                    "language": normalize_language(tags.get("language")),
                    "title": tags.get("title"),
                    "default": bool(stream.get("disposition", {}).get("default")),
                    "forced": bool(stream.get("disposition", {}).get("forced")),
                    "delay_ms": parse_int(stream.get("start_time")),
                }
            )
        elif stype == "subtitle":
            tags = stream.get("tags", {}) if isinstance(stream, dict) else {}
            subtitles.append(
                {
                    "format": stream.get("codec_name"),
                    "language": normalize_language(tags.get("language")),
                    "title": tags.get("title"),
                    "default": bool(stream.get("disposition", {}).get("default")),
                    "forced": bool(stream.get("disposition", {}).get("forced")),
                }
            )

    return {
        "general": general,
        "videos": videos,
        "audios": audios,
        "subtitles": subtitles,
        "tool": "ffprobe",
    }


def extract_tech(path: Path) -> Dict[str, Any]:
    filename = path.name
    if shutil.which("mediainfo"):
        output = _run_cmd(["mediainfo", "--Output=JSON", str(path)])
        if output:
            try:
                return _parse_mediainfo(json.loads(output), filename)
            except json.JSONDecodeError:
                pass
    output = _run_cmd(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    if output:
        try:
            return _parse_ffprobe(json.loads(output), filename)
        except json.JSONDecodeError:
            pass
    raise RuntimeError("Unable to extract technical metadata (mediainfo/ffprobe).")
