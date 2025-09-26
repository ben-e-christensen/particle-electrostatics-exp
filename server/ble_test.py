import time
import struct, bluetooth




print("=== BLE Test Script Starting ===")

def advertising_payload(limited_disc=False, br_edr=False, name=None, services=None):
    payload = bytearray()

    def _append(adv_type, value):
        payload.extend(struct.pack("BB", len(value) + 1, adv_type) + value)

    _append(0x01, struct.pack("B", (0x02 if limited_disc else 0x06) + (0x00 if br_edr else 0x04)))

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

# Step 1: Check if BLE is supported
try:
    ble = bluetooth.BLE()
    ble.active(True)
    print("[OK] BLE stack is active")
except Exception as e:
    print("[ERROR] BLE not supported in this firmware:", e)
    while True:
        time.sleep(1)

# Step 2: Define UUIDs
SVC_UUID = bluetooth.UUID("4fafc201-1fb5-459e-8fcc-c5c9c331914b")

def irq(event, data):
    print("[BLE] IRQ:", event, data)

ble.irq(irq)

# Step 3: First try with just a name
print("[TEST] Advertising with name only...")
payload_name = advertising_payload(name="FeatherTest")
ble.gap_advertise(500000, adv_data=payload_name)  # 500 ms interval

print(">>> Check your phone/nRF Connect for 'FeatherTest'")
time.sleep(10)

# Step 4: Now try with service UUID
print("[TEST] Advertising with name + service UUID...")
payload_uuid = advertising_payload(name="FeatherTestUUID", services=[SVC_UUID])
ble.gap_advertise(500000, adv_data=payload_uuid)

print(">>> Check your phone/nRF Connect for 'FeatherTestUUID' + service UUID")

# Keep alive so board doesn’t reset
while True:
    print("[RUNNING] BLE still active...")
    time.sleep(5)
