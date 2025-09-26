#include <SPI.h>


SPISettings MAX1032(2000000, MSBFIRST, SPI_MODE0);  

int CS = 26;

float Vref = 4.096;

void setup() {
 Serial.begin(9600);
 pinMode(CS, OUTPUT);
 digitalWrite(CS, LOW);
 digitalWrite(CS, HIGH);
 SPI.begin();
 

}

void loop() {
  configADC(0x00); // Set desired channel (0-7)
  unsigned int rawResult = readADC(0x00); // Read desired channel (0-7)
  Serial.println(rawResult);
  Serial.println((float)rawResult/(16384.0)*3*Vref/2 - 3*Vref/4);
  delay(1000);

}


void configADC(byte readAddress) {
  byte configByte = 0b1010001 | (readAddress<<4);  // See table 2 in datasheet 

 // Bit 7 (MSB): Start Bit
 // Bits 6-4: Address bits (readAddress)
 // Bit 3: Single ended (0) or differential (1)
 // Bits 2-0: Analog input range (see table Fig 7 for single ended, Fig 8 for diff)
 // In the example above Bits 2-0 are set to 001, which correspond to range of 3*Vref/2
 
  Serial.println(configByte);
  SPI.beginTransaction(MAX1032); // MAX1032 expects 4 bytes
  digitalWrite(CS, LOW);
  SPI.transfer(configByte); //First byte
  SPI.transfer(0x00); // all other bytes 0x00
  SPI.transfer(0x00); 
  SPI.transfer(0x00); 
  digitalWrite(CS, HIGH);
  SPI.endTransaction();
}

unsigned int readADC(byte readAddress) {
  byte result[2];
  byte readByte = 0b10100000 | (readAddress<<4);  // See table 3 in datasheet

  // Bit 7 (MSB): Start Bit
  // Bits 6-4: Address bits
  // All other bits 0

 
  Serial.println(readByte);
  SPI.beginTransaction(MAX1032); // MAX1032 expects 4 bytes
  digitalWrite(CS, LOW);
  SPI.transfer(readByte); // Send read conversion byte
  SPI.transfer(0x00);  // Next byte 0
  result[0]= SPI.transfer(0x00); // Next byte 0; read MSbyte of conversion
  result[1] =SPI.transfer(0x00); // Next byte 0; read LSbyte of conversion
  Serial.println(result[0]);
  digitalWrite(CS, HIGH);
  SPI.endTransaction();

  return (result[0] << 6 | (result[1] >> 2));  // Rearrange according to according to Figure 3
}