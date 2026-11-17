#!/usr/bin/env python3
"""
Burst capture TEST — standalone camera-settings check.

Steps through a list of speeds, holds each briefly, captures ONE full
revolution at 1 frame per degree (fps = 6 x RPM), and saves an evenly spaced
subset of frames (default 150) per speed plus brightness/frame-rate stats.
Use it to pick exposure, gain and ROI before a real Burst Run.

Runs standalone: it owns the serial port AND the camera, so close main.py
(the GUI) and pylon Viewer first.

Examples:
    python burst_test.py
    python burst_test.py --exposure-us 4000 --gain 20
    python burst_test.py --speeds 6 16 26 --settle 3 --roi 1280 1024
    python burst_test.py --no-motor          # camera only, speeds still set fps

Output: <BASE_DIR>/burst_test_<date_time>/
    rpm01/frame_000000.png ...  frames.csv  burst_info.json
    rpm06/...
    summary.csv                 one row per speed
"""

import argparse, os, sys, time, csv, threading, json

import numpy as np
import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import burst_capture as bc
from states import file_state, motor_state


# ------------------------------------------------------------ motor ----

class Motor:
    """Minimal owner of the ESP32 serial link: speed commands + angle readback."""

    def __init__(self, port, baud=115200):
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)
        self.angle = None
        self.angle_time = None
        self._stop = threading.Event()
        threading.Thread(target=self._listen, daemon=True).start()
        print(f"[test] Serial open on {port}")

    def _listen(self):
        while not self._stop.is_set():
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            except serial.SerialException as e:
                print(f"[test] Serial error: {e}")
                return
            if not line or line.startswith("[") or "," in line:
                continue
            try:
                self.angle = float(line)       # firmware prints degrees every 500 ms
                self.angle_time = time.time()
            except ValueError:
                pass

    def set_rpm(self, rpm):
        sps = (rpm / 60.0) * motor_state["spr"]
        self.ser.write(f"S{int(sps)}\n".encode())

    def stop(self):
        try:
            self.ser.write(b"X\n")
        except Exception:
            pass

    def close(self):
        self.stop()
        self._stop.set()
        self.ser.close()


class NoMotor:
    angle = None
    angle_time = None
    def set_rpm(self, rpm): print(f"[test] (no motor) would set {rpm} RPM")
    def stop(self): pass
    def close(self): pass


