import pandas as pd
import os

csv_path = "experiment_log (Copy).csv"  # your active file

# Safety check
if os.path.exists(csv_path):
    df = pd.read_csv(csv_path)

    # Keep only rows that have a valid frame_name
    df = df[df["frame_name"].notna() & (df["frame_name"].astype(str).str.strip() != "")]

    # Overwrite the file with the cleaned data
    df.to_csv(csv_path, index=False)
    print("✅ Deleted all rows without frame_name.")
else:
    print("⚠️ CSV file not found.")
