import argparse
import os
import pyttsx3

def synthesize_text(text: str,
                    play: bool = True,
                    save_path: str = None,
                    rate: int = 200,
                    volume: float = 1.0,
                    voice_id: str = None):
    """
    テキストを再生・またはファイルに保存する。

    :param text: 読み上げたい文字列
    :param play: True ならスピーカー再生
    :param save_path: 指定するとそのファイルへ保存（.wav 推奨）
    :param rate: 読み上げ速度
    :param volume: 音量
    :param voice_id: 使用する音声ID
    """
    engine = pyttsx3.init()
    engine.setProperty('rate', rate)
    engine.setProperty('volume', volume)
    if voice_id:
        engine.setProperty('voice', voice_id)

    if save_path:
        engine.save_to_file(text, save_path)
    elif play:
        engine.say(text)
    else:
        # 再生も保存もしないなら何もしない
        return

    engine.runAndWait()
    engine.stop()
    if save_path:
        print(f"[OK] Saved speech to '{save_path}'")

def main():
    parser = argparse.ArgumentParser(
        description="テキストファイルを読み込んで音声合成（再生 or WAV保存）を行うツール"
    )
    parser.add_argument("input_file", help="読み込みたいテキストファイルのパス")
    parser.add_argument("-o", "--output", metavar="OUT_WAV",
                        help="WAV 形式で保存したい場合に出力先ファイル名を指定")
    parser.add_argument("--no-play", action="store_true",
                        help="標準再生を行わない（ファイル保存のみ）")
    parser.add_argument("--rate", type=int, default=200,
                        help="読み上げ速度（デフォルト: 200）")
    parser.add_argument("--volume", type=float, default=1.0,
                        help="音量 0.0～1.0（デフォルト: 1.0）")
    parser.add_argument("--voice", metavar="VOICE_ID",
                        help="利用する音声の ID（省略時はデフォルト）")

    args = parser.parse_args()

    # ファイル存在チェック
    if not os.path.isfile(args.input_file):
        print(f"[Error] ファイルが見つかりません: {args.input_file}")
        return

    # テキスト読み込み
    with open(args.input_file, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        print(f"[Error] ファイルが空です: {args.input_file}")
        return

    # 再生／保存フラグ
    play = not args.no_play

    synthesize_text(
        text=text,
        play=play,
        save_path=args.output,
        rate=args.rate,
        volume=args.volume,
        voice_id=args.voice
    )

if __name__ == "__main__":
    main()
