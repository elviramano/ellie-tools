#!/usr/bin/env python3
"""Build the macOS app from source; requires Python 3.11+ and Xcode CLI tools."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path.home(),
                        help='Installation home (default: your home; override for isolated tests)')
    args = parser.parse_args()
    if sys.platform != 'darwin' or sys.version_info < (3, 11):
        parser.error('Requires macOS and Python 3.11 or newer.')
    subprocess.run(['xcrun', '--find', 'swiftc'], check=True, capture_output=True)
    source = Path(__file__).resolve().parent
    prefix = args.prefix.expanduser().resolve()
    support = prefix / 'Library/Application Support/YouTube Transcripts'
    applications = prefix / 'Applications'
    app = applications / 'YouTube Transcripts.app'
    support.mkdir(parents=True, exist_ok=True)
    applications.mkdir(parents=True, exist_ok=True)
    venv = support / 'venv'
    if not (venv / 'bin/python').exists():
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
    python = venv / 'bin/python'
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(source / 'requirements.txt')], check=True)
    with tempfile.TemporaryDirectory(prefix='youtube-transcripts-build-') as tmp:
        stage = Path(tmp) / 'YouTube Transcripts.app'
        contents = stage / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Resources').mkdir()
        env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(Path(tmp) / 'module-cache'))
        subprocess.run(['xcrun', 'swiftc', str(source / 'App.swift'), '-o',
                        str(contents / 'MacOS/YouTubeTranscripts'), '-framework', 'Cocoa',
                        '-O', '-target', os.uname().machine + '-apple-macosx13.0'], check=True, env=env)
        for name in ['transcripts.py', 'requirements.txt']:
            shutil.copy2(source / name, contents / 'Resources' / name)
        for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
            shutil.copy2(source.parent / name, contents / 'Resources' / name)
        plist = {'CFBundleExecutable': 'YouTubeTranscripts',
                 'CFBundleIdentifier': 'local.ellie-tools.youtube-transcripts',
                 'CFBundleName': 'YouTube Transcripts', 'CFBundleDisplayName': 'YouTube Transcripts',
                 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.0.0',
                 'CFBundleVersion': '1', 'LSMinimumSystemVersion': '13.0',
                 'NSHighResolutionCapable': True, 'YTSupportDirectory': str(support)}
        with (contents / 'Info.plist').open('wb') as f:
            plistlib.dump(plist, f)
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(stage)], check=True)
        # Build and sign before touching a previous installation.
        replacement = applications / '.YouTube Transcripts.installing.app'
        if replacement.exists():
            parser.error(f'An unfinished installation exists at {replacement}; inspect it before retrying.')
        shutil.copytree(stage, replacement)
        backup = applications / '.YouTube Transcripts.previous.app'
        if backup.exists():
            shutil.rmtree(replacement)
            parser.error(f'A previous backup exists at {backup}; inspect it before retrying.')
        had_app = app.exists()
        if had_app:
            app.rename(backup)
        try:
            replacement.rename(app)
        except OSError:
            if had_app:
                backup.rename(app)
            raise
        if had_app:
            shutil.rmtree(backup)
    print(json.dumps({'app': str(app), 'python': str(python)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
