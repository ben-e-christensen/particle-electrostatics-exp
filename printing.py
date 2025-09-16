import serial

# ---- Edit this section for your setup ----
PORT = "/dev/ttyACM0"   # e.g. Linux: /dev/ttyACM0, Windows: "COM3", macOS: "/dev/cu.usbmodemXXX"
BAUD = 115200           # must match Serial.begin() in your Arduino code

# ------------------------------------------
try:
    with serial.Serial(PORT, BAUD, timeout=1) as ser:
        print(f"Listening on {PORT} at {BAUD} baud...\n(Press Ctrl+C to stop)\n")
        while True:
            line = ser.readline().decode(errors="ignore").strip()
            if line:
                print(line)

except serial.SerialException as e:
    print(f"Error opening serial port {PORT}: {e}")
except KeyboardInterrupt:
    print("\nStopped.")
