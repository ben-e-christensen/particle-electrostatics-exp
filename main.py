import tkinter as tk
import threading, time, os, signal, sys, atexit
from states import file_state
from gui.live_feed_gui import run_gui, update_plot
# from camera.camera_module import start_camera_loop
from BLE.client.ble_thread import start_ble_in_thread
from BLE.client.ble_plotter import stop_event


today = time.strftime("%Y-%m-%d_%H_%M", time.localtime())
save_dir = f"{file_state['BASE_DIR']}/{today}"
os.makedirs(save_dir, exist_ok=True)
file_state['CURRENT_DIR'] = save_dir

def _shutdown(*_):
    stop_event.set()
    time.sleep(0.2)
    sys.exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)
atexit.register(_shutdown)



def handle_ints(ints):
    print("-> received:", ints)   # replace with your logic


def main():
    # print("Starting camera thread...")
    # threading.Thread(target=start_camera_loop, daemon=True).start()

    print("Starting BLE thread...")
    csv_path = os.path.join(file_state['CURRENT_DIR'], "ble_samples.csv")
    start_ble_in_thread(csv_path=csv_path)


    
    # Run the GUI. The GUI module will handle creating the root
    # window and starting its own update loop.
    run_gui()

if __name__ == '__main__':
    main()
