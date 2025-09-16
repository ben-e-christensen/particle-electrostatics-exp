// Feather ESP32 V2 — BLE Notifier Server @100 Hz
// Sends 12-byte packets: [uint32 seq][uint32 ms][uint16 a26][uint16 a25]

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define SVC_UUID  "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHR_UUID  "beb5483e-36e1-4688-b7f5-ea07361b26a8"

// Analog pins (ESP32 GPIO numbers)
const int PIN_A26 = 26;  // ADC2
const int PIN_A25 = 25;  // ADC2

BLEServer*         gServer = nullptr;
BLECharacteristic* gChr    = nullptr;
volatile bool      gConnected = false;

struct __attribute__((packed)) Packet {
  uint32_t seq;   // monotonically increasing counter
  uint32_t ms;    // millis() at send time
  uint16_t a26;   // analogRead(GPIO26), 0..4095
  uint16_t a25;   // analogRead(GPIO25), 0..4095
};

class ServerCB : public BLEServerCallbacks {
  void onConnect(BLEServer* s) override {
    gConnected = true;
  }
  void onDisconnect(BLEServer* s) override {
    gConnected = false;
    BLEDevice::startAdvertising(); // allow quick reattach
  }
};

void setupAnalog() {
  // ESP32 ADC defaults to 12-bit; set attenuation for ~0–3.3V range
  // (Works for ADC1/ADC2. ADC2 is fine with BLE; it conflicts only with Wi-Fi.)
  analogSetPinAttenuation(PIN_A26, ADC_11db);
  analogSetPinAttenuation(PIN_A25, ADC_11db);
  // Optional: analogReadResolution(12); // default on ESP32
}

void setupBLE() {
  BLEDevice::init("FeatherV2_TX_100Hz_AIO");
  BLEDevice::setMTU(128);

  gServer = BLEDevice::createServer();
  gServer->setCallbacks(new ServerCB());

  BLEService* svc = gServer->createService(SVC_UUID);
  gChr = svc->createCharacteristic(
    CHR_UUID,
    BLECharacteristic::PROPERTY_NOTIFY
  );
  gChr->addDescriptor(new BLE2902()); // CCCD for notifications
  svc->start();

  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SVC_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[BLE TX] Starting 100 Hz notifier with AINs 26/25…");

  setupAnalog();
  setupBLE();

  Serial.println("[BLE TX] Advertising. Waiting for subscriber…");
}

void loop() {
  static uint32_t seq = 0;
  static uint32_t last_us = micros();

  // 100 Hz tick every 10,000 µs
  const uint32_t now = micros();
  if (now - last_us >= 10000) {
    last_us += 10000;

    // Sample as close to the tick as possible
    const uint16_t a26 = analogRead(PIN_A26); // 0..4095
    const uint16_t a25 = analogRead(PIN_A25); // 0..4095

    if (gConnected) {
      Packet p{ seq++, millis(), a26, a25 };
      gChr->setValue(reinterpret_cast<const uint8_t*>(&p), sizeof(p));
      gChr->notify(); // fire-and-forget
    }
  }

  // Keep the loop short; do other work here if needed
}
