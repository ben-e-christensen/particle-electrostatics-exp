// Feather ESP32 V2 — BLE Client + Stepper Motor Control + Homing task + Serial bridge
// - Subscribes to 100 Hz notifications (14 bytes): [u32 seq][u32 ms][u16 ch0][u16 ch2][u16 ch3]
// - Forwards each sample to USB Serial as CSV: "seq,ms,ch0,ch2,ch3\n"
// - Prints once-per-second RX% stats
// - Serial motor cmds: S (speed), T (toggle dir), X (stop), L (home)

#include <Arduino.h>
#include <AccelStepper.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <math.h>

// ======================== USER CONFIG ========================
#define STEP_PIN    26
#define DIR_PIN     25
#define PROBE_PIN   14  // digital probe

const int motorInterfaceType = 1;
AccelStepper stepper(motorInterfaceType, STEP_PIN, DIR_PIN);

// ========================= BLE SETUP ========================
#define SVC_UUID  "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define CHR_UUID  "beb5483e-36e1-4688-b7f5-ea07361b26a8"

static BLEUUID serviceUUID(SVC_UUID);
static BLEUUID charUUID(CHR_UUID);

static BLERemoteCharacteristic* gRemoteChr = nullptr;
static BLEAdvertisedDevice*     gTarget    = nullptr;
static bool                     gDoConnect = false;
static bool                     gConnected = false;

struct __attribute__((packed)) Packet {
  uint32_t seq;
  uint32_t ms;
  uint16_t ch0;
  uint16_t ch2;
  uint16_t ch3;
};
static_assert(sizeof(Packet) == 14, "Packet must be 14 bytes");

// Mailbox for latest sample (BLE callback -> main loop)
volatile uint32_t g_latest_seq = 0;
volatile uint32_t g_latest_ms  = 0;
volatile uint16_t g_latest_ch0 = 0;
volatile uint16_t g_latest_ch2 = 0;
volatile uint16_t g_latest_ch3 = 0;
volatile bool     g_latest_ready = false;

// RX stats (per-second window)
volatile uint32_t g_rx_in_window   = 0;
volatile uint32_t g_miss_in_window = 0;
volatile bool     g_have_prev      = false;
volatile uint32_t g_prev_seq       = 0;

static inline uint32_t seq_gap(uint32_t prev, uint32_t cur) {
  return (cur - prev) - 1U;
}

void notifyCB(BLERemoteCharacteristic* chr, uint8_t* data, size_t len, bool) {
  if (len < sizeof(Packet)) return;
  Packet p;
  memcpy(&p, data, sizeof(Packet));

  // Stats
  if (g_have_prev) {
    g_miss_in_window += seq_gap(g_prev_seq, p.seq);
  } else {
    g_have_prev = true;
  }
  g_prev_seq = p.seq;
  g_rx_in_window++;

  // Publish latest (mailbox)
  g_latest_seq  = p.seq;
  g_latest_ms   = p.ms;
  g_latest_ch0  = p.ch0;
  g_latest_ch2  = p.ch2;
  g_latest_ch3  = p.ch3;
  g_latest_ready = true;
}

class ClientCB : public BLEClientCallbacks {
  void onConnect(BLEClient* c) override { gConnected = true; }
  void onDisconnect(BLEClient* c) override { gConnected = false; }
};

class ScanCB : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    if (d.haveServiceUUID() && d.isAdvertisingService(serviceUUID)) {
      BLEDevice::getScan()->stop();
      gTarget = new BLEAdvertisedDevice(d);
      gDoConnect = true;
    }
  }
};

bool connectAndSubscribe() {
  if (!gTarget) return false;
  BLEClient* cli = BLEDevice::createClient();
  cli->setClientCallbacks(new ClientCB());
  cli->setMTU(128);

  if (!cli->connect(gTarget)) {
    Serial.println("[BLE RX] Connect failed");
    return false;
  }

  BLERemoteService* svc = cli->getService(serviceUUID);
  if (!svc) { Serial.println("[BLE RX] Service not found"); cli->disconnect(); return false; }

  gRemoteChr = svc->getCharacteristic(charUUID);
  if (!gRemoteChr) { Serial.println("[BLE RX] Characteristic not found"); cli->disconnect(); return false; }
  if (!gRemoteChr->canNotify()) { Serial.println("[BLE RX] Notifiable=false"); cli->disconnect(); return false; }

  gRemoteChr->registerForNotify(notifyCB);

  // Enable CCCD
  BLERemoteDescriptor* cccd = gRemoteChr->getDescriptor(BLEUUID((uint16_t)0x2902));
  if (cccd) { uint8_t on[2] = {0x01, 0x00}; cccd->writeValue(on, 2, true); }

  Serial.println("[BLE RX] Subscribed");
  return true;
}

