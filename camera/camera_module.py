import cv2
import numpy as np
from picamera2 import Picamera2
from PIL import Image
import time
import os
import threading
import queue
from datetime import datetime
from states import file_state, blob_state, location_state
from gui.gui_module import video_queue
from gpiozero import InputDevice
running_signal = InputDevice(16)




# --- Global Shared State & Threading Primitives ---
# This dictionary will hold data shared between threads
shared_data = {
    "original_frame": None,
    "raw_roi_frame": None,      # Raw ROI for drawing in the consumer thread
    "contour_to_draw": None,    # Data needed for visualization
    "ellipse_to_draw": None,    # ...
    "center_to_draw": None,     # ...
}
# A queue to hold frames that need to be saved to disk
save_queue = queue.Queue()
# A lock to ensure thread-safe access to shared_data
data_lock = threading.Lock()
# An event to signal all threads to stop gracefully
stop_event = threading.Event()
# An event to synchronize the producer (tracking) and consumer (recording) threads
frame_ready_event = threading.Event()


# --- Directory Setup ---
today = time.strftime("%Y-%m-%d_%H_%M", time.localtime())
save_dir_base = f"{file_state['BASE_DIR']}/{today}"
os.makedirs(save_dir_base, exist_ok=True)
file_state['CURRENT_DIR'] = save_dir_base

image_save_dir = f"{file_state['CURRENT_DIR']}/images"
os.makedirs(image_save_dir, exist_ok=True)


