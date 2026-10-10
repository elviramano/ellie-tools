#!/usr/bin/env python3
"""Save complete YouTube caption tracks locally, without model processing."""
import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from youtube_transcript_api import YouTubeTranscriptApi

APP_HOME = Path(os.environ.get('YOUTUBE_TRANSCRIPTS_HOME', Path.home() / 'Library/Application Support/YouTube Transcripts'))
CONFIG = APP_HOME / 'config.json'
DEFAULT_OUTPUT = Path.home() / 'Documents/YouTube Transcripts'
VERSION = '1.0.0'


class SaveError(Exception):
    pass


def video_id(value):
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        return value
    if value.startswith(('youtu.be/', 'youtube.com/', 'www.youtube.com/')):
        value = 'https://' + value
    u = urlparse(value)
    if u.scheme not in ('http', 'https') or u.username or u.password:
        raise SaveError('Вставьте ссылку на одно видео YouTube.')
    host = (u.hostname or '').lower()
    if host == 'youtu.be':
        candidate = u.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if u.path == '/watch':
            candidate = parse_qs(u.query).get('v', [''])[0]
        else:
            match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', u.path)
            candidate = match.group(1) if match else ''
    else:
        candidate = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate):
        raise SaveError('Не удалось найти ID видео. Нужна ссылка YouTube на видео, а не канал или плейлист.')
    return candidate


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name[:30], dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def output_folder():
    if CONFIG.exists():
        return Path(json.loads(CONFIG.read_text())['output_dir']).expanduser().resolve()
    return DEFAULT_OUTPUT


def set_output(path):
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    atomic(CONFIG, json.dumps({'output_dir': str(path)}, ensure_ascii=False, indent=2) + '\n')
    return path


def embedded_player(page):
    for match in re.finditer(r'(?:var\s+)?ytInitialPlayerResponse\s*=\s*', page):
        try:
            result, _ = json.JSONDecoder().raw_decode(page[match.end():])
            if isinstance(result, dict):
                return result
        except ValueError:
            pass
    return {}


class CaptureSession(requests.Session):
    """Capture metadata and source XML from the library's existing requests."""
    def __init__(self):
        super().__init__()
        self.player = {}
        self.web_player = {}
        self.caption_xml = ''
        retry = Retry(total=2, backoff_factor=0.7, status_forcelist=[500, 502, 503, 504],
                      allowed_methods=['GET', 'POST'], respect_retry_after_header=False)
        self.mount('https://', HTTPAdapter(max_retries=retry))

    def request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', (10, 30))
        response = super().request(method, url, **kwargs)
        if response.ok:
            if '/watch?' in url:
                self.web_player = embedded_player(response.text)
            elif '/youtubei/v1/player' in url:
                self.player = response.json()
            elif '/api/timedtext' in url:
                self.caption_xml = response.text
        return response


def base_lang(language):
    return language.lower().split('-')[0]


def original_language(player):
    streaming = player.get('streamingData', {})
    audio = [f.get('audioTrack', {}) for f in streaming.get('formats', []) + streaming.get('adaptiveFormats', [])]
    original = {a['id'].split('.')[0] for a in audio
                if a.get('audioIsDefault') and not a.get('isAutoDubbed') and a.get('id')}
    if len(original) == 1:
        return original.pop()
    captions = player.get('captions', {}).get('playerCaptionsTracklistRenderer', {})
    tracks = captions.get('captionTracks', [])
    audio_tracks = captions.get('audioTracks', [])
    index = captions.get('defaultAudioTrackIndex', 0)
    if isinstance(index, int) and 0 <= index < len(audio_tracks):
        selected = audio_tracks[index]
        ci = selected.get('defaultCaptionTrackIndex')
        if isinstance(ci, int) and 0 <= ci < len(tracks):
            return tracks[ci].get('languageCode')
        # Used only if the page has no explicit default caption index.
        if selected.get('audioTrackId'):
            return selected['audioTrackId'].split('.')[0]
    return None


def select_track(tracks, language, players):
    if language == 'auto':
        language = next((v for p in players if (v := original_language(p))), None)
        if not language:
            generated = {base_lang(t.language_code) for t in tracks if t.is_generated}
            all_languages = {base_lang(t.language_code) for t in tracks}
            candidates = generated or all_languages
            if len(candidates) == 1:
                language = candidates.pop()
            else:
                raise SaveError('YouTube не указал исходный язык однозначно. Выберите English или Русский.')
    if base_lang(language) not in ('en', 'ru'):
        raise SaveError(f'Исходный язык — {language}. Для этой библиотеки поддерживаются английский и русский.')
    candidates = [t for t in tracks if base_lang(t.language_code) == base_lang(language)]
    if not candidates:
        raise SaveError(f'Нет субтитров на языке {language}. Перевод автоматически не создаётся.')
    # Native human captions outrank ASR; exact locale breaks ties.
    return min(candidates, key=lambda t: (t.is_generated, t.language_code != language))


