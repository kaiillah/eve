import time

import cv2
import face_recognition

import database
from audio import VAD_AVAILABLE, WHISPER_MODEL_AVAILABLE, speak
from config import DOWNSCALE, FACE_TOLERANCE, ROBOT_NAME
from flow import ask_and_listen, conduct_chat, greet_known_user
from llm import get_ollama_response


print(f"OpenCV version: {cv2.__version__}")
print(f"faster-whisper available: {WHISPER_MODEL_AVAILABLE}")
print(f"VAD available: {VAD_AVAILABLE}")


def main():
    database.setup_database()
    database.load_known_faces()

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
            face_boxes = face_recognition.face_locations(rgb_small, model="hog")
            face_encs = face_recognition.face_encodings(rgb_small, face_boxes)
        except Exception as e:
            print(f"[Face error] {e}")
            face_boxes, face_encs = [], []

        current_cycle_detected_names = set()

        for (top, right, bottom, left), face_encoding in zip(face_boxes, face_encs):
            name = "unknown"
            user_id = None
            user_role = None

            if database.known_face_encodings:
                matches = face_recognition.compare_faces(
                    database.known_face_encodings,
                    face_encoding,
                    tolerance=FACE_TOLERANCE,
                )
                if True in matches:
                    idx = matches.index(True)
                    name = database.known_face_names[idx]
                    user_id, user_role = database.get_user_id_by_name(name)

            top = int(top / DOWNSCALE)
            right = int(right / DOWNSCALE)
            bottom = int(bottom / DOWNSCALE)
            left = int(left / DOWNSCALE)

            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
            cv2.putText(frame, name, (left, top - 6), font, 0.75, (0, 255, 0), 2)

            current_cycle_detected_names.add(name)

            # unknown face flow
            if name == "unknown" and "unknown" not in detected_faces_this_cycle:
                print("\n[FLOW] Unknown face detected → onboarding.")
                cv2.imshow(f"{ROBOT_NAME} Vision", frame)
                cv2.waitKey(1)

                conversation_history = []

                name_prompt = (
                    "A new person has approached. Introduce yourself briefly in character and ask "
                    "for this person's name: 'What's your name?' Keep it about 2 sentences."
                )
                person_name = ask_and_listen(
                    name_prompt,
                    conversation_history,
                    fallback_label="Your name:",
                )
                if not person_name:
                    person_name = f"guest_{int(time.time())}"

                role_prompt = (
                    f"They told their name or mentioned it in: {person_name}. "
                    "Acknowledge it by name, then ask if they are a team member, a mentor, "
                    "or a visitor. One short sentence."
                )
                role_text = ask_and_listen(
                    role_prompt,
                    conversation_history,
                    fallback_label="Your role:",
                )
                if not role_text:
                    role_text = "visitor"

                uid = database.add_new_user(person_name, face_encoding, role_text)
                if uid is None:
                    print("[ERR] Could not store new user; continuing without memory.")
                else:
                    database.save_conversation_history(uid, conversation_history)

                confirm = get_ollama_response(
                    f"Confirm to {person_name} that their name and role '{role_text}' have been saved. "
                    "Keep it to one sentence.",
                    conversation_history,
                )
                speak(confirm)

                segue = get_ollama_response(
                    f"You just onboarded {person_name} ({role_text}). Welcome them and ask how you can help.",
                    conversation_history,
                )
                speak(segue)

                detected_faces_this_cycle.add("unknown")
                conduct_chat(cam, face_encoding, person_name, uid, conversation_history)
                detected_faces_this_cycle.discard("unknown")

            # Known face flow
            elif name != "unknown" and name not in detected_faces_this_cycle:
                print(f"\n[FLOW] Known face: {name} (id={user_id}, role={user_role})")
                cv2.imshow(f"{ROBOT_NAME} Vision", frame)
                cv2.waitKey(1)

                conversation_history = (
                    database.load_conversation_history(user_id) if user_id else []
                )

                greet_known_user(name, user_role, conversation_history)
                detected_faces_this_cycle.add(name)
                conduct_chat(cam, face_encoding, name, user_id, conversation_history)
                detected_faces_this_cycle.discard(name)

        removed = detected_faces_this_cycle - current_cycle_detected_names
        for detected_name in removed:
            detected_faces_this_cycle.discard(detected_name)

        cv2.imshow(f"{ROBOT_NAME} Vision", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
