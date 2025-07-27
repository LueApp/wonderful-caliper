#ifndef OLED_DISPLAY_HPP
#define OLED_DISPLAY_HPP

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "tm003_sensor.hpp"

// OLED display configuration
#define OLED_WIDTH        128    // OLED display width in pixels
#define OLED_HEIGHT       32     // OLED display height in pixels (0.91" is usually 32)
#define OLED_RESET        -1     // Reset pin (not used, set to -1)
#define OLED_ADDRESS      0x3C   // I2C address for 0.91" OLED

// I2C pin configuration
#define OLED_SDA_PIN      8      // GPIO8 - SDA pin
#define OLED_SCL_PIN      9      // GPIO9 - SCL pin

// Display globals
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);
bool oled_initialized = false;

// Function declarations
void oled_init();
void oled_display_measurement(const TM003SensorData* data, int current_index = -1, double target_value = 0.0);
void oled_clear();

// Initialize OLED display
void oled_init() {
  Serial.println("[OLED] Initializing 0.91\" OLED display...");
  
  // Initialize I2C with custom pins
  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  Wire.setClock(400000); // 400kHz I2C speed
  
  // Initialize display
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    Serial.println("[OLED] ❌ Failed to initialize SSD1306 display");
    oled_initialized = false;
    return;
  }
  
  // Clear display and set defaults
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("TM003 Caliper");
  display.println("Ready...");
  display.display();
  
  oled_initialized = true;
  
  Serial.printf("[OLED] ✅ Display initialized at address 0x%02X\n", OLED_ADDRESS);
  Serial.printf("[OLED] I2C pins - SDA: GPIO%d, SCL: GPIO%d\n", OLED_SDA_PIN, OLED_SCL_PIN);
  Serial.printf("[OLED] Resolution: %dx%d pixels\n", OLED_WIDTH, OLED_HEIGHT);
}

// Display measurement data with index and target
void oled_display_measurement(const TM003SensorData* data, int current_index, double target_value) {
  if (!oled_initialized || !data) return;
  
  display.clearDisplay();
  
  if (data->data_valid) {
    // Display relative displacement (main measurement)
    display.setTextSize(2);
    display.setCursor(0, 0);
    display.printf("%+.2f", data->displacement_mm);
    
    // Display "mm" unit
    display.setTextSize(1);
    display.setCursor(90, 8);
    display.println("mm");
    
    // Display measurement index and target on second line
    display.setTextSize(1);
    display.setCursor(0, 24);
    if (current_index >= 0) {
      display.printf("P%d Target: %.2f", current_index + 1, target_value);
    } else {
      display.printf("Ready to measure");
    }
    
  } else {
    // Display error message
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("Sensor Error");
    display.println("No Data");
  }
  
  display.display();
}

// Clear display
void oled_clear() {
  if (!oled_initialized) return;
  display.clearDisplay();
  display.display();
}

#endif // OLED_DISPLAY_HPP