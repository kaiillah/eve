import os
import time
import json
import pickle
import sqlite3
import tempfile
import subprocess
import shutil
import re
import wave
import serial
from collections import deque

import cv2
import numpy as np
import face_recognition
import ollama

import sounddevice as sd
import soundfile as sf
import simpleaudio as sa

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

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200

try:
 pico = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.01)
 print("[SERVO] Connected to Pico.")
except Exception:
 print("[SERVO] Failed to connect to Pico:", Exception)
 pico = None


print(f"OpenCV version: {cv2.__version__}")
print(f"faster-whisper available: {WHISPER_MODEL_AVAILABLE}")
print(f"VAD available: {VAD_AVAILABLE}")

DB_NAME = 'face_recognition5.db'
MODEL_NAME = "eve-template"
FACE_TOLERANCE = 0.5
DOWNSCALE = 0.25

BASE_SYSTEM_PROMPT = (
 "You are Eve, an AI robot built by the Allen High School Robotics Team. "
 "You exist after a rogue AI named Adam devastated the world. "
 "Your mission is to protect and assist the team. "
 "Speak like you are in a conversation (2–4 sentences). Stay in character."
 "if it's a mentor or guest address using surfix (don't say Mr., say Mister"
 "DO NOT include asterisk and your emotions in your responses, this is a conversation."
)

PIPER_BIN = "/opt/piper/piper/piper"
PIPER_VOICE = "/opt/piper/voices/en_US-amy-low.onnx"
PIPER_SAMPLERATE = 22050

WHISPER_MODEL_NAME = "tiny.en"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1
LISTEN_SECONDS = 5.0
PRESENCE_KEEP_ALIVE = 3.0
KEEPALIVE_MARGIN = 2.0

GOODBYE_KEYWORDS = ( #ran out of ideas to cut off one's conversation so I just did this, didnt even use like 90% of it btw
 "bye", "goodbye", "bye bye", "see you", "see ya",
 "gotta go", "have to go", "i have to go", "i gotta go",
 "i'm leaving", "i am leaving", "heading out", "gotta run", "i gotta run",
 "later", "catch you", "talk to you later", "ttyl", "farewell"
)


VAD_SAMPLE_RATE = 16000 #experimenting with voice activity detection but too late since it was implemented 2 days before comp :(
VAD_FRAME_MS = 20 #I think it actually does work a bit, but hardcoding every variable was hell and turn out not very great
VAD_AGGRESSIVENESS = 2 
PRE_ROLL_MS = 300 
END_SILENCE_MS = 500 
MIN_SPEECH_MS = 300 
MAX_UTTERANCE_SEC = 25 
BEEP_ON_LISTEN = False 

known_face_encodings = []
known_face_names = []
_whisper_model = None

def setup_database():
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute('''
 CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 encoding BLOB NOT NULL,
 role TEXT NOT NULL
 )
 ''')
        cur.execute('''
 CREATE TABLE IF NOT EXISTS conversations (
 user_id INTEGER PRIMARY KEY,
 history TEXT,
 FOREIGN KEY (user_id) REFERENCES users(id)
 )
 ''')
        conn.commit()
        print("Database setup complete.")
    except sqlite3.Error as e:
        print(f"Database setup error: {e}")
    finally:
        try: conn.close()
        except: pass

def extract_mouth_envelope(wav_path, frame_ms=30, servo_min=30, servo_max=120):
    try:
        audio, sr = sf.read(wav_path)
        if audio.ndim > 1:
            audio = audio[:, 0]

        frame_len = int(sr * frame_ms / 1000)
        positions = []

        for i in range(0, len(audio), frame_len):
            frame = audio[i:i+frame_len]
            if len(frame) == 0:
                break
            rms = np.sqrt(np.mean(frame**2))
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

def load_known_faces():
    global known_face_encodings, known_face_names
    known_face_encodings = []
    known_face_names = []
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT name, encoding FROM users")
        rows = cur.fetchall()
        for name, enc_blob in rows:
            known_face_names.append(name)
            known_face_encodings.append(pickle.loads(enc_blob))
        print(f"Loaded {len(known_face_names)} known faces from the database.")
    except sqlite3.Error as e:
        print(f"Database load error: {e}")
    finally:
        try: conn.close()
        except: pass

