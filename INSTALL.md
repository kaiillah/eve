# Install Eve on Linux / Jetson

Eve is the example configuration. The same software can use another Ollama model alias, persona, voice, and compatible peripherals.

## Hardware

| Component | Selection requirement |
| --- | --- |
| Computer | Linux with a graphical desktop; the original build used a Jetson Orin Nano Developer Kit (8 GB) |
| Camera | Linux-compatible USB webcam accessible through OpenCV |
| Microphone | Linux audio input supporting mono capture at 16 kHz |
| Speaker | Working Linux audio output |
| Optional mouth | Hobby PWM servo with suitable torque/travel, a compatible controller such as Pico H, and a supply matched to the servo voltage/current requirements |

Brands do not need to match Eve. For a mouth build, select the PWM pin in the controller firmware, match the wiring to that selection, connect the required signal ground, and calibrate motion to the linkage. The Python envelope defaults to 30–120 degrees in `eve_main/audio.py`; those values are examples, not universal mechanical limits. No mouth hardware is required to run the conversation software.

Eve ran on the original Jetson during the 2025 competition season. The installed package versions and original Ollama Modelfile were not retained when the robot was handed off to the team, and that Jetson is no longer available for testing. This guide reconstructs the setup for the customizable edition; a fresh Jetson installation has not yet been tested. The commands below use Ubuntu 22.04 as a starting point; compatibility depends on the selected JetPack and Python versions.

Download and extract the project, then open a Bash terminal in the folder containing `requirements.txt`. Run each step from that folder.

## 1. Python dependencies

```bash
sudo apt update
sudo apt install python3-venv python3-dev build-essential cmake \
  libportaudio2 libasound2-dev libsndfile1 libgl1 libglib2.0-0 curl

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

`requirements.txt` installs the Python packages and their dependencies together. Ollama's server, Piper's executable, and model downloads are separate steps. See [pip requirements files](https://pip.pypa.io/en/stable/user_guide/#requirements-files).

**JetPack OpenCV:** the commands above install a separate pip OpenCV in the virtual environment. To retain system-provided OpenCV instead, create the venv with `--system-site-packages` and use a copy of `requirements.txt` with `opencv-python` removed. Confirm `python -c "import cv2; print(cv2.__file__)"` resolves to the intended installation. Eve uses `cv2.imshow`, so headless OpenCV is unsuitable.

**Optional VAD:** the default recording window is five seconds. WebRTC VAD enables speech-based endpoint detection:

```bash
python -m pip install -r requirements-vad.txt
```

The current VAD path repeatedly listens when a transcript contains fewer than three words. Leave this optional package uninstalled to use fixed-duration recording.

## 2. Ollama: run Eve or create another persona

Install Ollama with its [official Linux installer](https://docs.ollama.com/linux), then run the base model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama run llama3.2:3b
```

`ollama run` downloads the model if needed and opens a terminal chat. Enter `/bye` to return to Bash. If the server is not running, use `sudo systemctl start ollama`; on an installation without a service, use `ollama serve` in another terminal.

The project [Modelfile](Modelfile) defines Eve's persona in `SYSTEM` and the generation settings in `PARAMETER`. Create and run the example alias:

```bash
ollama create eve-template -f Modelfile
ollama run eve-template
```

