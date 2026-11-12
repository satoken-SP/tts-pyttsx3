"""Fixed parser worker. Data arrives over stdin; no dictionary writes."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pronunciation_editor import _extract_candidates

if __name__ == '__main__':
    task = json.loads(sys.stdin.buffer.read())
    result = _extract_candidates(task['documents'], task['blocked'])
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode('utf-8'))
