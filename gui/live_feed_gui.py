import tkinter as tk
from tkinter import TclError
from PIL import Image, ImageTk
import threading
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import time
from queue import Queue
import cv2

# Import the shared queues and stop_event from the BLE module
from BLE.client.ble_plotter import data_queue_a0, data_queue_a1, stop_event

# --- PLOTTING Globals ---
data_buffer_a0 = []
data_buffer_a1 = []
time_buffer = []
buffer_size = 500  # Number of data points to display

# --- VIDEO Globals ---
video_queue = Queue()
video_label = None
tk_img = None # A global reference to prevent garbage collection
DISPLAY_W, DISPLAY_H = 640, 480

# --- Matplotlib and Tkinter Setup ---
fig, ax = plt.subplots(1, 2, figsize=(10, 5))
fig.suptitle("Live Data Stream from BLE Device", fontsize=16)

# First subplot (A0 data)
ax[0].set_title("Analog Channel 0")
ax[0].set_xlabel("Data Point Index")
ax[0].set_ylabel("Sensor Value")
ax[0].grid(True)
line_a0, = ax[0].plot([], [], 'r-')

# Second subplot (A1 data)
ax[1].set_title("Analog Channel 1")
ax[1].set_xlabel("Data Point Index")
ax[1].set_ylabel("Sensor Value")
ax[1].grid(True)
line_a1, = ax[1].plot([], [], color='#87CEEB')

def update_plot():
    """
    Checks the queues for new data and updates both Matplotlib plots.
    """
    new_data_count = 0
    while not data_queue_a0.empty() and not data_queue_a1.empty():
        data_point_a0 = data_queue_a0.get()
        data_point_a1 = data_queue_a1.get()
        
        data_buffer_a0.append(data_point_a0)
        data_buffer_a1.append(data_point_a1)
        time_buffer.append(len(time_buffer))
        new_data_count += 1

    if new_data_count > 0:
        if len(data_buffer_a0) > buffer_size:
            data_buffer_a0[:] = data_buffer_a0[-buffer_size:]
            data_buffer_a1[:] = data_buffer_a1[-buffer_size:]
            time_buffer[:] = list(range(len(data_buffer_a0)))

        line_a0.set_xdata(time_buffer)
        line_a0.set_ydata(data_buffer_a0)
        line_a1.set_xdata(time_buffer)
        line_a1.set_ydata(data_buffer_a1)

        ax[0].set_xlim(0, buffer_size)
        ax[1].set_xlim(0, buffer_size)
        if data_buffer_a0:
            ax[0].set_ylim(min(data_buffer_a0) - 50, max(data_buffer_a0) + 50)
            ax[1].set_ylim(min(data_buffer_a1) - 50, max(data_buffer_a1) + 50)
        
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        canvas.draw_idle()

    root.after(50, update_plot)

def update_video():
    """Checks the video queue and updates the video label with a new frame (resized)."""
    global tk_img
    if not video_queue.empty():
        pil_img = None
        # Drain queue so we always show the most recent frame
        while not video_queue.empty():
            pil_img = video_queue.get_nowait()

        if pil_img is not None:
            # Resize to fixed dimensions
            pil_img = pil_img.resize((DISPLAY_W, DISPLAY_H), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img, master=video_label)
            video_label.configure(image=tk_img)
            video_label.image = tk_img  # keep ref

    root.after(15, update_video)


# Main control window
root = tk.Tk()
root.title("Live Data & Camera Feed")

# Widgets for the data window
canvas = FigureCanvasTkAgg(fig, master=root)
canvas_widget = canvas.get_tk_widget()
canvas_widget.pack(fill=tk.BOTH, expand=True)

video_label = tk.Label(root)
video_label.pack()

def run_gui():
    root.after(50, update_plot)
    root.after(15, update_video)
    root.mainloop()

if __name__ == "__main__":
    run_gui()