def fetch(vid, language='auto'):
    with CaptureSession() as session:
        tracks = list(YouTubeTranscriptApi(http_client=session).list(vid))
        players = [session.web_player, session.player]
        details = next((p['videoDetails'] for p in players if p.get('videoDetails', {}).get('title')), {})
        if details.get('isLive') or any(p.get('videoDetails', {}).get('isLive') for p in players):
            raise SaveError('Эфир ещё идёт. Полный транскрипт можно сохранить после его завершения.')
        track = select_track(tracks, language, players)
        segments = track.fetch().to_raw_data()
        validate_segments(segments)
        if not details.get('title') or not details.get('author'):
            raise SaveError('YouTube не вернул название или канал. Файл не сохранён; повторите позже.')
        published = None
        for p in players:
            micro = p.get('microformat', {}).get('playerMicroformatRenderer', {})
            published = micro.get('publishDate') or micro.get('uploadDate') or published
        metadata = {
            'youtube_id': vid, 'title': details['title'], 'channel': details['author'],
            'url': f'https://www.youtube.com/watch?v={vid}',
            'published_at': published, 'saved_at': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
            'duration_seconds': int(details.get('lengthSeconds', 0)),
            'language': track.language_code, 'caption_type': 'automatic' if track.is_generated else 'manual',
            'segment_count': len(segments), 'caption_end_seconds': max(s['start'] + s['duration'] for s in segments),
            'source': 'YouTube captions', 'app_version': VERSION,
        }
        return metadata, segments, session.caption_xml


def validate_segments(segments):
    if not segments or not any(s.get('text', '').strip() for s in segments):
        raise SaveError('YouTube вернул пустой транскрипт. Файл не сохранён.')
    previous = -1
    for s in segments:
        if not isinstance(s.get('text'), str):
            raise SaveError('Неверный формат текста субтитров.')
        for field in ('start', 'duration'):
            if not isinstance(s.get(field), (int, float)) or not math.isfinite(s[field]) or s[field] < 0:
                raise SaveError('Некорректные таймкоды субтитров. Файл не сохранён.')
        if s['start'] < previous:
            raise SaveError('Нарушен порядок субтитров. Файл не сохранён.')
        previous = s['start']


def clean(text):
    # Whitespace only: no punctuation fixes, word deletion, deduplication or translation.
    return ' '.join(text.split())


def md_escape(text):
    text = html.escape(text, quote=False)
    return re.sub(r'([\\`*_{}\[\]#!|~])', r'\\\1', text)


