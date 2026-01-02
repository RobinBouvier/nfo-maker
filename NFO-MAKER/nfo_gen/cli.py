"""Interface en ligne de commande pour nfo_gen."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .extract_tech import extract_tech
from .imdb_client import ImdbClient, ImdbError
from .nfo_template import render_nfo, render_nfo_from_sections, render_nfo_sections
from .parser_filename import parse_filename
from .tmdb_client import TmdbClient, TmdbError
from .utils import compute_hash, format_duration, format_size, normalize_language, quality_from_resolution


SOURCE_TOKENS = {
    "bdrip": "BDRIP",
    "dvdrip": "DVDRIP",
    "webrip": "WEBRIP",
    "webdl": "WEBDL",
    "web-dl": "WEBDL",
    "bluray": "BLURAY",
    "remux": "REMUX",
    "hdrip": "HDRIP",
    "brrip": "BRRIP",
}


def build_parser() -> argparse.ArgumentParser:
    """Construit l'argparse avec les options supportees."""
    parser = argparse.ArgumentParser(
        prog="nfo_gen",
        description="Generate a release-style NFO from a video file.",
    )
    parser.add_argument("video", nargs="?", help="Path to the video file")
    parser.add_argument("--tmdb-id", type=int, help="TMDB movie id")
    parser.add_argument("--title", help="Override movie title")
    parser.add_argument("--year", type=int, help="Override movie year")
    parser.add_argument("--lang", default="fr-FR", help="TMDB language (default: fr-FR)")
    parser.add_argument("--output", help="Output .nfo path")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output file")
    parser.add_argument("--no-tmdb", action="store_true", help="Disable TMDB lookup")
    parser.add_argument("--interactive", action="store_true", help="Interactive guided CLI")
    parser.add_argument("--config", help="Path to config.json (tmdb_token/tmdb_api_key)")
    parser.add_argument("--print", dest="print_out", action="store_true", help="Print NFO to console")
    parser.add_argument(
        "--hash",
        dest="hash_algo",
        choices=["sha1", "sha256"],
        default="sha1",
        help="Hash algorithm for file hash (default: sha1)",
    )
    return parser


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Pose une question oui/non avec un choix par defaut."""
    suffix = " [O/n] " if default else " [o/N] "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in {"o", "oui", "y", "yes"}:
            return True
        if answer in {"n", "non", "no"}:
            return False
        print("Reponse invalide, reessayez.")


def prompt_nonempty(prompt: str) -> str:
    """Demande une valeur non vide."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("La valeur ne peut pas etre vide.")


def prompt_multiline(prompt: str) -> List[str]:
    """Demande plusieurs lignes jusqu'a une ligne vide."""
    print(prompt)
    lines: List[str] = []
    while True:
        value = input().rstrip()
        if not value:
            break
        lines.append(value)
    return lines


def prompt_int_in_range(prompt: str, min_value: int, max_value: int) -> int:
    """Demande un entier dans une plage donnee."""
    while True:
        value = input(prompt).strip()
        if value.isdigit():
            num = int(value)
            if min_value <= num <= max_value:
                return num
        print(f"Entrez un nombre entre {min_value} et {max_value}.")


def format_section(name: str, lines: List[str], numbered: bool = False) -> None:
    """Affiche une section complete."""
    print("")
    print(name)
    if numbered:
        for idx, line in enumerate(lines, start=1):
            label = line if line else "(empty)"
            print(f"{idx:>2}) {label}")
    else:
        for line in lines:
            print(line)


def na_indices(lines: List[str]) -> List[int]:
    """Liste des lignes contenant un N/A."""
    return [idx for idx, line in enumerate(lines) if "N/A" in line]


def replace_line(lines: List[str], idx: int, new_value: str) -> List[str]:
    """Remplace une ligne en preservant l'alignement si possible."""
    value = new_value if new_value.strip() else "N/A"
    line = lines[idx]
    if " : " in line:
        left, _ = line.split(" : ", 1)
        lines[idx] = f"{left} : {value}"
    else:
        lines[idx] = value
    return lines


def replace_header_field(line: str, field: str, value: str) -> str:
    """Remplace une valeur dans la ligne de header (Source/Resolution/etc.)."""
    safe_value = value if value.strip() else "N/A"
    pattern = rf"({re.escape(field)}:\s*)([^|]+)"
    if re.search(pattern, line):
        return re.sub(pattern, rf"\1{safe_value} ", line)
    return line


