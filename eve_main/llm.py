import json
import os

import ollama

from config import BASE_SYSTEM_PROMPT, MODEL_NAME, ROBOT_NAME


def _ensure_system(conversation_history):
    # Saved conversations may contain an old persona. Apply the current choice
    # on every request while preserving user/assistant conversation messages.
    conversation_history[:] = [
        message for message in conversation_history if message.get("role") != "system"
    ]
    if BASE_SYSTEM_PROMPT:
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
        )
        msg = resp.get("message") or {}
        reply = (msg.get("content") or "").strip()
        if not reply:
            print(f"[ollama][ERR] empty reply; raw resp={json.dumps(resp)[:400]}")
            reply = ""
    except Exception as e:
        print("[ollama][ERR]", e)
        reply = ""

    conversation_history.append({"role": "assistant", "content": reply})
    if reply:
        print(f"{ROBOT_NAME}: {reply}")
    return reply
