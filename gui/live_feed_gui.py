"""
Live feed plotting window (attaches to existing Tk root)

- Imports data queues from motor_controls_gui (single serial owner).
- Uses deques for rolling Y-buffers and a monotonically increasing X index
  so the plot side-scrolls smoothly past the visible window.
- attach_live_feed(parent=...) creates a Toplevel inside your main app.
- If run directly (python live_feed_gui.py), it creates its own root and runs standalone.
"""

import tkinter as tk
from collections import deque
from queue import Empty
import traceback

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Make sure this import path matches your project structure exactly.
# Both main.py and this file must import the SAME module object.
from gui.motor_controls_gui import data_queue_a0, data_queue_a1

# ----------------------- Config -----------------------
BUFFER_SIZE = 500           # how many points visible
DRAIN_CAP_PER_FRAME = 200   # max pairs drained per UI tick
UI_REFRESH_MS = 16          # ~60 fps

# -------------------- Plotting State ------------------
data_buffer_a0 = deque(maxlen=BUFFER_SIZE)  # CH2 volts
data_buffer_a1 = deque(maxlen=BUFFER_SIZE)  # CH3 volts
sample_idx = 0  # monotonically increasing x counter

# -------------------- Window Builder ------------------
def _build_live_feed_window(parent):
    """Create the live feed plotting window as a Toplevel attached to 'parent'."""
    top = tk.Toplevel(parent)
    top.title("Live Feed")

    # Matplotlib figure & axes
    fig, ax = plt.subplots(1, 2, figsize=(10, 5))
    fig.suptitle("Live Data Stream", fontsize=16)

    # Left subplot (CH2)
    ax[0].set_title("CH2")
    ax[0].set_xlabel("Sample Index")
    ax[0].set_ylabel("Voltage (V)")
    ax[0].grid(True)
    line_a0, = ax[0].plot([], [], 'r-')

    # Right subplot (CH3)
    ax[1].set_title("CH3")
    ax[1].set_xlabel("Sample Index")
    ax[1].set_ylabel("Voltage (V)")
    ax[1].grid(True)
    line_a1, = ax[1].plot([], [], '#87CEEB')

    fig.tight_layout(rect=[0, 0, 1, 0.95])

    canvas = FigureCanvasTkAgg(fig, master=top)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill=tk.BOTH, expand=True)

    # Heartbeat: show queue sizes in the window title (quick sanity check)
    def heartbeat():
        try:
            top.title(f"Live Feed  |  CH2_q={data_queue_a0.qsize()}  CH3_q={data_queue_a1.qsize()}")
        finally:
            top.after(250, heartbeat)

    def update_plot():
        global sample_idx
        try:
            # Drain paired samples (keep queues in lockstep)
            n_pairs = min(data_queue_a0.qsize(), data_queue_a1.qsize())
            n_pairs = min(n_pairs, DRAIN_CAP_PER_FRAME)

            if n_pairs > 0:
                for _ in range(n_pairs):
                    try:
                        a0 = data_queue_a0.get_nowait()
                        a1 = data_queue_a1.get_nowait()
                    except Empty:
                        break
                    data_buffer_a0.append(a0)
                    data_buffer_a1.append(a1)
                    sample_idx += 1

                # Build x for the current visible window
                n = len(data_buffer_a0)  # == len(data_buffer_a1)
                x_start = max(0, sample_idx - n)
                x_vals = list(range(x_start, x_start + n))

                # Update line data
                line_a0.set_xdata(x_vals)
                line_a0.set_ydata(list(data_buffer_a0))
                line_a1.set_xdata(x_vals)
                line_a1.set_ydata(list(data_buffer_a1))

                # Scroll x-axis with data
                x_left  = max(0, sample_idx - BUFFER_SIZE)
                x_right = max(BUFFER_SIZE, sample_idx)
                ax[0].set_xlim(x_left, x_right)
                ax[1].set_xlim(x_left, x_right)

                # Autoscale Y with padding
                if n > 0:
                    ymin0, ymax0 = min(data_buffer_a0), max(data_buffer_a0)
                    ymin1, ymax1 = min(data_buffer_a1), max(data_buffer_a1)
                    pad0 = max(0.05, 0.05 * (ymax0 - ymin0 + 1))
                    pad1 = max(0.05, 0.05 * (ymax1 - ymin1 + 1))
                    ax[0].set_ylim(ymin0 - pad0, ymax0 + pad0)
                    ax[1].set_ylim(ymin1 - pad1, ymax1 + pad1)

                canvas.draw_idle()

        except Exception:
            print("[live_feed_gui] update_plot error:")
            traceback.print_exc()

        finally:
            top.after(UI_REFRESH_MS, update_plot)

    top.after(250, heartbeat)
    top.after(UI_REFRESH_MS, update_plot)
    return top

# -------------------- Public API ----------------------
def attach_live_feed(parent: tk.Misc | None = None):
    """
    Attach the live feed window to an existing Tk root if present,
    otherwise create a root and run standalone.
    """
    root = parent or tk._get_default_root()
    if root is None:
        root = tk.Tk()
        _build_live_feed_window(root)
        root.mainloop()
    else:
        _build_live_feed_window(root)

# -------------------- Standalone ----------------------
if __name__ == "__main__":
    attach_live_feed(None)
