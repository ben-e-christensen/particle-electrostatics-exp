import time, os
from states import file_state

# Motor GUI (creates Tk root and owns serial)
from gui.motor_controls_gui import root as motor_root, run_gui

# Option A: sensor plots and camera in seperate windows
from gui.live_feed_gui import attach_live_feed
from gui.camera_feed_gui import attach_camera_feed

# Option B: camera + plots in one window
from gui import motor_controls_gui

today = time.strftime("%Y-%m-%d_%H_%M", time.localtime())
save_dir = f"{file_state['BASE_DIR']}/{today}"
os.makedirs(save_dir, exist_ok=True)
file_state['CURRENT_DIR'] = save_dir

# now init CSV in motor_controls_gui

motor_controls_gui.init_csv()

def main():
    print("Launching application…")

    # Pick ONE of these attach calls (or both, if you want multiple windows):

    attach_live_feed(parent=motor_root)      # ← plots-only
    attach_camera_feed(parent=motor_root)
    # attach_unified_feed(parent=motor_root)     # ← unified camera + plots

    # Start the motor GUI mainloop (single Tk mainloop in main thread)
    run_gui()


if __name__ == '__main__':
    main()
