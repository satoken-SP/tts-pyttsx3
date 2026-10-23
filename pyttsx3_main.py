import argparse
import os
import pyttsx3
from conversion_limits import validate_text, validate_options, validate_filename, read_text_file
from speech_runner import run_speech

def synthesize_text(text: str, play: bool = True, save_path: str = None,
                    rate: int = 200, volume: float = 1.0, voice_id: str = None):
    validate_text(text)
    validate_options(rate, volume)
    if save_path:
        validate_filename(os.path.basename(save_path))
    if not save_path and not play:
        return
    run_speech(dict(text=text, play=play, save_path=save_path, rate=rate,
                    volume=volume, voice_id=voice_id))


def _synthesize_direct(text: str,
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
    try:
        engine.setProperty('rate', rate)
        engine.setProperty('volume', volume)
        if voice_id:
            engine.setProperty('voice', voice_id)
        if save_path:
            engine.save_to_file(text, save_path)
        elif play:
            engine.say(text)
        else:
            return
        engine.runAndWait()
    finally:
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
    text = read_text_file(args.input_file)
    if not text:
        print(f"[Error] ファイルが空です: {args.input_file}")
        return

    # 再生／保存フラグ
    play = not args.no_play

    completed = False
    reserved = False
    try:
        validate_options(args.rate, args.volume)
        if args.output:
            validate_filename(os.path.basename(args.output))
            with open(args.output, 'xb'):
                pass
            reserved = True
        synthesize_text(text=text, play=play, save_path=args.output,
                        rate=args.rate, volume=args.volume, voice_id=args.voice)
        completed = True
    finally:
        if reserved and not completed:
            try:
                os.remove(args.output)
            except FileNotFoundError:
                pass

if __name__ == "__main__":
    main()
