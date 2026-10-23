"""機密情報を含み得る例外文を保存せず、診断用メタデータだけを記録する。"""
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import threading
import traceback

LOG_DIRECTORY = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'tts-pyttsx3' / 'logs'
MAX_LOG_BYTES = 1024 * 1024
LOG_BACKUPS = 3
_write_lock = threading.Lock()
_OPERATIONS = {'convert', 'folder', 'download', 'request', 'cleanup'}


def _name(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,127}', value) else 'unknown'


def _safe_diagnostic(value):
    if not isinstance(value, dict):
        return {'type': 'unknown', 'codes': {}, 'frames': []}
    codes = {name: number for name, number in value.get('codes', {}).items()
             if name in ('errno', 'winerror', 'hresult') and type(number) is int and -(2**63) <= number < 2**63}
    frames = []
    for frame in value.get('frames', [])[-12:]:
        if not isinstance(frame, dict):
            continue
        frames.append({'file': _name(frame.get('file')), 'function': _name(frame.get('function')),
                       'line': frame.get('line') if type(frame.get('line')) is int else 0})
    return {'type': _name(value.get('type')), 'codes': codes, 'frames': frames}


class WorkerFailure(RuntimeError):
    def __init__(self, diagnostics):
        super().__init__('音声エンジンで変換に失敗しました。')
        self.diagnostics = [_safe_diagnostic(item) for item in diagnostics[:4]] if isinstance(diagnostics, list) else []


def describe_exception(error):
    """例外文・args・ローカル変数・ソース行・絶対パスは記録しない。"""
    diagnostics, seen = [], set()
    while error is not None and id(error) not in seen and len(diagnostics) < 4:
        seen.add(id(error))
        codes = {}
        for name in ('errno', 'winerror', 'hresult'):
            value = getattr(error, name, None)
            if type(value) is int:
                codes[name] = value
        frames = [{'file': Path(frame.f_code.co_filename).name,
                   'function': frame.f_code.co_name, 'line': line}
                  for frame, line in traceback.walk_tb(error.__traceback__)]
        diagnostics.append(_safe_diagnostic({'type': type(error).__name__, 'codes': codes, 'frames': frames}))
        if isinstance(error, WorkerFailure):
            diagnostics.extend(error.diagnostics[:4])
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return diagnostics[:8]


class _QuietRotatingHandler(RotatingFileHandler):
    write_failed = False

    def handleError(self, record):
        # logging自身の例外表示にも、レコード内容を流出させない。
        self.write_failed = True


def record_error(error, operation):
    error_id = secrets.token_hex(8)
    handler = None
    saved = False
    try:
        import json
        data = {'timestamp': datetime.now(timezone.utc).isoformat(), 'error_id': error_id,
                'operation': operation if operation in _OPERATIONS else 'request',
                'diagnostics': describe_exception(error)}
        with _write_lock:
            try:
                LOG_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
                handler = _QuietRotatingHandler(LOG_DIRECTORY / 'errors.log', maxBytes=MAX_LOG_BYTES,
                                               backupCount=LOG_BACKUPS, encoding='utf-8', delay=True)
                handler.setFormatter(logging.Formatter('%(message)s'))
                record = logging.LogRecord('tts.errors', logging.ERROR, '', 0,
                                           json.dumps(data, ensure_ascii=True), (), None)
                handler.handle(record)
                saved = not handler.write_failed
            finally:
                if handler is not None:
                    try:
                        handler.close()
                    except Exception:
                        saved = False
    except Exception:
        saved = False
    return error_id, saved
