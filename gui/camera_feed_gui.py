#!/usr/bin/env python3
"""
Basler Camera Feed + Contour Tracking + Asynchronous Frame Saving
-----------------------------------------------------------------
- Draws particle outline (contour).
- Tracks angle (from minAreaRect) and area.
- Saves frames asynchronously every N frames while motor is running.
"""

import tkinter as tk
import threading, queue, time, os
from PIL import Image, ImageTk
import cv2
import numpy as np
from pypylon import pylon

from states import motor_state, file_state, ellipse_state, frame_state

TARGET_UI_FPS = 30
SAVE_EVERY_N_FRAMES = 5  # <----- SAVE 1 OUT OF EVERY 10 FRAMES


# ==============================================================
# Camera Thread
# ==============================================================
class CameraGrabber(threading.Thread):
    def __init__(self, frame_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.q = frame_queue
        self.stop_event = stop_event
        self.cam = None
        self.converter = None
        self.err = None

    def run(self):
        try:
            tl = pylon.TlFactory.GetInstance()
            devs = tl.EnumerateDevices()
            if not devs:
                self.err = "No Basler cameras found."
                return

            self.cam = pylon.InstantCamera(tl.CreateFirstDevice())
            self.cam.Open()
            print("[camera_feed_gui] Opened:", self.cam.GetDeviceInfo().GetModelName())

            self.cam.GainAuto.SetValue("Off")
            self.cam.Gain.SetValue(28.0)

            syms = self.cam.PixelFormat.GetSymbolics()
            self.cam.PixelFormat.SetValue(syms[0])
            print("[camera_feed_gui] Using PixelFormat:", self.cam.PixelFormat.GetValue())

            self.converter = pylon.ImageFormatConverter()
            if "Mono" in self.cam.PixelFormat.GetValue():
                self.converter.OutputPixelFormat = pylon.PixelType_Mono8
            else:
                self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
            self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

            self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

            while not self.stop_event.is_set() and self.cam.IsGrabbing():
                grab = self.cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                if grab.GrabSucceeded():
                    img = self.converter.Convert(grab).GetArray()
                    try:
                        self.q.put_nowait(img)
                    except queue.Full:
                        pass
                grab.Release()

        except Exception as e:
            self.err = f"{type(e).__name__}: {e}"

        finally:
            try:
                if self.cam:
                    if self.cam.IsGrabbing():
                        self.cam.StopGrabbing()
                    if self.cam.IsOpen():
                        self.cam.Close()
            except Exception:
                pass


# ==============================================================
# Camera Window + UI
# ==============================================================
def _build_camera_window(parent):
    top = tk.Toplevel(parent)
    top.title("Basler Camera Feed + Contour Tracking")

    label = tk.Label(top)
    label.pack(fill="both", expand=True)

    info = tk.Label(top, text="Initializing camera…")
    info.pack(anchor="w")

    frame_queue = queue.Queue(maxsize=2)
    save_queue = queue.Queue(maxsize=20)  # bigger buffer
    stop_event = threading.Event()

    grabber = CameraGrabber(frame_queue, stop_event)
    grabber.start()

    tk_image = None
    frame_index = 0
    dropped = 0  # track dropped frames

    # ----------------------------------------------------------
    # FRAME SAVER THREAD
    # ----------------------------------------------------------
    def frame_saver():
        base_dir = file_state["CURRENT_DIR"]
        images_dir = os.path.join(base_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        while not stop_event.is_set():
            try:
                ts, idx, frame_to_save = save_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            filename = f"{ts}_frame_{idx:06d}.jpg"
            path_full = os.path.join(images_dir, filename)
            cv2.imwrite(path_full, frame_to_save)
            print(f"[camera_feed_gui] Saved {filename}")

            save_queue.task_done()

    threading.Thread(target=frame_saver, daemon=True).start()

    # ----------------------------------------------------------
    # UI UPDATE LOOP
    # ----------------------------------------------------------
    def update_ui():
        nonlocal tk_image, frame_index, dropped

        # Get latest frame only
        frame = None
        try:
            while True:
                frame = frame_queue.get_nowait()
        except queue.Empty:
            pass

        if frame is not None:
            display = frame.copy()

            gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 50, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if contours:
                largest = max(contours, key=cv2.contourArea)
                area = cv2.contourArea(largest)

                M = cv2.moments(largest)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                else:
                    cx, cy = 0, 0

                rect = cv2.minAreaRect(largest)
                (x, y), (w, h), angle = rect

                cv2.drawContours(display, [largest], -1, (0, 255, 0), 2)
                cv2.circle(display, (cx, cy), 4, (0, 0, 255), -1)

                ellipse_state["angle_deg"] = angle
                ellipse_state["area_px2"] = area

                cv2.putText(display, f"Angle: {angle:.1f}",
                            (display.shape[1] - 200, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(display, f"Area: {area:.0f} px^2",
                            (display.shape[1] - 200, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Display image in Tkinter
            rgb = display if display.ndim == 3 else cv2.cvtColor(display, cv2.COLOR_GRAY2RGB)
            pil = Image.fromarray(cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB))
            tk_image = ImageTk.PhotoImage(pil)
            label.configure(image=tk_image)

            # -------- ASYNC SAVE EVERY NTH FRAME --------
            if motor_state.get("running", False):
                if frame_index % SAVE_EVERY_N_FRAMES == 0:

                    ts = int(time.time() * 1000)
                    frame_state["name"] = f"{ts}_frame_{frame_index:06d}.jpg"

                    try:
                        save_queue.put_nowait((ts, frame_index, frame.copy()))
                    except queue.Full:
                        dropped += 1
                        if dropped % 100 == 0:
                            print(f"[warning] dropped {dropped} frames")

                frame_index += 1

        # Update text
        if grabber.err:
            info.config(text=f"[!] {grabber.err}")
        else:
            info.config(text="Streaming…")

        top.after(int(1000 / TARGET_UI_FPS), update_ui)

    # ----------------------------------------------------------
    # WINDOW CLOSE
    # ----------------------------------------------------------
    def on_close():
        stop_event.set()
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", on_close)
    top.after(100, update_ui)
    return top


# ==============================================================
# Entry
# ==============================================================
def attach_camera_feed(parent: tk.Misc | None = None):
    root = parent or tk._get_default_root()
    if root is None:
        root = tk.Tk()
        _build_camera_window(root)
        root.mainloop()
    else:
        _build_camera_window(root)


if __name__ == "__main__":
    attach_camera_feed(None)
