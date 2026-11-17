# Burst Capture Run — Design Notes

Automated run mode: the motor spins at a fixed speed while the Basler camera takes
high-frame-rate image bursts into RAM, then writes them to disk losslessly.
First implementation landed 2026-11-16; **not yet tested on the real hardware**.

## What exists

| File | Role |
|---|---|
| `burst_capture.py` | Shared library: `revs_for_rpm`, `burst_plan`, `BurstCamera` (open, set fps, grab into a preallocated array), `save_burst` (PNG + `frames.csv` + `burst_info.json`), `check_disk_space`, `frame_stats`. |
| `gui/motor_controls_gui.py` | **"Burst Run" button** → `burst_run_sequence()`. Also now parses the bare-float angle lines from the ESP32 into `motor_state['angle']`. |
| `gui/camera_feed_gui.py` | `pause_live_feed()` / `resume_live_feed()` so a burst can borrow the camera. The grabber closes the camera on pause and reopens it on resume. |
| `burst_test.py` | Standalone camera-settings test (owns serial + camera; close the GUI first). |

## Decisions (all confirmed with the user)

- **Sampling: 1 frame per degree.** `fps = 6 × RPM`, 360 frames per rev.
- **Revs per burst** from this table, **rounded to the nearest RPM row**
  (so 13 RPM → 3 revs, 40 RPM → 6 revs):

| RPM | Revs | FPS | Duration | Frames | 1920×1200 Mono8 | 1280×1024 | 640×480 |
|---|---|---|---|---|---|---|---|
| 1  | 1 | 6   | 60.0 s | 360   | 0.83 GB | 0.47 GB | 0.11 GB |
| 6  | 2 | 36  | 20.0 s | 720   | 1.7 GB  | 0.94 GB | 0.22 GB |
| 11 | 3 | 66  | 16.4 s | 1,080 | 2.5 GB  | 1.4 GB  | 0.33 GB |
| 16 | 4 | 96  | 15.0 s | 1,440 | 3.3 GB  | 1.9 GB  | 0.44 GB |
| 21 | 5 | 126 | 14.3 s | 1,800 | 4.1 GB  | 2.4 GB  | 0.55 GB |
| 26 | 6 | 156 | 13.8 s | 2,160 | 5.0 GB  | 2.8 GB  | 0.66 GB |

- **Main run structure:** a button in the existing GUI. It uses **whatever RPM is in
  the GUI box**, runs the motor for **1 hour**, takes a burst **every 10 minutes**
  (t = 0, 10, …, 60 min → 7 bursts, after a 5 s settle), then stops the motor.
  Constants: `BURST_RUN_HOURS`, `BURST_INTERVAL_MIN`, `BURST_SETTLE_S` in
  `motor_controls_gui.py`. "Stop Motor" interrupts the run (and an in-progress burst).
- **Test script is standalone** (`burst_test.py`): steps through 1, 6, 11, 16, 21, 26
  RPM, 5 s settle each, **one full revolution per speed**, saves **150 evenly spaced
  frames per speed** plus `summary.csv` (achieved fps, block-id gaps, brightness
  mean/saturation, save time). Exposure/gain/ROI are CLI flags so it can be iterated
  to choose the settings for the real run. ~6 min total (dominated by the 60 s rev at 1 RPM).
- **Don't fill RAM.** Burst size is fixed by revs; the largest burst (~5 GB at full res)
  fits the 16 GB machine. The buffer is preallocated with `np.empty`.
- **Save lossless** PNG (`cv2.imwrite`, compression level 1) via a thread pool. Saving is
  synchronous in the sequence thread and must finish before the next burst (10 min apart,
  so plenty of slack). The electrometer CSV keeps logging throughout.
- **Camera free-runs** at `AcquisitionFrameRate = 6 × RPM`, no hardware trigger
  (25,600 steps/rev = 71.1 steps/degree, not a whole number). Each frame's row in
  `frames.csv` has: frame index, camera timestamp, block id, PC time, motor angle (and
  when that angle was last received), RPM. Sync with `experiment_log.csv` by PC time.
- **Disk check** before the run: refuses if free < 1.2 × (raw bytes of all planned bursts).
- Exposure: fixed. `BurstCamera.set_fps` clamps exposure to 90 % of the frame period if
  it is too long for the requested fps. Default exposure is the camera default (`EXPOSURE_US = None`
  in `burst_capture.py`); set it there once the test script shows what works.

## Output layout

```
<CURRENT_DIR>/bursts/burst_03_t030min_rpm6/
    frame_000000.png … frames.csv  burst_info.json
<BASE_DIR>/burst_test_<time>/rpm06/…  summary.csv  args.json
```

## Known gaps / things to verify on the hardware

- `pypylon` node access (`GetNodeMap().GetNode(...)`, `genicam.IsAvailable`,
  USB vs GigE names `AcquisitionFrameRate`/`...Abs`, `ExposureTime`/`...Abs`) was written
  from the pylon API docs and could not be run here (no camera, no pypylon on this PC).
  Run `burst_test.py --no-motor` first to shake this out.
- **Firmware angle mismatch:** `client/client.ino` computes the printed degrees with
  `stepsPerRev = 6400`, but Python sends speed using `spr = 25600`. If the driver really
  is at 25600 microsteps/rev the reported angle wraps 4× per revolution. Fix in firmware
  (or divide by 4) before trusting `motor_angle_deg`.
- Angle arrives only every 500 ms, so at 26 RPM it is ~78° stale at worst. Use camera
  timestamps + known RPM for fine angle; the logged angle is for coarse alignment.
- Camera model/resolution still unknown; `burst_test.py` prints them and whether 156 fps
  is reachable (`ResultingFrameRate` warning).
- Disk write speed on the original machine (`/dev/sda2`, possibly HDD) — `summary.csv`
  `save_s` column shows it.
- The 16 GB machine has ~12 GB available; the 5 GB burst plus the live-feed process is fine,
  but don't run two bursts' worth of buffers at once.

## Constraints from the existing code (unchanged)

- Only one process can open the camera; the live grabber must be paused (done automatically
  by `burst_run_sequence`). `burst_test.py` requires the GUI to be closed.
- `gui/motor_controls_gui.py` owns the only serial connection: `send_command('S', sps)` /
  `send_command('X')`, `sps = rpm / 60 × 25600`.
- Output directory is `file_state['CURRENT_DIR']` = `~/Desktop/<date_time>/`.
