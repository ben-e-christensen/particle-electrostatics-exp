# Basler Camera + Live Tkinter Feed

How to open a Basler camera with `pypylon` and show a live feed in a Tkinter window.
Adapted from `gui/camera_feed_gui.py` in `particle-electrostatics-exp`, with the contour
tracking, frame saving, and shared-state stuff removed.

## Dependencies

```
pip install pypylon==4.2.0 opencv-python numpy pillow
```

- `pypylon` wheels bundle the pylon runtime, so the full Basler pylon SDK is not
  strictly required. On Linux, USB3 cameras still need udev permissions. If
  `EnumerateDevices()` returns nothing but `lsusb` shows the camera, install the pylon
  SDK (it installs the udev rules) or run once with sudo to confirm it's a permissions problem.
- Tkinter comes with Python (`sudo apt install python3-tk` if it's missing on Linux).
- Only one process can open the camera at a time. Close pylon Viewer before running.

## Architecture

- **Grabber thread** (`CameraGrabber`): opens the camera, grabs frames in a loop,
  converts each one to a numpy array, and pushes it into a small `queue.Queue(maxsize=2)`.
  When the queue is full it drops frames (`put_nowait`), so the UI never falls behind.
- **Tk UI loop**: `root.after(...)` runs about 30 times per second, drains the queue
  down to the newest frame, and draws it on a `tk.Label`.
- **Shutdown**: a `threading.Event` tells the grabber to stop. The grabber's `finally`
  block always calls `StopGrabbing()` and `Close()` so the camera is released.
- Never call Tk from the grabber thread. Tk is not thread-safe, so only the main thread
  touches widgets.

## Camera settings used in the original project

- `GainAuto = "Off"` and `Gain = 28.0`.
- `PixelFormat` is set to the first supported format (`GetSymbolics()[0]`), which is
  usually `Mono8` on mono cameras. Set it explicitly (for example `"Mono8"`) if you need
  a specific format.
- `GrabStrategy_LatestImageOnly`: always hands over the newest frame and skips any backlog.
- `ImageFormatConverter` outputs `Mono8` for mono formats and `BGR8packed` otherwise,
  so frames can go straight into OpenCV.
- Exposure is not set (the camera default is used). To set it:
  `cam.ExposureAuto.SetValue("Off")`, then `cam.ExposureTime.SetValue(us)` on
  USB/ace2 cameras, or `cam.ExposureTimeAbs.SetValue(us)` on older GigE models.

## Reference implementation (drop-in module)

```python
#!/usr/bin/env python3
"""Minimal Basler live feed in Tkinter (no processing)."""

import tkinter as tk
import threading, queue
from PIL import Image, ImageTk
import cv2
from pypylon import pylon

TARGET_UI_FPS = 30


class CameraGrabber(threading.Thread):
    def __init__(self, frame_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.q = frame_queue
        self.stop_event = stop_event
        self.cam = None
        self.err = None

    def run(self):
        try:
            tl = pylon.TlFactory.GetInstance()
            if not tl.EnumerateDevices():
                self.err = "No Basler cameras found."
                return

            self.cam = pylon.InstantCamera(tl.CreateFirstDevice())
            self.cam.Open()
            print("Opened:", self.cam.GetDeviceInfo().GetModelName())

            self.cam.GainAuto.SetValue("Off")
            self.cam.Gain.SetValue(28.0)
            self.cam.PixelFormat.SetValue(self.cam.PixelFormat.GetSymbolics()[0])

            converter = pylon.ImageFormatConverter()
            if "Mono" in self.cam.PixelFormat.GetValue():
                converter.OutputPixelFormat = pylon.PixelType_Mono8
            else:
                converter.OutputPixelFormat = pylon.PixelType_BGR8packed
            converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

            self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            while not self.stop_event.is_set() and self.cam.IsGrabbing():
                grab = self.cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
                if grab.GrabSucceeded():
                    img = converter.Convert(grab).GetArray()
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


def build_camera_window(parent: tk.Misc) -> tk.Toplevel:
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

    tk_image = None  # keep a reference or Tk garbage-collects the image

    def update_ui():
        nonlocal tk_image
        if stop_event.is_set():
            return

        frame = None
        try:
            while True:  # drain to newest frame
                frame = frame_queue.get_nowait()
        except queue.Empty:
            pass

        if frame is not None:
            if frame.ndim == 2:
                pil = Image.fromarray(frame)  # mono8
            else:
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tk_image = ImageTk.PhotoImage(pil)
            label.configure(image=tk_image)

        info.config(text=f"[!] {grabber.err}" if grabber.err else "Streaming…")
        top.after(int(1000 / TARGET_UI_FPS), update_ui)

    def on_close():
        stop_event.set()
        top.destroy()

    top.protocol("WM_DELETE_WINDOW", on_close)
    top.after(100, update_ui)
    return top


def attach_camera_feed(parent: tk.Misc | None = None):
    """Open the camera window. Pass an existing Tk root to embed it in an app,
    or None to run it standalone."""
    if parent is None:
        root = tk.Tk()
        root.withdraw()  # hide empty root; only the camera window shows
        top = build_camera_window(root)
        top.bind("<Destroy>", lambda e: root.quit() if e.widget is top else None)
        root.mainloop()
    else:
        build_camera_window(parent)


if __name__ == "__main__":
    attach_camera_feed(None)
```

## Using it from another app

```python
import tkinter as tk
from basler_feed import attach_camera_feed   # whatever you name the module above

root = tk.Tk()
# ... build your own controls on root ...
attach_camera_feed(parent=root)   # opens the camera in its own Toplevel window
root.mainloop()
```

## Adding processing later

Do per-frame work (OpenCV, etc.) inside `update_ui` on the `frame` array before it is
converted to PIL. If the processing is heavy, move it into a separate worker thread with
its own queue so the UI stays responsive. Use `frame.copy()` before modifying a frame
you also want to save or pass on.

## ADC raw → voltage conversion (electrometer channels)

This is unrelated to the camera, but it's the conversion used in the same project
(`gui/motor_controls_gui.py`). Each electrometer signal goes through an **INA159**
level-shifting amplifier and then into an **ADS1115** (16-bit, PGA set to ±4.096 V).
The raw ADS1115 count arrives over serial as a signed integer.

**The math:**

1. Count → voltage at the ADC pin: the ADS1115 LSB is `4.096 / 32768 = 125 µV`, so
   `V_pin = raw * 4.096 / 32768`.
2. Undo the INA159 (gain 0.2, output centered at 1.25 V):
   `V_in = (V_pin - 1.25) / 0.2 = 5 * (V_pin - 1.25)`.

Combined: `V_in = 5 * (raw * 4.096 / 32768 - 1.25)`

```python
ADS_LSB = 4.096 / 32768.0   # 125 uV per count (ADS1115 @ +/-4.096 V PGA)

def convert_to_voltage(raw: int) -> float:
    """ADS1115 @ +/-4.096V PGA through INA159: V = 5*(Vpin - 1.25)"""
    return 5.0 * (raw * ADS_LSB - 1.25)
```

**Sanity checks:**

| raw   | V_pin   | V_in (electrometer) |
|-------|---------|---------------------|
| 0     | 0.000 V | −6.25 V             |
| 10000 | 1.250 V | 0.00 V              |
| 20000 | 2.500 V | +6.25 V             |

- Resolution at the input is `5 * 125 µV = 625 µV` per count.
- If the PGA gain setting on the ADS1115 changes, update `ADS_LSB`
  (full-scale / 32768: ±2.048 V → 62.5 µV, ±6.144 V → 187.5 µV).
- Serial wire format: `seq,ms,spare,electro1_raw,electro2_raw` (five integers per line,
  about 100 Hz). The third field is unused.
- The project also computes `dV/dt = (V - V_prev) / 0.01`, which assumes the 100 Hz
  sample rate.

**Legacy note:** `server/server.py` (the older ESP32 + BLE setup) uses a different 14-bit
SPI ADC with range codes, `ratio = raw / 2**14`. Range 4, which was the default, gives
`V = ratio * 3 * 4.096 - 1.5 * 4.096` (±6.144 V). Don't mix the two formulas.

## Gotchas

- `RetrieveResult(5000, ...)` raises an exception after 5 s with no frame (for example
  in hardware-trigger mode). The exception ends up in `grabber.err` and is shown in the window.
- Always call `grab.Release()`. Otherwise pylon runs out of buffers.
- High-resolution frames may be bigger than the screen. Resize before display with
  `pil.thumbnail((w, h))` or `cv2.resize`.
- `CreateFirstDevice()` picks whichever camera it finds first. With several cameras,
  filter `EnumerateDevices()` by `GetSerialNumber()` and use `tl.CreateDevice(dev)`.
