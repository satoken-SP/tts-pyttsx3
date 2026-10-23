"""音声エンジン専用の子プロセス。入力は親が作った一時JSONだけ。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyttsx3_main import _synthesize_direct
from error_reporting import describe_exception


def main():
    task_path = Path(sys.argv[1])
    result_path = task_path.with_name('result.json')
    try:
        task = json.loads(task_path.read_text(encoding='utf-8'))
        _synthesize_direct(**task)
        result = {'success': True}
    except Exception as error:
        result = {'success': False, 'diagnostics': describe_exception(error)}
    result_path.write_text(json.dumps(result, ensure_ascii=True), encoding='utf-8')
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
