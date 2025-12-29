"""Interface en ligne de commande pour nfo_gen."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .extract_tech import extract_tech
from .nfo_template import render_nfo
from .parser_filename import parse_filename
from .tmdb_client import TmdbClient, TmdbError
from .utils import compute_hash, format_duration, format_size


def build_parser() -> argparse.ArgumentParser:
    """Construit l'argparse avec les options supportees."""
    parser = argparse.ArgumentParser(
        prog="nfo_gen",
        description="Generate a release-style NFO from a video file.",
    )
    parser.add_argument("video", help="Path to the video file")
    parser.add_argument("--tmdb-id", type=int, help="TMDB movie id")
    parser.add_argument("--title", help="Override movie title")
    parser.add_argument("--year", type=int, help="Override movie year")
    parser.add_argument("--lang", default="fr-FR", help="TMDB language (default: fr-FR)")
    parser.add_argument("--output", help="Output .nfo path")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output file")
    parser.add_argument("--no-tmdb", action="store_true", help="Disable TMDB lookup")
    parser.add_argument("--interactive", action="store_true", help="Interactive TMDB selection")
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


def main(argv: Optional[list[str]] = None) -> int:
    """Point d'entree principal: genere le NFO pour un fichier video."""
    parser = build_parser()
    args = parser.parse_args(argv)

    video_path = Path(args.video)
    if not video_path.exists():
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

    movie = None
    match_note = None
    if not args.no_tmdb:
        # Client TMDB (env ou config).
        config_path = Path(args.config) if args.config else None
        client = TmdbClient.from_env(config_path=config_path)
        try:
            # Resout le film (id direct ou recherche).
            movie, match_note = client.resolve_movie(
                tmdb_id=args.tmdb_id,
                title=title,
                year=year,
                lang=args.lang,
                interactive=args.interactive,
            )
            if movie and movie.get("id"):
                movie["tmdb_url"] = f"https://www.themoviedb.org/movie/{movie['id']}"
                try:
                    # Ajoute l'URL IMDb si possible.
                    external = client.get_external_ids(movie["id"])
                    imdb_id = external.get("imdb_id") if isinstance(external, dict) else None
                    if imdb_id:
                        movie["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}"
                except TmdbError:
                    pass
        except TmdbError as exc:
            print(f"TMDB error: {exc}", file=sys.stderr)
            return 1

    # Infos fichier: taille/duree/hash.
    size_bytes = tech.get("general", {}).get("size_bytes")
    duration_sec = tech.get("general", {}).get("duration_sec")
    if size_bytes is None:
        size_bytes = video_path.stat().st_size
    if duration_sec is None:
        duration_sec = None

    file_hash = compute_hash(video_path, args.hash_algo)
    file_info = {
        "path": str(video_path),
        "size_bytes": size_bytes,
        "duration_sec": duration_sec,
        "hash": f"{args.hash_algo.upper()} {file_hash}",
    }

    # Rendu final du NFO.
    nfo_text = render_nfo(
        movie=movie,
        tech=tech,
        file_info=file_info,
        match_note=match_note,
        title_override=title,
        year_override=year,
    )

    output_path = Path(args.output) if args.output else video_path.with_suffix(".nfo")
    if output_path.exists() and not args.overwrite:
        print(f"Output exists: {output_path} (use --overwrite)", file=sys.stderr)
        return 1

    # Ecriture du fichier NFO.
    output_path.write_text(nfo_text, encoding="utf-8")
    if args.print_out:
        print(nfo_text)

    print(
        f"Wrote NFO: {output_path} ({format_size(size_bytes)}, {format_duration(duration_sec)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
