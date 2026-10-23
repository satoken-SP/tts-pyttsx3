from flask import Flask, Request, render_template, request, jsonify, send_file
import os
import secrets
import tempfile
import threading
import time
import atexit
from werkzeug.exceptions import RequestEntityTooLarge, SecurityError, HTTPException
from change_token_katakana import apply_pronunciations, load_pronunciation_dictionary
from pyttsx3_main import synthesize_text
from output_files import timestamp_name, available_name, synthesize_new_file
import conversion_limits as limits
from speech_runner import stop_all_workers
from error_reporting import record_error

class UploadRequest(Request):
    """容量・項目数の超過で解析が中断されても、作成済みストリームを閉じる。"""

    def _get_file_stream(self, total_content_length, content_type, filename=None,
                         content_length=None):
        stream = super()._get_file_stream(total_content_length, content_type,
                                          filename, content_length)
        self.__dict__.setdefault('_upload_streams', []).append(stream)
        return stream

    def close(self):
        try:
            super().close()
        finally:
            for stream in self.__dict__.pop('_upload_streams', []):
                stream.close()


app = Flask(__name__)
app.request_class = UploadRequest
# 通常利用では環境変数由来のデバッグ設定も無効にする。
app.config['DEBUG'] = False
# 単独PCの通常起動専用。ポートを含むHostも下の検証で限定する。
app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1']
ALLOWED_HOSTS = frozenset({'localhost:5051', '127.0.0.1:5051'})
csrf_token = secrets.token_hex(32)


def internal_error_payload(error, operation):
    error_id, saved = record_error(error, operation)
    # ターミナルにも例外本文・トレースバック・リクエスト内容は出さない。
    app.logger.error('Internal error: operation=%s error_id=%s log_saved=%s', operation, error_id, saved)
    messages = {
        'convert': '音声変換に失敗しました。アプリを再起動して再試行してください。',
        'folder': 'このファイルの音声変換に失敗しました。',
        'download': '音声の取得に失敗しました。再試行してください。',
        'request': '処理に失敗しました。アプリを再起動して再試行してください。'
    }
    message = messages.get(operation, messages['request'])
    if not saved:
        message += ' 詳細ログの保存にも失敗しました。ディスクの空き容量と権限を確認してください。'
    return {'error': message, 'error_id': error_id}


@app.errorhandler(Exception)
def unexpected_error(error):
    if isinstance(error, HTTPException) and error.code is not None and error.code < 500:
        message = {400: '要求の形式が正しくありません。', 404: '対象が見つかりません。',
                   405: 'この操作方法は許可されていません。', 416: '音声の取得範囲が正しくありません。'}.get(
                       error.code, '要求を処理できません。')
        response = error.get_response()
        response.set_data(app.json.dumps({'error': message}))
        response.mimetype = 'application/json'
        return response
    return jsonify(internal_error_payload(error, 'request')), 500


@app.errorhandler(SecurityError)
def untrusted_host(error):
    return jsonify({'error': '許可されていない接続先です。http://localhost:5051 から開いてください。'}), 400


@app.errorhandler(limits.ConversionLimitError)
def conversion_limit_error(error):
    response = jsonify({'error': str(error)})
    if error.status == 429:
        response.headers['Retry-After'] = '5'
    return response, error.status


@app.before_request
def validate_local_request():
    # フォーム解析や一時音声の掃除より前に拒否する。
    host = request.host.lower()
    if host not in ALLOWED_HOSTS or request.scheme != 'http':
        return jsonify({'error': '許可されていない接続先です。http://localhost:5051 から開いてください。'}), 400
    if request.method in ('GET', 'HEAD'):
        return None
    if (request.headers.get('Origin') != f'http://{host}' or
            request.headers.get('Sec-Fetch-Site') == 'cross-site'):
        return jsonify({'error': 'この画面以外からの操作は許可されていません。ツールのページから操作してください。'}), 403
    supplied_token = request.headers.get('X-CSRF-Token', '')
    if not secrets.compare_digest(supplied_token.encode('utf-8'), csrf_token.encode('ascii')):
        return jsonify({'error': '操作の確認に失敗しました。ページを再読み込みしてから、もう一度お試しください。'}), 403
    return None


