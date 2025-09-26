"""
Camera live feed window (attaches to existing Tk root)

- Creates a Toplevel that shows the Basler acA1440-220um feed.
- Uses a background thread (pypylon + OpenCV) to grab frames.
- Converts frames to Tk images with Pillow for display.
- Saves frames to disk when motor_state['running'] is True.
"""

import tkinter as tk
import threading, queue, time, os
from collections import deque
from PIL import Image, ImageTk
import cv2
from pypylon import pylon

# import shared state
from states import motor_state, file_state

# ---------------- Config ----------------
TARGET_UI_FPS = 30  # Tkinter refresh limit (camera may be faster)
# ----------------------------------------


class CameraGrabber(threading.Thread):
    """Background thread that pulls frames from the first Basler camera."""
    def __init__(self, frame_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.q = frame_queue
        self.stop_event = stop_event
        self.cam = None
        self.converter = None
        self.err = None
        self.fps_meter = deque(maxlen=100)

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

            # Set manual gain (dB) directly, clamps automatically if out of range
            self.cam.GainAuto.SetValue("Off")
            self.cam.Gain.SetValue(25.0)   # just change this value when you need
            # Auto-pick pixel format
            try:
                syms = self.cam.PixelFormat.GetSymbolics()
                self.cam.PixelFormat.SetValue(syms[0])
                print("[camera_feed_gui] Using PixelFormat:", self.cam.PixelFormat.GetValue())
            except Exception as e:
                print("[camera_feed_gui] PixelFormat unchanged:", e)

            # Converter setup
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


def _build_camera_window(parent):
    """Create the camera feed window inside parent."""
    top = tk.Toplevel(parent)
    top.title("Basler Camera Feed")

    label = tk.Label(top)
    label.pack(fill="both", expand=True)

    info = tk.Label(top, text="Initializing camera…")
    info.pack(anchor="w")

    frame_queue = queue.Queue(maxsize=2)
    stop_event = threading.Event()
    grabber = CameraGrabber(frame_queue, stop_event)
    grabber.start()
    tk_image = None  # keep reference
    frame_index = 0  # counter for saved images

    def update_ui():
        nonlocal tk_image, frame_index
        frame = None
        try:
            while True:
                frame = frame_queue.get_nowait()
        except queue.Empty:
            pass

        if frame is not None:
            # Convert for Tkinter display
            if frame.ndim == 2:
                pil = Image.fromarray(frame)
            else:
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tk_image = ImageTk.PhotoImage(pil)
            label.configure(image=tk_image)

            # -----------------------------
            # -----------------------------
            # Save frame if motor running
            # -----------------------------
            if motor_state.get("running", False):
                print("[DEBUG] Motor running, attempting to save frame")
                ts = int(time.time() * 1000)  # ms timestamp
                images_dir = os.path.join(file_state["CURRENT_DIR"], "images")
                print(f"[DEBUG] Using images_dir={images_dir}")
                try:
                    os.makedirs(images_dir, exist_ok=True)
                    filename = f"{ts}_frame_{frame_index:06d}.jpg"
                    path = os.path.join(images_dir, filename)
                    print(f"[DEBUG] Writing to {path}")
                    ok = cv2.imwrite(path, frame)
                    if ok:
                        print(f"[camera_feed_gui] Saved {filename}")
                    else:
                        print(f"[camera_feed_gui] cv2.imwrite failed for {filename}")
                except Exception as e:
                    print(f"[camera_feed_gui] Exception while saving: {e}")
                frame_index += 1
            else:
                print("[DEBUG] Motor not running, skipping frame save")


        # update status
        if grabber.err:
            info.config(text=f"[!] {grabber.err}")
        else:
            info.config(text=f"Streaming… {frame.shape if frame is not None else ''}")

        top.after(int(1000 / TARGET_UI_FPS), update_ui)

    def on_close():
        stop_event.set()
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", on_close)
    top.after(100, update_ui)
    return top


# ---------------- Public API ----------------
def attach_camera_feed(parent: tk.Misc | None = None):
    """
    Attach the camera feed window to an existing Tk root if present,
    otherwise create a root and run standalone.
    """
    root = parent or tk._get_default_root()
    if root is None:
        root = tk.Tk()
        _build_camera_window(root)
        root.mainloop()
    else:
        _build_camera_window(root)


if __name__ == "__main__":
    attach_camera_feed(None)
