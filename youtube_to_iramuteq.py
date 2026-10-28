#!/usr/bin/env python3
"""Download YouTube captions, assign speakers, and write an IRaMuTeQ corpus."""

from __future__ import annotations

import argparse
import getpass
import html
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

MODEL = "pyannote/speaker-diarization-community-1"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / "YouTube_Videos"
TIMESTAMP = r"(?:\d{2}:)?\d{2}:\d{2}\.\d{3}"
CUE_TIMING = re.compile(rf"^({TIMESTAMP})\s+-->\s+({TIMESTAMP})(?:\s|$)")
INLINE_TIMING = re.compile(rf"<({TIMESTAMP})>")

# Each tuple contains a start time, an end time, and a word or speaker label.
Word = tuple[float, float, str]
Turn = tuple[float, float, str]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube video URL (put it in quotes)")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help="Output folder (default: data/YouTube_Videos next to this script)",
    )
    parser.add_argument(
        "--language", default="fr-orig",
        help="Exact subtitle language code (default: fr-orig)",
    )
    parser.add_argument(
        "--speaker", action="append", default=[], metavar="LABEL=NAME",
        help="Optional name, e.g. --speaker SPEAKER_00=Presenter; repeat as needed",
    )
    args = parser.parse_args()
    if urlparse(args.url).scheme not in {"https", "http"} or not urlparse(args.url).netloc:
        parser.error("Provide a full video URL, such as https://www.youtube.com/watch?v=...")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.language):
        parser.error("--language must be one exact code, such as fr-orig or fr")
    names = {}
    for item in args.speaker:
        label, separator, name = item.partition("=")
        if not separator or not label.strip() or not name.strip():
            parser.error("Use --speaker LABEL=NAME, for example SPEAKER_00=Presenter")
        names[label.strip()] = name.strip()
    args.speaker_names = names
    return args


def seconds(timestamp: str) -> float:
    """Convert a VTT timestamp to seconds."""
    total = 0.0
    for part in timestamp.split(":"):
        total = total * 60 + float(part)
    return total


def clean_text(text: str) -> str:
    """Remove VTT tags and decode HTML entities."""
    return html.unescape(re.sub(r"<[^>]*>", "", text))


def read_vtt_words(path: Path) -> list[Word]:
    """Read words and remove repeated text from overlapping rolling captions.

    Use inline timestamps when available. Within each timed fragment, divide
    its duration between its words. These word times are estimates.
    """
    content = path.read_text(encoding="utf-8-sig")
    words: list[Word] = []
    previous_end = -1.0

    for block in re.split(r"\n\s*\n", content):
        lines = block.splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_index = next(
            (index for index, line in enumerate(lines) if CUE_TIMING.match(line)),
            None,
        )
        if timing_index is None:
            continue
        match = CUE_TIMING.match(lines[timing_index])
        assert match is not None
        cue_start, cue_end = map(seconds, match.groups())
        if cue_end <= cue_start:
            continue
        payload = " ".join(lines[timing_index + 1:])
        parts = INLINE_TIMING.split(payload)
        fragment_start = cue_start
        cue_words: list[Word] = []

        for index in range(0, len(parts), 2):
            fragment_end = (
                seconds(parts[index + 1]) if index + 1 < len(parts) else cue_end
            )
            fragment_end = min(cue_end, max(fragment_start, fragment_end))
            tokens = clean_text(parts[index]).split()
            duration = fragment_end - fragment_start
            for position, token in enumerate(tokens):
                start = fragment_start + duration * position / len(tokens)
                end = fragment_start + duration * (position + 1) / len(tokens)
                cue_words.append((start, end, token))
            fragment_start = fragment_end

        # Match only the old suffix and new prefix when caption times overlap.
        overlap = 0
        if words and cue_start <= previous_end + 0.05:
            limit = min(len(words), len(cue_words))
            old_tokens = [word for _, _, word in words[-limit:]] if limit else []
            new_tokens = [word for _, _, word in cue_words]
            for count in range(limit, 0, -1):
                if old_tokens[-count:] == new_tokens[:count]:
                    overlap = count
                    break
        words.extend(cue_words[overlap:])
        previous_end = max(previous_end, cue_end)
    return words


def speaker_for_interval(start: float, end: float, turns: list[Turn]) -> str:
    """Choose the speaker with the greatest overlap; leave gaps as UNKNOWN."""
    scores: dict[str, float] = defaultdict(float)
    for turn_start, turn_end, speaker in turns:
        if turn_start >= end:
            break
        if turn_end > start:
            scores[speaker] += max(0.0, min(end, turn_end) - max(start, turn_start))
    return max(scores, key=scores.get) if scores else "UNKNOWN"


