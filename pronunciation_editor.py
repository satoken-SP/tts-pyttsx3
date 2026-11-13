"""Local candidate extraction and explicit, per-word dictionary updates."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from conversion_limits import ConversionLimitError

DICTIONARY_PATH = Path(__file__).with_name('change_library.txt')
EXCLUSIONS_PATH = Path(__file__).with_name('pronunciation_exclusions.json')
MAX_TERM_LENGTH = 120
MAX_READING_LENGTH = 240
MAX_CONTEXT_LENGTH = 500
_lock = threading.RLock()
_analysis_lock = threading.Lock()
_english = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[._/\-][A-Za-z0-9]+)*(?:\+\+|#)?')


def validate_word(value, reading=False):
    maximum = MAX_READING_LENGTH if reading else MAX_TERM_LENGTH
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum
            or any(ord(c) < 32 or c in '\u2028\u2029' for c in value)
            or (not reading and ('=' in value or value.strip().startswith('#')))):
        raise ConversionLimitError(f'{"読み" if reading else "単語"}は1～{maximum}文字で、改行を含めず指定してください。単語の先頭の#と単語内の=は使用できません。')
    return value.strip()


def _dictionary_text():
    try:
        with DICTIONARY_PATH.open(encoding='utf-8', newline='') as source:
            return source.read()
    except FileNotFoundError:
        return ''


def _parse_dictionary(text):
    result = {}
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            word, reading = line.split('=', 1)
            result[word.strip()] = reading.strip()
    return result


def _exclusions():
    try:
        value = json.loads(EXCLUSIONS_PATH.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return set()
    if not isinstance(value, list) or any(not isinstance(word, str) for word in value):
        raise ValueError('Invalid pronunciation exclusions file')
    return set(value)


def _atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_exclusions(words):
    _atomic_write(EXCLUSIONS_PATH, json.dumps(sorted(words), ensure_ascii=False, indent=2) + '\n')


def state():
    with _lock:
        return {'dictionary': _parse_dictionary(_dictionary_text()), 'excluded': sorted(_exclusions())}


def save_word(word, reading):
    word, reading = validate_word(word), validate_word(reading, reading=True)
    with _lock:
        original = _dictionary_text()
        newline = '\r\n' if '\r\n' in original else '\n'
        lines = []
        replaced = False
        for line in original.splitlines(keepends=True):
            if (not line.lstrip().startswith('#') and '=' in line
                    and line.split('=', 1)[0].strip() == word):
                if not replaced:
                    lines.append(f'{word}={reading}{newline}')
                    replaced = True
            else:
                lines.append(line)
        if not replaced:
            if original and not original.endswith(('\r', '\n')):
                lines.append(newline)
            lines.append(f'{word}={reading}{newline}')
        _atomic_write(DICTIONARY_PATH, ''.join(lines))
        # The dictionary is now saved. A later exclusion failure must not hide that.
        try:
            excluded = _exclusions()
            if word in excluded:
                excluded.remove(word)
                _write_exclusions(excluded)
        except (OSError, ValueError, UnicodeError) as error:
            return {'exclusion_removed': False, 'error': error}
        return {'exclusion_removed': True}


def set_excluded(word, excluded):
    word = validate_word(word)
    with _lock:
        words = _exclusions()
        if excluded:
            words.add(word)
        else:
            words.discard(word)
        _write_exclusions(words)


@lru_cache(maxsize=1)
def _tokenizer():
    # Load only after the user requests extraction, never during text entry/startup.
    from janome.tokenizer import Tokenizer
    return Tokenizer()


def _context(text, start, end):
    separators = '。！？!?\n\r'
    left = max(text.rfind(mark, 0, start) for mark in separators) + 1
    stops = [position for mark in separators if (position := text.find(mark, end)) >= 0]
    right = min(stops) + 1 if stops else len(text)
    # Very long sentences are shown as an excerpt that always includes the term.
    left = max(left, start - 180)
    right = min(right, left + MAX_CONTEXT_LENGTH)
    return text[left:right].strip()


def extract_candidates(documents):
    from candidate_runner import run_candidates
    if not _analysis_lock.acquire(blocking=False):
        raise ConversionLimitError('候補を抽出中です。完了してから再試行してください。', 429)
    try:
        saved = state()
        return run_candidates(documents, list(set(saved['dictionary']) | set(saved['excluded'])))
    finally:
        _analysis_lock.release()


def _extract_candidates(documents, blocked):
    blocked = set(blocked)
    found = {}
    for source, text in documents:
        english_spans = list(_english.finditer(text))
        candidates = [(m.start(), m.end(), m.group(), '') for m in english_spans]
        offset = 0
        compound = None
        for token in _tokenizer().tokenize(text):
            start = text.find(token.surface, offset)
            if start < 0:
                continue
            end = start + len(token.surface)
            offset = end
            pos = token.part_of_speech.split(',')
            if (pos[0] == '名詞' and pos[1] not in ('数', '非自立', '代名詞', '接尾')
                    and re.search(r'[一-龯々ァ-ヴー]', token.surface)
                    and len(token.surface) >= (1 if pos[1] == '固有名詞' else 2)):
                reading = '' if token.reading == '*' else token.reading
                if compound is not None and compound[1] == start:
                    compound = (compound[0], end, compound[2] + token.surface,
                                compound[3] + reading if compound[3] and reading else '')
                else:
                    if compound is not None:
                        candidates.append(compound)
                    compound = (start, end, token.surface, reading)
            else:
                if compound is not None:
                    candidates.append(compound)
                    compound = None
        if compound is not None:
            candidates.append(compound)
        for start, end, word, reading in sorted(candidates):
            if word in blocked or word in found or len(word) > MAX_TERM_LENGTH:
                continue
            found[word] = {'term': word, 'reading': reading,
                           'sentence': _context(text, start, end), 'source': source}
    return {'candidates': list(found.values())}
