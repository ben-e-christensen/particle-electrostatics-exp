import threading, asyncio, time
from BLE.client.ble_plotter import run_ble_in_thread, stop_event, data_queue_a0, data_queue_a1
from gui.live_feed_gui import data_queue_a0, data_queue_a1

def _runner(csv_path):
    """
    This is the entry point for the background BLE thread.
    It runs the asyncio loop for BLE communication.
    """
    print("[Thread] Starting BLE runner...")
    run_ble_in_thread(csv_path)
    print("[Thread] BLE runner finished.")

def start_ble_in_thread(csv_path: str | None = None):
    """
    Starts the BLE communication in a separate daemon thread.
    Returns the Thread object.
    """
    t = threading.Thread(target=_runner, args=(csv_path,), daemon=True)
    t.start()
    return t