def timestamp(seconds):
    seconds = int(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def paragraphs(segments):
    group = []
    for segment in segments:
        if group and (segment['start'] - group[0]['start'] >= 30 or sum(len(clean(s['text'])) for s in group) >= 900):
            yield group
            group = []
        group.append(segment)
    if group:
        yield group


def render(metadata, segments):
    fields = dict(metadata)
    fields['tags'] = ['youtube', 'transcript']
    lines = ['---'] + [f'{k}: {json.dumps(v, ensure_ascii=False)}' for k, v in fields.items()] + ['---', '', '# ' + md_escape(metadata['title']), '']
    caption_type = 'автоматические субтитры YouTube' if metadata['caption_type'] == 'automatic' else 'субтитры, загруженные автором'
    lines += [f"**Канал:** {md_escape(metadata['channel'])}  ",
              f"**Оригинал:** {metadata['url']}  ",
              f"**Дата публикации:** {(metadata['published_at'] or 'YouTube не сообщил')[:25]}  ",
              f"**Сохранено:** {metadata['saved_at']}  ",
              f"**Язык:** {metadata['language']} · **Источник текста:** {caption_type}  ",
              f"**Длительность видео:** {timestamp(metadata['duration_seconds'])} · **Фрагментов:** {len(segments)}", '',
              '> Сохранена вся доступная дорожка субтитров без пересказа и правки слов. Ошибки и пропуски исходных субтитров могут сохраняться. Абзацы объединены для чтения; все исходные таймкоды и текст сохранены также в архиве .sources.', '']
    duration = metadata['duration_seconds']
    if duration and duration - metadata['caption_end_seconds'] > 60:
        lines += [f"> Внимание: последний субтитр заканчивается на {timestamp(metadata['caption_end_seconds'])}, раньше конца видео. Это может быть тишина, музыка или неполнота исходной дорожки.", '']
    lines += ['## Транскрипт', '']
    for group in paragraphs(segments):
        start = group[0]['start']
        text = ' '.join(clean(s['text']) for s in group if clean(s['text']))
        lines += [f"[{timestamp(start)}]({metadata['url']}&t={int(start)}s) {md_escape(text)}", '']
    return '\n'.join(lines)


def safe_component(text, limit):
    text = re.sub(r'[\x00-\x1f<>:"/\\|?*]', ' ', text)
    text = clean(text).strip('. ')
    # macOS limits each filename to 255 UTF-8 bytes, not characters.
    return text.encode('utf-8')[:limit].decode('utf-8', errors='ignore').rstrip('. ') or 'Untitled'


def filename(metadata):
    date = metadata['published_at'][:10] if metadata.get('published_at') else 'undated'
    return f"{date} — {safe_component(metadata['channel'], 45)} — {safe_component(metadata['title'], 140)} [{metadata['youtube_id']}].md"


def existing(output, vid):
    # Look at frontmatter too, so a user-renamed file still counts as saved.
    for path in sorted(output.glob('*.md')):
        with path.open(encoding='utf-8') as f:
            head = f.read(8192)
        if re.search(r'^youtube_id:\s*[\"\']?' + re.escape(vid) + r'[\"\']?\s*$', head, re.M):
            if '## Транскрипт' in head or path.stat().st_size > 8192:
                return path
    return None


def save(url, output=None, language='auto', fetcher=fetch):
    vid = video_id(url)
    output = (output or output_folder()).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = output / '.sources'
    sources.mkdir(exist_ok=True)
    with (sources / '.save.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SaveError('Сейчас сохраняется другое видео. Дождитесь завершения и повторите.')
        duplicate = existing(output, vid)
        if duplicate:
            return {'status': 'exists', 'path': str(duplicate), 'message': 'Уже сохранено — дубликат не создан.'}
        metadata, segments, xml = fetcher(vid, language)
        validate_segments(segments)
        text = render(metadata, segments)
        path = output / filename(metadata)
        archive = {'metadata': metadata, 'segments': segments, 'markdown_sha256': hashlib.sha256(text.encode()).hexdigest()}
        # Publish the Markdown last. Interrupted writes can never look like a completed transcript.
        atomic(sources / (vid + '.json'), json.dumps(archive, ensure_ascii=False, indent=2) + '\n')
        if xml:
            atomic(sources / (vid + '.xml'), xml)
        if path.exists():
            raise SaveError('Такое имя уже занято другим файлом. Он не перезаписан.')
        atomic(path, text)
        return {'status': 'saved', 'path': str(path), 'title': metadata['title'], 'language': metadata['language'],
                'segments': len(segments), 'message': 'Транскрипт сохранён.'}


def friendly_error(error):
    kind = type(error).__name__
    if isinstance(error, SaveError):
        return str(error)
    if kind in ('RequestBlocked', 'IpBlocked', 'PoTokenRequired'):
        return 'YouTube временно не разрешает получить субтитры с этого подключения. Файл не сохранён. Повторите позже.'
    if kind in ('TranscriptsDisabled', 'NoTranscriptFound'):
        return 'У этого видео нет доступных субтитров. Оригинальный текст сохранить невозможно; файл не создан.'
    if kind in ('VideoUnavailable', 'VideoUnplayable', 'AgeRestricted'):
        return 'Видео недоступно без входа, удалено или ограничено YouTube. Файл не создан.'
    if isinstance(error, requests.RequestException):
        return 'Не удалось связаться с YouTube. Проверьте интернет и повторите. Файл не создан.'
    if isinstance(error, PermissionError):
        return 'Нет доступа к папке сохранения. Выберите доступную папку в приложении.'
    return f'Не удалось сохранить транскрипт ({kind}). Повторите позже или сообщите эту ошибку в GitHub Issues.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urls', nargs='*')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--language', choices=['auto', 'en', 'ru'], default='auto')
    parser.add_argument('--set-output', type=Path)
    parser.add_argument('--get-output', action='store_true')
    args = parser.parse_args()
    if args.set_output:
        print(json.dumps({'output_dir': str(set_output(args.set_output))}, ensure_ascii=False))
        return 0
    if args.get_output:
        print(json.dumps({'output_dir': str(output_folder()), 'configured': CONFIG.exists()}, ensure_ascii=False))
        return 0
    if not args.urls:
        parser.error('Нужна ссылка YouTube.')
    failed = False
    for url in args.urls:
        try:
            result = save(url, args.output, args.language)
        except Exception as error:
            failed = True
            result = {'status': 'error', 'message': friendly_error(error), 'error_type': type(error).__name__}
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