def alceste_value(value: str) -> str:
    """Keep ASCII letters and digits in metadata, without changing speech."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]", "", value) or "unknown"


def write_transcript(
    words: list[Word], turns: list[Turn], output_path: Path,
    video_id: str, speaker_names: dict[str, str],
) -> int:
    """Write one ALCESTE text per consecutive run of words from one speaker."""
    blocks: list[str] = []
    current_speaker = "UNKNOWN"
    current_words: list[str] = []

    def save_turn(speaker: str, tokens: list[str]) -> None:
        # Asterisks belong to the corpus structure, not the speech.
        text = re.sub(r"\s+", " ", " ".join(tokens).replace("*", " ")).strip()
        if not text:
            return
        video = alceste_value(video_id)
        participant = f"v{video}s{alceste_value(speaker)}"
        header = (
            f"**** *video_{video} *locuteur_{participant}"
            f" *tour_{len(blocks) + 1:05d}"
        )
        if speaker in speaker_names:
            header += f" *nom_{alceste_value(speaker_names[speaker])}"
        blocks.append(f"{header}\n{text}")

    for start, end, word in words:
        speaker = speaker_for_interval(start, end, turns)
        if speaker != current_speaker:
            save_turn(current_speaker, current_words)
            current_speaker = speaker
            current_words = []
        current_words.append(word)
    save_turn(current_speaker, current_words)
    output_path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
    return len(blocks)


def download_video(url: str, output_dir: Path, language: str) -> tuple[str, Path, Path]:
    """Download audio and one caption language; prefer manual captions if present."""
    from yt_dlp import YoutubeDL

    options = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        # yt-dlp treats subtitle codes as regular expressions.
        "subtitleslangs": [re.escape(language)],
        "subtitlesformat": "vtt",
        "sleep_interval_subtitles": 10,
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if not info or "id" not in info:
            raise ValueError("The URL did not return a video.")
        audio_path = Path(downloader.prepare_filename(info))
    video_id = info["id"]
    # Check this run's selected subtitles rather than reusing a stale VTT file.
    selected = (info.get("requested_subtitles") or {}).get(language)
    if not selected:
        raise FileNotFoundError(
            f"No {language} captions selected. List languages with:\n"
            f'  python -m yt_dlp --list-subs "{url}"\n'
            "Then run this script with --language CODE."
        )
    vtt_path = Path(selected.get("filepath") or output_dir / f"{video_id}.{language}.vtt")
    if not vtt_path.is_file():
        raise FileNotFoundError(f"Caption file not found: {vtt_path}")
    return video_id, audio_path, vtt_path


def convert_audio(source: Path, destination: Path) -> None:
    """Keep the timeline and convert to mono, 16 kHz WAV."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
        check=True,
    )


def diarize_audio(wav_path: Path, token: str) -> list[Turn]:
    """Find speaker intervals using the exclusive pyannote output."""
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(MODEL, token=token)
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
    audio, sample_rate = sf.read(wav_path, dtype="float32", always_2d=True)
    result = pipeline({
        "waveform": torch.from_numpy(audio.T.copy()),
        "sample_rate": sample_rate,
    })
    return sorted(
        (turn.start, turn.end, speaker)
        for turn, _, speaker
        in result.exclusive_speaker_diarization.itertracks(yield_label=True)
    )


def main() -> int:
    args = parse_arguments()
    if not shutil.which("ffmpeg"):
        print("Error: install FFmpeg and add it to PATH.", file=sys.stderr)
        return 1
    try:
        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            token = getpass.getpass("Hugging Face token (hidden): ").strip()
        if not token:
            raise ValueError("A Hugging Face token is required.")
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        video_id, audio_path, vtt_path = download_video(args.url, output_dir, args.language)
        words = read_vtt_words(vtt_path)
        if not words:
            raise ValueError(f"No transcript words found in {vtt_path}")
        wav_path = output_dir / f"{video_id}.16k.wav"
        convert_audio(audio_path, wav_path)
        print(f"Finding speakers in {video_id}...")
        turns = diarize_audio(wav_path, token)
        txt_path = output_dir / f"{video_id}.txt"
        count = write_transcript(words, turns, txt_path, video_id, args.speaker_names)
        if not count:
            raise ValueError("No usable text remained after cleaning.")
        print(f"Saved {count} speaker turns: {txt_path}")
        print("Review captions and speaker assignments before analysis.")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
