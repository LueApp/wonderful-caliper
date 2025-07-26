/*
 * Simple LED Blink Test for ESP32-S3
 * 
 * This example blinks the built-in LED and an external LED
 * to verify the ESP32-S3 development environment is working.
 * 
 * Board: ESP32-S3-DevKitC-1 (or similar ESP32-S3 board)
 * Built-in LED: GPIO 48 (for most ESP32-S3 boards)
 * External LED: GPIO 2 (connect LED + resistor to this pin)
 */

// Pin definitions for ESP32-S3
#define BUILTIN_LED 48  // Built-in RGB LED (may vary by board)
#define EXTERNAL_LED 2  // External LED pin

void setup() {
  // Initialize serial communication at 115200 baud rate
  Serial.begin(115200);
  
  // Wait for serial port to connect (useful for debugging)
  while (!Serial) {
    delay(10);
  }
  
  Serial.println("ESP32-S3 LED Blink Test Starting...");
  Serial.println("Board: ESP32-S3 N16R8");
  Serial.println("Built-in LED Pin: GPIO 48");
  Serial.println("External LED Pin: GPIO 2");
  
  // Configure LED pins as outputs
  pinMode(BUILTIN_LED, OUTPUT);
  pinMode(EXTERNAL_LED, OUTPUT);
  
  // Turn off both LEDs initially
  digitalWrite(BUILTIN_LED, LOW);
  digitalWrite(EXTERNAL_LED, LOW);
  
  Serial.println("Setup complete! Starting blink pattern...");
}

void loop() {
  // Turn on built-in LED, turn off external LED
  digitalWrite(BUILTIN_LED, HIGH);
  digitalWrite(EXTERNAL_LED, LOW);
  Serial.println("Built-in LED: ON, External LED: OFF");
  delay(500);  // Wait 500ms
  
  // Turn off built-in LED, turn on external LED
  digitalWrite(BUILTIN_LED, LOW);
  digitalWrite(EXTERNAL_LED, HIGH);
  Serial.println("Built-in LED: OFF, External LED: ON");
  delay(500);  // Wait 500ms
  
  // Turn off both LEDs
  digitalWrite(BUILTIN_LED, LOW);
  digitalWrite(EXTERNAL_LED, LOW);
  Serial.println("Both LEDs: OFF");
  delay(200);  // Short pause
}