import sys
import os
import argparse
from change_token_katakana import load_pronunciation_dictionary, apply_pronunciations
from pyttsx3_main import synthesize_text
from output_files import synthesize_new_file
from conversion_limits import read_text_file, validate_text, validate_filename, ConversionLimitError

def main():
    parser = argparse.ArgumentParser(description="CLI: テキストファイルを音声合成（output/に.wav保存）")
    parser.add_argument("input_filename", help="inputフォルダ内のテキストファイル名（例: test2.txt）")
    parser.add_argument("--rate", type=int, default=170, help="読み上げ速度（50～400、省略時170）")
    args = parser.parse_args()
    try:
        validate_filename(args.input_filename)
    except ConversionLimitError as error:
        parser.error(str(error))

    # 入力ファイルパス
    input_path = os.path.join("input", args.input_filename)
    if not os.path.isfile(input_path):
        print(f"[ERROR] 入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    # 読み上げ速度チェック
    rate = args.rate
    if not (50 <= rate <= 400):
        print(f"[ERROR] 読み上げ速度は50～400の範囲で指定してください（指定値: {rate}）", file=sys.stderr)
        sys.exit(2)

    # 出力ファイル名
    base = os.path.splitext(os.path.basename(args.input_filename))[0]
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    # テキスト読み込み
    try:
        text = read_text_file(input_path)
    except Exception as e:
        print(f"[ERROR] ファイル読み込み失敗: {e}", file=sys.stderr)
        sys.exit(3)

    if not text.strip():
        print(f"[ERROR] 入力ファイルが空です: {input_path}", file=sys.stderr)
        sys.exit(4)

    # 専門用語変換
    try:
        dic = load_pronunciation_dictionary()
        processed_text = apply_pronunciations(text, dic)
        validate_text(processed_text)
    except Exception as e:
        print(f"[ERROR] 専門用語変換失敗: {e}", file=sys.stderr)
        sys.exit(5)

    # 音声合成
    try:
        output_path = synthesize_new_file(
            processed_text, output_dir, base, rate, synthesize_text)
    except Exception as e:
        print(f"[ERROR] 音声合成失敗: {e}", file=sys.stderr)
        sys.exit(6)

    if not os.path.isfile(output_path):
        print(f"[ERROR] 出力ファイル作成失敗: {output_path}", file=sys.stderr)
        sys.exit(7)

    print(f"[OK] {output_path} を作成しました。")
    sys.exit(0)

if __name__ == "__main__":
    main() 
