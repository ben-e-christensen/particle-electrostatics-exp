# motor_controls_gui.py
"""
Motor GUI + Serial owner + Data queues for plotting

- Talks to ONE device (Feather V2 that runs both: motor control + BLE client).
- Owns the ONLY serial connection (no other file should open the port).
- Parses CSV data lines from device: "seq,ms,a26,a25".
- Publishes thread-safe queues:
    data_queue_a0  -> a26 (GPIO26)
    data_queue_a1  -> a25 (GPIO25)
- Still prints once/second BLE loss summaries from lines like:
    [BLE RX] 99.0% (rx=99, miss=1, exp=100)

Other modules can:
    from motor_controls_gui import data_queue_a0, data_queue_a1
and consume the live stream without opening serial again.
"""

import tkinter as tk
import printing
import time
import threading
import re
from datetime import datetime
from queue import Queue

# --- External modules (your project) ---
from helpers import update_tkinter_input_box
from states import motor_state

# ===== Config =====
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200

# ===== Public data queues (import these elsewhere) =====
# a0 == GPIO26 (A26), a1 == GPIO25 (A25)
data_queue_a0: Queue[int] = Queue(maxsize=2000)
data_queue_a1: Queue[int] = Queue(maxsize=2000)

# Optional: latest snapshot others can read without touching queues
latest = {"seq": 0, "ms": 0, "a26": 0, "a25": 0}

def _q_put_drop_oldest(q: Queue, item):
    """Non-blocking put; if full, drop one oldest item then insert."""
    try:
        q.put_nowait(item)
    except:
        try:
            q.get_nowait()
        except:
            pass
        try:
            q.put_nowait(item)
        except:
            pass

# Regex for BLE summary lines
BLE_LINE_RE = re.compile(
    r"\[BLE RX\]\s+([\d\.]+)%\s+\(rx=(\d+),\s+miss=(\d+),\s+exp=(\d+)\)"
)

# Track degrees if you use 's' markers
degrees = 0.0

# --- Serial Connection Setup ---
try:
    ser = printing.Serial(SERIAL_PORT, BAUD, timeout=1)
    time.sleep(2)  # Wait for serial port to initialize
    print(f"[i] Serial connection established on {SERIAL_PORT} @ {BAUD}.")
    print("[i] Expecting BLE summaries like: [BLE RX] 99.0% (rx=99, miss=1, exp=100)")
except printing.SerialException as e:
    print(f"Error opening serial port: {e}")
    ser = None

# --- Serial Command Functions ---
def send_command(command, value=None):
    if ser:
        if value is not None:
            message = f"{command}{value}\n".encode()
        else:
            message = f"{command}\n".encode()
        try:
            ser.write(message)
        except printing.SerialException as e:
            print(f"[!] Serial write error: {e}")
    else:
        print("Serial port not connected.")

# --- Serial Listener Thread ---
def serial_listener_thread():
    """
    Reads lines from the Feather and:
      - Parses BLE summary lines -> prints concise status once per second.
      - Parses CSV "seq,ms,a26,a25" -> pushes a26/a25 into queues, updates 'latest'.
      - Handles any legacy markers ("PROBE_LOW", "s") without spamming.
    """
    global degrees, latest
    if not ser:
        return
    print("[i] Starting serial listener thread.")
    while True:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            # # 1) BLE summary line
            # GOOD ERROR HANDLING AT SOME POINT, BUT DONT NEED RIGHT NOW
            # m = BLE_LINE_RE.search(line)
            # if m:
            #     pct, rx, miss, exp = m.groups()
            #     ts = datetime.now().isoformat(timespec="seconds")
            #     print(f"[{ts}] [BLE] SUCCESS={float(pct):5.1f}%  RX={int(rx):3d}  "
            #           f"MISS={int(miss):3d}  EXP={int(exp):3d}")
            #     continue

            # 2) CSV sample line: seq,ms,a26,a25
            #    (Ignore non-CSV lines like headers, probe prints, etc.)
            if ',' in line and not line.startswith('[') and not line.lower().startswith('seq'):
                parts = line.split(',')
                if len(parts) == 4:
                    try:
                        seq = int(parts[0], 10)
                        ms  = int(parts[1], 10)
                        a26 = int(parts[2], 10)
                        a25 = int(parts[3], 10)
                    except ValueError:
                        # Not a clean CSV line; skip
                        pass
                    else:
                        latest = {"seq": seq, "ms": ms, "a26": a26, "a25": a25}
                        _q_put_drop_oldest(data_queue_a0, a26)
                        _q_put_drop_oldest(data_queue_a1, a25)
                        # No per-sample printing to keep console quiet
                        continue

            # 3) Handle your existing markers (quietly)
            if line == "PROBE_LOW":
                print("[EVENT] Probe activated!")
            elif line == "RUNNING":
                motor_state['running'] = True
            elif line == "STOP":
                motor_state['running'] = False
            else:
                # Occasional device prints show up here (keep minimal)
                if line:  # comment this block out for total silence
                    print(f"[DEV] {line}")

        except printing.SerialException as e:
            print(f"[!] Serial error: {e}")
            break
        except Exception as e:
            print(f"[!] Error reading serial line: {e}")
        time.sleep(0.005)

