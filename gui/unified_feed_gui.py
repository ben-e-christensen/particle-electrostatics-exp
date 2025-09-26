"""
Unified GUI window with:
- Left: Basler camera live feed
- Right: Two matplotlib plots (A26 and A25)

Attach via attach_unified_feed(parent).
"""

import tkinter as tk
import threading, queue, time
from collections import deque
import traceback

from PIL import Image, ImageTk
import cv2
from pypylon import pylon

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ⚠️ adjust import path to your project
from gui.motor_controls_gui import data_queue_a0, data_queue_a1

# ---------------- Config ----------------
BUFFER_SIZE = 500
UI_REFRESH_MS = 16
TARGET_UI_FPS = 30
# ----------------------------------------

# ---------------- Camera Thread ----------------
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
            print("[unified_feed_gui] Opened:", self.cam.GetDeviceInfo().GetModelName())

            # Pixel format
            syms = self.cam.PixelFormat.GetSymbolics()
            self.cam.PixelFormat.SetValue(syms[0])
            print("[unified_feed_gui] Using PixelFormat:", self.cam.PixelFormat.GetValue())

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
            self.err = str(e)
        finally:
            if self.cam:
                if self.cam.IsGrabbing():
                    self.cam.StopGrabbing()
                if self.cam.IsOpen():
                    self.cam.Close()

# ---------------- Unified Window ----------------
def _build_unified_window(parent):
    top = tk.Toplevel(parent)
    top.title("Unified Live Feed")

    # Split into two rows
    top.rowconfigure(0, weight=3)
    top.rowconfigure(1, weight=2)
    top.columnconfigure(0, weight=1)

    # --- Camera feed area ---
    cam_frame = tk.Frame(top, bg="black")
    cam_frame.grid(row=0, column=0, sticky="nsew")

    cam_label = tk.Label(cam_frame, bg="black")
    cam_label.pack(fill="both", expand=True)
    cam_info = tk.Label(cam_frame, text="Initializing camera…", anchor="w")
    cam_info.pack(anchor="w")

    # --- Matplotlib plots ---
    plot_frame = tk.Frame(top)
    plot_frame.grid(row=1, column=0, sticky="nsew")

    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle("Live Data Stream", fontsize=14)

    ax[0].set_title("GPIO26 (A26)")
    ax[0].grid(True)
    line_a0, = ax[0].plot([], [], 'r-')

    ax[1].set_title("GPIO25 (A25)")
    ax[1].grid(True)
    line_a1, = ax[1].plot([], [], '#87CEEB')

    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill="both", expand=True)

    data_buffer_a0 = deque(maxlen=BUFFER_SIZE)
    data_buffer_a1 = deque(maxlen=BUFFER_SIZE)
    sample_idx = 0

    # --- Threads & queues ---
    frame_queue = queue.Queue(maxsize=2)
    stop_event = threading.Event()
    grabber = CameraGrabber(frame_queue, stop_event)
    grabber.start()
    tk_image = None

    # --- Update loop ---
    def update_ui():
        nonlocal tk_image, sample_idx

        # Update camera
        frame = None
        try:
            while True:
                frame = frame_queue.get_nowait()
        except queue.Empty:
            pass

        if frame is not None:
            if frame.ndim == 2:
                pil = Image.fromarray(frame)
            else:
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tk_image = ImageTk.PhotoImage(pil)
            cam_label.configure(image=tk_image)
        if grabber.err:
            cam_info.config(text=f"[!] {grabber.err}")
        else:
            cam_info.config(text="Streaming…")

        # Update plots
        n_pairs = min(data_queue_a0.qsize(), data_queue_a1.qsize(), 200)
        for _ in range(n_pairs):
            try:
                a0 = data_queue_a0.get_nowait()
                a1 = data_queue_a1.get_nowait()
            except queue.Empty:
                break
            data_buffer_a0.append(a0)
            data_buffer_a1.append(a1)
            sample_idx += 1

        n = len(data_buffer_a0)
        if n > 0:
            x_vals = list(range(sample_idx - n, sample_idx))
            line_a0.set_xdata(x_vals)
            line_a0.set_ydata(list(data_buffer_a0))
            line_a1.set_xdata(x_vals)
            line_a1.set_ydata(list(data_buffer_a1))

            # Scroll X axis
            ax[0].set_xlim(max(0, sample_idx - BUFFER_SIZE), sample_idx)
            ax[1].set_xlim(max(0, sample_idx - BUFFER_SIZE), sample_idx)

            # Autoscale Y
            ymin0, ymax0 = min(data_buffer_a0), max(data_buffer_a0)
            ymin1, ymax1 = min(data_buffer_a1), max(data_buffer_a1)
            pad0 = max(1, int(0.05 * (ymax0 - ymin0 + 1)))
            pad1 = max(1, int(0.05 * (ymax1 - ymin1 + 1)))
            ax[0].set_ylim(ymin0 - pad0, ymax0 + pad0)
            ax[1].set_ylim(ymin1 - pad1, ymax1 + pad1)

            canvas.draw_idle()

        top.after(UI_REFRESH_MS, update_ui)

    def on_close():
        stop_event.set()
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", on_close)
    top.after(100, update_ui)
    return top

# ---------------- Public API ----------------
def attach_unified_feed(parent: tk.Misc | None = None):
    root = parent or tk._get_default_root()
    if root is None:
        root = tk.Tk()
        _build_unified_window(root)
        root.mainloop()
    else:
        _build_unified_window(root)

if __name__ == "__main__":
    attach_unified_feed(None)
