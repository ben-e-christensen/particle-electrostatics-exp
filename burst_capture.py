#!/usr/bin/env python3
"""
Burst capture: grab a fixed number of frames from the Basler camera at a fixed
frame rate into a preallocated RAM buffer, then write them to disk losslessly.

Shared by:
  - gui/motor_controls_gui.py  ("Burst Run (1 hr)" button)
  - burst_test.py              (standalone camera-settings test)

Sampling rule: 1 frame per degree of rotation, so fps = 6 * RPM and each
revolution is 360 frames. Revolutions per burst come from REV_TABLE, rounded to
the nearest RPM row.

Only one process can hold the camera. Callers that run alongside the live feed
must pause it first (see gui/camera_feed_gui.pause_live_feed).
"""

import os, time, json, csv, shutil
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import cv2
from pypylon import pylon, genicam

# ---------------------------------------------------------------- config ----

# (rpm, revs per burst). Nearest row by RPM is used for any requested speed.
REV_TABLE = [(1, 1), (6, 2), (11, 3), (16, 4), (21, 5), (26, 6)]
FRAMES_PER_REV = 360                      # 1 frame per degree

# Camera settings applied for every burst. None = leave camera default.
GAIN_DB = 28.0
EXPOSURE_US = None          # e.g. 4000.0; must be < 1e6 / fps
ROI = None                  # e.g. (1280, 1024) (width, height); None = full sensor
PNG_COMPRESSION = 1         # 0..9, 1 is fast and still lossless
MAX_EXPOSURE_FRACTION = 0.9 # exposure may use at most this fraction of the frame period


# --------------------------------------------------------------- helpers ----

def revs_for_rpm(rpm: float) -> int:
    """Revolutions per burst, from the nearest REV_TABLE row."""
    _, revs = min(REV_TABLE, key=lambda row: abs(row[0] - rpm))
    return revs


def fps_for_rpm(rpm: float) -> float:
    return 6.0 * rpm                       # rpm * 360 deg / 60 s


def burst_plan(rpm: float, revs: int | None = None) -> dict:
    """Frame rate, frame count and duration for one burst at this speed."""
    revs = revs_for_rpm(rpm) if revs is None else revs
    fps = fps_for_rpm(rpm)
    n_frames = int(round(revs * FRAMES_PER_REV))
    return {"rpm": rpm, "revs": revs, "fps": fps,
            "n_frames": n_frames, "duration_s": n_frames / fps if fps > 0 else 0.0}


def check_disk_space(path: str, needed_bytes: int, margin: float = 1.2) -> tuple[bool, int]:
    """Return (ok, free_bytes). Refuses if free < needed * margin."""
    os.makedirs(path, exist_ok=True)
    free = shutil.disk_usage(path).free
    return free >= needed_bytes * margin, free


def _node(cam, *names):
    """First existing GenICam node among names, or None (USB and GigE differ)."""
    nm = cam.GetNodeMap()
    for n in names:
        node = nm.GetNode(n)
        if node is not None and genicam.IsAvailable(node):
            return node
    return None


# ---------------------------------------------------------- BurstCamera ----