@app.after_request
def protect_local_response(response):
    # トークンを含む画面の保存や、外部ページへの埋め込みを防ぐ。
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    return response

# このプロセスで生成を完了した音声だけを公開する。表示名は保存先に使わない。
# アプリ再起動時には登録を引き継がない。
audio_directory = tempfile.TemporaryDirectory(prefix='tts-pyttsx3-')
# 通常終了では子を止めてから一時音声を掃除する。
atexit.register(stop_all_workers)
generated_audio = {}
generated_audio_times = {}
generated_audio_lock = threading.Lock()
AUDIO_TTL_SECONDS = 24 * 60 * 60
MAX_RETAINED_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
MAX_RETAINED_AUDIO_FILES = 100


def prune_audio_locked(incoming_bytes=0, incoming_files=0):
    """呼出元がロックを保持。配信中など削除できないファイルは次回再試行。"""
    now = time.monotonic()
    for token in set(generated_audio_times) - set(generated_audio):
        generated_audio_times.pop(token, None)
    sizes = {}
    for token, (path, _) in list(generated_audio.items()):
        if not os.path.isfile(path):
            generated_audio.pop(token, None)
            generated_audio_times.pop(token, None)
        else:
            sizes[token] = os.path.getsize(path)
    total = sum(sizes.values())
    for token in sorted(sizes, key=lambda key: generated_audio_times.get(key, 0)):
        expired = now - generated_audio_times.get(token, 0) >= AUDIO_TTL_SECONDS
        over_limit = (total + incoming_bytes > MAX_RETAINED_AUDIO_BYTES or
                      len(generated_audio) + incoming_files > MAX_RETAINED_AUDIO_FILES)
        if not expired and not over_limit:
            continue
        path, _ = generated_audio[token]
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            # Windowsで配信中のファイル等は消せない。期限の延長はしない。
            continue
        total -= sizes[token]
        generated_audio.pop(token, None)
        generated_audio_times.pop(token, None)
    return (total + incoming_bytes <= MAX_RETAINED_AUDIO_BYTES and
            len(generated_audio) + incoming_files <= MAX_RETAINED_AUDIO_FILES)


def audio_cleanup_loop():
    while True:
        time.sleep(60)
        try:
            with generated_audio_lock:
                prune_audio_locked()
        except OSError as error:
            internal_error_payload(error, 'cleanup')


@app.before_request
def cleanup_expired_audio():
    with generated_audio_lock:
        prune_audio_locked()

# 制限設定
MAX_TEXT_LENGTH = limits.MAX_TEXT_LENGTH
MAX_FILE_SIZE = limits.MAX_INPUT_BYTES
MAX_REQUEST_SIZE = 1024 * 1024  # HTTPリクエスト全体（1MiB）
MAX_FORM_FIELD_SIZE = 400 * 1024  # ファイル以外の項目（400KiB）
MAX_FORM_PARTS = 10
app.config.update(
    MAX_CONTENT_LENGTH=MAX_REQUEST_SIZE,
    MAX_FORM_MEMORY_SIZE=MAX_FORM_FIELD_SIZE,
    MAX_FORM_PARTS=MAX_FORM_PARTS,
)

# 辞書を読み込み
pronunciation_dictionary = load_pronunciation_dictionary()


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(error):
    return jsonify({
        'error': '送信データが上限を超えています。要求全体は1MiB、フォームは10項目まで、'
                 '各項目は400KiBまでです。ファイルは500KiB以下にしてください。'
    }), 413


