from flask import Flask, render_template, request, jsonify, send_file
import os
import tempfile
import time
from change_token_katakana import apply_pronunciations, load_pronunciation_dictionary
from pyttsx3_main import synthesize_text

app = Flask(__name__)

# 制限設定
MAX_TEXT_LENGTH = 100000  # 最大文字数
MAX_FILE_SIZE = 500 * 1024  # 最大ファイルサイズ（500KB）

# 辞書を読み込み
pronunciation_dictionary = load_pronunciation_dictionary()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
def convert_text():
    # 変換開始時間を記録
    start_time = time.time()
    
    try:
        output_filename = request.form.get('outputFilename', 'output.wav')
        input_type = request.form.get('inputType')
        rate = int(request.form.get('rate', 200))  # ここで先に取得
        
        # ファイル名の安全性を検証
        if not output_filename or output_filename.strip() == '':
            return jsonify({'error': '無効なファイル名です'}), 400
        
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
            for file in os.listdir(input_folder):
                if file.endswith('.txt'):
                    txt_files.append(file)
            
            if not txt_files:
                return jsonify({'error': f'"{input_folder}" フォルダ内にtxtファイルが見つかりません。'}), 400
            
            # 各ファイルを処理
            processed_files = []
            total_conversion_time = 0
            
            for txt_file in txt_files:
                file_path = os.path.join(input_folder, txt_file)
                
                try:
                    # ファイルサイズの制限チェック
                    file_size = os.path.getsize(file_path)
                    if file_size > MAX_FILE_SIZE:
                        processed_files.append({
                            'filename': txt_file,
                            'status': 'error',
                            'message': f'ファイルサイズが大きすぎます（{file_size // 1024}KB）'
                        })
                        continue
                    
                    # ファイルの内容を読み込み
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # ファイル内容の文字数制限チェック
                    if len(content) > MAX_TEXT_LENGTH:
                        processed_files.append({
                            'filename': txt_file,
                            'status': 'error',
                            'message': f'ファイルの内容が長すぎます（{len(content):,}文字）'
                        })
                        continue
                    
                    # 専門用語変換処理
                    processed_text = apply_pronunciations(content, pronunciation_dictionary)
                    
                    # 出力ファイル名を生成（元のファイル名から拡張子を除いて.wavを追加）
                    base_name = os.path.splitext(txt_file)[0]
                    output_filename = f"{base_name}.wav"
                    output_path = os.path.join(output_folder, output_filename)
                    
                    # 音声変換処理
                    file_start_time = time.time()
                    synthesize_text(
                        text=processed_text,
                        play=False,
                        save_path=output_path,
                        rate=rate,
                        volume=1.0
                    )
                    file_end_time = time.time()
                    file_conversion_time = round(file_end_time - file_start_time, 2)
                    total_conversion_time += file_conversion_time
                    
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'success',
                        'output_filename': output_filename,
                        'conversion_time': file_conversion_time
                    })
                    
                except UnicodeDecodeError:
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'error',
                        'message': 'ファイルの文字エンコーディングが正しくありません。UTF-8で保存してください。'
                    })
                except Exception as e:
                    processed_files.append({
                        'filename': txt_file,
                        'status': 'error',
                        'message': f'処理エラー: {str(e)}'
                    })
            
            # フォルダ処理の結果を返す
            return jsonify({
                'success': True,
                'message': f'フォルダ処理が完了しました。{len(processed_files)}ファイルを処理しました。',
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
        processed_text = apply_pronunciations(content, pronunciation_dictionary)
        
        # 一時ファイルに音声を保存
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, safe_filename)
        
        # 音声変換処理
        synthesize_text(
            text=processed_text,
            play=False,  # ブラウザでは再生しない
            save_path=output_path,
            rate=rate,
            volume=1.0
        )
        
        # ファイルが正常に作成されたか確認
        if not os.path.exists(output_path):
            return jsonify({'error': '音声ファイルの作成に失敗しました'}), 500
        
        # 変換完了時間を計算
        end_time = time.time()
        conversion_time = round(end_time - start_time, 2)
        
        return jsonify({
            'success': True,
            'message': f'音声ファイルが正常に作成されました: {safe_filename}',
            'filename': safe_filename,
            'processed_text': processed_text,
            'conversion_time': conversion_time
        })
        
    except Exception as e:
        return jsonify({'error': f'エラーが発生しました: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        # ファイル名の安全性を検証
        if not filename or filename.strip() == '':
            return jsonify({'error': '無効なファイル名です'}), 400
        
        # 危険な文字やパスをチェック
        dangerous_chars = ['/', '\\', '..', '~']
        if any(char in filename for char in dangerous_chars):
            return jsonify({'error': '無効なファイル名です'}), 400
        
        # ファイル名の長さを制限
        if len(filename) > 100:
            return jsonify({'error': 'ファイル名が長すぎます'}), 400
        
        # 一時ディレクトリのパスを取得
        temp_dir = tempfile.gettempdir()
        
        # 安全なファイルパスを構築
        safe_filename = os.path.basename(filename)  # ディレクトリ部分を除去
        file_path = os.path.join(temp_dir, safe_filename)
        
        # パスを正規化して絶対パスに変換
        file_path = os.path.abspath(file_path)
        temp_dir_abs = os.path.abspath(temp_dir)
        
        # ファイルパスが一時ディレクトリ内にあることを確認
        if not file_path.startswith(temp_dir_abs):
            return jsonify({'error': '無効なファイルパスです'}), 400
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'ファイルが見つかりません'}), 404
        
        return send_file(file_path, as_attachment=True, download_name=safe_filename)
        
    except Exception as e:
        return jsonify({'error': f'ダウンロードエラー: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5051) 