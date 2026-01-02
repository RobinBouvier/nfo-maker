"""Rendu texte du NFO a partir des donnees normalisees."""

from __future__ import annotations

from pathlib import Path
import textwrap
from typing import Any, Dict, List, Optional

from .utils import format_bitrate, format_duration, format_size, normalize_language, quality_from_resolution


VIDEO_CODEC_MAP = {
    "avc": "H.264 (AVC)",
    "h264": "H.264 (AVC)",
    "hevc": "H.265 (HEVC)",
    "h265": "H.265 (HEVC)",
    "av1": "AV1",
}

AUDIO_CODEC_MAP = {
    "ac-3": "AC3",
    "e-ac-3": "E-AC3",
    "dts": "DTS",
    "aac": "AAC",
    "truehd": "TrueHD",
}


def _codec_label(value: Optional[str], mapping: Dict[str, str]) -> str:
    """Mappe un codec vers un libelle lisible."""
    if not value:
        return "N/A"
    key = value.strip().lower()
    return mapping.get(key, value)


def _kv(key: str, value: Optional[str], width: int = 20) -> Optional[str]:
    """Formatte une ligne cle/valeur."""
    if value in (None, ""):
        return None
    return f"{key}: {value}"


def _bool_label(value: Optional[bool]) -> Optional[str]:
    """Affiche Yes/No pour un booleen."""
    if value is None:
        return None
    return "Yes" if value else "No"


def _channels_label(channels: Optional[int]) -> Optional[str]:
    """Normalise un nombre de canaux en 5.1/7.1/etc."""
    if not channels:
        return None
    mapping = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
    return mapping.get(channels, str(channels))


def _audio_summary(audios: List[Dict[str, Any]]) -> str:
    """Resume les pistes audio pour le header."""
    parts = []
    for audio in audios:
        lang = normalize_language(audio.get("language")) or "N/A"
        codec = _codec_label(audio.get("codec"), AUDIO_CODEC_MAP)
        channels = _channels_label(audio.get("channels")) or ""
        if channels:
            parts.append(f"{lang} {codec} {channels}")
        else:
            parts.append(f"{lang} {codec}")
    return " + ".join(parts) if parts else "N/A"


def _video_summary(videos: List[Dict[str, Any]]) -> str:
    """Resume la piste video principale pour le header."""
    if not videos:
        return "N/A"
    codec = _codec_label(videos[0].get("codec"), VIDEO_CODEC_MAP)
    return codec


