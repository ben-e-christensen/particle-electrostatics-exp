# state.py
from threading import Lock
# Corrected motor_state definition
spr = 25600  # steps per revolution
rpm = 1  # revolutions per minute
rps = rpm / 60  # revolutions per second
sps = rps * spr  # steps per second

motor_state = {
    'spr': 25600,
    'rpm': 1, # Use rpm directly as it's the user-facing value
    'revs': 3,
    'total_steps': 25600 * 3,
    'running': False,
}

file_state = {
    "BASE_DIR": "/media/ben/SANDISK/particle-electrostatics-exp",
    "CURRENT_DIR": "",
    "index": -1
}

ellipse_state = {
    "angle_deg": None,
    "area_px2": None
}

state_lock = Lock()

location_state = {
    'flag': False,
    'pin_count': 0,
    'tracked_revs': 0,
    'last_reading': False,
    'a0_angle': 0,
    'a1_angle': 0,
}

frame_state = {
    'name': '',
}