class BurstCamera:
    """Opens the first Basler camera and captures bursts at a set fps.

    Use as a context manager so the camera is always released:
        with BurstCamera() as cam:
            frames, meta = cam.capture_burst(fps, n_frames)
    """

    def __init__(self, gain_db=GAIN_DB, exposure_us=EXPOSURE_US, roi=ROI):
        self.gain_db = gain_db
        self.exposure_us = exposure_us
        self.roi = roi
        self.cam = None
        self.converter = None
        self.mono8 = False
        self.width = self.height = 0
        self.model = ""

    # -- lifecycle --
    def open(self):
        tl = pylon.TlFactory.GetInstance()
        if not tl.EnumerateDevices():
            raise RuntimeError("No Basler cameras found.")
        self.cam = pylon.InstantCamera(tl.CreateFirstDevice())
        self.cam.Open()
        cam = self.cam
        self.model = cam.GetDeviceInfo().GetModelName()

        # Pixel format: prefer Mono8 so frames go straight into the buffer.
        syms = cam.PixelFormat.GetSymbolics()
        cam.PixelFormat.SetValue("Mono8" if "Mono8" in syms else syms[0])
        self.mono8 = cam.PixelFormat.GetValue() == "Mono8"
        if not self.mono8:
            self.converter = pylon.ImageFormatConverter()
            self.converter.OutputPixelFormat = pylon.PixelType_Mono8
            self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        # ROI (optional). Offsets reset to 0 first so a smaller size always fits.
        if self.roi:
            w, h = self.roi
            for name, val in (("OffsetX", 0), ("OffsetY", 0), ("Width", w), ("Height", h)):
                node = _node(cam, name)
                if node is not None and genicam.IsWritable(node):
                    node.SetValue(int(val))
        self.width = int(cam.Width.GetValue())
        self.height = int(cam.Height.GetValue())

        # Gain
        if self.gain_db is not None:
            cam.GainAuto.SetValue("Off")
            node = _node(cam, "Gain", "GainRaw")
            node.SetValue(self.gain_db if node.GetName() == "Gain" else int(self.gain_db))

        # Exposure
        if self.exposure_us is not None:
            cam.ExposureAuto.SetValue("Off")
            _node(cam, "ExposureTime", "ExposureTimeAbs").SetValue(float(self.exposure_us))

        # Let USB3 cameras use the full link bandwidth.
        node = _node(cam, "DeviceLinkThroughputLimitMode")
        if node is not None and genicam.IsWritable(node):
            node.SetValue("Off")

        # Free-run with a fixed frame rate (no hardware trigger).
        cam.TriggerMode.SetValue("Off")
        cam.AcquisitionFrameRateEnable.SetValue(True)
        print(f"[burst] Opened {self.model} {self.width}x{self.height} "
              f"{cam.PixelFormat.GetValue()}")
        return self

    def close(self):
        try:
            if self.cam:
                if self.cam.IsGrabbing():
                    self.cam.StopGrabbing()
                if self.cam.IsOpen():
                    self.cam.Close()
        except Exception:
            pass
        self.cam = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- settings --
    def bytes_per_frame(self) -> int:
        return self.width * self.height

    def set_fps(self, fps: float) -> float:
        """Set AcquisitionFrameRate; returns the camera's resulting frame rate."""
        cam = self.cam
        exp_node = _node(cam, "ExposureTime", "ExposureTimeAbs")
        max_exp = MAX_EXPOSURE_FRACTION * 1e6 / fps
        if exp_node is not None and exp_node.GetValue() > max_exp:
            print(f"[burst] Exposure {exp_node.GetValue():.0f} us too long for {fps:.1f} fps, "
                  f"reducing to {max_exp:.0f} us")
            cam.ExposureAuto.SetValue("Off")
            exp_node.SetValue(max_exp)
        _node(cam, "AcquisitionFrameRate", "AcquisitionFrameRateAbs").SetValue(float(fps))
        res = _node(cam, "ResultingFrameRate", "ResultingFrameRateAbs")
        resulting = float(res.GetValue()) if res is not None else fps
        if resulting < fps * 0.99:
            print(f"[burst] WARNING: camera can only do {resulting:.1f} fps, asked for {fps:.1f}")
        return resulting

    def current_settings(self) -> dict:
        cam = self.cam
        exp = _node(cam, "ExposureTime", "ExposureTimeAbs")
        gain = _node(cam, "Gain", "GainRaw")
        return {
            "model": self.model,
            "width": self.width, "height": self.height,
            "pixel_format": cam.PixelFormat.GetValue(),
            "exposure_us": float(exp.GetValue()) if exp is not None else None,
            "gain": float(gain.GetValue()) if gain is not None else None,
        }

    # -- capture --
    def capture_burst(self, fps: float, n_frames: int, meta_fn=None, should_abort=None):
        """Grab n_frames at fps into RAM.

        meta_fn():   optional, returns a dict merged into each frame's metadata
                     (e.g. motor angle and rpm at grab time).
        should_abort(): optional, return True to stop early.

        Returns (frames, meta): frames is a uint8 array (n, h, w), possibly
        shorter than n_frames if aborted; meta is a list of dicts, one per frame.
        """
        cam = self.cam
        resulting_fps = self.set_fps(fps)
        frames = np.empty((n_frames, self.height, self.width), dtype=np.uint8)
        meta = []
        cam.MaxNumBuffer = min(max(16, n_frames), 128)
        timeout_ms = int(max(5000, 3000 / fps * 1000))

        t_start = time.time()
        cam.StartGrabbingMax(n_frames, pylon.GrabStrategy_OneByOne)
        i = 0
        errors = 0
        try:
            while cam.IsGrabbing() and i < n_frames:
                grab = cam.RetrieveResult(timeout_ms, pylon.TimeoutHandling_ThrowException)
                try:
                    if grab.GrabSucceeded():
                        if self.mono8:
                            frames[i] = grab.GetArray()
                        else:
                            frames[i] = self.converter.Convert(grab).GetArray()
                        row = {
                            "frame": i,
                            "cam_timestamp": int(grab.GetTimeStamp()),
                            "block_id": int(grab.GetBlockID()),
                            "pc_time": time.time(),
                        }
                        if meta_fn:
                            row.update(meta_fn())
                        meta.append(row)
                        i += 1
                    else:
                        errors += 1
                finally:
                    grab.Release()
                if should_abort and should_abort():
                    print("[burst] Capture aborted.")
                    break
        finally:
            if cam.IsGrabbing():
                cam.StopGrabbing()
        elapsed = time.time() - t_start
        achieved = (i - 1) / (meta[-1]["pc_time"] - meta[0]["pc_time"]) if i > 1 else 0.0
        print(f"[burst] Captured {i}/{n_frames} frames in {elapsed:.1f}s "
              f"(requested {fps:.1f} fps, camera {resulting_fps:.1f}, achieved {achieved:.1f}), "
              f"{errors} grab errors")
        return frames[:i], meta