if ser:
    listener_thread = threading.Thread(target=serial_listener_thread, daemon=True)
    listener_thread.start()

# --- Motor Control Functions ---
def calculate_speed_sps():
    """Calculates SPS from the current RPM in the GUI."""
    try:
        current_rpm = float(freq.get())
    except ValueError:
        print("Invalid RPM value. Please enter a number.")
        return 0.0
    motor_state['rpm'] = current_rpm
    sps = (current_rpm / 60.0) * motor_state['spr']
    return sps

def update_gui_state():
    """Updates the GUI with the current motor state."""
    try:
        current_rpm = float(freq.get())
    except ValueError:
        current_rpm = motor_state['rpm']
    motor_state['rpm'] = current_rpm
    sps = (current_rpm / 60.0) * motor_state['spr']
    dps = (current_rpm / 60.0) * 360.0
    result_label.config(text=f"Steps Per Second: {sps:.2f}\nDegrees Per Second: {dps:.2f}")

def adjust_speed(direction):
    """Adjusts the RPM in the GUI and sends the new speed to the device."""
    try:
        current_rpm = float(freq.get())
        inc = float(inc_val.get())
    except ValueError:
        print("Invalid speed or incremental value.")
        return

    if direction == 'u':
        new_rpm = current_rpm + inc
    elif direction == 'd':
        new_rpm = current_rpm - inc
    else:
        new_rpm = current_rpm

    freq.delete(0, tk.END)
    freq.insert(0, str(new_rpm))

    new_sps = (new_rpm / 60.0) * motor_state['spr']
    send_command('S', int(new_sps))
    update_gui_state()

def start_motor():
    sps_value = calculate_speed_sps()
    motor_state['running'] = True
    send_command('S', int(sps_value))

def stop_motor():
    motor_state['running'] = False
    send_command('X')

def reverse_direction():
    send_command('T')

def find_origin():
    print('[i] Running find origin')
    send_command('L')

def handle_enter(event=None):
    sps_value = calculate_speed_sps()
    send_command('S', int(sps_value))
    update_gui_state()

# --- GUI Creation ---
root = tk.Tk()
root.title("Motor Control & BLE Monitor")
root.lift()
root.attributes('-topmost', True)
root.after(100, lambda: root.attributes('-topmost', False))

# GUI state variables
inc_val = tk.StringVar(value="1")
checkbox_val = tk.IntVar()

# Widgets
result_label = tk.Label(root, text="")
start_button = tk.Button(root, text="Start Motor", command=start_motor)
stop_button = tk.Button(root, text="Stop Motor", command=stop_motor)
reverse_button = tk.Button(root, text="Reverse", command=reverse_direction)
speed_up_button = tk.Button(root, text="Speed Up", command=lambda: adjust_speed('u'))
slow_down_button = tk.Button(root, text="Slow Down", command=lambda: adjust_speed('d'))
homing_button = tk.Button(root, text="Find Origin", command=find_origin)
inc_label = tk.Label(root, text="Incremental value for speed adjustments (in revs per minute)")
inc = tk.Spinbox(root, from_=0, to=10, increment=0.25, textvariable=inc_val)
freq_label = tk.Label(root, text="Enter frequency (in revolutions per minute):")
freq = tk.Entry(root, width=30)
revs_label = tk.Label(root, text="Enter total revolutions:")
total_revs = tk.Entry(root, width=30)
checkbox = tk.Checkbutton(root, text="Run motor until stopped", variable=checkbox_val, onvalue=1, offvalue=0)
input_button = tk.Button(root, text="Apply Speed", command=handle_enter)

# Set initial values for entry widgets
update_tkinter_input_box(freq, motor_state['rpm'])
update_tkinter_input_box(total_revs, motor_state['revs'])
update_gui_state()

# Pack widgets
for w in [start_button, stop_button, reverse_button, speed_up_button,
          slow_down_button, homing_button,
          inc_label, inc, freq_label, freq, revs_label, total_revs,
          checkbox, input_button, result_label]:
    w.pack(pady=5)

# Bind keys to functions
root.bind("<Return>", handle_enter)
root.bind("<KP_Enter>", handle_enter)

def run_gui():
    print('[i] Running GUI…')
    root.mainloop()

if __name__ == '__main__':
    run_gui()
