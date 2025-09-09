#!/usr/bin/env python3
# flash.py — always erase+flash MicroPython, copy main.py, reset
import os, sys, subprocess, shutil, glob
# flash.py (snippet)

# source micropython-tools/bin/activate


TOOLS = os.path.expanduser("~/micropython-tools/bin")
ESPTOOL = os.path.join(TOOLS, "esptool.py")
MPREMOTE = os.path.join(TOOLS, "mpremote")

PORT = None  # set to "/dev/ttyUSB0" to skip auto-detect
BAUD = "460800"
FIRMWARE_BIN = "esp32-firmware.bin"  # must be in the same folder
MAIN_PY = "main.py"                  # must be in the same folder

def which_or_die(cmd, pip_hint=None):
    if shutil.which(cmd) is None:
        print(f"[!] Required tool not found: {cmd}")
        if pip_hint:
            print(f"    Install with: sudo pip3 install {pip_hint}")
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
    which_or_die("esptool.py", "esptool")
    which_or_die("mpremote", "mpremote")

    base = os.path.dirname(os.path.abspath(__file__))
    fw_path = os.path.join(base, FIRMWARE_BIN)
    main_path = os.path.join(base, MAIN_PY)

    if not os.path.isfile(fw_path):
        print(f"[!] Firmware not found: {fw_path}")
        sys.exit(1)
    if not os.path.isfile(main_path):
        print(f"[!] Script not found: {main_path}")
        sys.exit(1)

    port = PORT or autodetect_port()
    if not port:
        print("[!] Could not auto-detect serial port. Plug the board in or set PORT.")
        sys.exit(1)
    print(f"[i] Using port: {port}")

    print("[i] Put the ESP32 in ROM bootloader (hold BOOT, tap EN/RESET).")
    run(["esptool.py", "--port", port, "--baud", BAUD, "erase_flash"])
    run(["esptool.py", "--port", port, "--baud", BAUD, "write_flash", "-z", "0x1000", fw_path])
    print("[✓] Firmware flashed.")

    print(f"[i] Copying {MAIN_PY} -> /main.py")
    # switch to normal mode: just press EN/RESET once if needed
    run(["mpremote", "connect", port, "fs", "cp", main_path, ":/main.py"])
    print("[✓] Script copied.")

    print("[i] Resetting board…")
    run(["mpremote", "connect", port, "reset"])
    print("[✓] Done.")

if __name__ == "__main__":
    main()