def render_nfo_sections(
    movie: Optional[Dict[str, Any]],
    tech: Dict[str, Any],
    file_info: Dict[str, Any],
    match_note: Optional[str] = None,
    title_override: Optional[str] = None,
    year_override: Optional[int] = None,
    source_override: Optional[str] = None,
) -> List[tuple[str, List[str]]]:
    """Construit les sections NFO pour une verification interactive."""
    general = tech.get("general", {})
    videos = tech.get("videos", [])
    audios = tech.get("audios", [])
    subtitles = tech.get("subtitles", [])

    title = title_override
    year = year_override
    if movie:
        title = movie.get("title") or title
        release = movie.get("release_date") or ""
        if not year and release[:4].isdigit():
            year = int(release[:4])

    if not title:
        title = general.get("filename") or "Unknown"

    title_line = f"{title} ({year})" if year else title

    if videos:
        resolution = quality_from_resolution(videos[0].get("height"), videos[0].get("width"))
    else:
        resolution = "N/A"
    source = source_override or "N/A"
    # Header compact style release.
    header = (
        f"{title_line}\n"
        f"Source: {source}  |  Resolution: {resolution}  |  Video: {_video_summary(videos)}  |  "
        f"Audio: {_audio_summary(audios)}"
    )

    movie_lines: List[str] = []
    if movie:
        movie_lines.extend(
            filter(
                None,
                [
                    _kv("Title", movie.get("title")),
                    _kv("Original Title", movie.get("original_title")),
                    _kv("Year", str(year) if year else None),
                    _kv("Runtime", f"{movie.get('runtime')} min" if movie.get("runtime") else None),
                    _kv(
                        "Genres",
                        ", ".join(g.get("name") for g in movie.get("genres", [])) or None,
                    ),
                    _kv(
                        "Countries",
                        ", ".join(c.get("name") for c in movie.get("production_countries", []))
                        or None,
                    ),
                    _kv("TMDB URL", movie.get("tmdb_url")),
                    _kv("IMDb URL", movie.get("imdb_url")),
                    _kv("TMDB Match", match_note),
                ],
            )
        )
    else:
        movie_lines.append(_kv("Title", title) or "Title                        : N/A")

    general_lines = list(
        filter(
            None,
            [
                _kv("Filename", general.get("filename")),
                _kv("Extension", general.get("extension")),
                _kv("File Size", format_size(general.get("size_bytes"))),
                _kv("Duration", format_duration(general.get("duration_sec"))),
                _kv("Overall Bitrate", format_bitrate(general.get("overall_bitrate"))),
                _kv("Container", general.get("container")),
                _kv("Encoded Date", general.get("encoded_date")),
                _kv("Writing App", general.get("writing_app")),
                _kv("Writing Library", general.get("writing_library")),
            ],
        )
    )

    video_lines: List[str] = []
    if not videos:
        video_lines.append("N/A")
    else:
        for idx, video in enumerate(videos, start=1):
            if len(videos) > 1:
                video_lines.append(f"Video #{idx}")
            video_lines.extend(
                filter(
                    None,
                    [
                        _kv("Format", _codec_label(video.get("codec"), VIDEO_CODEC_MAP)),
                        _kv("Profile", video.get("profile")),
                        _kv("Bitrate", format_bitrate(video.get("bitrate"))),
                        _kv("Resolution", _resolution(video)),
                        _kv("Aspect Ratio", video.get("aspect_ratio")),
                        _kv("Frame Rate", _frame_rate(video)),
                        _kv("Scan Type", video.get("scan_type")),
                        _kv("Bit Depth", _int_unit(video.get("bit_depth"), "bits")),
                        _kv("Chroma", video.get("chroma")),
                        _kv("Color Primaries", video.get("color_primaries")),
                        _kv("Transfer", video.get("color_transfer")),
                        _kv("Matrix", video.get("color_matrix")),
                        _kv("HDR", video.get("hdr")),
                    ],
                )
            )
            if len(videos) > 1:
                video_lines.append("")

    audio_lines: List[str] = []
    if not audios:
        audio_lines.append("N/A")
    else:
        for idx, audio in enumerate(audios, start=1):
            audio_lines.append(f"Audio #{idx}")
            audio_lines.extend(
                filter(
                    None,
                    [
                        _kv("Format", _codec_label(audio.get("codec"), AUDIO_CODEC_MAP)),
                        _kv("Bitrate", format_bitrate(audio.get("bitrate"))),
                        _kv("Channels", _channels_label(audio.get("channels"))),
                        _kv("Channel Layout", audio.get("channel_layout")),
                        _kv("Sample Rate", _int_unit(audio.get("sample_rate"), "Hz")),
                        _kv("Language", audio.get("language")),
                        _kv("Title", audio.get("title")),
                        _kv("Default", _bool_label(audio.get("default"))),
                        _kv("Forced", _bool_label(audio.get("forced"))),
                        _kv("Delay", _int_unit(audio.get("delay_ms"), "ms")),
                    ],
                )
            )
            audio_lines.append("")

    subtitle_lines: List[str] = []
    if not subtitles:
        subtitle_lines.append("N/A")
    else:
        for idx, sub in enumerate(subtitles, start=1):
            subtitle_lines.append(f"Subtitle #{idx}")
            subtitle_lines.extend(
                filter(
                    None,
                    [
                        _kv("Format", sub.get("format")),
                        _kv("Language", sub.get("language")),
                        _kv("Title", sub.get("title")),
                        _kv("Default", _bool_label(sub.get("default"))),
                        _kv("Forced", _bool_label(sub.get("forced"))),
                    ],
                )
            )
            subtitle_lines.append("")

    file_lines = list(
        filter(
            None,
            [
                _kv("Size", format_size(file_info.get("size_bytes"))),
                _kv("Duration", format_duration(file_info.get("duration_sec"))),
                _kv("Hash", file_info.get("hash")),
            ],
        )
    )

    overview_text = movie.get("overview") if movie else None
    summary_lines = [overview_text] if overview_text else ["N/A"]

    return [
        ("Header", [header]),
        ("Movie", movie_lines or ["N/A"]),
        ("Summary", summary_lines),
        ("General", general_lines or ["N/A"]),
        ("Video", video_lines or ["N/A"]),
        ("Audio", audio_lines or ["N/A"]),
        ("Subtitles", subtitle_lines or ["N/A"]),
        ("File", file_lines or ["N/A"]),
    ]


