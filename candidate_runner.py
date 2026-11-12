"""Bounded candidate parsing, independent of the browser connection."""
import atexit
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from conversion_limits import ConversionLimitError

MAX_ANALYSIS_SECONDS = 30
WORKER_PATH = Path(__file__).with_name('candidate_worker.py')
_workers = set()
_lock = threading.Lock()


def stop_all_workers():
    with _lock:
        for process in list(_workers):
            if process.poll() is None:
                process.kill()


atexit.register(stop_all_workers)


def run_candidates(documents, blocked):
    started = time.monotonic()
    payload = json.dumps({'documents': documents, 'blocked': blocked}, ensure_ascii=True)
    process = subprocess.Popen(
        [sys.executable, '-I', '-B', str(WORKER_PATH)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    with _lock:
        _workers.add(process)
    try:
        try:
            output, _ = process.communicate(payload.encode('utf-8'),
                timeout=max(0, MAX_ANALYSIS_SECONDS - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            raise ConversionLimitError('候補抽出が制限時間（30秒）を超えました。文章を分けて再試行してください。', 504) from None
        if process.returncode != 0:
            raise RuntimeError('候補抽出プロセスが正常に終了しませんでした。')
        result = json.loads(output)
        if not isinstance(result, dict) or not isinstance(result.get('candidates'), list):
            raise RuntimeError('候補抽出の結果が正しくありません。')
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
        with _lock:
            _workers.discard(process)
