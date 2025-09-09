// Arduino Code (arduino_motor_controls.ino)
// arduino-cli compile --upload --fqbn esp32:esp32:XIAO_ESP32C3 -p /dev/ttyACM0 .
#include <AccelStepper.h>

// Define motor pins
#define DIR_PIN 3
#define STEP_PIN 2

// Define the probe pin
#define PROBE_PIN 9

// Define the motor interface type: 1 for a stepper driver
#define motorInterfaceType 1

// Create a new AccelStepper object
AccelStepper stepper(motorInterfaceType, STEP_PIN, DIR_PIN);

// Set motor parameters
const int stepsPerRevolution = 6400;

// Variables for communication and state
char command;
int value;
bool running = false;
bool dirInverted = false; // Tracks the current direction state
bool homing = false;

// --- Pin Locator Variables ---
// These are used by the new, blocking locate function
int pin_count = 0;
bool location_flag = false;
int tracked_revs = 0;
bool lastProbeState = false;

// Function to manually step the motor once
void take_one_step(bool direction) {
  // Set the direction pin
  digitalWrite(DIR_PIN, direction);

  // Send a pulse to the step pin
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(2000); // Wait for a short duration
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(2000); // Wait again before the next step
}

// The core blocking homing function
void locate() {
  Serial.println("Starting homing procedure...");
  homing = true;
  long steps_taken = 0;
  bool flag = false;

  // Set the motor to move in the homing direction
  digitalWrite(DIR_PIN, false);
  
  // Loop until the sensor is found and cleared
  while (true) {
    take_one_step(false); // Move in one direction

    // The logic to find and count steps over the mark
    if (digitalRead(PROBE_PIN) == HIGH) {
      steps_taken++;
      flag = true;
    } else if (digitalRead(PROBE_PIN) == LOW && flag) {
      // The mark has been passed, so back up halfway and exit
      Serial.print("Limit switch hit and passed. Steps taken: ");
      Serial.println(steps_taken);

      // Go back by half the steps
      long steps_to_go_back = steps_taken / 2;
      
      // Move in the opposite direction for the calculated number of steps
      for (long i = 0; i < steps_to_go_back; i++) {
        take_one_step(true); // Move in the opposite direction
      }

      // We have now found the home position, exit the function.
      break; 
    }
  }
  
  // Set a new origin after homing
  stepper.setCurrentPosition(0);
  Serial.println("Homing complete. New origin set.");
  
  homing = false;
}

void setup() {
  Serial.begin(115200);
  stepper.setMaxSpeed(40000.0);
  stepper.setAcceleration(50000.0);
  
  // Configure the probe pin as an input with a pull-up resistor
  pinMode(PROBE_PIN, INPUT_PULLUP);
}

void loop() {
  // Only process serial commands if not in the middle of a homing sequence
  if (!homing) {
    if (Serial.available() > 0) {
      command = Serial.read();

      if (command == 'S') { // Set Speed command
        while (Serial.available() == 0) {} // Wait for value
        value = Serial.parseInt();
        stepper.setSpeed(value);
        Serial.print("Speed set: ");
        Serial.println(value);
        running = true;
      } else if (command == 'T') { // Toggle Direction command
        dirInverted = !dirInverted; // Flip the state
        stepper.setPinsInverted(dirInverted, false, false);
        Serial.println("Direction toggled.");
      } else if (command == 'X') { // Stop Motor command
        stepper.stop();
        running = false;
        Serial.println("Motor stopped.");
      } else if (command == 'L') { // New: Locate/Homing command
        locate();
      }
    }
  }

  // Run the motor if a speed is set (non-blocking) and not homing
  if (running && !homing) {
    stepper.runSpeed();
  }
}
