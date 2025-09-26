"""
Motor GUI + Serial owner + Data queues for plotting

- Talks to ONE device (Feather V2 that runs both: motor control + BLE client).
- Owns the ONLY serial connection (no other file should open the port).
- Parses CSV data lines from device: "seq,ms,ch0,ch2,ch3".
- Publishes thread-safe queues:
    data_queue_a0  -> CH2 volts
    data_queue_a1  -> CH3 volts
- Still prints once/second BLE loss summaries from lines like:
    [BLE RX] 99.0% (rx=99, miss=1, exp=100)

Also logs every sample to experiment_log.csv with:
    index,timestamp,seq,ms,motor_angle_deg,CH0_volts,CH2_volts,CH3_volts
"""

import tkinter as tk
import serial, time, threading, re, csv, atexit, os
from datetime import datetime
from queue import Queue

# --- External modules (your project) ---
from helpers import update_tkinter_input_box
from states import motor_state, file_state

# ===== Config =====
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200

# ===== Public data queues (import these elsewhere) =====
data_queue_a0: Queue[float] = Queue(maxsize=2000)  # CH2 volts
data_queue_a1: Queue[float] = Queue(maxsize=2000)  # CH3 volts

# Optional: latest snapshot others can read without touching queues
latest = {"seq": 0, "ms": 0, "ch0": 0.0, "ch2": 0.0, "ch3": 0.0}

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

# --- ADC Conversion ---
def convert_to_voltage(raw, inputRange=4, vREF=4.096):
    ratio = raw / (1 << 14)
    if inputRange == 1:
        return ratio * 3 * vREF / 2 - 1.5 * vREF / 2
    elif inputRange == 2:
        return ratio * 3 * vREF / 2 - 3 * vREF / 2
    elif inputRange == 3:
        return ratio * 3 * vREF / 2
    elif inputRange == 4:
        return ratio * 3 * vREF - 1.5 * vREF
    elif inputRange == 5:
        return ratio * 3 * vREF - 3 * vREF
    elif inputRange == 6:
        return ratio * 3 * vREF
    elif inputRange == 7:
        return ratio * 6 * vREF - 3 * vREF
    return 0

# --- CSV Setup ---
import os, csv, atexit
from states import file_state   # make sure you import file_state

CSV_PATH = None
csv_file = None
csv_writer = None
csv_index = 0

def init_csv():
    global CSV_PATH, csv_file, csv_writer, csv_index
    # make base dir
    os.makedirs(file_state["CURRENT_DIR"], exist_ok=True)
    # make images subfolder too
    images_dir = os.path.join(file_state["CURRENT_DIR"], "images")
    os.makedirs(images_dir, exist_ok=True)

    CSV_PATH = os.path.join(file_state["CURRENT_DIR"], "experiment_log.csv")
    csv_file = open(CSV_PATH, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow([
        "index","timestamp","seq","ms","motor_angle_deg",
        "CH0_volts","CH2_volts","CH3_volts"
    ])
    csv_index = 0

def _close_csv():
    global csv_file
    if csv_file:
        csv_file.close()

atexit.register(_close_csv)


# --- Serial Connection Setup ---
try:
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
    time.sleep(2)  # Wait for serial port to initialize
    print(f"[i] Serial connection established on {SERIAL_PORT} @ {BAUD}.")
    print("[i] Expecting BLE summaries like: [BLE RX] 99.0% (rx=99, miss=1, exp=100)")
except serial.SerialException as e:
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
        except serial.SerialException as e:
            print(f"[!] Serial write error: {e}")
    else:
        print("Serial port not connected.")

# --- Serial Listener Thread ---
def serial_listener_thread():
    """
    Reads lines from the Feather and:
      - Parses CSV "seq,ms,ch0,ch2,ch3" -> converts to volts, updates queues, logs CSV.
      - Handles any legacy markers ("PROBE_LOW", "s") without spamming.
    """
    global degrees, latest, csv_index
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

            # 1) CSV sample line
            if ',' in line and not line.startswith('[') and not line.lower().startswith('seq'):
                parts = line.split(',')
                if len(parts) == 5:
                    try:
                        seq, ms, ch0_raw, ch2_raw, ch3_raw = map(int, parts)
                    except ValueError:
                        continue

                    # Convert to volts
                    ch0_v = convert_to_voltage(ch0_raw, inputRange=4)
                    ch2_v = convert_to_voltage(ch2_raw, inputRange=4)
                    ch3_v = convert_to_voltage(ch3_raw, inputRange=4)

                    # Update latest snapshot
                    latest.update({"seq": seq, "ms": ms,
                                   "ch0": ch0_v, "ch2": ch2_v, "ch3": ch3_v})

                    # Push CH2/CH3 to queues
                    _q_put_drop_oldest(data_queue_a0, ch2_v)
                    _q_put_drop_oldest(data_queue_a1, ch3_v)

                    # Motor angle (from motor_state)
                    motor_angle = motor_state.get("angle", 0.0)

                    # Write CSV row
                    ts = time.time()
                    csv_writer.writerow([
                        csv_index, ts, seq, ms, motor_angle, ch0_v, ch2_v, ch3_v
                    ])
                    csv_file.flush()
                    csv_index += 1
                    continue

            # 2) Handle markers
            if line == "PROBE_LOW":
                print("[EVENT] Probe activated!")
            elif line == "RUNNING":
                motor_state['running'] = True
            elif line == "STOP":
                motor_state['running'] = False
            else:
                if line:
                    print(f"[DEV] {line}")

        except serial.SerialException as e:
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