@app.before_request
def validate_conversion_form():
    if request.endpoint != 'convert_text' or request.method != 'POST':
        return None

    if request.mimetype not in ('multipart/form-data', 'application/x-www-form-urlencoded'):
        return jsonify({'error': 'フォーム形式で送信してください。'}), 415

    # 解析時の413をconvert_textの包括的な例外処理に取り込ませない。
    form, files = request.form, request.files
    field_count = sum(len(values) for _, values in form.lists())
    field_count += sum(len(values) for _, values in files.lists())
    if field_count > MAX_FORM_PARTS:
        raise RequestEntityTooLarge()

    # URLエンコード形式にも、デコード後の各項目の容量制限を適用する。
    for _, values in form.lists():
        if any(len(value.encode('utf-8')) > MAX_FORM_FIELD_SIZE for value in values):
            raise RequestEntityTooLarge()

    allowed_fields = {'inputType', 'text', 'outputFilename', 'rate'}
    if set(form) - allowed_fields or set(files) - {'file'}:
        return jsonify({'error': '未対応のフォーム項目が含まれています。'}), 400
    for name in set(form) | set(files):
        if len(form.getlist(name)) + len(files.getlist(name)) > 1:
            return jsonify({'error': '同じフォーム項目を複数送信できません。'}), 400

    input_type = form.get('inputType')
    if input_type not in ('text', 'file', 'folder'):
        return jsonify({'error': '入力種別が正しくありません。'}), 400
    if files and input_type != 'file':
        return jsonify({'error': 'この入力種別ではファイルを送信できません。'}), 400
    rate = form.get('rate', '200')
    if not rate or len(rate) > 10 or not rate.isascii() or not rate.isdecimal():
        return jsonify({'error': '読み上げ速度は50～400の整数で指定してください。'}), 400
    if not 50 <= int(rate) <= 400:
        return jsonify({'error': '読み上げ速度は50～400の整数で指定してください。'}), 400
    return None

@app.route('/')
def index():
    return render_template('index.html', csrf_token=csrf_token,
        max_batch_files=limits.MAX_BATCH_FILES,
        max_batch_characters=f'{limits.MAX_BATCH_CHARACTERS:,}',
        max_file_minutes=f'{limits.MAX_FILE_SECONDS / 60:g}',
        max_job_minutes=f'{limits.MAX_JOB_SECONDS / 60:g}',
        max_file_gib=f'{limits.MAX_OUTPUT_BYTES / (1024 ** 3):g}',
        max_job_gib=f'{limits.MAX_JOB_OUTPUT_BYTES / (1024 ** 3):g}')

