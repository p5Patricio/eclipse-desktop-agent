import os
import tempfile
from pathlib import Path
from eclipse_agent.pal.base import TTSProvider, AudioRecorder
from eclipse_agent.voice import SpeechResult, RecordingResult


class WindowsTTSProvider(TTSProvider):
    """Windows text-to-speech.

    Prefers the WinRT speech synthesizer (Windows 10/11 OneCore and downloadable
    "Natural" neural voices) and falls back to classic SAPI5 when WinRT is
    unavailable. Set ECLIPSE_TTS_NEURAL=0 to force SAPI, or ECLIPSE_TTS_VOICE to
    pick a voice by name.
    """

    def __init__(self, *, prefer_neural: bool | None = None, voice_name: str | None = None) -> None:
        if prefer_neural is None:
            prefer_neural = os.environ.get("ECLIPSE_TTS_NEURAL", "1") != "0"
        self.prefer_neural = prefer_neural
        self.voice_name = voice_name or os.environ.get("ECLIPSE_TTS_VOICE")

    def speak(self, text: str, *, dry_run: bool = True) -> SpeechResult:
        if not text:
            return SpeechResult(
                success=False,
                provider="sapi",
                command=(),
                message="Cannot speak empty text.",
                dry_run=dry_run,
            )

        if dry_run:
            return SpeechResult(
                success=True,
                provider="winrt-neural" if self.prefer_neural else "sapi",
                command=(),
                message="Prepared local TTS speech.",
                dry_run=True,
            )

        if self.prefer_neural:
            neural = self._speak_neural(text)
            if neural is not None:
                return neural

        return self._speak_sapi(text)

    def _speak_neural(self, text: str) -> SpeechResult | None:
        try:
            wav = self._neural_wav(text)
            _play_wav(wav)
        except Exception:  # noqa: BLE001 - any WinRT failure falls back to SAPI
            return None
        return SpeechResult(
            success=True,
            provider="winrt-neural",
            command=(),
            message="Spoken via WinRT neural voice.",
            dry_run=False,
            executed=True,
        )

    def _neural_wav(self, text: str) -> bytes:
        import asyncio

        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        voice_name = self.voice_name

        async def _run() -> bytes:
            synthesizer = SpeechSynthesizer()
            voice = _select_voice(list(SpeechSynthesizer.all_voices), voice_name=voice_name)
            if voice is not None:
                synthesizer.voice = voice
            stream = await synthesizer.synthesize_text_to_stream_async(text)
            size = stream.size
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            return bytes(reader.read_buffer(size))

        return asyncio.run(_run())

    def _speak_sapi(self, text: str) -> SpeechResult:
        try:
            import win32com.client

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
            return SpeechResult(
                success=True,
                provider="sapi",
                command=(),
                message="Spoken via SAPI.",
                dry_run=False,
                executed=True,
            )
        except Exception as e:
            return SpeechResult(
                success=False,
                provider="sapi",
                command=(),
                message=f"SAPI synthesis failed: {e}",
                dry_run=False,
            )


def _select_voice(voices: list, *, voice_name: str | None = None):
    """Pick the best voice: an explicit name, else a Natural voice, else the first."""

    if not voices:
        return None
    if voice_name:
        for voice in voices:
            if voice_name.casefold() in voice.display_name.casefold():
                return voice
    natural = [voice for voice in voices if "natural" in voice.display_name.casefold()]
    if natural:
        return natural[0]
    return voices[0]


def _play_wav(data: bytes) -> None:
    import winsound

    path = Path(tempfile.gettempdir()) / "eclipse-tts.wav"
    path.write_bytes(data)
    winsound.PlaySound(str(path), winsound.SND_FILENAME)

class WindowsAudioRecorder(AudioRecorder):
    def record(
        self,
        audio_path: str | Path,
        *,
        seconds: int = 5,
        dry_run: bool = True,
    ) -> RecordingResult:
        path = Path(audio_path).expanduser()
        if seconds <= 0:
            return RecordingResult(
                success=False,
                command=(),
                audio_path=path,
                message="Recording duration must be positive.",
                dry_run=dry_run,
            )
            
        if dry_run:
            return RecordingResult(
                success=True,
                command=(),
                audio_path=path,
                message="Prepared Windows microphone recording.",
                dry_run=True,
            )
            
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np
            
            fs = 16000
            chunk_size = int(0.1 * fs)  # 100ms chunk = 1600 samples
            recording_data = []
            
            max_chunks = int(seconds / 0.1)
            silent_chunks = 0
            silence_threshold_chunks = 15  # 1.5s / 0.1s
            
            with sd.InputStream(samplerate=fs, channels=1, dtype='int16') as stream:
                for _ in range(max_chunks):
                    data, overflow = stream.read(chunk_size)
                    recording_data.append(data)
                    
                    # Compute RMS energy with defensive fallback for mocks
                    try:
                        rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                    except Exception:
                        rms = 0.0
                        
                    if rms < 200:
                        silent_chunks += 1
                    else:
                        silent_chunks = 0
                        
                    if silent_chunks >= silence_threshold_chunks:
                        # VAD early stop
                        break
                        
            if recording_data:
                myrecording = np.concatenate(recording_data, axis=0)
            else:
                myrecording = np.zeros((0, 1), dtype='int16')
                
            sf.write(str(path), myrecording, fs)
            
            return RecordingResult(
                success=True,
                command=(),
                audio_path=path,
                message="Audio recorded via sounddevice.",
                dry_run=False,
                executed=True,
            )
        except Exception as e:
            return RecordingResult(
                success=False,
                command=(),
                audio_path=path,
                message=f"Audio recording failed: {e}",
                dry_run=False,
            )


