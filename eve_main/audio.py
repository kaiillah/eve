import os
import shutil
import subprocess
import tempfile
import time
import wave
from collections import deque

import numpy as np
import serial
import simpleaudio as sa
import sounddevice as sd
import soundfile as sf

from config import (
    BEEP_ON_LISTEN,
    LISTEN_SECONDS,
    MAX_UTTERANCE_SEC,
    MIC_CHANNELS,
    MIC_SAMPLE_RATE,
    MIN_SPEECH_MS,
    PIPER_BIN,
    PIPER_VOICE,
    PRE_ROLL_MS,
    SERIAL_BAUD,
    SERIAL_PORT,
    VAD_AGGRESSIVENESS,
    VAD_FRAME_MS,
    VAD_SAMPLE_RATE,
    END_SILENCE_MS,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL_NAME,
)

try:
    import webrtcvad
    VAD_AVAILABLE = True
except Exception:
    webrtcvad = None
    VAD_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_MODEL_AVAILABLE = True
except Exception:
    WhisperModel = None
    WHISPER_MODEL_AVAILABLE = False

try:
    pico = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.01)
    print("[SERVO] Connected to Pico.")
except Exception as e:
    print("[SERVO] Failed to connect to Pico:", e)
    pico = None

_whisper_model = None


def extract_mouth_envelope(wav_path, frame_ms=30, servo_min=30, servo_max=120):
    try:
        audio, sr = sf.read(wav_path)
        if audio.ndim > 1:
            audio = audio[:, 0]

        frame_len = int(sr * frame_ms / 1000)
        positions = []

        for i in range(0, len(audio), frame_len):
            frame = audio[i : i + frame_len]
            if len(frame) == 0:
                break
            rms = np.sqrt(np.mean(frame ** 2))
            angle = servo_min + rms * (servo_max - servo_min) * 4.0
            angle = max(servo_min, min(servo_max, int(angle)))
            positions.append(angle)

        return positions
    except Exception as e:
        print("[SERVO] Envelope error:", e)
        return []


def play_audio_with_mouth_sync(wav_path, positions, frame_ms=30):
    try:
        wave_obj = sa.WaveObject.from_wave_file(wav_path)
        play_obj = wave_obj.play()

        if pico:
            for angle in positions:
                pico.write(f"ANGLE:{angle}\n".encode())
                time.sleep(frame_ms / 1000.0)

        play_obj.wait_done()
    except Exception as e:
        print("[Audio+Servo ERROR]", e)


def piper_tts_to_wav(text, out_wav_path):
    if not shutil.which(PIPER_BIN):
        return False
    try:
        subprocess.run(
            [PIPER_BIN, "-m", PIPER_VOICE, "-f", out_wav_path],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return os.path.exists(out_wav_path)
    except Exception as e:
        print(f"[Piper TTS error] {e}")
        return False


def speak(text):
    if not text:
        return
    if not shutil.which(PIPER_BIN) or not os.path.exists(PIPER_VOICE):
        return

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    ok = piper_tts_to_wav(text, path)
    if not ok:
        return

    try:
        positions = extract_mouth_envelope(path)
        play_audio_with_mouth_sync(path, positions)
    except Exception as e:
        print("[speak ERROR]", e)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# stt + vad

def _init_whisper():
    global _whisper_model
    if _whisper_model is None and WHISPER_MODEL_AVAILABLE:
        try:
            _whisper_model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
            print(
                f"[STT] loaded faster-whisper '{WHISPER_MODEL_NAME}' "
                f"on {WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE}"
            )
        except Exception as e:
            print(f"[STT load error] {e}")
            _whisper_model = None


def _beep(duration_ms=120, freq=880):
    if not BEEP_ON_LISTEN:
        return
    try:
        import numpy as _np

        sr = 16000
        t = _np.linspace(0, duration_ms / 1000, int(sr * duration_ms / 1000), False)
        tone = (0.15 * _np.sin(2 * _np.pi * freq * t)).astype(_np.float32)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        sf.write(path, tone, sr)
        sa.WaveObject.from_wave_file(path).play().wait_done()
        os.remove(path)
    except Exception:
        pass


def _record_utterance_vad(device=None):
    if not VAD_AVAILABLE:
        return None

    frame_len = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000)
    bytes_per_frame = frame_len * 2
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    preroll = deque(maxlen=max(1, PRE_ROLL_MS // VAD_FRAME_MS))
    voiced = []
    triggered = False
    speech_ms = 0
    silence_ms = 0
    t0 = time.time()

    try:
        with sd.RawInputStream(
            samplerate=VAD_SAMPLE_RATE,
            blocksize=frame_len,
            dtype="int16",
            channels=1,
            device=device,
        ) as stream:
            while True:
                raw_bytes, overflowed = stream.read(frame_len)
                if len(raw_bytes) != bytes_per_frame:
                    continue
                is_speech = vad.is_speech(raw_bytes, VAD_SAMPLE_RATE)

                if not triggered:
                    preroll.append(raw_bytes)
                    if is_speech:
                        triggered = True
                        voiced.extend(preroll)
                        speech_ms = VAD_FRAME_MS
                        silence_ms = 0
                else:
                    voiced.append(raw_bytes)
                    if is_speech:
                        speech_ms += VAD_FRAME_MS
                        silence_ms = 0
                    else:
                        silence_ms += VAD_FRAME_MS

                if (
                    silence_ms >= END_SILENCE_MS and speech_ms >= MIN_SPEECH_MS
                ) or ((time.time() - t0) >= MAX_UTTERANCE_SEC):
                    break
    except Exception as e:
        print(f"[VAD stream error] {e}")
        return None

    if not voiced or speech_ms < MIN_SPEECH_MS:
        return None

    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(VAD_SAMPLE_RATE)
            wf.writeframes(b"".join(voiced))
        return out_path
    except Exception as e:
        print(f"[VAD write error] {e}")
        try:
            os.remove(out_path)
        except Exception:
            pass
        return None


def _record_wav_timer(seconds=LISTEN_SECONDS, samplerate=MIC_SAMPLE_RATE, channels=MIC_CHANNELS):
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        audio = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=channels)
        sd.wait()
        sf.write(path, audio, samplerate)
        return path
    except Exception as e:
        print(f"[Record error] {e}")
        try:
            os.remove(path)
        except Exception:
            pass
        return None


def listen_once(seconds=LISTEN_SECONDS):
    _beep()
    _init_whisper()
    if _whisper_model is None:
        return ""

    wav = _record_utterance_vad()
    if not wav:
        wav = _record_wav_timer(seconds)
    if not wav:
        return ""

    text = ""
    try:
        segments, _info = _whisper_model.transcribe(wav, vad_filter=False)
        text = " ".join(
            getattr(s, "text", "").strip()
            for s in segments
            if getattr(s, "text", "").strip()
        )
    except Exception as e:
        print(f"[STT error] {e}")
    finally:
        try:
            os.remove(wav)
        except Exception:
            pass

    if len(text.split()) < 3 and VAD_AVAILABLE:
        more = listen_once(seconds)
        if more:
            text = (text + " " + more).strip()

    return text
