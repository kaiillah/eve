import time

from audio import listen_once, speak
from config import KEEPALIVE_MARGIN, LISTEN_SECONDS, PRESENCE_KEEP_ALIVE, ROBOT_NAME
from database import save_conversation_history
from llm import get_ollama_response
from utils import said_goodbye
from vision import user_present_now


def ask_and_listen(llm_prompt, conversation_history, listen_secs=LISTEN_SECONDS, fallback_label="(type)"):
    reply = get_ollama_response(llm_prompt, conversation_history)
    speak(reply)

    print(f"\n[{ROBOT_NAME} listening…] Speak now.")
    utterance = listen_once(listen_secs).strip()
    if not utterance:
        utterance = input(f"{fallback_label} ").strip()
    if utterance:
        print(f"You said: {utterance}")
    return utterance


def greet_known_user(name, role, conversation_history):
    line = (
        f"{name} has approached you again. "
        + (f"They are a {role}. " if role else "")
        + "Greet them briefly and ask how you can help."
    )
    reply = get_ollama_response(line, conversation_history)
    speak(reply)


def conduct_chat(cam, ref_encoding, person_name, user_id, conversation_history):
    keepalive = max(PRESENCE_KEEP_ALIVE, LISTEN_SECONDS + KEEPALIVE_MARGIN)
    last_seen = time.time()

    while True:
        print(f"\n[{ROBOT_NAME} listening…]")
        utter = listen_once(LISTEN_SECONDS).strip()
        if not utter:
            utter = input("(type if mic is quiet) ").strip()
        if utter:
            print(f"You said: {utter}")

            if said_goodbye(utter):
                closing = get_ollama_response(f"The user said: '{utter}'. They are leaving now. "
                    "Say a concise in-character goodbye and end the conversation.",
                    conversation_history,
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
                conversation_history,
            )
            speak(farewell)
            if user_id:
                save_conversation_history(user_id, conversation_history)
            print("[FLOW] Conversation ended by presence timeout.")
            break
