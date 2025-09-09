#!/usr/bin/env python3
# deploy.py — copy main.py to ESP32 and reset (no firmware flash)

# source micropython-tools/bin/activate

import os, sys, subprocess, glob, shutil

PORT = None  # set to "/dev/ttyUSB0" if you want fixed port
MAIN_PY = "main.py"

def which_or_die(cmd, pip_hint=None):
    if shutil.which(cmd) is None:
        print(f"[!] Required tool not found: {cmd}")
        if pip_hint:
            print(f"    Install with: pip install {pip_hint}")
        sys.exit(1)

def autodetect_port():
    cands = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    return cands[0] if cands else None

def run(cmd):
    print("$", " ".join(cmd))
    res = subprocess.run(cmd)
    if res.returncode != 0:
        sys.exit(res.returncode)

def main():
    which_or_die("mpremote", "mpremote")

    base = os.path.dirname(os.path.abspath(__file__))
    main_path = os.path.join(base, MAIN_PY)

    if not os.path.isfile(main_path):
        print(f"[!] Script not found: {main_path}")
        sys.exit(1)

    port = PORT or autodetect_port()
    if not port:
        print("[!] Could not auto-detect serial port. Plug the board in or set PORT.")
        sys.exit(1)

    print(f"[i] Using port: {port}")
    print(f"[i] Copying {MAIN_PY} -> /main.py")
    run(["mpremote", "connect", port, "fs", "cp", main_path, ":/main.py"])

    print("[i] Resetting board…")
    run(["mpremote", "connect", port, "reset"])
    print("[✓] Done.")

if __name__ == "__main__":
    main()
