from machine import SPI, Pin, Timer, ADC
import time, struct, bluetooth
import _thread

print("=== Feather V2 ADC + BLE Debug ===")

"""
source ~/esp32env/bin/activate
mpremote connect /dev/ttyACM1 fs cp server.py :main.py
"""

# ======================================================
# === CONFIG ===
# ======================================================
DEBUG = False        # True = print voltages to USB, False = BLE stream
vREF = 4.096
inputRange = 4    # Keep your conditional ranges intact

# SPI Setup
spi = SPI(1, baudrate=100000, polarity=0, phase=0,
          sck=Pin(5), mosi=Pin(19), miso=Pin(21))
cs = Pin(25, Pin.OUT)
cs.value(1)

# ======================================================
# === ADC FUNCTIONS ===
# ======================================================
def configADC(readAddress, rangeV):
    cmd = bytearray([0b10000000 | (readAddress << 4) | rangeV])
    cs.value(0)
    spi.write(cmd)
    cs.value(1)
    time.sleep_us(50)

def readADC(readAddress):
    cmd = bytearray(4)
    cmd[0] = 0b10000000 | (readAddress << 4)
    cs.value(0)
    spi.write_readinto(cmd, cmd)
    cs.value(1)
    raw = ((cmd[2] << 8) | cmd[3]) >> 2
    return raw

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

# ======================================================
# === INLINE BLE ADVERTISING PAYLOAD ===
# ======================================================
import struct as _struct
def advertising_payload(limited_disc=False, br_edr=False, name=None, services=None):
    payload = bytearray()
    def _append(adv_type, value):
        payload.extend(_struct.pack("BB", len(value) + 1, adv_type) + value)
    _append(0x01, _struct.pack("B", (0x02 if limited_disc else 0x06) +
                                      (0x00 if br_edr else 0x04)))
    if name:
        _append(0x09, name.encode())
    if services:
        for uuid in services:
            b = bytes(uuid)
            if len(b) == 2:
                _append(0x03, b)
            elif len(b) == 16:
                _append(0x07, b)
    return payload

# ======================================================
# === BLE SETUP ===
# ======================================================
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)

ble = bluetooth.BLE()
ble.active(True)
print("[INIT] BLE active")

SVC_UUID = bluetooth.UUID("4fafc201-1fb5-459e-8fcc-c5c9c331914b")
CHR_UUID = bluetooth.UUID("beb5483e-36e1-4688-b7f5-ea07361b26a8")
print("[INIT] Service UUID:", SVC_UUID)
print("[INIT] Char UUID:", CHR_UUID)

adc_chr = (CHR_UUID, bluetooth.FLAG_NOTIFY,)
adc_svc = (SVC_UUID, (adc_chr,),)
services = (adc_svc,)
handles = ble.gatts_register_services(services)
print("[INIT] Raw handles returned:", handles)

# Your build shows ((16,),) so grab [0][0]
adc_handle = handles[0][0]
print("[INIT] Using adc_handle =", adc_handle)

def irq(event, data):
    print("[BLE] IRQ event:", event, data)
    if event == _IRQ_CENTRAL_CONNECT:
        print("[BLE] Central connected")
    elif event == _IRQ_CENTRAL_DISCONNECT:
        print("[BLE] Central disconnected — restarting advertising")
        advertise()

ble.irq(irq)
adv_payload = advertising_payload(services=[SVC_UUID])
scan_payload = advertising_payload(name="FeatherV2_TX_100Hz")

def advertise():
    print("[BLE] Advertising start...")
    ble.gap_advertise(500000, adv_data=adv_payload, resp_data=scan_payload)

advertise()

# ======================================================
# === BATTERY MONITORING ===
# ======================================================
vbat_pin = Pin(35)
        
batt_voltage = ADC(vbat_pin)     

# Set attenuation so it can measure up to 3.3 V
batt_voltage.atten(ADC.ATTN_11DB)   # Full 0-3.3V range

def read_vbat():
    raw = batt_voltage.read()                       # 0–4095 on ESP32 (12-bit)
    measured = raw * (3.3 / 4095.0)        # Convert to voltage at pin
    return measured * 2.0     

# ======================================================
# === MAIN LOOP / TIMER CALLBACK ===
# ======================================================
seq = 0
t0 = time.ticks_ms()

def send_packet(timer):
    global seq
    now = time.ticks_ms()
    ms = time.ticks_diff(now, t0)

    # Configure and read channels
    configADC(0, inputRange)
    configADC(2, inputRange)
    configADC(3, inputRange)
    ch0 = readADC(0)
    ch2 = readADC(2)
    ch3 = readADC(3)

    pkt = struct.pack("<IIHHH", seq, ms, ch0, ch2, ch3)
    ble.gatts_notify(0, adc_handle, pkt)

    if DEBUG:
        v2 = convert_to_voltage(ch2)
        v3 = convert_to_voltage(ch3)
        print("[ADC] CH2 raw={} V={:.5f}".format(ch2, v2))
        print("[ADC] CH3 raw={} V={:.5f}".format(ch3, v3))
    else:
        pkt = struct.pack("<IIHH", seq, ms, ch2, ch3)  # [seq][ms][ch2][ch3]
        try:
            ble.gatts_notify(0, adc_handle, pkt)
            # print("[BLE] Notify seq={} ms={} ch2={} ch3={}".format(seq, ms, ch2, ch3))
        except OSError as e:
            # -128 = not ready / unsubscribed yet
            print("[BLE] Notify failed (seq={}, err={})".format(seq, e))


    seq += 1


led = Pin(13, Pin.OUT)   # adjust if needed, sometimes Pin(2) is the LED

def led_thread():
    while True:
        vbat = read_vbat()
        if vbat > 3.5:
            led.value(1)   # LED on
            time.sleep(0.5)
            led.value(0)   # LED off
        # wait remaining time of 5s period
        time.sleep(4.5)

# start the LED blink thread



if DEBUG:
    print("[MODE] Debug print mode")
    while True:
        send_packet(None)
        time.sleep(3)
else:
    print("[MODE] BLE streaming at 100 Hz")
    tim = Timer(0)
    print("Starting LED monitoring thread...")
    _thread.start_new_thread(led_thread, ())
    tim.init(freq=100, mode=Timer.PERIODIC, callback=send_packet)
