# nfo_gen

Generate a release-style .nfo from a video file by combining:
- technical metadata from mediainfo (preferred) or ffprobe
- movie info from TMDB (optional)

## Requirements
- Python 3.11+
- mediainfo or ffprobe available on PATH
- TMDB credentials when using TMDB lookups:
  - TMDB_TOKEN (Bearer token) or
  - TMDB_API_KEY (v3 API key)
  - Or a config file (Windows): %LOCALAPPDATA%\nfo-gen\config.json

## Config file (Windows)
Create `%LOCALAPPDATA%\nfo-gen\config.json` with one of:

```json
{
  "tmdb_token": "YOUR_BEARER_TOKEN"
}
```

or

```json
{
  "tmdb_api_key": "YOUR_API_KEY"
}
```

Environment variables take precedence over the config file.

## Usage
From the repo root:

```bash
python -m nfo_gen "path/to/movie.mkv"
```

Options:
- --tmdb-id <id>
- --title "override"
- --year 2017
- --lang fr-FR
- --output path/to/output.nfo
- --overwrite
- --no-tmdb
- --interactive (guided CLI prompts + TMDB selection)
- --config path/to/config.json
- --hash sha1|sha256
- --print

Examples:

```bash
python -m nfo_gen "Kingsman le Cercle d Or 2017 1080p FR EN X264 AC3-mHDgz.mkv"
python -m nfo_gen --tmdb-id 343668 --lang fr-FR "movie.mkv"
python -m nfo_gen --interactive
```

Interactive flow:
- selects the movie from the first 5 TMDB results
- reviews each NFO section and lets you fix incorrect lines
- handles N/A values (enter a value, keep N/A, or remove the line)
- optional rename to a conventional filename (default: yes)

## Cache
TMDB movie details are cached in:
- Windows: %LOCALAPPDATA%\nfo-gen
- Linux: ~/.cache/nfo-gen

## Tests

```bash
python -m unittest Tests/test_parser_filename.py
```
