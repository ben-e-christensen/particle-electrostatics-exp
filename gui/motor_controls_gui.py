import tkinter as tk
import serial
import time
import threading

# Import your modules
from helpers import update_tkinter_input_box
from states import motor_state

global degrees 

# --- Serial Connection Setup ---
try:
    ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
    time.sleep(2)  # Wait for serial port to initialize
    print("Serial connection established.")
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
        
        ser.write(message)
    else:
        print("Serial port not connected.")

# --- Serial Listener Thread ---
def serial_listener_thread():
    if ser:
        print("Starting serial listener thread.")
        while True:
            try:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8').strip()
                    print(f"Received from Arduino: {line}")
                    if line == "PROBE_LOW":
                        print("Probe activated!")
                    elif line == "s":
                        global degrees 
                        degrees += 360 / motor_state['spr']
                        print(degrees)
            except serial.SerialException as e:
                print(f"Serial error: {e}")
                break
            except Exception as e:
                print(f"Error reading serial line: {e}")
            time.sleep(0.01)

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
        return 0
        
    motor_state['rpm'] = current_rpm
    
    sps = (current_rpm / 60) * motor_state['spr']
    return sps

def update_gui_state():
    """Updates the GUI with the current motor state."""
    try:
        current_rpm = float(freq.get())
    except ValueError:
        current_rpm = motor_state['rpm']
    
    motor_state['rpm'] = current_rpm
    
    sps = (current_rpm / 60) * motor_state['spr']
    dps = (current_rpm / 60) * 360
    
    result_label.config(text=f"Steps Per Second: {sps:.2f}\nDegrees Per Second: {dps:.2f}")

def adjust_speed(direction):
    """Adjusts the RPM in the GUI and sends the new speed to the Arduino."""
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
    
    freq.delete(0, tk.END)
    freq.insert(0, str(new_rpm))
    
    # Calculate the new SPS and send it to the Arduino
    new_sps = (new_rpm / 60) * motor_state['spr']
    send_command('S', int(new_sps))
    
    update_gui_state()

def start_motor():
    """Starts the motor using the current speed from the GUI."""
    sps_value = calculate_speed_sps()
    motor_state['running'] = True
    send_command('S', int(sps_value))

def stop_motor():
    """Sends a stop command to the Arduino."""
    motor_state['running'] = False
    send_command('X')

def reverse_direction():
    """Sends a toggle direction command to the Arduino."""
    send_command('T')

def find_origin():
    """Command to go directly below a sensor"""
    print('running find origin')
    send_command('L')

def handle_enter(event=None):
    """Updates the GUI state and sends the speed when 'Enter' is pressed."""
    sps_value = calculate_speed_sps()
    send_command('S', int(sps_value))
    update_gui_state()

# --- GUI Creation ---
root = tk.Tk()
root.title("Motor Control & Angle Tracker")
root.lift()
root.attributes('-topmost', True)
root.after(100, lambda: root.attributes('-topmost', False))

# GUI state variables
inc_val = tk.StringVar(value="1")
checkbox_val = tk.IntVar()

# Define widgets
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
input_button = tk.Button(root, text="Get Input", command=handle_enter)

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
    print('running run_gui')
    root.mainloop()

if __name__ == '__main__':
    run_gui()