The alias is the name after `create`; the persona is the text in `SYSTEM`. Creating a new alias does not rename or remove the base model. See the [Ollama Modelfile reference](https://docs.ollama.com/modelfile).

### Customize the assistant

Edit `SYSTEM` in `Modelfile`, for example:

```text
SYSTEM """
You are Nova, a friendly workshop assistant.
Explain robotics clearly and keep spoken replies concise.
"""
```

Keep `FROM llama3.2:3b` and the existing `PARAMETER` lines, or adjust them for another supported model and workload. Then create the chosen alias:

```bash
ollama create nova -f Modelfile
ollama run nova
```

In `eve_main/config.py`, select it:

```python
MODEL_NAME = "nova"
ROBOT_NAME = "Nova"
BASE_SYSTEM_PROMPT = None
```

`MODEL_NAME` selects the Ollama alias. `ROBOT_NAME` changes console labels and the camera-window title. `BASE_SYSTEM_PROMPT = None` lets the Modelfile control the persona; setting it to a string explicitly overrides that persona in Python. Re-run `ollama create` after editing the Modelfile. The app also uses the model's generation settings rather than overriding them.

Saved system messages are removed from request history so an older persona cannot override the current choice. Previous user/assistant messages are retained; a separate `DB_NAME` gives a new assistant its own visitor history if desired.

## 3. Piper speech synthesis

The application uses the standalone Piper executable. Download the appropriate Linux release from [Piper releases](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2): `aarch64` for Jetson, `x86_64` for an Intel/AMD Linux computer. This guide uses the standalone release for its command-line interface.

For a fresh Jetson setup, place the downloaded `piper_linux_aarch64.tar.gz` in the project folder, then extract the entire bundle:

```bash
sudo mkdir -p /opt/piper/voices
sudo tar -xzf piper_linux_aarch64.tar.gz -C /opt/piper
```

The expected executable location is `/opt/piper/piper/piper`. Keep the bundled libraries alongside it. If the archive layout or installation path differs, update `PIPER_BIN` in `eve_main/config.py`.

Eve uses the [Amy low voice](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/low). Download its model and matching configuration:

```bash
sudo curl -fL --output /opt/piper/voices/en_US-amy-low.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx
sudo curl -fL --output /opt/piper/voices/en_US-amy-low.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low/en_US-amy-low.onnx.json
```

Test synthesis and playback separately from Eve:

```bash
/opt/piper/piper/piper -m /opt/piper/voices/en_US-amy-low.onnx \
  -f /tmp/eve-voice-test.wav <<<'Hello, I am Eve.'
python -c "import simpleaudio as sa; sa.WaveObject.from_wave_file('/tmp/eve-voice-test.wav').play().wait_done()"
```

For another compatible Piper voice, download its `.onnx` and matching `.onnx.json`, then update `PIPER_VOICE` in `eve_main/config.py`.

## 4. Configure hardware and run

| Setting | Default / location |
| --- | --- |
| Camera | Index `0` in `eve_main/main.py` |
| Microphone | Default sounddevice input; mono, 16 kHz |
| Speaker | Default playback device |
| Ollama | `http://127.0.0.1:11434`; override with `OLLAMA_HOST` |
| Model and voice | `eve_main/config.py` |
| Pico serial | `/dev/ttyACM0`, 115200 baud in `eve_main/config.py` |
| Database | `face_recognition.db`, relative to the launch directory |

Optional audio-driven mouth control sends `ANGLE:<integer>` lines over USB serial at 115200 baud. Controller firmware must parse those commands and drive the chosen servo's PWM pin. Without a serial connection, the software continues with speech playback. The original booth mouth used a separate manually switched animation; this repository does not include controller firmware for either approach.

```bash
source .venv/bin/activate
python eve_main/main.py
```

The [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `tiny.en` model downloads at first initialization if it is not already cached. Initial setup needs internet access. This configuration uses CPU `int8` speech recognition.

Press `q` while the camera loop is active to exit. Blocking speech or terminal input can delay its response. Empty transcription falls back to terminal input.

The preserved fallback runs with `python legacy/single_script_fall_back.py`. It retains its historical settings and prompt handling, including the old `face_recognition5.db` filename. Use `eve_main/main.py` for the customizable version; run one version at a time.

## 5. View or edit the database

The app creates `face_recognition.db` automatically in the launch directory. No separate database server or pip SQLite package is required. `DB_NAME` in `eve_main/config.py` can select a different path.

Open the file in [DB Browser for SQLite](https://sqlitebrowser.org/) and select **Browse Data**:

| Table / field | Contents |
| --- | --- |
| `users.name`, `users.role` | Visitor names and roles; editable text |
| `users.encoding` | Serialized face embedding generated by the app |
| `conversations.user_id` | Links each history to a visitor |
| `conversations.history` | JSON list of conversation messages |

Stop the app and back up the database before editing. Use **Write Changes** to save, then restart the app to reload visitor information. Keep conversation history valid JSON and preserve user IDs and their relationships. Face encodings are binary data; use the camera onboarding flow to create them instead of editing the bytes manually.

To reuse a database from an older copy, stop the app and copy that file to `face_recognition.db`, or set `DB_NAME` to its existing path. The filename change does not migrate data automatically. Use a separate file for a clean assistant persona. Visitor databases remain excluded from Git.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| pip fails building dlib | CMake/compiler installation and [face-recognition platform requirements](https://github.com/ageitgey/face_recognition#installation) |
| CTranslate2 installation fails | ARM64/Python compatibility for the selected faster-whisper dependencies |
| Camera window fails | GUI-enabled OpenCV, desktop session, camera index and device access |
| No microphone input | `python -m sounddevice` lists available audio devices |
| Ollama connection error | Server status, `OLLAMA_HOST`, and `ollama list` |
| Text reply but no speech | Piper paths, matching voice configuration, and the standalone playback test |
| No mouth movement | Pico firmware, serial port, device permissions and wiring |

After a successful hardware run, save the installed versions with `python -m pip freeze > requirements.lock.txt` and record the JetPack, Ubuntu, and Python versions alongside them.