def slugify_ascii(value: str) -> str:
    """Normalise un texte pour un nom de fichier conventionnel."""
    cleaned = []
    for char in value.strip():
        if char.isalnum() and ord(char) < 128:
            cleaned.append(char)
        else:
            cleaned.append("-")
    slug = "".join(cleaned)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def slugify_release_title(value: str) -> str:
    """Normalise un titre pour un nom de release avec des points."""
    cleaned = []
    for char in value.strip():
        if char.isalnum() and ord(char) < 128:
            cleaned.append(char)
        else:
            cleaned.append(".")
    slug = "".join(cleaned)
    while ".." in slug:
        slug = slug.replace("..", ".")
    return slug.strip(".")


def audio_tag(audios: List[Dict[str, object]]) -> str:
    """Construit un tag audio court pour le nom de fichier."""
    if not audios:
        return "AUDIO"
    audio = audios[0]
    codec = str(audio.get("codec") or "").upper().replace(" ", "")
    channels = audio.get("channels")
    channel_tag = ""
    if isinstance(channels, int):
        channel_tag = f"{channels}ch"
    return (codec + channel_tag) or "AUDIO"


def language_tag(audios: List[Dict[str, object]]) -> str:
    """Construit un tag langue court (ex: MULTi/FR/EN)."""
    langs: List[str] = []
    for audio in audios:
        lang = normalize_language(audio.get("language"))
        if lang and lang not in langs:
            langs.append(lang)
    if not langs:
        return "LANG"
    if len(langs) > 1:
        return "MULTi"
    return langs[0]


def video_tag(videos: List[Dict[str, object]]) -> str:
    """Construit un tag video court (H264/H265/AV1)."""
    if not videos:
        return "VIDEO"
    codec = str(videos[0].get("codec") or "").lower()
    if codec in {"hevc", "h265"}:
        return "H265"
    if codec in {"avc", "h264"}:
        return "H264"
    if codec == "av1":
        return "AV1"
    return codec.upper() or "VIDEO"


def build_conventional_name(
    video_path: Path,
    title: Optional[str],
    year: Optional[int],
    tech: Dict[str, object],
    source: Optional[str],
) -> str:
    """Propose un nom de fichier conventionnel."""
    general = tech.get("general", {}) if isinstance(tech, dict) else {}
    videos = tech.get("videos", []) if isinstance(tech, dict) else []
    audios = tech.get("audios", []) if isinstance(tech, dict) else []
    base_title = title or general.get("filename") or video_path.stem
    title_slug = slugify_release_title(str(base_title))
    year_tag = str(year) if year else "YEAR"
    lang = language_tag(audios) if isinstance(audios, list) else "LANG"
    source = (source or "SOURCE").upper()
    resolution = "RESOLUTION"
    if videos:
        height = videos[0].get("height")
        width = videos[0].get("width")
        resolution = quality_from_resolution(height, width)
    video = video_tag(videos) if isinstance(videos, list) else "VIDEO"
    group = "TSC"
    ext = video_path.suffix
    return f"{title_slug}.{year_tag}.{lang}.{resolution}.{source}.{video}-{group}{ext}"


def prompt_rename(
    video_path: Path,
    title: Optional[str],
    year: Optional[int],
    tech: Dict[str, object],
    source: Optional[str],
) -> Path:
    """Propose un renommage de fichier et applique si confirme."""
    proposed = build_conventional_name(video_path, title, year, tech, source)
    print(f"Nom propose: {proposed}")
    if not prompt_yes_no("Renommer le fichier avec ce nom ?", default=True):
        manual = input("Nom manuel (laisser vide pour ne pas renommer): ").strip()
        if not manual:
            return video_path
        proposed = manual
    target = Path(proposed)
    if not target.is_absolute():
        target = video_path.parent / target
    if target.exists() and target != video_path:
        if not prompt_yes_no(f"{target} existe. Ecraser ?", default=False):
            return video_path
    if target == video_path:
        return video_path
    video_path.rename(target)
    return target


def detect_source_from_name(filename: str) -> Optional[str]:
    """Detecte une source probable depuis le nom de fichier."""
    tokens = re.split(r"[^a-z0-9]+", filename.lower())
    for token in tokens:
        if token in SOURCE_TOKENS:
            return SOURCE_TOKENS[token]
    return None


