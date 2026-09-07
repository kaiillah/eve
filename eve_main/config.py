SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200

DB_NAME = "face_recognition.db"
MODEL_NAME = "eve-template"
ROBOT_NAME = "Eve"  # Display label, keep consistent with the Modelfile persona.
FACE_TOLERANCE = 0.5
DOWNSCALE = 0.25

# None uses the persona from the Ollama Modelfile. A string overrides it.
BASE_SYSTEM_PROMPT = None

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

GOODBYE_KEYWORDS = (
    "bye",
    "goodbye",
    "bye bye",
    "see you",
    "see ya",
    "gotta go",
    "have to go",
    "i have to go",
    "i gotta go",
    "i'm leaving",
    "i am leaving",
    "heading out",
    "gotta run",
    "i gotta run",
    "later",
    "catch you",
    "talk to you later",
    "ttyl",
    "farewell",
)


VAD_SAMPLE_RATE = 16000
VAD_FRAME_MS = 20
VAD_AGGRESSIVENESS = 2
PRE_ROLL_MS = 300
END_SILENCE_MS = 500
MIN_SPEECH_MS = 300
MAX_UTTERANCE_SEC = 25
BEEP_ON_LISTEN = False
