import time

import cv2
import face_recognition

from config import DOWNSCALE, FACE_TOLERANCE


def user_present_now(cam, ref_encoding, tolerance=FACE_TOLERANCE, checks=3):
    for _ in range(checks):
        ret, frame = cam.read()
        if not ret:
            continue
        small = cv2.resize(frame, (0, 0), fx=DOWNSCALE, fy=DOWNSCALE)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        try:
            boxes = face_recognition.face_locations(rgb, model="hog")
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
