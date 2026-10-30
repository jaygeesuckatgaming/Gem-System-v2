"""Transcribe an audio file with faster-whisper (one-shot CLI).

Used by the control panel to fill an engine's reference-voice transcript
(Audio8 zero-shot cloning needs the exact spoken words). Runs in the panel's
own interpreter, so it uses the `mcp_env_2` install of faster-whisper.

Examples:
    python clients/transcribe_audio.py path/to/reference.wav --json
    python clients/transcribe_audio.py ref.mp3 --model small.en --language en
"""

from __future__ import annotations

import argparse
import json
import sys
import time

DEFAULT_MODEL = "base.en"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Transcribe an audio file with faster-whisper")
    parser.add_argument("audio", help="path to the audio file (wav/flac/mp3/m4a/ogg)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Whisper model size or path (default: {DEFAULT_MODEL})")
    parser.add_argument("--language", default="auto",
                        help="language code, or 'auto' to detect (default: auto)")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:N")
    parser.add_argument("--compute-type", default="int8", help="int8, int8_float16, float16, float32")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--no-vad", action="store_true", help="disable VAD filtering")
    parser.add_argument("--json", action="store_true", help="print a JSON object")
    return parser.parse_args(argv)


def transcribe(args) -> dict:
    from faster_whisper import WhisperModel

    language = None if str(args.language).lower() in ("auto", "", "none") else args.language
    started = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(
        args.audio,
        language=language,
        beam_size=max(1, args.beam_size),
        vad_filter=not args.no_vad,
        condition_on_previous_text=False,
        log_progress=False,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return {
        "text": text,
        "language": getattr(info, "language", None),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "duration": round(float(getattr(info, "duration", 0.0)), 3),
        "model": args.model,
        "elapsed_s": round(time.time() - started, 2),
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        result = transcribe(args)
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        else:
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["text"])
    return 0 if result["text"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
