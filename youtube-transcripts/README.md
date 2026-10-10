# YouTube Transcripts

A small native macOS app: paste a YouTube link, press Save, and get the full available caption track as Markdown. No summarization, translation, or LLM calls. The app interface and document labels are currently in Russian; caption text stays in its original language (English or Russian).

## Features

- Original-language detection, including videos with multiple automatically dubbed tracks.
- Uploaded captions preferred over automatic captions in the selected language.
- Readable paragraphs with clickable timestamps approximately every 30 seconds.
- Title, channel, canonical URL, publication date when available, local save time, language, and caption type.
- Filenames: `YYYY-MM-DD — Channel — Title [video-id].md`.
- Duplicate detection by the video ID stored inside the Markdown, including renamed files.
- Raw XML and JSON archives in `.sources/`, preserving every caption's text, start time, and duration.
- Atomic file writes and a folder lock to prevent concurrent saves from producing duplicates.
- No subscriptions, API keys, analytics, background service, or automatic updates.

## Install from source

Requirements: macOS 13+, Python 3.11+, and Apple's Xcode Command Line Tools. The installer builds for the current Mac's architecture. The first release was tested on Apple Silicon; Intel and older macOS versions have not been tested.

Install Python from [python.org](https://www.python.org/downloads/macos/) if needed. Install Apple's command line tools if absent:

```sh
xcode-select --install
```

Then clone and build:

```sh
git clone https://github.com/elviramano/ellie-tools.git
cd ellie-tools/youtube-transcripts
python3 install.py
open "$HOME/Applications/YouTube Transcripts.app"
```

Installation uses `~/Applications/YouTube Transcripts.app` and an isolated Python environment in `~/Library/Application Support/YouTube Transcripts/`. It does not install Python packages globally. It downloads pinned dependencies from PyPI. Quit an existing instance before reinstalling. The source installer signs the local build with an ad-hoc signature; this is not a notarized, standalone binary distribution.

The installed app depends on the Python interpreter used to create its environment. If that interpreter is removed, reinstall the app with a supported Python. Do not move the built app to a different Mac: build it there instead.

## Use

On first launch, choose an output folder. The suggested location is `~/Documents/YouTube Transcripts`; cancelling the picker keeps that default for the current launch. You can change it with **Выбрать папку…** at any time.

1. Paste a video link, or click **Вставить** to read the clipboard.
2. Leave **Исходный язык — автоматически** selected, or choose English / Русский.
3. Press **Сохранить транскрипт**.
4. Use **Открыть папку** to open the result folder.

Clipboard content is read only when you press Paste. The app sends the requested video's ID to YouTube. Caption text is processed locally and is not sent to an AI service.

Duplicate checks cover Markdown files directly in the selected folder. Changing the folder does not move earlier files or search other folders. An existing transcript is returned unchanged even if a different language is selected. Files remain ordinary Markdown suitable for Obsidian or manual use in AI tools; the app does not connect or sync to those services.

## Command line

```sh
"$HOME/Library/Application Support/YouTube Transcripts/venv/bin/python" \
  "$HOME/Applications/YouTube Transcripts.app/Contents/Resources/transcripts.py" \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

Multiple links are supported. Options: `--language auto|en|ru`, `--output PATH`, `--get-output`, `--set-output PATH`. Each video produces one JSON result; any failed video makes the process exit nonzero. `YOUTUBE_TRANSCRIPTS_HOME` overrides the settings directory for isolated runs. `install.py --prefix PATH` installs under a separate home directory for testing.

## Fidelity and limitations

The app saves the **entire available caption track**, not a guarantee that every spoken word in the audio was captioned accurately. Only whitespace is normalized; the app does not correct names, punctuation, repetitions, or recognition errors. The library parses subtitle markup into plain text, while the raw XML is retained for inspection. Paragraph timestamps are rounded down to the nearest second; the JSON archive keeps the original precision for every cue.

If captions end more than a minute before the video, the Markdown includes a warning. This can mean silence, music, or incomplete source captions. This heuristic cannot prove transcript completeness. Missing captions, restricted videos, ongoing live streams, blocked requests, and network errors produce an error instead of an empty transcript. Audio transcription, login cookies, proxy services, and access-restriction bypasses are not included.

The app uses the unofficial [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api). YouTube can change its interfaces or block requests. Failures may require a dependency or code update. Requests have bounded retries and timeouts; the GUI stops a job after three minutes. No paid service is required, but uninterrupted future availability is not guaranteed. Respect content creators' rights and applicable service terms; the software license does not license downloaded videos or transcripts.

## Development and verification

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
```

Tests use synthetic captions and no network. They cover URL parsing, original-language selection, caption priority, Russian text, ambiguous tracks, content fidelity, filename limits, duplicates after renaming, failures, timestamps, and concurrent writes.

The initial version was also checked locally against three public English videos and one Russian video. All words in the downloaded caption segments matched the generated Markdown after removing formatting and normalizing whitespace. Downloaded material and personal configuration are intentionally not included in the repository.

Swift/AppKit implements the window. `transcripts.py` implements retrieval and Markdown output. `install.py` builds and installs both. After source changes, run tests and reinstall to update the installed copy. The current dependency versions are pinned in `requirements.txt`.
