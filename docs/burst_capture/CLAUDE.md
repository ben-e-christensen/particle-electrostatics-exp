# Burst Capture Run — Design Notes (in progress, nothing implemented yet)

This is a new automated run mode. While the motor spins, the Basler camera takes
high-frame-rate image bursts in RAM, then writes them to disk.
This file records what has been decided and what is still open. **Resolve the open
questions with the user before writing code.** The user asked for this explicitly:
"clear up any uncertainties before just writing a shit load of code that doesn't do
what I actually want."

## Goal

- Run the motor at set speeds and capture image bursts sized by **revolutions**, not
  by how much fills RAM.
- **1 frame per degree of rotation**, so the camera frame rate depends on speed:
  `fps = 6 × RPM` (RPM × 360° / 60 s). Each rev = 360 frames.
- More revs are captured at higher speeds so every burst lasts a similar time:

| RPM | Revs | FPS | Duration | Frames | 1920×1200 Mono8 | 1280×1024 | 640×480 |
|---|---|---|---|---|---|---|---|
| 1  | 1 | 6   | 60.0 s | 360   | 0.83 GB | 0.47 GB | 0.11 GB |
| 6  | 2 | 36  | 20.0 s | 720   | 1.7 GB  | 0.94 GB | 0.22 GB |
| 11 | 3 | 66  | 16.4 s | 1,080 | 2.5 GB  | 1.4 GB  | 0.33 GB |
| 16 | 4 | 96  | 15.0 s | 1,440 | 3.3 GB  | 1.9 GB  | 0.44 GB |
| 21 | 5 | 126 | 14.3 s | 1,800 | 4.1 GB  | 2.4 GB  | 0.55 GB |
| 26 | 6 | 156 | 13.8 s | 2,160 | 5.0 GB  | 2.8 GB  | 0.66 GB |
| **Total** | | | | **7,560** | **17 GB** | **9.9 GB** | **2.3 GB** |

Speeds are assumed from `auto_ramp_sequence` (1, 6, 11, 16, 21, 26). The pattern is
n revs at 5n−4 RPM. Confirm this, and the upper limit (the infinite cycle goes to 24).

## How we got here

1. First idea: one hour at a fixed speed, and every ~5 min a burst at 200 fps that
   fills as much RAM as possible (16 GB machine; a 32 GB one is available).
2. The user then said 200 fps is overkill, and that a fixed burst length makes no
   sense across speeds (2 revs at 1 RPM takes 2 min). Considered next: 50 fps at
   1 RPM and 100 fps at ≥6 RPM. That gives uneven angular resolution (0.12°/frame at
   1 RPM vs 1.56°/frame at 26 RPM).
3. **Settled on 1 frame per degree**, so every speed has the same angular sampling.

## Decisions already made

- **Don't fill RAM until the machine runs out.** That causes swapping, dropped
  frames or the OOM killer. Burst size is now set by revs, and the largest burst
  is ~5 GB, which fits on the 16 GB machine.
- **Save lossless** (raw `.npy` or PNG/TIFF), not JPEG. The current
  `camera_feed_gui.py` saves JPEG, which is lossy and unsuitable for analysis.
- **The camera runs on its own clock** at `AcquisitionFrameRate = 6 × RPM`, not
  triggered by the motor, so frames are only approximately 1 per degree. Log a
  per-frame CSV: frame index, camera hardware timestamp, PC time, motor angle and
  RPM, so each frame can be mapped to its real angle and synced with the
  electrometer CSV. A hardware trigger from the ESP32 was considered and set
  aside: 25,600 steps/rev gives 71.1 steps/degree, which isn't a whole number.

## Open questions (ask the user)

1. **Run structure.** How does the per-speed burst fit into a run?
   - (a) One hour per speed, a burst every 5 min (13 bursts). Multiply that
     speed's row by 13; for example, an hour at 26 RPM at full res is ~65 GB.
   - (b) One pass through the ramp, one burst per speed (~17 GB at full res).
   - (c) Something else, such as the 1→24→1 `infinite_cycle_sequence` with a burst
     at each step.
   - If there are multiple bursts at a speed, should the bursts start at fixed
     times (t = 0, 5, 10 … min)? That was suggested and not yet confirmed.
2. **Camera model and resolution / ROI.** Unknown so far; `pypylon` is not in the
   system Python on the original machine (probably a venv). This sets the real
   GB per frame and whether 156 fps is possible at that resolution.
3. **Exposure.** At 156 fps exposure must be < ~6.4 ms. Gain is already 28 dB in
   `camera_feed_gui.py`, which suggests dim lighting. Will frames be bright enough?
   Motion blur in degrees is (6 × RPM) × exposure; at 26 RPM with 5 ms that is
   ~0.8°. Option: scale exposure with speed so blur stays constant, but brightness
   then changes and gain would need compensating. The default is fixed exposure
   unless the user wants scaling.
4. **More revs per speed?** RAM is no longer the limit, so more revs could be
   captured for better statistics.
5. **Separate script or a GUI mode?** Recommended: a "Burst Run" button in the
   existing GUI (see constraints below), with the live preview paused during each
   burst.

## Constraints from the existing code

- Only **one process can open the Basler camera**. `gui/camera_feed_gui.py`
  (`CameraGrabber`, which uses `GrabStrategy_LatestImageOnly`) holds it while the
  GUI runs. A burst mode either has to take over that grabber (stop it, change
  `AcquisitionFrameRate`, grab with `GrabStrategy_OneByOne` into a preallocated
  numpy array, then hand the camera back) or run as a standalone script without
  the GUI.
- `gui/motor_controls_gui.py` owns the **only serial connection** to the ESP32:
  motor commands via `send_command('S', sps)` / `send_command('X')`, and
  electrometer samples written to the CSV by `serial_listener_thread`.
  `sps = rpm / 60 × motor_state['spr']` (spr = 25600). Existing automated
  sequences to copy from: `auto_ramp_sequence`, `infinite_cycle_sequence`.
- Motor angle is in `motor_state['angle']`. Output directory is
  `file_state['CURRENT_DIR']`, set in `main.py` to `~/Desktop/<date_time>/`.
- Frames must finish writing to disk before the next burst (or before the next
  speed step, if that comes sooner). Preallocate the burst buffer and do the
  compression/saving in a separate thread or process pool so grabbing never stalls.

## Hardware notes

- Original machine: 16 GB RAM (~12 GB available), **~94 GB free disk** (90% full,
  on `/dev/sda2`, which may be an HDD; check write speed). A 32 GB machine is
  also available.
- Check free disk space before the run and refuse to start if the planned total
  won't fit.