// ============== MOTOR STATE / SERIAL COMMANDS ===============
char command;
int  value;
bool running     = false;
bool dirInverted = false;
volatile bool homing = false;

static inline void take_one_step(bool direction) {
  digitalWrite(DIR_PIN, direction);
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(2000);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(2000);
}

bool is_probe_present() {
  return digitalRead(PROBE_PIN) == LOW;
}

// =================== HOMING TASK (CORE 0) ===================
TaskHandle_t homingTaskHandle = nullptr;

void homingTask(void* arg) {
  Serial.printf("[HOMING] Task start on core %d\n", xPortGetCoreID());

  long steps_taken = 0;
  bool on_mark = false, was_on_mark = false;
  const bool homeDir = false;

  while (homing) {
    take_one_step(homeDir);
    on_mark = is_probe_present();

    if (on_mark && !was_on_mark) {
      steps_taken = 0;
    } else if (!on_mark && was_on_mark) {
      long steps_to_go_back = max(1L, steps_taken / 2);
      Serial.printf("[HOMING] Mark passed. Backing up %ld steps…\n", steps_to_go_back);
      for (long i = 0; i < steps_to_go_back && homing; i++) {
        take_one_step(!homeDir);
        vTaskDelay(pdMS_TO_TICKS(1));  // Yield while backing up too
      }
      stepper.setCurrentPosition(0);
      Serial.println("[HOMING] Complete. Origin set.");
      homing = false;
      break;
    }

    if (on_mark) steps_taken++;
    was_on_mark = on_mark;

    vTaskDelay(pdMS_TO_TICKS(1));
  }

  Serial.println("[HOMING] Task exit");
  vTaskDelete(nullptr);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[INIT] Feather ESP32 V2 Client + Motor + Serial bridge");
  Serial.println("seq,ms,ch0,ch2,ch3"); // CSV header once

  stepper.setMaxSpeed(40000.0);
  stepper.setAcceleration(50000.0);
  stepper.setCurrentPosition(0);

  pinMode(DIR_PIN, OUTPUT);
  pinMode(STEP_PIN, OUTPUT);
  digitalWrite(DIR_PIN, LOW);
  digitalWrite(STEP_PIN, LOW);

  pinMode(PROBE_PIN, INPUT);

  BLEDevice::init("FeatherV2_RX_100Hz");
  BLEScan* scan = BLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new ScanCB());
  scan->setActiveScan(true);
  scan->setInterval(1349);
  scan->setWindow(449);
  scan->start(5, false);
}

void loop() {
  // --- BLE connect/maintain
  if (gDoConnect) {
    if (connectAndSubscribe()) Serial.println("[BLE RX] Connected & subscribed");
    else { Serial.println("[BLE RX] Connection attempt failed"); BLEDevice::getScan()->start(5, false); }
    gDoConnect = false;
  }
  if (!gConnected) BLEDevice::getScan()->start(5, false);

  // --- Stream latest sample over Serial (CSV)
  if (g_latest_ready) {
    noInterrupts();
    uint32_t seq = g_latest_seq, ms = g_latest_ms;
    uint16_t ch0 = g_latest_ch0, ch2 = g_latest_ch2, ch3 = g_latest_ch3;
    g_latest_ready = false;
    interrupts();

    Serial.printf("%lu,%lu,%u,%u,%u\n",
                  (unsigned long)seq, (unsigned long)ms, ch0, ch2, ch3);
  }

  // --- Serial motor commands (same as before)
  if (!homing && Serial.available() > 0) {
    command = Serial.read();
    if (command == 'S') {
      while (Serial.available() == 0) {}
      value = Serial.parseInt();
      stepper.setSpeed(value);
      running = true;
    } else if (command == 'T') {
      dirInverted = !dirInverted;
      stepper.setPinsInverted(dirInverted, false, false);
      Serial.println("[MOTOR] Direction toggled.");
    } else if (command == 'X') {
      stepper.stop(); running = false;
    } else if (command == 'L') {
      if (!homing) {
        homing = true;
        Serial.println("[HOMING] Starting…");
        xTaskCreatePinnedToCore(homingTask, "homingTask", 4096, nullptr, 2, &homingTaskHandle, 0);
      }
    }
  }

  // --- Run motor
  uint32_t now = millis();
  if (running && !homing){
    stepper.runSpeed();
    static uint32_t last_probe_ms = 0;
    if (now - last_probe_ms >= 500) {
      last_probe_ms = now;
      long pos = stepper.currentPosition();
      float stepsPerRev = 6400.0;
      float degrees = fmod(pos, stepsPerRev) * (360.0 / stepsPerRev);
      Serial.println(degrees);
    }
  } else {
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}