# ------------------------------------------------------------- main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speeds", type=float, nargs="+", default=[1, 6, 11, 16, 21, 26],
                    help="RPM values to step through (default: 1 6 11 16 21 26)")
    ap.add_argument("--revs", type=float, default=1.0, help="revolutions per burst (default 1)")
    ap.add_argument("--save-frames", type=int, default=150, help="frames saved per speed (default 150)")
    ap.add_argument("--settle", type=float, default=5.0, help="seconds to hold speed before burst")
    ap.add_argument("--exposure-us", type=float, default=bc.EXPOSURE_US, help="exposure time in microseconds")
    ap.add_argument("--gain", type=float, default=bc.GAIN_DB, help="gain in dB (default 28)")
    ap.add_argument("--roi", type=int, nargs=2, metavar=("W", "H"), default=bc.ROI, help="ROI width height")
    ap.add_argument("--port", default="/dev/ttyACM0", help="ESP32 serial port")
    ap.add_argument("--no-motor", action="store_true", help="skip the motor; camera only")
    ap.add_argument("--out", default=None, help="output directory (default: BASE_DIR/burst_test_<time>)")
    args = ap.parse_args()

    out_root = args.out or os.path.join(
        file_state["BASE_DIR"], "burst_test_" + time.strftime("%Y-%m-%d_%H_%M"))
    os.makedirs(out_root, exist_ok=True)

    # --- plan & disk check ---
    plans = [bc.burst_plan(rpm, revs=args.revs) for rpm in args.speeds]
    total_s = sum(p["duration_s"] + args.settle for p in plans)
    print(f"[test] {len(plans)} speeds, ~{total_s/60:.1f} min of motor time, output -> {out_root}")
    for p in plans:
        print(f"[test]   {p['rpm']:>5g} RPM  {p['fps']:>6.1f} fps  {p['n_frames']} frames  {p['duration_s']:.1f}s")

    # --- motor ---
    if args.no_motor:
        motor = NoMotor()
    else:
        try:
            motor = Motor(args.port)
        except serial.SerialException as e:
            print(f"[test] Could not open serial port {args.port}: {e}")
            print("[test] Use --no-motor to test the camera alone, or --port to pick another port.")
            return 1

    summary_rows = []
    current = {"rpm": 0.0}

    def meta_fn():
        return {"motor_angle_deg": "" if motor.angle is None else motor.angle,
                "motor_angle_time": "" if motor.angle_time is None else motor.angle_time,
                "rpm": current["rpm"]}

    try:
        with bc.BurstCamera(gain_db=args.gain, exposure_us=args.exposure_us,
                            roi=tuple(args.roi) if args.roi else None) as cam:
            settings = cam.current_settings()
            print(f"[test] Camera settings: {settings}")
            largest = max(p["n_frames"] for p in plans) * cam.bytes_per_frame()
            print(f"[test] Largest burst buffer: {largest/1e9:.2f} GB RAM")
            ok, free = bc.check_disk_space(out_root, args.save_frames * len(plans) * cam.bytes_per_frame())
            if not ok:
                print(f"[test] Not enough disk space ({free/1e9:.1f} GB free).")
                return 1

            for p in plans:
                rpm = p["rpm"]
                current["rpm"] = rpm
                out_dir = os.path.join(out_root, f"rpm{rpm:02g}")
                print(f"\n[test] === {rpm} RPM: settling {args.settle}s ===")
                motor.set_rpm(rpm)
                time.sleep(args.settle)

                t_cap = time.time()
                frames, meta = cam.capture_burst(p["fps"], p["n_frames"], meta_fn=meta_fn)
                cap_s = time.time() - t_cap
                n = len(frames)
                if n == 0:
                    print("[test] No frames captured; skipping save.")
                    continue

                achieved_fps = ((n - 1) / (meta[-1]["pc_time"] - meta[0]["pc_time"])) if n > 1 else 0.0
                # camera clock: ticks between first/last frame (units are camera-specific)
                cam_ticks = meta[-1]["cam_timestamp"] - meta[0]["cam_timestamp"]
                # frames the camera skipped show up as gaps in block id
                block_gaps = int((meta[-1]["block_id"] - meta[0]["block_id"]) - (n - 1))

                idx = np.unique(np.linspace(0, n - 1, min(args.save_frames, n)).round().astype(int))
                info = {"plan": p, "camera": cam.current_settings(),
                        "achieved_fps": achieved_fps, "capture_seconds": cap_s,
                        "block_id_gaps": block_gaps, "cam_ticks_first_to_last": cam_ticks}
                save_s = bc.save_burst(frames, meta, out_dir, info, indices=idx)
                stats = bc.frame_stats(frames)
                del frames

                row = {"rpm": rpm, "requested_fps": p["fps"], "achieved_fps": round(achieved_fps, 2),
                       "frames_captured": n, "frames_planned": p["n_frames"],
                       "block_id_gaps": block_gaps, "capture_s": round(cap_s, 2),
                       "save_s": round(save_s, 2), "frames_saved": len(idx),
                       "exposure_us": info["camera"]["exposure_us"], "gain": info["camera"]["gain"],
                       **{f"brightness_{k}": round(v, 2) for k, v in stats.items()}}
                summary_rows.append(row)
                print(f"[test] {rpm} RPM done: achieved {achieved_fps:.1f} fps "
                      f"(wanted {p['fps']:.1f}), mean brightness {stats['mean']:.1f}, "
                      f"saturated {stats['pct_saturated']:.2f}%, gaps {block_gaps}")
    finally:
        motor.close()

    if summary_rows:
        path = os.path.join(out_root, "summary.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            w.writeheader()
            w.writerows(summary_rows)
        with open(os.path.join(out_root, "args.json"), "w") as f:
            json.dump(vars(args), f, indent=2)
        print(f"\n[test] Summary written to {path}")
        print(f"{'rpm':>5} {'want':>7} {'got fps':>8} {'gaps':>5} {'mean':>6} {'sat%':>6} {'save s':>7}")
        for r in summary_rows:
            print(f"{r['rpm']:>5g} {r['requested_fps']:>7.1f} {r['achieved_fps']:>8.1f} "
                  f"{r['block_id_gaps']:>5} {r['brightness_mean']:>6.1f} "
                  f"{r['brightness_pct_saturated']:>6.2f} {r['save_s']:>7.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
