// --- PIN DEFINITIONS ---
// You MUST define these pins to match your PCB's schematic
const int csPin    = 25;     // Your Chip Select pin
const int sstrbPin = 26;     // << IMPORTANT: Set this to the GPIO connected to SSTRB
const int dinPin   = 19;     // Your board's MOSI/DIN pin
const int doutPin  = 21;     // Your board's MISO/DOUT pin

void setup() {
  // Start serial communication
  Serial.begin(115200); // Using a faster baud rate
  while (!Serial) {
    delay(10); // Wait for serial port to connect
  }

  // Set pin modes
  pinMode(csPin, OUTPUT);
  pinMode(sstrbPin, OUTPUT);
  pinMode(dinPin, OUTPUT);
  pinMode(doutPin, INPUT);

  // Set initial pin states
  digitalWrite(csPin, HIGH);    // Deselect ADC
  digitalWrite(sstrbPin, LOW);  // Strobe is initially low
  digitalWrite(dinPin, LOW);

  Serial.println("MAX1032 Bit-Bang ADC Reader Initialized");
}

void loop() {
  // Read from Channel 1
  int channel1Value = readADC_bitbang(0x9C); // Command for single-ended, unipolar, channel 1
  Serial.print("Channel 1: ");
  Serial.println(channel1Value);

  // Read from Channel 2
  int channel2Value = readADC_bitbang(0xAC); // Command for single-ended, unipolar, channel 2
  Serial.print("Channel 2: ");
  Serial.println(channel2Value);
  
  Serial.println("--------------------");

  delay(1000);
}

// Custom function to manually communicate with the MAX1032
int readADC_bitbang(byte commandByte) {
  // Start the transaction
  digitalWrite(csPin, LOW);

  // --- Send the 8-bit command byte (MSB first) ---
  // This tells the ADC which channel to read next
  for (int i = 7; i >= 0; i--) {
    // Set the DIN pin to the value of the current bit
    digitalWrite(dinPin, (commandByte >> i) & 0x01);
    
    // Pulse the SSTRB pin to tell the ADC to read the bit
    digitalWrite(sstrbPin, HIGH);
    digitalWrite(sstrbPin, LOW);
  }

  // --- Read the 16-bit result (MSB first) ---
  // The result is from the *previous* conversion
  unsigned int result = 0;
  for (int i = 15; i >= 0; i--) {
    // Pulse SSTRB to have the ADC present the next bit on DOUT
    digitalWrite(sstrbPin, HIGH);
    digitalWrite(sstrbPin, LOW);

    // Read the bit from DOUT and add it to our result variable
    if (digitalRead(doutPin) == HIGH) {
      result |= (1 << i);
    }
  }

  // End the transaction
  digitalWrite(csPin, HIGH);

  // The first conversion after power-up is invalid, subsequent ones are fine.
  // The 14-bit data is in the last 14 bits of the 16 bits received.
  return result & 0x3FFF;
}