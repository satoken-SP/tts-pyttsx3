import argparse
import os
import conversion_limits as limits

def load_pronunciation_dictionary(file_path: str = "change_library.txt") -> dict:
    """
    辞書ファイルから発音辞書を読み込む
    """
    dictionary = {}
    
    # 現在のスクリプトのディレクトリを基準にしたパスに変更
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(script_dir, file_path)
    
    try:
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # 空行とコメント行をスキップ
                        if '=' in line:
                            key, value = line.split('=', 1)
                            dictionary[key.strip()] = value.strip()
            print(f"[INFO] 辞書ファイル '{full_path}' から {len(dictionary)} 個のエントリを読み込みました")
        else:
            print(f"[WARNING] 辞書ファイル '{full_path}' が見つかりません。デフォルト辞書を使用します")
            # デフォルト辞書（フォールバック）
            dictionary = {
                "pyttsx3": "パイティーティーエスエックススリー",
                "RESTful": "レストフル",
            }
    except Exception as e:
        print(f"[ERROR] 辞書ファイルの読み込み中にエラーが発生しました: {e}")
        # エラー時もデフォルト辞書を使用
        dictionary = {
            "pyttsx3": "パイティーティーエスエックススリー",
            "RESTful": "レストフル",
        }
    
    return dictionary

# 辞書ファイルから読み込み
CUSTOM_PRONUNCIATIONS = load_pronunciation_dictionary()

def apply_pronunciations(text: str, dic: dict = None, max_length=None) -> str:
    """
    テキスト内の用語を辞書に従って置換する。
    """
    if dic is None:
        dic = CUSTOM_PRONUNCIATIONS
    max_length = limits.MAX_TEXT_LENGTH if max_length is None else max_length
    if len(text) > max_length:
        raise limits.ConversionLimitError(f'テキストは最大{max_length:,}文字までです。')
    
    for term, reading in dic.items():
        if not isinstance(term, str) or not term or not isinstance(reading, str):
            raise limits.ConversionLimitError('辞書のキーは空にできません。用語と読みを確認してください。')
        projected_length = len(text) + text.count(term) * (len(reading) - len(term))
        if projected_length > max_length:
            raise limits.ConversionLimitError(f'辞書変換後のテキストは最大{max_length:,}文字までです。')
        text = text.replace(term, reading)
    return text

def main():
    parser = argparse.ArgumentParser(
        description="テキストファイルを読み込み、用語置換して別ファイルに書き出すツール"
    )
    parser.add_argument("input_file", help="読み込むテキストファイルのパス")
    parser.add_argument("output_file", help="書き出すテキストファイルのパス")
    args = parser.parse_args()

    # 入力ファイルの存在チェック
    if not os.path.isfile(args.input_file):
        print(f"[Error] 入力ファイルが見つかりません: {args.input_file}")
        exit(1)

    # テキスト読み込み
    content = limits.read_text_file(args.input_file)

    # 置換処理
    converted = apply_pronunciations(content)

    # 出力ディレクトリがなければ作成
    out_dir = os.path.dirname(os.path.abspath(args.output_file))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # 結果を書き出し
    with open(args.output_file, "w", encoding="utf-8") as f:
        f.write(converted)

    print(f"[OK] 変換結果を '{args.output_file}' に保存しました。")

if __name__ == "__main__":
    print(f"これから実行")
    main()