@app.route('/convert', methods=['POST'])
@limits.serialized_conversion
def convert_text():
    # 変換開始時間を記録
    start_time = time.time()
    
    try:
        output_filename = request.form.get('outputFilename', '').strip()
        automatic_filename = not output_filename
        if automatic_filename:
            output_filename = timestamp_name() + '.wav'
        input_type = request.form.get('inputType')
        rate = int(request.form.get('rate', 200))  # ここで先に取得
        
        # 危険な文字やパスをチェック
        dangerous_chars = ['/', '\\', '..', '~', ':', '*', '?', '"', '<', '>', '|']
        if any(char in output_filename for char in dangerous_chars):
            return jsonify({'error': 'ファイル名に使用できない文字が含まれています'}), 400
        
        # ファイル名の長さを制限
        if len(output_filename) > 100:
            return jsonify({'error': 'ファイル名が長すぎます'}), 400
        
        # ファイル名からディレクトリ部分を除去
        safe_filename = os.path.basename(output_filename)
        
        # 出力ファイル名の拡張子を確認
        if not safe_filename.endswith('.wav'):
            safe_filename += '.wav'
        limits.validate_filename(safe_filename)
        
        # 入力タイプに応じてテキストを取得
        if input_type == 'file':
            # ファイルアップロードの場合
            if 'file' not in request.files:
                return jsonify({'error': 'ファイルが選択されていません'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'ファイルが選択されていません'}), 400
            
            # ファイルサイズの制限チェック
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)  # ファイルポインタを先頭に戻す
            
            if file_size > MAX_FILE_SIZE:
                return jsonify({
                    'error': f'ファイルサイズが大きすぎます。最大{MAX_FILE_SIZE // 1024}KBまでです。'
                }), 400
            
            # ファイルの内容を読み込み
            try:
                content = file.read().decode('utf-8')
            except UnicodeDecodeError:
                return jsonify({'error': 'ファイルの文字エンコーディングが正しくありません。UTF-8で保存してください。'}), 400
            
            # ファイル内容の文字数制限チェック
            if len(content) > MAX_TEXT_LENGTH:
                return jsonify({
                    'error': f'ファイルの内容が長すぎます。最大{MAX_TEXT_LENGTH:,}文字までです。'
                }), 400
            
        elif input_type == 'folder':
            # フォルダ処理の場合
            input_folder = 'input'
            output_folder = 'output'
            
            # inputフォルダの存在確認
            if not os.path.exists(input_folder):
                return jsonify({'error': f'入力フォルダ "{input_folder}" が存在しません。'}), 400
            
            # outputフォルダの作成（存在しない場合）
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
            
            # inputフォルダ内のtxtファイルを取得
            txt_files = []
            with os.scandir(input_folder) as entries:
                for entry in entries:
                    if entry.name.endswith('.txt') and entry.is_file(follow_symlinks=False):
                        txt_files.append(entry.name)
                        if len(txt_files) > limits.MAX_BATCH_FILES:
                            raise limits.ConversionLimitError(
                                f'フォルダ処理は最大{limits.MAX_BATCH_FILES}ファイルまでです。分けて実行してください。')
            
            if not txt_files:
                return jsonify({'error': f'"{input_folder}" フォルダ内にtxtファイルが見つかりません。'}), 400
            # 件数・総文字数は全件の合成前に検査。読み込んだ内容をそのまま使用する。
            prepared = {}
            total_characters = 0
            for txt_file in sorted(txt_files):
                limits.validate_filename(txt_file)
                content = limits.read_text_file(os.path.join(input_folder, txt_file))
                processed = apply_pronunciations(content, pronunciation_dictionary, max_length=MAX_TEXT_LENGTH)
                limits.validate_text(processed)
                total_characters += max(len(content), len(processed))
                if total_characters > limits.MAX_BATCH_CHARACTERS:
                    raise limits.ConversionLimitError(
                        f'フォルダ処理は合計{limits.MAX_BATCH_CHARACTERS:,}文字までです。分けて実行してください。')
                prepared[txt_file] = processed
            
            # 各ファイルを処理
            processed_files = []
            total_conversion_time = 0
            interrupted = False
            
            for txt_file in prepared:
                try:
                    # 事前検査したスナップショットを使用する。
                    content = prepared[txt_file]
                    
                    # 専門用語変換処理
                    processed_text = content
                    
                    # 元の名前に日時・連番を付け、新しい保存先だけを使用する。
                    base_name = os.path.splitext(txt_file)[0]
                    
                    # 音声変換処理
                    file_start_time = time.time()
                    output_path = synthesize_new_file(
                        processed_text, output_folder, base_name, rate, synthesize_text)
                    output_filename = os.path.basename(output_path)
                    file_end_time = time.time()
                    file_conversion_time = round(file_end_time - file_start_time, 2)
                    total_conversion_time += file_conversion_time
                    
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'success',
                        'output_filename': output_filename,
                        'conversion_time': file_conversion_time
                    })
                    
                except limits.ConversionLimitError as error:
                    processed_files.append({'filename': txt_file, 'status': 'error', 'message': str(error)})
                    interrupted = True
                    break
                except UnicodeDecodeError:
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'error',
                        'message': 'ファイルの文字エンコーディングが正しくありません。UTF-8で保存してください。'
                    })
                except Exception as error:
                    payload = internal_error_payload(error, 'folder')
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'error',
                        'message': payload['error'],
                        'error_id': payload['error_id']
                    })
            
            # フォルダ処理の結果を返す
            return jsonify({
                'success': True,
                'message': (f'フォルダ処理を中断しました。未処理{len(prepared) - len(processed_files)}ファイル。完成済みの音声は保持しています。'
                            if interrupted else f'フォルダ処理が完了しました。{len(processed_files)}ファイルを処理しました。'),
                'interrupted': interrupted,
                'processed_files': processed_files,
                'total_conversion_time': round(total_conversion_time, 2),
                'input_type': 'folder'
            })
            
        else:
            # テキストエリアの場合
            content = request.form.get('text', '')
            if not content.strip():
                return jsonify({'error': 'テキストが入力されていません'}), 400
            
            # テキストの文字数制限チェック
            if len(content) > MAX_TEXT_LENGTH:
                return jsonify({
                    'error': f'テキストが長すぎます。最大{MAX_TEXT_LENGTH:,}文字までです。'
                }), 400
        
        # 専門用語変換処理（辞書ファイルから読み込んだ辞書を使用）
        processed_text = apply_pronunciations(content, pronunciation_dictionary, max_length=MAX_TEXT_LENGTH)
        limits.validate_text(processed_text, limit=MAX_TEXT_LENGTH)
        
        # 専用領域へ衝突しない名前で保存し、完成後にだけ公開する。
        descriptor, output_path = tempfile.mkstemp(suffix='.wav', dir=audio_directory.name)
        os.close(descriptor)
        registered = False
        try:
            synthesize_text(
                text=processed_text,
                play=False,
                save_path=output_path,
                rate=rate,
                volume=1.0
            )
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError('音声ファイルの作成に失敗しました。')

            download_id = secrets.token_hex(32)
            with generated_audio_lock:
                size = os.path.getsize(output_path)
                if size > MAX_RETAINED_AUDIO_BYTES:
                    return jsonify({'error': '生成音声が一時保存の上限2GiBを超えています。入力を分割してください。'}), 507
                if not prune_audio_locked(incoming_bytes=size, incoming_files=1):
                    return jsonify({'error': '一時音声の保存容量を確保できません。再生・ダウンロード完了後に再試行してください。'}), 507
                if automatic_filename:
                    safe_filename = available_name(
                        safe_filename, {name for _, name in generated_audio.values()})
                generated_audio[download_id] = (output_path, safe_filename)
                generated_audio_times[download_id] = time.monotonic()
            registered = True
        finally:
            if not registered:
                try:
                    os.remove(output_path)
                except FileNotFoundError:
                    pass
        
        # 変換完了時間を計算
        end_time = time.time()
        conversion_time = round(end_time - start_time, 2)
        
        return jsonify({
            'success': True,
            'message': f'音声ファイルが正常に作成されました: {safe_filename}',
            'filename': safe_filename,
            'download_id': download_id,
            'processed_text': processed_text,
            'conversion_time': conversion_time
        })
        
    except limits.ConversionLimitError:
        raise
    except Exception as error:
        return jsonify(internal_error_payload(error, 'convert')), 500

@app.route('/download/<download_id>')
def download_file(download_id):
    try:
        # URLの値をパスに結合しない。未登録の名前・IDはすべて拒否する。
        with generated_audio_lock:
            audio = generated_audio.get(download_id)
            if audio is None or (time.monotonic() - generated_audio_times.get(download_id, 0)
                                 >= AUDIO_TTL_SECONDS):
                return jsonify({'error': 'ファイルが見つかりません。保存期限切れの場合は再変換してください。'}), 404
            file_path, display_filename = audio
            if not os.path.isfile(file_path):
                return jsonify({'error': 'ファイルが見つかりません'}), 404
            # ファイルを開くまでロックし、削除処理との競合を防ぐ。
            return send_file(file_path, mimetype='audio/wav', as_attachment=True,
                             download_name=display_filename)
        
    except HTTPException:
        raise
    except Exception as error:
        return jsonify(internal_error_payload(error, 'download')), 500

if __name__ == '__main__':
    threading.Thread(target=audio_cleanup_loop, daemon=True).start()
    app.run(debug=False, use_debugger=False, use_reloader=False,
            host='localhost', port=5051)
