"""日時による命名と、既存ファイルを上書きしない音声出力。"""
from datetime import datetime, timedelta, timezone
import os
from conversion_limits import validate_filename


def timestamp_name():
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M')


def available_name(filename, existing):
    stem, extension = os.path.splitext(filename)
    candidate = filename
    number = 2
    while candidate in existing:
        candidate = f'{stem}-{number}{extension}'
        number += 1
    return candidate


def synthesize_new_file(text, folder, prefix, rate, synthesize):
    """排他的に予約した新規パスにだけ書き込み、失敗時は未完成品を削除する。"""
    filename = f'{prefix}-{timestamp_name()}.wav'
    validate_filename(prefix + '.wav')
    validate_filename(filename)
    stem, extension = os.path.splitext(filename)
    number = 1
    while True:
        candidate = filename if number == 1 else f'{stem}-{number}{extension}'
        path = os.path.join(folder, candidate)
        try:
            with open(path, 'xb'):
                pass
            break
        except FileExistsError:
            number += 1
    completed = False
    try:
        synthesize(text=text, play=False, save_path=path, rate=rate, volume=1.0)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise OSError('音声ファイルの作成に失敗しました')
        completed = True
        return path
    finally:
        if not completed:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
