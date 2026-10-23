"""Web/CLI共通の入力制限と、同一チェックアウト内の変換ジョブ制御。"""
from contextlib import contextmanager
from functools import wraps
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

MAX_TEXT_LENGTH = 100000
MAX_INPUT_BYTES = 500 * 1024
MAX_BATCH_FILES = 20
MAX_BATCH_CHARACTERS = 500000
MAX_FILE_SECONDS = 60 * 60
MAX_JOB_SECONDS = 120 * 60
MAX_OUTPUT_BYTES = 1024 * 1024 * 1024
MAX_JOB_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_BYTES = 1024 * 1024 * 1024
MONITOR_INTERVAL = 0.1
_slot = threading.Lock()
_local = threading.local()


class ConversionLimitError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_text(text, limit=None):
    limit = MAX_TEXT_LENGTH if limit is None else limit
    if not isinstance(text, str) or not text.strip():
        raise ConversionLimitError('テキストが入力されていません。')
    if len(text) > limit:
        raise ConversionLimitError(f'テキストは最大{limit:,}文字までです。辞書変換後も同じ上限です。')


def validate_options(rate, volume=1.0):
    if isinstance(rate, bool) or not isinstance(rate, int) or not 50 <= rate <= 400:
        raise ConversionLimitError('読み上げ速度は50～400の整数で指定してください。')
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ConversionLimitError('音量は0～1の有限の数値で指定してください。')


def validate_filename(filename):
    # 拡張子が付いても予約名。末尾の空白/ピリオドや制御文字も拒否する。
    if (not filename or filename[-1] in ' .' or
            any(ord(char) < 32 or char in '/\\:*?"<>|' for char in filename) or
            filename in ('.', '..') or len(filename) > 240):
        raise ConversionLimitError('ファイル名に使用できない文字が含まれています。')
    stem = filename.split('.', 1)[0].rstrip(' ').upper()
    if re.fullmatch(r'CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³]', stem):
        raise ConversionLimitError('Windowsの予約名はファイル名に使用できません。')


def read_text_file(path):
    if not Path(path).is_file():
        raise ConversionLimitError('入力には通常のテキストファイルを指定してください。')
    with open(path, 'rb') as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ConversionLimitError('ファイルサイズは500KiB以下にしてください。')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ConversionLimitError('入力ファイルはUTF-8で保存してください。') from error
    validate_text(text)
    return text


def current_job():
    return getattr(_local, 'job', None)


@contextmanager
def conversion_job():
    if current_job() is not None:
        yield current_job()
        return
    if not _slot.acquire(blocking=False):
        raise ConversionLimitError('ほかの変換を実行中です。完了してから再試行してください。', 429)
    lockfile = None
    locked = False
    try:
        checkout = str(Path(__file__).resolve().parent).casefold().encode('utf-8')
        identifier = hashlib.sha256(checkout).hexdigest()[:24]
        lockfile = open(Path(tempfile.gettempdir()) / f'tts-conversion-{identifier}.lock', 'a+b')
        if os.fstat(lockfile.fileno()).st_size == 0:
            lockfile.write(b'0')
            lockfile.flush()
        lockfile.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ConversionLimitError('ほかの変換を実行中です。完了してから再試行してください。', 429) from error
        locked = True
        _local.job = {'deadline': time.monotonic() + MAX_JOB_SECONDS, 'output_bytes': 0}
        yield _local.job
    finally:
        _local.job = None
        try:
            if lockfile is not None:
                try:
                    if locked:
                        lockfile.seek(0)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)
                finally:
                    lockfile.close()
        finally:
            _slot.release()


def serialized_conversion(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with conversion_job():
            return function(*args, **kwargs)
    return wrapped
