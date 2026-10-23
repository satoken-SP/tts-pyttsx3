"""子プロセスを監視し、実行時間・生成量・ディスク空きを制限する。"""
import json
import atexit
import os
from pathlib import Path
import shutil
# 固定のPython/workerを実行し、シェルや利用者指定コマンドは使用しない。
import subprocess  # nosec B404
import sys
import tempfile
import time
import threading
import conversion_limits as limits
from error_reporting import WorkerFailure
WORKER_PATH = Path(__file__).with_name('speech_worker.py')
_active_workers = set()
_worker_lock = threading.Lock()


def check_resources(output_path, started, job):
    now = time.monotonic()
    if now - started >= limits.MAX_FILE_SECONDS or now >= job['deadline']:
        raise limits.ConversionLimitError('変換処理の制限時間を超えたため中断しました。入力を分割してください。', 504)
    size = 0
    if output_path:
        path = Path(output_path)
        size = path.stat().st_size if path.is_file() else 0
        if size > limits.MAX_OUTPUT_BYTES or job['output_bytes'] + size > limits.MAX_JOB_OUTPUT_BYTES:
            raise limits.ConversionLimitError('生成音声の容量上限を超えたため中断しました。入力を分割してください。', 507)
        if shutil.disk_usage(path.parent).free < limits.MIN_FREE_BYTES:
            raise limits.ConversionLimitError('保存先の空き容量が不足しています。空きを確保してから再試行してください。', 507)
    return size


def stop_worker(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def stop_all_workers():
    with _worker_lock:
        workers = list(_active_workers)
    for process in workers:
        stop_worker(process)


atexit.register(stop_all_workers)


def run_speech(task):
    with limits.conversion_job() as job:
        started = time.monotonic()
        output_path = task['save_path']
        if output_path:
            task = {**task, 'save_path': str(Path(output_path).resolve())}
            output_path = task['save_path']
        check_resources(output_path, started, job)
        with tempfile.TemporaryDirectory(prefix='tts-worker-') as directory:
            task_path = Path(directory) / 'task.json'
            task_path.write_text(json.dumps(task, ensure_ascii=True), encoding='utf-8')
            command = [sys.executable, '-I', '-B', str(WORKER_PATH), str(task_path)]
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            # 実行対象は現在のPythonと同梱workerのみ。文章・保存先はJSON経由。
            process = subprocess.Popen(  # nosec B603
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags)
            with _worker_lock:
                _active_workers.add(process)
            try:
                while process.poll() is None:
                    check_resources(output_path, started, job)
                    time.sleep(limits.MONITOR_INTERVAL)
                size = check_resources(output_path, started, job)
                result_path = Path(directory) / 'result.json'
                if not result_path.is_file() or result_path.stat().st_size > 16384:
                    raise RuntimeError('音声エンジンが正常に終了しませんでした。')
                result = json.loads(result_path.read_text(encoding='utf-8'))
                if process.returncode != 0 or not result.get('success'):
                    raise WorkerFailure(result.get('diagnostics', []))
                if output_path and size == 0:
                    raise RuntimeError('音声ファイルの作成に失敗しました。')
                job['output_bytes'] += size
            finally:
                try:
                    stop_worker(process)
                finally:
                    with _worker_lock:
                        _active_workers.discard(process)
