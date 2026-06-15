#!/usr/bin/env python3
"""Live score debug for the Eclipse wake-word model.

Run this, say 'Eclipse' several times, then Ctrl+C.
It prints the peak score seen per second so you know what threshold to use.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DEFAULT_MODEL = str(Path(__file__).resolve().parents[1] / "models" / "eclipse.onnx")
SAMPLE_RATE = 16000
FRAME_MS = 80
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)

BUILTIN_NAMES = {"hey_jarvis", "hey_mycroft", "alexa", "hey_rhasspy", "timer", "weather"}


def main() -> None:
    model_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
    except ModuleNotFoundError as exc:
        print(f"Missing module: {exc.name}. Use .venv-wake/bin/python to run this.")
        sys.exit(1)

    is_builtin = model_arg in BUILTIN_NAMES
    if not is_builtin and not Path(model_arg).exists():
        print(f"Model not found: {model_arg}")
        sys.exit(1)

    print(f"Loading model: {model_arg} ({'builtin' if is_builtin else 'custom onnx'})")
    model = Model(wakeword_models=[model_arg], inference_framework="onnx")
    print("Model loaded. Say 'Eclipse' into the microphone. Press Ctrl+C to stop.\n")

    peak = 0.0
    window_start = time.monotonic()
    frame_count = 0

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME_SIZE,
    ) as stream:
        while True:
            data, overflowed = stream.read(FRAME_SIZE)
            if overflowed:
                continue
            frame = np.frombuffer(data, dtype=np.int16)
            prediction = model.predict(frame)
            score = float(max(prediction.values(), default=0.0))
            if score > peak:
                peak = score
            frame_count += 1

            now = time.monotonic()
            if now - window_start >= 1.0:
                bar = "#" * int(peak * 40)
                print(f"peak={peak:.4f}  [{bar:<40}]  {'<<< DETECTED' if peak >= 0.5 else ''}")
                peak = 0.0
                window_start = now
                frame_count = 0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDone.")