def build_file_info(video_path: Path, tech: Dict[str, object], hash_algo: str) -> Dict[str, object]:
    """Construit les informations de fichier pour le NFO."""
    general = tech.get("general", {})
    size_bytes = general.get("size_bytes") or video_path.stat().st_size
    duration_sec = general.get("duration_sec")
    file_hash = compute_hash(video_path, hash_algo)
    return {
        "path": str(video_path),
        "size_bytes": size_bytes,
        "duration_sec": duration_sec,
        "hash": f"{hash_algo.upper()} {file_hash}",
    }


def enrich_movie(client: TmdbClient, movie: Optional[Dict[str, object]]) -> None:
    """Ajoute les liens TMDB/IMDb au film si possible."""
    if not movie or not movie.get("id"):
        return
    movie["tmdb_url"] = f"https://www.themoviedb.org/movie/{movie['id']}"
    try:
        external = client.get_external_ids(movie["id"])
    except TmdbError:
        return
    imdb_id = external.get("imdb_id") if isinstance(external, dict) else None
    if imdb_id:
        movie["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}"


def main(argv: Optional[list[str]] = None) -> int:
    """Point d'entree principal: genere le NFO pour un fichier video."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.video and not args.interactive:
        parser.error("video is required unless --interactive is used")

    if args.video:
        video_path = Path(args.video)
    else:
        video_path = None

    if args.interactive:
        while not video_path or not video_path.exists():
            if video_path and not video_path.exists():
                print("Fichier introuvable, reessayez.")
            candidate = Path(prompt_nonempty("Chemin du fichier video: ").strip('"'))
            if candidate.exists():
                video_path = candidate

    if not video_path or not video_path.exists():
        print(f"File not found: {video_path}", file=sys.stderr)
        return 1

    # Extraction technique via MediaInfo/ffprobe.
    try:
        tech = extract_tech(video_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Parsing du nom de fichier pour titre/annee.
    parsed = parse_filename(video_path.name)
    title = args.title or parsed.title
    year = args.year or parsed.year
    source = detect_source_from_name(video_path.name)

    movie: Optional[Dict[str, object]] = None
    match_note: Optional[str] = None
    client: Optional[TmdbClient] = None
    imdb_client: Optional[ImdbClient] = None
    if not args.no_tmdb:
        # Client TMDB (env ou config).
        config_path = Path(args.config) if args.config else None
        client = TmdbClient.from_env(config_path=config_path)
        imdb_client = ImdbClient.from_env(config_path=config_path)
        try:
            # Resout le film (id direct ou recherche).
            movie, match_note = client.resolve_movie(
                tmdb_id=args.tmdb_id,
                title=title,
                year=year,
                lang=args.lang,
                interactive=args.interactive,
            )
            if movie and not year:
                release = str(movie.get("release_date") or "")
                if release[:4].isdigit():
                    year = int(release[:4])
            if not movie and imdb_client and imdb_client.api_key and title:
                try:
                    imdb_result = imdb_client.search_title(title, year=year)
                except ImdbError:
                    imdb_result = None
                if imdb_result:
                    imdb_title, imdb_year = imdb_result
                    print(f"IMDb title: {imdb_title} ({imdb_year or 'N/A'})")
                    movie, match_note = client.resolve_movie(
                        tmdb_id=args.tmdb_id,
                        title=imdb_title,
                        year=imdb_year or year,
                        lang=args.lang,
                        interactive=args.interactive,
                    )
            if not movie and args.interactive:
                if prompt_yes_no("Aucun resultat TMDB. Lancer une recherche TMDB manuelle ?", default=True):
                    manual = input("Titre de recherche TMDB (laisser vide pour ignorer): ").strip()
                    if manual:
                        movie, match_note = client.resolve_movie(
                            tmdb_id=args.tmdb_id,
                            title=manual,
                            year=year,
                            lang=args.lang,
                            interactive=args.interactive,
                        )
                if not movie:
                    manual = input("Aucun resultat TMDB. Titre manuel (laisser vide pour ignorer): ").strip()
                    if manual:
                        movie, match_note = client.resolve_movie(
                            tmdb_id=args.tmdb_id,
                            title=manual,
                            year=year,
                            lang=args.lang,
                            interactive=args.interactive,
                        )
            if client:
                enrich_movie(client, movie)
        except TmdbError as exc:
            print(f"TMDB error: {exc}", file=sys.stderr)
            return 1

    file_info = build_file_info(video_path, tech, args.hash_algo)

    if args.interactive:
        sections = render_nfo_sections(
            movie=movie,
            tech=tech,
            file_info=file_info,
            match_note=match_note,
            title_override=title,
            year_override=year,
            source_override=source,
        )
        manual_sections: set[str] = set()

        def refresh_section(name: str, manual: set[str]) -> Dict[str, List[str]]:
            nonlocal movie, match_note, tech, file_info
            updates: Dict[str, List[str]] = {}
            if name in {"Movie", "Header"}:
                if args.no_tmdb:
                    print("TMDB est desactive.")
                    return updates
                if not client:
                    print("TMDB non configure.")
                    return updates
                movie, match_note = client.resolve_movie(
                    tmdb_id=args.tmdb_id,
                    title=title,
                    year=year,
                    lang=args.lang,
                    interactive=True,
                )
                enrich_movie(client, movie)
                new_sections = render_nfo_sections(
                    movie=movie,
                    tech=tech,
                    file_info=file_info,
                    match_note=match_note,
                    title_override=title,
                    year_override=year,
                    source_override=source,
                )
                section_map = {sec: sec_lines for sec, sec_lines in new_sections}
                updates["Movie"] = section_map.get("Movie", [])
                if "Header" not in manual:
                    updates["Header"] = section_map.get("Header", [])
            elif name in {"General", "Video", "Audio", "Subtitles"}:
                try:
                    tech = extract_tech(video_path)
                except RuntimeError as exc:
                    print(str(exc))
                    return updates
                file_info = build_file_info(video_path, tech, args.hash_algo)
                new_sections = render_nfo_sections(
                    movie=movie,
                    tech=tech,
                    file_info=file_info,
                    match_note=match_note,
                    title_override=title,
                    year_override=year,
                    source_override=source,
                )
                section_map = {sec: sec_lines for sec, sec_lines in new_sections}
                updates[name] = section_map.get(name, [])
                if "Header" not in manual:
                    updates["Header"] = section_map.get("Header", [])
            elif name == "File":
                file_info = build_file_info(video_path, tech, args.hash_algo)
                new_sections = render_nfo_sections(
                    movie=movie,
                    tech=tech,
                    file_info=file_info,
                    match_note=match_note,
                    title_override=title,
                    year_override=year,
                    source_override=source,
                )
                section_map = {sec: sec_lines for sec, sec_lines in new_sections}
                updates["File"] = section_map.get("File", [])
            return updates

        idx = 0
        while idx < len(sections):
            name, lines = sections[idx]
            while True:
                format_section(name, lines, numbered=False)
                missing = na_indices(lines)
                if missing:
                    if name == "Header":
                        header_line = lines[0] if lines else ""
                        if "Source:" in header_line and "Source: N/A" in header_line:
                            print("Valeur N/A detectee: Source.")
                            print("  1) Entrer une valeur manuellement")
                            print("  2) Laisser N/A")
                            choice = prompt_int_in_range("Choix: ", 1, 2)
                            if choice == 1:
                                new_value = input("Source: ").strip()
                                lines[0] = replace_header_field(header_line, "Source", new_value)
                                source = new_value or source
                                manual_sections.add(name)
                                sections[idx] = (name, lines)
                                continue
                        else:
                            print("Valeurs N/A detectees.")
                    else:
                        print("Valeurs N/A detectees.")
                    format_section(name, lines, numbered=True)
                    line_idx = prompt_int_in_range(
                        "Numero de ligne a changer: ", 1, len(lines)
                    )
                    current_line = lines[line_idx - 1]
                    print("  1) Entrer une valeur manuellement")
                    print("  2) Laisser N/A")
                    print("  3) Supprimer la ligne")
                    choice = prompt_int_in_range("Choix: ", 1, 3)
                    did_change = False
                    if choice == 1:
                        new_value = input("Nouvelle valeur: ").strip()
                        lines = replace_line(lines, line_idx - 1, new_value)
                        manual_sections.add(name)
                        did_change = True
                    elif choice == 3:
                        lines.pop(line_idx - 1)
                        if not lines:
                            lines.append("N/A")
                        manual_sections.add(name)
                        did_change = True
                    sections[idx] = (name, lines)
                    if did_change:
                        continue
                if prompt_yes_no(f"Section {name} correcte ?", default=True):
                    break
                format_section(name, lines, numbered=True)
                line_idx = prompt_int_in_range(
                    "Numero de ligne a changer: ", 1, len(lines)
                )
                if prompt_yes_no("Retenter une detection automatique ?", default=False):
                    updates = refresh_section(name, manual_sections)
                    if updates:
                        sections = [
                            (sec, updates.get(sec, sec_lines))
                            for sec, sec_lines in sections
                        ]
                        lines = dict(sections).get(name, lines)
                        if name in manual_sections:
                            manual_sections.remove(name)
                    else:
                        print("Aucune mise a jour automatique disponible.")
                else:
                    current_line = lines[line_idx - 1]
                    if "N/A" in current_line or current_line.strip().upper() == "N/A":
                        print("La ligne est N/A.")
                        print("  1) Entrer une valeur manuellement")
                        print("  2) Laisser N/A")
                        print("  3) Supprimer la ligne")
                        choice = prompt_int_in_range("Choix: ", 1, 3)
                        if choice == 1:
                            new_value = input("Nouvelle valeur: ").strip()
                            if name == "Header" and "Source:" in current_line:
                                lines[line_idx - 1] = replace_header_field(
                                    current_line, "Source", new_value
                                )
                                source = new_value or source
                            else:
                                lines = replace_line(lines, line_idx - 1, new_value)
                            manual_sections.add(name)
                        elif choice == 3:
                            lines.pop(line_idx - 1)
                            if not lines:
                                lines.append("N/A")
                            manual_sections.add(name)
                    else:
                        new_value = input("Nouvelle valeur: ").strip()
                        lines = replace_line(lines, line_idx - 1, new_value)
                        manual_sections.add(name)
                    sections[idx] = (name, lines)
                format_section(name, lines, numbered=False)
                if prompt_yes_no(f"Section {name} correcte maintenant ?", default=True):
                    break
            sections[idx] = (name, lines)
            idx += 1
        if prompt_yes_no("Renommer le fichier dans un format conventionnel ?", default=True):
            if not source:
                source = input("Source (BDRIP/WEBRIP/etc., laisser vide pour SOURCE): ").strip() or None
            rename_title = title
            if movie and movie.get("title"):
                rename_title = str(movie.get("title"))
            rename_year = year
            if movie and not rename_year:
                release = str(movie.get("release_date") or "")
                if release[:4].isdigit():
                    rename_year = int(release[:4])
            video_path = prompt_rename(video_path, rename_title, rename_year, tech, source)
            file_info = build_file_info(video_path, tech, args.hash_algo)
        if prompt_yes_no("Ajouter une section Notes ?", default=False):
            note_lines = prompt_multiline("Entrez les notes (ligne vide pour terminer):")
            if note_lines:
                sections.append(("Notes", note_lines))
        if prompt_yes_no("Ajouter une section Greetz ?", default=False):
            greetz_lines = prompt_multiline("Entrez les greetz (ligne vide pour terminer):")
            if greetz_lines:
                sections.append(("Greetz", greetz_lines))
        # Reconstruit le NFO avec les sections ajustees.
        nfo_text = render_nfo_from_sections(sections)
    else:
        # Rendu final du NFO.
        nfo_text = render_nfo(
            movie=movie,
            tech=tech,
            file_info=file_info,
            match_note=match_note,
            title_override=title,
            year_override=year,
            source_override=source,
        )

    output_path = Path(args.output) if args.output else video_path.with_suffix(".nfo")
    if output_path.exists() and not args.overwrite:
        if args.interactive and prompt_yes_no(f"{output_path} existe. Ecraser ?", default=False):
            pass
        else:
            print(f"Output exists: {output_path} (use --overwrite)", file=sys.stderr)
            return 1

    # Ecriture du fichier NFO.
    output_path.write_text(nfo_text, encoding="utf-8")
    if args.print_out:
        print(nfo_text)

    size_bytes = file_info.get("size_bytes")
    duration_sec = file_info.get("duration_sec")
    print(
        f"Wrote NFO: {output_path} ({format_size(size_bytes)}, {format_duration(duration_sec)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