def render_nfo_from_sections(sections: List[tuple[str, List[str]]]) -> str:
    """Construit le NFO complet en appliquant header/footer/separateurs."""
    header_banner = _read_banner("header.txt")
    footer_banner = _read_banner("footer.txt")
    separator_template = _read_banner("separator.txt")

    lines: List[str] = []
    if header_banner:
        lines.extend(header_banner)

    for name, section_lines in sections:
        if name == "Header":
            framed_header = _frame_section_lines(
                section_lines,
                separator_template,
                wrap=True,
                pad=1,
                use_dots=False,
                add_pad_lines=False,
            )
            lines.extend(framed_header if framed_header else section_lines)

    for name, section_lines in sections:
        if name == "Header":
            continue
        separator = _build_separator(name, separator_template)
        if separator:
            lines.extend(separator)
        else:
            lines.append(name)
        framed_lines = _frame_section_lines(
            section_lines,
            separator_template,
            wrap=(name == "Summary"),
            pad=1,
            use_dots=(name != "Summary"),
            add_pad_lines=True,
        )
        lines.extend(framed_lines)

    if footer_banner:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(footer_banner)

    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def render_nfo(
    movie: Optional[Dict[str, Any]],
    tech: Dict[str, Any],
    file_info: Dict[str, Any],
    match_note: Optional[str] = None,
    title_override: Optional[str] = None,
    year_override: Optional[int] = None,
    source_override: Optional[str] = None,
) -> str:
    """Construit le NFO complet en sections Movie/General/Video/Audio/Subtitles/File."""
    sections = render_nfo_sections(
        movie=movie,
        tech=tech,
        file_info=file_info,
        match_note=match_note,
        title_override=title_override,
        year_override=year_override,
        source_override=source_override,
    )
    return render_nfo_from_sections(sections)


def _resolution(video: Dict[str, Any]) -> Optional[str]:
    """Formate la resolution WxH si presente."""
    width = video.get("width")
    height = video.get("height")
    if width and height:
        return f"{width}x{height}"
    return None


def _frame_rate(video: Dict[str, Any]) -> Optional[str]:
    """Formate le framerate avec 3 decimales."""
    rate = video.get("frame_rate")
    if not rate:
        return None
    return f"{rate:.3f} FPS" if isinstance(rate, (int, float)) else str(rate)


def _int_unit(value: Optional[int], unit: str) -> Optional[str]:
    """Ajoute une unite a une valeur numerique."""
    if value is None:
        return None
    return f"{value} {unit}"


def _read_banner(name: str) -> List[str]:
    """Lit un fichier de bannieres (header/footer/separator) si present."""
    banners_dir = Path(__file__).resolve().parent.parent / "banners"
    banner_path = banners_dir / name
    if not banner_path.exists():
        return []
    content = banner_path.read_text(encoding="utf-8")
    return content.splitlines()


def _build_separator(title: str, template_lines: List[str]) -> List[str]:
    """Construit un separateur centre avec le titre de section."""
    if len(template_lines) < 3:
        return []
    top, middle, bottom = template_lines[0], template_lines[1], template_lines[2]
    if len(middle) < 2:
        return [top, middle, bottom]
    inner_width = len(middle) - 2
    safe_title = title[:inner_width]
    centered = safe_title.center(inner_width)
    return [top, f"{middle[0]}{centered}{middle[-1]}", bottom]


def _frame_section_lines(
    lines: List[str],
    template_lines: List[str],
    wrap: bool = False,
    pad: int = 0,
    use_dots: bool = True,
    add_pad_lines: bool = True,
) -> List[str]:
    """Encadre les lignes avec des motifs alternes gauche/droite."""
    if len(template_lines) < 4:
        return list(lines)
    motifs = _extract_motifs(template_lines[3:])
    if not motifs:
        return list(lines)
    width = len(template_lines[0])
    sample_left, sample_right = motifs[0]
    inner_width = width - len(sample_left) - len(sample_right) - (pad * 2)
    framed: List[str] = []
    line_idx = 0
    pad_token = object()
    cleaned = [line for line in lines if line and line.strip()]
    if add_pad_lines:
        render_lines = [pad_token] + cleaned + [pad_token]
    else:
        render_lines = cleaned
    for line in render_lines:
        if line == pad_token:
            chunks = [""]
            line = ""
        else:
            line = line or ""
        if wrap:
            chunks = textwrap.wrap(
                line,
                width=inner_width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            if not chunks:
                chunks = [""]
        else:
            chunks = [line]
        for chunk in chunks:
            left, right = motifs[line_idx % len(motifs)]
            safe_line = _format_line(chunk, inner_width, use_dots=use_dots and ":" in chunk)
            pad_str = " " * pad
            framed.append(f"{left}{pad_str}{safe_line}{pad_str}{right}")
            line_idx += 1
    return framed


def _extract_motifs(lines: List[str]) -> List[tuple[str, str]]:
    """Extrait les motifs gauche/droite depuis les lignes du template."""
    motifs: List[tuple[str, str]] = []
    for line in lines:
        if len(line) < 6:
            continue
        left = line[:3]
        right = line[-3:]
        motifs.append((left, right))
    return motifs


def _format_line(line: str, width: int, use_dots: bool = True) -> str:
    """Formate une ligne (dots ou centré)."""
    if use_dots and ":" in line:
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            text = key[:width]
            return text.center(width)
        left_pad = " " * 5
        right_pad = " " * 5
        usable = width - len(left_pad) - len(right_pad)
        key = key[:usable]
        value = value[:usable]
        dot_width = max(2, usable - len(key) - len(value))
        dots = "." * dot_width
        combined = f"{left_pad}{key}{dots}{value}{right_pad}"
        return combined[:width].ljust(width)
    text = line[:width]
    return text.center(width)
