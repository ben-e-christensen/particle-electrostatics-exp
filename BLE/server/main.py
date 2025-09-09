# main.py — ESP32 (HUZZAH32) BLE ADC streamer on A3/A4 + heartbeat (MicroPython)
import time, struct, machine, bluetooth
from micropython import const

# ===== Board =====
LED_PIN = 13
led = machine.Pin(LED_PIN, machine.Pin.OUT)

# Analog inputs (HUZZAH32: A3=GPIO35 [input-only], A4=GPIO32)
PIN_A3 = 39
PIN_A4 = 36

# ===== BLE UUIDs (must match your Pi receiver) =====
_IRQ_CENTRAL_CONNECT    = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
SVC_UUID  = bluetooth.UUID("c0de0001-0000-4a6f-9e00-000000000001")
CHR_UUID  = bluetooth.UUID("c0de1000-0000-4a6f-9e00-000000000001")
_PROP_READ   = const(0x02)
_PROP_NOTIFY = const(0x10)

# ===== Stream timing =====
NAME       = "ESP32-Analog-100Hz"
N          = const(5)         # 5 samples per channel -> 10 u16 total
GAP_US     = const(2000)      # 2 ms between samples -> 500 Hz
PERIOD_US  = const(10000)     # 10 ms per packet -> ~100 Hz

def adv_payload(name: str) -> bytes:
    n = name.encode()
    # Flags: LE General Discoverable + BR/EDR Not Supported
    return bytes([2, 0x01, 0x06, len(n) + 1, 0x09]) + n

class App:
    def __init__(self):
        # --- ADC setup (ADC1) ---
        self.adc3 = machine.ADC(machine.Pin(PIN_A3))  # A3 (GPIO35, input-only)
        self.adc4 = machine.ADC(machine.Pin(PIN_A4))  # A4 (GPIO32)
        try:
            self.adc3.atten(machine.ADC.ATTN_11DB)
            self.adc4.atten(machine.ADC.ATTN_11DB)
            self.adc3.width(machine.ADC.WIDTH_12BIT)
            self.adc4.width(machine.ADC.WIDTH_12BIT)
        except Exception:
            # Some ports default to 12-bit; okay to ignore if not present
            pass

        self._buf = bytearray(20)  # 10 x u16
        # --- BLE setup ---
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        ((self._chr_handle,),) = self.ble.gatts_register_services((
            (SVC_UUID, ((CHR_UUID, _PROP_READ | _PROP_NOTIFY),)),
        ))
        self._conn = None
        self._advertise()
        print("Booted. Advertising as", NAME)

    def _advertise(self):
        try:
            self.ble.gap_advertise(None)
        except Exception:
            pass
        self.ble.gap_advertise(100_000, adv_payload(NAME))

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn, _, _ = data
            print("Connected", self._conn)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn = None
            print("Disconnected; restarting advertising")
            self._advertise()

    def run(self):
        hb_div = 0
        while True:
            t0 = time.ticks_us()
            try:
                # --- sample A3/A4: 5 samples each with 2 ms gap ---
                a3 = [0]*N
                a4 = [0]*N
                for i in range(N):
                    # read_u16() is 0..65535 → scale to ~12-bit by >>4
                    a3[i] = (self.adc3.read_u16() >> 4)
                    a4[i] = (self.adc4.read_u16() >> 4)
                    if i < N - 1:
                        target = time.ticks_add(time.ticks_us(), GAP_US)
                        while time.ticks_diff(target, time.ticks_us()) > 0:
                            pass

                # Pack as 10 x u16 LE: A3[5], then A4[5]
                vals = a3 + a4
                struct.pack_into("<10H", self._buf, 0, *vals)

                # Update GATT value and notify
                self.ble.gatts_write(self._chr_handle, self._buf)
                if self._conn is not None:
                    try:
                        self.ble.gatts_notify(self._conn, self._chr_handle, self._buf)
                    except OSError:
                        pass

                # Heartbeat at ~2 Hz (toggle every ~0.5 s)
                hb_div = (hb_div + 1) % 50
                if hb_div == 0:
                    led.value(1 - led.value())

            except Exception as e:
                print("Loop error:", e)
                time.sleep(0.1)
                self._advertise()

            # keep 10 ms cadence
            dt = time.ticks_diff(time.ticks_us(), t0)
            if dt < PERIOD_US:
                time.sleep_us(PERIOD_US - dt)

try:
    App().run()
except Exception as e:
    print("Init error:", e)
    while True:
        led.value(1); time.sleep(0.1)
        led.value(0); time.sleep(0.1)
