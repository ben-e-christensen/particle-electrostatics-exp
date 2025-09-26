from machine import SPI, Pin
import time
# source ~/esp32env/bin/activate
# mpremote connect /dev/ttyACM0 fs cp ADC.py :main.py

# SPI Setup (with correct pin mapping!)
spi = SPI(1, baudrate=100000, polarity=0, phase=0,
          sck=Pin(5), mosi=Pin(19), miso=Pin(21))
cs = Pin(25, Pin.OUT)
cs.value(1)  # Deselect MAX1032

# Constants
vREF = 4.096
inputRange = 4  

# Configure the ADC
def configADC(readAddress, rangeV):
    cmd = bytearray([0b10000000 | (readAddress << 4) | rangeV])
    cs.value(0)
    spi.write(cmd)
    cs.value(1)
    time.sleep_ms(10)  # Allow ADC time to settle

# Read from ADC
def readADC(readAddress):
    cmd = bytearray(4)
    cmd[0] = 0b10000000 | (readAddress << 4)
    cs.value(0)
    spi.write_readinto(cmd, cmd)
    cs.value(1)
    print("Raw SPI response:", [hex(b) for b in cmd])
    result = ((cmd[2] << 8) | cmd[3]) >> 2
    return result

# Convert raw ADC to voltage
def convert_to_voltage(raw):
    ratio = raw / (1 << 14)
    if inputRange == 1:
        return ratio * 3 * vREF / 2 - 1.5 * vREF / 2
    elif inputRange == 2:
        return ratio * 3 * vREF / 2 - 3 * vREF / 2
    elif inputRange == 3:
        return ratio * 3 * vREF / 2
    elif inputRange == 4:
        return ratio * 3 * vREF - 1.5 * vREF
    elif inputRange == 5:
        return ratio * 3 * vREF - 3 * vREF
    elif inputRange == 6:
        return ratio * 3 * vREF
    elif inputRange == 7:
        return ratio * 6 * vREF - 3 * vREF
    return 0

# Main Loop

print("Starting ADC loop...")

while True:
    configADC(0, inputRange)
    configADC(2, inputRange)
    configADC(3, inputRange)

    raw = readADC(0)
    voltage = convert_to_voltage(raw)
    print("ADC_CH{} = {:.5f} V".format(0, voltage))
    raw = readADC(2)
    voltage = convert_to_voltage(raw)
    print("ADC_CH{} = {:.5f} V".format(2, voltage))

    raw = readADC(3)
    voltage = convert_to_voltage(raw)
    print("ADC_CH{} = {:.5f} V".format(3, voltage))
    time.sleep(3)