# -------------------------------------------------------------- saving ----

def frame_stats(frames: np.ndarray) -> dict:
    """Brightness stats over a burst (for checking exposure/gain)."""
    if len(frames) == 0:
        return {}
    sample = frames[:: max(1, len(frames) // 20)]      # subsample for speed
    return {
        "mean": float(sample.mean()),
        "std": float(sample.std()),
        "min": int(sample.min()),
        "max": int(sample.max()),
        "pct_saturated": float((sample >= 250).mean() * 100),
        "pct_black": float((sample <= 5).mean() * 100),
    }


def save_burst(frames: np.ndarray, meta: list, out_dir: str, info: dict | None = None,
               indices=None) -> float:
    """Write frames as lossless PNGs plus frames.csv and burst_info.json.

    indices: optional iterable of frame indices to save (default: all).
    Blocks until every file is written. Returns seconds taken.
    """
    os.makedirs(out_dir, exist_ok=True)
    idx = list(range(len(frames))) if indices is None else [int(k) for k in indices]
    t0 = time.time()

    def _write(k):
        cv2.imwrite(os.path.join(out_dir, f"frame_{k:06d}.png"), frames[k],
                    [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION])

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(_write, idx))

    if meta:
        keys = list(meta[0].keys())
        with open(os.path.join(out_dir, "frames.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys + ["saved"])
            w.writeheader()
            saved = set(idx)
            for row in meta:
                w.writerow({**row, "saved": row["frame"] in saved})

    elapsed = time.time() - t0
    info = dict(info or {})
    info.update({"n_frames_captured": int(len(frames)), "n_frames_saved": len(idx),
                 "save_seconds": round(elapsed, 2), "stats": frame_stats(frames)})
    with open(os.path.join(out_dir, "burst_info.json"), "w") as f:
        json.dump(info, f, indent=2)
    print(f"[burst] Saved {len(idx)} PNGs to {out_dir} in {elapsed:.1f}s")
    return elapsed
