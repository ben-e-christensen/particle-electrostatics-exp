from machine import SPI, Pin, Timer
import time

print("--- Starting 1Hz ADC Test (Standard Feather) ---")

# ======================================================
# === CONFIG ===
# ======================================================
vREF = 4.096
inputRange = 4 

# Pins for Standard Feather (Huzzah32):
# SCK=5, MOSI=18, MISO=19. Hardware ID is 2 (VSPI).
spi = SPI(2, baudrate=100000, polarity=0, phase=0,
          sck=Pin(5), mosi=Pin(18), miso=Pin(19))

# Chip Select - verify wire is on pin 25
cs = Pin(25, Pin.OUT)
cs.value(1)

# ======================================================
# === ADC LOGIC (Using your known command bytes) ===
# ======================================================
def configADC(readAddress, rangeV):
    # Command: 1 | Address(3 bits) | Range(4 bits)
    cmd = bytearray([0b10000000 | (readAddress << 4) | rangeV])
    cs.value(0)
    spi.write(cmd)
    cs.value(1)
    time.sleep_us(50)

def readADC(readAddress):
    # Your V2 code used a 4-byte buffer for the read
    cmd = bytearray(4)
    cmd[0] = 0b10000000 | (readAddress << 4)
    cs.value(0)
    spi.write_readinto(cmd, cmd)
    cs.value(1)
    # Extract the 14-bit data shifted from the 32-bit result
    raw = ((cmd[2] << 8) | cmd[3]) >> 2
    return raw

def convert_to_voltage(raw):
    ratio = raw / 16384.0  # 2^14
    if inputRange == 4:
        return (ratio * 3 * vREF) - (1.5 * vREF)
    return ratio * vREF

# ======================================================
# === EXECUTION LOOP ===
# ======================================================
seq = 0

def run_sample(timer):
    global seq
    
    # Target Channel 2 (as in your previous tests)
    configADC(2, inputRange)
    raw_val = readADC(2)
    voltage = convert_to_voltage(raw_val)
    
    # \r\n explicitly fixes the "stair-case" layout in the REPL
    print("Seq: {} | Raw: {} | Volts: {:.5f}V\r".format(seq, raw_val, voltage))
    seq += 1

# Setup timer to trigger once every second
tim = Timer(0)
tim.init(freq=1, mode=Timer.PERIODIC, callback=run_sample)