def add_new_user(name, encoding, role):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        enc_blob = pickle.dumps(encoding)
        cur.execute("INSERT INTO users (name, encoding, role) VALUES (?, ?, ?)",
            (name, enc_blob, role))
        user_id = cur.lastrowid
        conn.commit()
        print(f"[DB] New user added (id={user_id})")
        print(f"[DB] Role stored: '{role}'")
        load_known_faces()
        return user_id
    except sqlite3.Error as e:
        print(f"Database insert error: {e}")
        return None
    finally:
        try: conn.close()
        except: pass

def get_user_id_by_name(name):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT id, role FROM users WHERE name = ?", (name,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
    except sqlite3.Error as e:
        print(f"DB lookup error: {e}")
        return (None, None)
    finally:
        try: conn.close()
        except: pass

def load_conversation_history(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT history FROM conversations WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return []
    except sqlite3.Error as e:
        print(f"DB load convo error: {e}")
        return []
    finally:
        try: conn.close()
        except: pass

def save_conversation_history(user_id, history):
    try:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        hx = json.dumps(history)
        cur.execute("INSERT OR REPLACE INTO conversations (user_id, history) VALUES (?, ?)",
            (user_id, hx))
        conn.commit()
        print(f"[DB] Conversation saved for user ID {user_id}.")
    except sqlite3.Error as e:
        print(f"DB save convo error: {e}")
    finally:
        try: conn.close()
        except: pass

def _ensure_system(conversation_history):
    if not conversation_history or conversation_history[0].get("role") != "system":
        conversation_history.insert(0, {"role": "system", "content": BASE_SYSTEM_PROMPT})

def get_ollama_response(user_prompt, conversation_history, user_id=None):
    _ensure_system(conversation_history)
    conversation_history.append({"role": "user", "content": user_prompt})

    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    reply = ""
    try:
        client = ollama.Client(host=host)
        resp = client.chat(
            model=MODEL_NAME,
            messages=conversation_history,
            stream=False,
            options={"num_ctx": 1024, "num_predict": 256, "temperature": 0.6},
        )
        msg = (resp.get("message") or {})
        reply = (msg.get("content") or "").strip()
        if not reply:
            print(f"[ollama][ERR] empty reply; raw resp={json.dumps(resp)[:400]}")
            reply = ""
    except Exception as e:
        print("[ollama][ERR]", e)
        reply = ""

    conversation_history.append({"role": "assistant", "content": reply})
    if reply:
        print(f"Eve: {reply}")
    return reply

def piper_tts_to_wav(text, out_wav_path):
    if not shutil.which(PIPER_BIN):
        return False
    try:
        subprocess.run(
            [PIPER_BIN, "-m", PIPER_VOICE, "-f", out_wav_path],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
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
        try: os.remove(path)
        except: pass

# STT + VAD
def _init_whisper():
    global _whisper_model
    if _whisper_model is None and WHISPER_MODEL_AVAILABLE:
        try:
            _whisper_model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
            print(f"[STT] loaded faster-whisper '{WHISPER_MODEL_NAME}' on {WHISPER_DEVICE}/{WHISPER_COMPUTE_TYPE}")
        except Exception as e:
            print(f"[STT load error] {e}")
            _whisper_model = None

def _beep(duration_ms=120, freq=880):
    if not BEEP_ON_LISTEN:
        return
    try:
        import numpy as _np
        sr = 16000
        t = _np.linspace(0, duration_ms/1000, int(sr*duration_ms/1000), False)
        tone = (0.15*_np.sin(2*_np.pi*freq*t)).astype(_np.float32)
        fd, path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        sf.write(path, tone, sr)
        sa.WaveObject.from_wave_file(path).play().wait_done()
        os.remove(path)
    except Exception:
        pass

def _record_utterance_vad(device=None):
    if not VAD_AVAILABLE:
        return None

    frame_len = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000) # samples/frame
    bytes_per_frame = frame_len * 2 # int16 mono
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    preroll = deque(maxlen=max(1, PRE_ROLL_MS // VAD_FRAME_MS))
    voiced = []
    triggered = False
    speech_ms = 0
    silence_ms = 0
    t0 = time.time()

    try:
        with sd.RawInputStream(samplerate=VAD_SAMPLE_RATE,
            blocksize=frame_len,
            dtype='int16',
            channels=1,
            device=device) as stream:
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

                if (silence_ms >= END_SILENCE_MS and speech_ms >= MIN_SPEECH_MS) or \
                    ((time.time() - t0) >= MAX_UTTERANCE_SEC):
                    break
    except Exception as e:
        print(f"[VAD stream error] {e}")
        return None

    if not voiced or speech_ms < MIN_SPEECH_MS:
        return None

    fd, out_path = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    try:
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(VAD_SAMPLE_RATE)
            wf.writeframes(b"".join(voiced))
        return out_path
    except Exception as e:
        print(f"[VAD write error] {e}")
        try: os.remove(out_path)
        except: pass
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
        try: os.remove(path)
        except: pass
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
        text = " ".join(getattr(s, "text", "").strip() for s in segments if getattr(s, "text", "").strip())
    except Exception as e:
        print(f"[STT error] {e}")
    finally:
        try: os.remove(wav)
        except: pass

 
    if len(text.split()) < 3 and VAD_AVAILABLE:
        more = listen_once(seconds) 
        if more:
            text = (text + " " + more).strip()

    return text

def user_present_now(cam, ref_encoding, tolerance=FACE_TOLERANCE, checks=3):
    for _ in range(checks):
        ret, frame = cam.read()
        if not ret:
            continue
        small = cv2.resize(frame, (0, 0), fx=DOWNSCALE, fy=DOWNSCALE)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        try:
            boxes = face_recognition.face_locations(rgb, model='hog')
            encs = face_recognition.face_encodings(rgb, boxes)
        except Exception:
            encs = []
        if not encs:
            time.sleep(0.03)
            continue
        matches = face_recognition.compare_faces(encs, ref_encoding, tolerance=tolerance)
        if True in matches:
            return True
        time.sleep(0.03)
    return False

def normalize_text(t: str) -> str:
    return re.sub(r'[^a-z\s]', ' ', t.lower())

def said_goodbye(text: str) -> bool:
    t = normalize_text(text)
    return any(kw in t for kw in GOODBYE_KEYWORDS)

def ask_and_listen(llm_prompt, conversation_history, listen_secs=LISTEN_SECONDS, fallback_label="(type)"):
    reply = get_ollama_response(llm_prompt, conversation_history)
    speak(reply)

    print(f"\n[Eve listening…] Speak now.")
    utterance = listen_once(listen_secs).strip()
    if not utterance:
        utterance = input(f"{fallback_label} ").strip()
    if utterance:
        print(f"You said: {utterance}")
    return utterance

def greet_known_user(name, role, conversation_history):
    line = f"{name} has approached you again. " + (f"They are a {role}. " if role else "") + "Greet them briefly and ask how you can help."
    reply = get_ollama_response(line, conversation_history)
    speak(reply)

def conduct_chat(cam, ref_encoding, person_name, user_id, conversation_history):
    keepalive = max(PRESENCE_KEEP_ALIVE, LISTEN_SECONDS + KEEPALIVE_MARGIN)
    last_seen = time.time()

    while True:
        print("\n[Eve listening…]")
        utter = listen_once(LISTEN_SECONDS).strip()
        if not utter:
            utter = input("(type if mic is quiet) ").strip()
        if utter:
            print(f"You said: {utter}")

            if said_goodbye(utter):
                closing = get_ollama_response(
                    f"The user said: '{utter}'. They are leaving now. "
                    "Say a concise in-character goodbye and end the conversation.",
                    conversation_history
                )
                speak(closing)
                if user_id:
                    save_conversation_history(user_id, conversation_history)
                print("[FLOW] Conversation ended by explicit goodbye.")
                break

            reply = get_ollama_response(utter, conversation_history)
            speak(reply)
            last_seen = time.time()
            if user_id:
                save_conversation_history(user_id, conversation_history)

        if user_present_now(cam, ref_encoding):
            last_seen = time.time()
        elif (time.time() - last_seen) > keepalive:
            farewell = get_ollama_response(
                f"{person_name} appears to have walked away. End politely and say you'll be here.",
                conversation_history
            )
            speak(farewell)
            if user_id:
                save_conversation_history(user_id, conversation_history)
            print("[FLOW] Conversation ended by presence timeout.")
            break

def main():
    setup_database()
    load_known_faces()

    font = cv2.FONT_HERSHEY_SIMPLEX
    cam = cv2.VideoCapture(0)
    time.sleep(2.0)

    detected_faces_this_cycle = set()

    while True:
        ret, frame = cam.read()
        if not ret:
            print("Camera read failed.")
            break

        small = cv2.resize(frame, (0, 0), fx=DOWNSCALE, fy=DOWNSCALE)
        rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        try:
            face_boxes = face_recognition.face_locations(rgb_small, model='hog') # faster than 'cnn'
            face_encs = face_recognition.face_encodings(rgb_small, face_boxes)
        except Exception as e:
            print(f"[Face error] {e}")
            face_boxes, face_encs = [], []

        current_cycle_detected_names = set()

        for (top, right, bottom, left), face_encoding in zip(face_boxes, face_encs):
            name = 'unknown'
            user_id = None
            user_role = None

            if known_face_encodings:
                matches = face_recognition.compare_faces(
                    known_face_encodings, face_encoding, tolerance=FACE_TOLERANCE
                )
                if True in matches:
                    idx = matches.index(True)
                    name = known_face_names[idx]
                    user_id, user_role = get_user_id_by_name(name)

            top = int(top / DOWNSCALE)
            right = int(right / DOWNSCALE)
            bottom = int(bottom / DOWNSCALE)
            left = int(left / DOWNSCALE)

            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
            cv2.putText(frame, name, (left, top - 6), font, 0.75, (0, 255, 0), 2)

            current_cycle_detected_names.add(name)

            # Unknown flow
            if name == 'unknown' and 'unknown' not in detected_faces_this_cycle:
                print("\n[FLOW] Unknown face detected → onboarding.")
                cv2.imshow('EveVision', frame)
                cv2.waitKey(1)

                conversation_history = [] # fresh convo

                # Ask name
                name_prompt = (
                    "A new person has approached. Introduce yourself briefly as Eve and ask for this person's name: "
                    "'What's your name?' Keep it about 2 sentences."
                )
                person_name = ask_and_listen(name_prompt, conversation_history, fallback_label="Your name:")
                if not person_name:
                    person_name = f"guest_{int(time.time())}"

                # Ask role
                role_prompt = (
                    f"They told their name or mentioned it in: {person_name}. "
                    "Acknowledge it by name, then ask if they are a team member, a mentor, or a visitor. "
                    "One short sentence."
                )
                role_text = ask_and_listen(role_prompt, conversation_history, fallback_label="Your role:")
                if not role_text:
                    role_text = "visitor"

                # Store user
                uid = add_new_user(person_name, face_encoding, role_text)
                if uid is None:
                    print("[ERR] Could not store new user; continuing without memory.")
                else:
                    save_conversation_history(uid, conversation_history)

                confirm = get_ollama_response(
                    f"Confirm to {person_name} that their name and role '{role_text}' have been saved. "
                    "Keep it to one sentence.",
                    conversation_history
                )
                speak(confirm)

                segue = get_ollama_response(
                    f"You just onboarded {person_name} ({role_text}). Welcome them and ask how you can help.",
                    conversation_history
                )
                speak(segue)

                detected_faces_this_cycle.add('unknown')
                conduct_chat(cam, face_encoding, person_name, uid, conversation_history)
                detected_faces_this_cycle.discard('unknown')

            # Known flow
            elif name != 'unknown' and name not in detected_faces_this_cycle:
                print(f"\n[FLOW] Known face: {name} (id={user_id}, role={user_role})")
                cv2.imshow('EveVision', frame)
                cv2.waitKey(1)

                conversation_history = load_conversation_history(user_id) if user_id else []
                if not conversation_history or conversation_history[0].get("role") != "system":
                    conversation_history = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]

                greet_known_user(name, user_role, conversation_history)
                detected_faces_this_cycle.add(name)
                conduct_chat(cam, face_encoding, name, user_id, conversation_history)
                detected_faces_this_cycle.discard(name)

        removed = detected_faces_this_cycle - current_cycle_detected_names
        for n in removed:
            detected_faces_this_cycle.discard(n)

        # Display
        cv2.imshow('EveVision', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cam.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
 main()
