# main.py
import time, os
from states import file_state

# Import the motor GUI (creates the Tk root and owns serial)
from gui.motor_controls_gui import root as motor_root, run_gui

# Import the live feed "attacher"
from gui.live_feed_gui import attach_live_feed

today = time.strftime("%Y-%m-%d_%H_%M", time.localtime())
save_dir = f"{file_state['BASE_DIR']}/{today}"
os.makedirs(save_dir, exist_ok=True)
file_state['CURRENT_DIR'] = save_dir

def main():
    print("Attaching live feed window…")
    attach_live_feed(parent=motor_root)  # create Toplevel for the live feed

    # Start the motor GUI mainloop (single Tk mainloop in main thread)
    run_gui()

if __name__ == '__main__':
    main()