# --- Image Processing Utilities ---
def apply_circular_mask(gray_img):
    """Applies a circular mask to the center of the image."""
    h, w = gray_img.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    center = (w // 2, h // 2)
    radius = min(center[0], center[1], w - center[0], h - center[1])
    cv2.circle(mask, center, radius, 255, -1)
    masked = cv2.bitwise_and(gray_img, gray_img, mask=mask)
    return masked, mask

def smooth_angle(new_angle, history, N=10):
    """Smooths an angle value over the last N readings."""
    history.append(new_angle)
    if len(history) > N:
        history.pop(0)
    return sum(history) / len(history)


# --- Thread 1: Lean Ellipse Tracking (60Hz) ---
def ellipse_tracking_loop(picam2, roi, stop_event_flag, frame_event):
    """
    Captures frames and calculates ellipse data. Does NO drawing.
    This is the lean "producer" thread.
    """
    x, y, w, h = roi
    angle_history = []
    
    print("Ellipse tracking thread started.")
    while not stop_event_flag.is_set():
        loop_start_time = time.time()

        full_frame = picam2.capture_array()
        roi_frame = full_frame[y:y + h, x:x + w]

        # --- Image processing is now ACTIVE for data calculation ---
        gray = cv2.cvtColor(roi_frame, cv2.COLOR_RGB2GRAY)
        masked_gray, _ = apply_circular_mask(gray)
        _, binary = cv2.threshold(masked_gray, 125, 75, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Drawing data is kept as None so the GUI thread doesn't draw it
        contour_to_draw, ellipse_to_draw, center_to_draw = None, None, None

        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            # contour_to_draw = largest_contour # This remains commented out
            
            blob_state['area'] = cv2.contourArea(largest_contour)
            
            # --- Center calculation (using moments) is now commented out ---
            # M = cv2.moments(largest_contour)
            # if M["m00"] != 0:
            #     cx = int(M["m10"] / M["m00"])
            #     cy = int(M["m01"] / M["m00"])
            #     blob_state['center'] = [cx, cy]
            #     # center_to_draw = (cx, cy) # This remains commented out
            # --- End of center calculation block ---

            if len(largest_contour) >= 5:
                ellipse = cv2.fitEllipse(largest_contour)
                if ellipse[1][0] > 0 and ellipse[1][1] > 0:
                    smoothed_angle = smooth_angle(ellipse[2], angle_history)
                    # ANGLE CALCULATION IS NOW ACTIVE
                    blob_state['angle'] = smoothed_angle
                    # ellipse_to_draw = ellipse # This remains commented out
        
        # --- End of processing block ---

        with data_lock:
            shared_data["original_frame"] = full_frame
            shared_data["raw_roi_frame"] = roi_frame
            shared_data["contour_to_draw"] = contour_to_draw
            shared_data["ellipse_to_draw"] = ellipse_to_draw
            shared_data["center_to_draw"] = center_to_draw
        
        frame_event.set()

        elapsed_time = time.time() - loop_start_time
        sleep_duration = max(0, (1/60) - elapsed_time)
        time.sleep(sleep_duration)
    
    print("Ellipse tracking thread finished.")


# --- Thread 2: GUI Updates, Drawing & Save Dispatch ---
def recording_gui_loop(save_path, running_pin, stop_event_flag, frame_event):
    """
    Waits for new data, performs drawing operations for the GUI,
    and dispatches the original frame to the save queue.
    """
    frame_counter = -1
    print("Recording/GUI thread started.")

    while not stop_event_flag.is_set():
        frame_event.wait() 
        if stop_event_flag.is_set(): break

        with data_lock:
            is_recording = running_pin.is_active
            frame_to_save = shared_data.get("original_frame")
            raw_roi_frame = shared_data.get("raw_roi_frame")
            contour = shared_data.get("contour_to_draw")
            ellipse = shared_data.get("ellipse_to_draw")
            center = shared_data.get("center_to_draw")
            frame_event.clear()

        # --- Perform Drawing Here, Offloading from Tracking Thread ---
        if raw_roi_frame is not None:
            # Convert to BGR for OpenCV drawing functions
            roi_bgr = cv2.cvtColor(raw_roi_frame, cv2.COLOR_RGB2BGR)
            
            # NOTE: Drawing is skipped automatically when contour, ellipse, etc. are None
            if contour is not None:
                cv2.drawContours(roi_bgr, [contour], -1, (0, 0, 255), 2)
            if ellipse is not None:
                cv2.ellipse(roi_bgr, ellipse, (255, 0, 255), 2)
            if center is not None:
                cv2.circle(roi_bgr, center, 5, (255, 255, 255), -1)

            # Convert back to RGB for PIL and send to GUI
            pil_img = Image.fromarray(cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB))
            try:
                while not video_queue.empty():
                    video_queue.get_nowait()
                video_queue.put_nowait(pil_img)
            except (queue.Full, queue.Empty):
                pass

        # --- Dispatch Original, Un-drawn Frame for Saving ---
        if is_recording and frame_to_save is not None and location_state['flag']:
            frame_counter += 1
            now = datetime.now()
            formatted_time = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{now.microsecond // 1000:03d}"
            img_name = f"frame_{frame_counter:04d}_{formatted_time}.jpg"
            filename = os.path.join(save_path, img_name)
            
            frame_bgr = cv2.cvtColor(frame_to_save, cv2.COLOR_RGB2BGR)
            save_queue.put((filename, frame_bgr))
        
    print("Recording/GUI thread finished.")

# --- Thread 3: Asynchronous Save Worker ---
def save_worker(stop_event_flag):
    """
    A dedicated thread that pulls frames from a queue and saves them to disk.
    """
    print("Save worker thread started.")
    while not stop_event_flag.is_set() or not save_queue.empty():
        try:
            filename, frame_bgr = save_queue.get(timeout=1)
            cv2.imwrite(filename, frame_bgr)
            save_queue.task_done()
        except queue.Empty:
            continue
    print("Save worker thread finished.")


# --- Main Application Logic ---
def start_camera_loop():
    """
    Initializes the camera, sets up the ROI, and starts all processing threads.
    """
    picam2 = Picamera2()
    config = picam2.create_video_configuration(
        main={"size": (1280, 720), "format": "RGB888"},
        controls={"FrameRate": 60, "AnalogueGain": 8.0, "ExposureTime": 10000}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(1)

    frame = picam2.capture_array()
    roi = cv2.selectROI("Select Top of Drum", frame, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Select Top of Drum")
    if not any(roi):
        print("No ROI selected. Exiting.")
        picam2.stop()
        return

    # --- Create and Start All Threads ---
    tracking_thread = threading.Thread(
        target=ellipse_tracking_loop, 
        args=(picam2, roi, stop_event, frame_ready_event)
    )
    recording_thread = threading.Thread(
        target=recording_gui_loop, 
        args=(image_save_dir, running_signal, stop_event, frame_ready_event)
    )
    save_thread = threading.Thread(
        target=save_worker,
        args=(stop_event,)
    )
    
    tracking_thread.start()
    recording_thread.start()
    save_thread.start()

    try:
        while all(t.is_alive() for t in [tracking_thread, recording_thread, save_thread]):
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutdown signal received. Stopping threads...")
    finally:
        # --- Graceful Shutdown ---
        stop_event.set()
        frame_ready_event.set() 
        tracking_thread.join()
        recording_thread.join()
        save_thread.join()
        picam2.stop()
        cv2.destroyAllWindows()
        print("Application has been shut down cleanly.")