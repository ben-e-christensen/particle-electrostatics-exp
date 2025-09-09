#helpers.py
import tkinter as tk
import os
import re
import time
import pandas as pd

# Directory to save captured frames
today = time.strftime("%Y-%m-%d_%H:%M", time.localtime())


def calc_spin(freq, revs, state, result_label, freq_tk, total_revs_tk):
    steps_per_rev = 25600
    steps_per_sec = float(freq) / 60 * steps_per_rev
    delay_seconds = 1.0 / (steps_per_sec * 2.0)
    steps = float(revs) * steps_per_rev
    state['delay'] = delay_seconds
    state['total_steps'] = int(steps)
    
    update_ui(state, result_label)
    update_tkinter_input_box(freq_tk, freq)
    update_tkinter_input_box(total_revs_tk, revs)

    
def update_ui(state, result_label):
    result_label.config(text=f"Delay (us): {state['delay'] * 10e5:.0f} u_sec\nSteps: {state['total_steps']}\nTotal Time: {state['delay'] * 2 * state['total_steps']:.1f} sec")
    
def update_tkinter_input_box(input_box, val):
    input_box.delete(0, tk.END)
    if isinstance(val, float):
        val = round(val,3)
    input_box.insert(0, val)

def get_next_session_folder(base_dir):
    os.makedirs(base_dir, exist_ok=True)

    existing = [
        name for name in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, name)) and re.match(r"session\d+", name)
    ]

    # Extract numbers from session folder names
    indices = [int(re.findall(r"\d+", name)[0]) for name in existing]
    next_index = max(indices, default=0) + 1

    folder_name = f"session{next_index}_{today}"
    full_path = os.path.join(base_dir, folder_name)

    # Make folders: datasets/sessionX/ and datasets/sessionX/images/
    os.makedirs(os.path.join(full_path, "images"), exist_ok=True)

    return full_path, next_index

def get_readings(csv_path):

    df = pd.read_csv(csv_path, sep=",")  
    # Ensure "Frame" column exists
    if "Frame" in df.columns:
        df["image_path"] = df["Frame"].apply(
            lambda name: f"/images/{name.strip()}" if pd.notna(name) and name.strip() != "" else None
        )
    else:
        print("ERROR: 'Frame' column missing")
        df["image_path"] = None

    records = df.to_dict(orient="records")
    
    return records

def html_generator(dir, i):
    import os

    csv_path = os.path.join(dir, "readings.csv")
    records = get_readings(csv_path)
    html_path = os.path.join(dir, f"session{i}.html")

    with open(html_path, "w") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Session {i} Data</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Bootstrap + Styling -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
    .image-scroll {{
        height: 88vh;
        overflow-y: auto;
        border: 1px solid #ccc;
        padding: 10px 10px; /* extra vertical padding */
        background-color: white;
        display: flex;
        flex-direction: column;
        align-items: center;
        position: sticky; 
        top: 0; 
        right: 0;
    }}
    .image-scroll img {{
        max-width: 100%;
        margin: 3px 0;
        border-radius: 5px;
    }}
    .image-wrapper {{
        position: relative;
        height: 100%;
        width: 90%;
    }}
    .image-wrapper.highlight::before {{
        content: "";
        position: absolute;
        top: -5px;
        left: -5px;
        right: -5px;
        bottom: -5px;
        # border: 3px solid #0d6efd;
        # border-radius: 12px;
        # box-shadow: 0 0 10px #0d6efd;
        z-index: 1;
    }}
    .image-wrapper:not(.highlight) img {{
        transform: scale(0.6);
        opacity: 1;
    }}
    .image-wrapper.highlight img {{
        transform: scale(0.8);
        opacity: 1;
        z-index: 2;
    }}
</style>

</head>
<body>
<div class="container-fluid mt-4">
    <h1 class="mb-4">Session {i} Data</h1>
    <div class="row">
        <!-- Data Table -->
        <div class="col-md-8">
            <table class="table table-bordered table-hover align-middle text-center" id="data-table">
                <thead class="table-dark">
                    <tr>
                        <th>Timestamp</th>
                        <th>Voltage (V)</th>
                        <th>Angle (deg)</th>
                    </tr>
                </thead>
                <tbody>
""")

        for idx, row in enumerate(records):
            f.write(f"""<tr data-index="{idx}">
    <td>{row['Timestamp']}</td>
    <td>{row['Voltage (V)']}</td>
    <td>{row['Angle (deg)']}</td>
</tr>
""")

        f.write("""            </tbody>
            </table>
        </div>

        <!-- Vertical Image Scroll -->
        <div class="col-md-4">
            <div class="image-scroll" id="image-list">
""")

        for idx, row in enumerate(records):
            image = row.get("Frame", "").strip()
            if image:
                f.write(f"""
<div class="image-wrapper" data-index="{idx}">
    <img src="images/{image}" alt="Image {idx}">
</div>
""")

        f.write("""            </div>
        </div>
    </div>
</div>

<!-- JS -->
<script>
    const rows = document.querySelectorAll("#data-table tbody tr");
    const imageWrappers = document.querySelectorAll(".image-wrapper");
    const imageList = document.getElementById("image-list");

    rows.forEach(row => {
        row.addEventListener("mouseenter", () => {
            const index = row.getAttribute("data-index");

            // Remove highlight from all
            imageWrappers.forEach(div => div.classList.remove("highlight"));

            // Add highlight to current image
            const target = document.querySelector(`.image-wrapper[data-index='${index}']`);
            if (target) {
                target.classList.add("highlight");
                const scrollTop = target.offsetTop - imageList.clientHeight / 2 + target.clientHeight / 2;
                imageList.scrollTop = scrollTop;  // instant jump, no animation
            }
        });
    });
</script>

</body>
</html>""")

