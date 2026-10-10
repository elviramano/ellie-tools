import copy
import fcntl
import html
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace as Track
import unittest

import transcripts as t

ID = 'abcDEF12345'
META = {'youtube_id': ID, 'title': 'Тест / Test ** <literal>', 'channel': 'Канал',
        'url': 'https://www.youtube.com/watch?v=' + ID, 'published_at': '2026-10-10',
        'saved_at': '2026-10-10T12:00:00-07:00', 'duration_seconds': 60,
        'language': 'ru', 'caption_type': 'manual', 'caption_end_seconds': 60}
SEGMENTS = [{'text': 'Да, да!\nНе удалять повтор.', 'start': 0., 'duration': 12.},
            {'text': '2 < 3 & [brackets] **literal**', 'start': 13., 'duration': 18.},
            {'text': 'Последняя реплика.', 'start': 32.5, 'duration': 27.5}]


def fake(vid, lang):
    return dict(META, youtube_id=vid), copy.deepcopy(SEGMENTS), '<transcript/>'


class Tests(unittest.TestCase):
    def test_url_variants_same_id(self):
        for url in [ID, 'https://youtu.be/' + ID + '?is=whatever',
                    'https://www.youtube.com/watch?v=' + ID + '&list=x&t=50',
                    'https://m.youtube.com/shorts/' + ID]:
            self.assertEqual(t.video_id(url), ID)

    def test_reject_non_youtube_and_injection(self):
        for url in ['https://evil.example/watch?v=' + ID, 'https://youtube.com.evil/watch?v=' + ID,
                    'https://youtube.com/playlist?list=x', '$(touch /tmp/injected)',
                    'https://youtube.com@evil.example/watch?v=' + ID]:
            with self.assertRaises(t.SaveError):
                t.video_id(url)

    def test_original_audio_outranks_first_translation(self):
        tracks = [Track(language_code='ar', is_generated=True), Track(language_code='ru', is_generated=True),
                  Track(language_code='en', is_generated=True)]
        player = {'streamingData': {'adaptiveFormats': [
            {'audioTrack': {'id': 'ru.10', 'audioIsDefault': False, 'isAutoDubbed': True}},
            {'audioTrack': {'id': 'en-US.4', 'audioIsDefault': True}}]}}
        self.assertEqual(t.select_track(tracks, 'auto', [player]).language_code, 'en')

    def test_author_track_preferred(self):
        tracks = [Track(language_code='en', is_generated=True), Track(language_code='en', is_generated=False)]
        self.assertFalse(t.select_track(tracks, 'auto', [{}]).is_generated)

    def test_russian_auto_detect(self):
        tracks = [Track(language_code='ru', is_generated=True)]
        self.assertEqual(t.select_track(tracks, 'auto', [{}]).language_code, 'ru')

    def test_ambiguous_language_not_guessed(self):
        tracks = [Track(language_code='ru', is_generated=True), Track(language_code='en', is_generated=True)]
        with self.assertRaises(t.SaveError):
            t.select_track(tracks, 'auto', [{}])

    def test_default_caption_index(self):
        player = {'captions': {'playerCaptionsTracklistRenderer': {
            'captionTracks': [{'languageCode': 'ru'}, {'languageCode': 'en'}],
            'audioTracks': [{'defaultCaptionTrackIndex': 1}], 'defaultAudioTrackIndex': 0}}}
        self.assertEqual(t.original_language(player), 'en')

    def test_roundtrip_words_and_special_characters(self):
        body = t.render(META, SEGMENTS).split('## Транскрипт\n\n', 1)[1]
        body = re.sub(r'\[\d\d:\d\d:\d\d\]\([^\n]*?\) ', '', body)
        body = html.unescape(re.sub(r'\\([\\`*_{}\[\]#!|~])', r'\1', body))
        self.assertEqual(t.clean(body), t.clean(' '.join(s['text'] for s in SEGMENTS)))
        self.assertIn('&t=32s', t.render(META, SEGMENTS))

    def test_unicode_filename_byte_limit(self):
        name = t.filename(dict(META, title='я' * 400, channel='ю' * 100))
        self.assertLessEqual(len(name.encode()), 255)
        self.assertNotIn('/', name)

    def test_duplicate_even_after_rename_no_network(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            result = t.save('https://youtu.be/' + ID, output, fetcher=fake)
            renamed = output / 'My renamed transcript.md'
            Path(result['path']).rename(renamed)
            def fail(*args):
                self.fail('Duplicate must not make a network request')
            duplicate = t.save('https://youtube.com/watch?v=' + ID + '&t=100', output, fetcher=fail)
            self.assertEqual(duplicate['status'], 'exists')
            self.assertEqual(duplicate['path'], str(renamed.resolve()))
            self.assertEqual(len(list(output.glob('*.md'))), 1)
            raw = json.loads((output / '.sources' / (ID + '.json')).read_text())
            self.assertEqual(raw['segments'], SEGMENTS)

    def test_failure_does_not_publish_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            def fail(*args):
                raise RuntimeError('simulated network failure')
            with self.assertRaises(RuntimeError):
                t.save(ID, output, fetcher=fail)
            self.assertEqual(list(output.glob('*.md')), [])

    def test_empty_invalid_or_unordered_rejected(self):
        for data in [[], [{'text': 'a', 'start': float('nan'), 'duration': 1}],
                     [{'text': 'a', 'start': 4, 'duration': 1}, {'text': 'b', 'start': 1, 'duration': 1}]]:
            with self.assertRaises(t.SaveError):
                t.validate_segments(data)

    def test_overlapping_spoken_repetition_retained(self):
        data = [{'text': 'yes', 'start': 0, 'duration': 3}, {'text': 'yes', 'start': 1, 'duration': 3}]
        t.validate_segments(data)
        self.assertIn('yes yes', t.render(META, data))

    def test_simultaneous_save_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / '.sources').mkdir()
            with (output / '.sources/.save.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(t.SaveError):
                    t.save(ID, output, fetcher=fake)

    def test_metadata_json_braces_and_escaping(self):
        player = {'videoDetails': {'title': 'Test } "quoted"'}}
        self.assertEqual(t.embedded_player('var ytInitialPlayerResponse = ' + json.dumps(player) + '; other'), player)


if __name__ == '__main__':
    unittest.main()
