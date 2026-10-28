# YouTube to IRaMuTeQ

This script turns a YouTube video's captions into a text file for IRaMuTeQ.
It downloads the audio, finds when each speaker talks, and assigns the caption
words to speakers. It uses existing captions; it does not transcribe the audio.

## Setup

Use Python 3.10 or later and install [FFmpeg](https://ffmpeg.org/download.html).
FFmpeg must be available in your terminal. Check with `ffmpeg -version`.

Put `youtube_to_iramuteq.py` and `requirements.txt` in one folder. Open a terminal
in that folder, then run:

```bash
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the Python packages:

```bash
python -m pip install -r requirements.txt
```

On Hugging Face, accept the conditions for
[the speaker model](https://huggingface.co/pyannote/speaker-diarization-community-1)
and create a [read token](https://huggingface.co/settings/tokens).
The script asks for this token without displaying it. For unattended runs,
set the `HF_TOKEN` environment variable. Do not put tokens in the script or README.
Revoke any token you have shared and create a new one.

## Run

The URL is required. Keep the quotes:

```bash
python youtube_to_iramuteq.py "https://www.youtube.com/watch?v=45jNv0XptsU"
```

The default subtitle code is `fr-orig`. To see the video's available codes:

```bash
python -m yt_dlp --list-subs "https://www.youtube.com/watch?v=45jNv0XptsU"
```

Use another code or output folder:

```bash
python youtube_to_iramuteq.py "https://www.youtube.com/watch?v=45jNv0XptsU" --language fr --output-dir ./corpus
```

After checking who is speaking, add names with repeated options:

```bash
python youtube_to_iramuteq.py "https://www.youtube.com/watch?v=45jNv0XptsU" --speaker SPEAKER_00=Presenter --speaker "SPEAKER_01=Guest Name"
```

Names add metadata; they do not change the model's speaker assignments.
Use `python youtube_to_iramuteq.py --help` to see all options.

## Output

By default, files go in `data/YouTube_Videos` beside the script:

- The downloaded audio.
- `<video_id>.<language>.vtt`: captions and timestamps.
- `<video_id>.16k.wav`: mono audio for speaker detection.
- `<video_id>.txt`: the UTF-8 corpus to open in IRaMuTeQ.

Running the same video again replaces its WAV and corpus files.
The model downloads on first use. It uses a CUDA GPU if available, or the CPU.
Long videos need more time and memory.

## ALCESTE format

Each consecutive run of words assigned to one speaker becomes one text:

```text
**** *video_45jNv0XptsU *locuteur_v45jNv0XptsUsSPEAKER00 *tour_00001 *nom_Presenter
Bonjour à tous. Voici le sujet du jour.

**** *video_45jNv0XptsU *locuteur_v45jNv0XptsUsSPEAKER01 *tour_00002
Merci pour cette invitation.
```

`****` starts a text. The starred fields describe it:

| Field | Meaning |
| --- | --- |
| `*video_...` | Video identifier. |
| `*locuteur_...` | Video identifier plus speaker label. |
| `*tour_...` | Turn number, starting at `00001` in each video. |
| `*nom_...` | Optional speaker name. |

Each field follows `*variable_value`. Metadata keeps only ASCII letters and
digits: `SPEAKER_00` becomes `SPEAKER00`, and `Guest Name` becomes `GuestName`.
Speech keeps its accents and punctuation. Asterisks in speech become spaces
because they are reserved for corpus structure.

## Use in IRaMuTeQ

1. Choose **Fichier → Ouvrir un corpus texte** (or **Ouvrir un corpus**).
2. Select the generated `.txt` file.
3. Choose **UTF-8**, the language of the captions, and `****` as the text marker.
4. Import the corpus and check its text count and word statistics.

IRaMuTeQ analyzes the speech. Starred fields are metadata, not speech words.
Use `locuteur` to compare vocabulary between speakers or select a speaker's
texts; use `video` when combining recordings. Keep `tour` as a reference rather
than a comparison group. IRaMuTeQ may split each text into smaller segments for
analysis. Short speaker turns can limit classification results.

Review the corpus before analysis. Captions and speaker detection can contain
errors. Word times are estimates. `UNKNOWN` means no speaker interval overlapped
the word. Simultaneous speech is reduced to one speaker assignment. Labels such
as `SPEAKER_00` do not identify the same person across recordings.

## References

- [IRaMuTeQ documentation: corpus format and import](https://pratinaud.gitpages.huma-num.fr/iramuteq-website/documentation/documentation_19_02_2014.pdf)
- [pyannote model: setup and speaker detection](https://huggingface.co/pyannote/speaker-diarization-community-1)
- [yt-dlp: downloads and subtitles](https://github.com/yt-dlp/yt-dlp#readme)
