from pathlib import Path
from eclipse_agent.pal.base import TTSProvider, AudioRecorder
from eclipse_agent.voice import SpeechResult, RecordingResult

class WindowsTTSProvider(TTSProvider):
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
                provider="sapi",
                command=(),
                message="Prepared local SAPI TTS speech.",
                dry_run=True,
            )
            
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


