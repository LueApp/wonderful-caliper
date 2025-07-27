#ifndef TM003_SENSOR_HPP
#define TM003_SENSOR_HPP

#include <Arduino.h>

// GPIO pin definitions for TM003 sensor
#define TM003_DATA_PIN    1   // GPIO1 - SDATA from TM003
#define TM003_CLOCK_PIN   2   // GPIO2 - SCLK from TM003

// TM003 sensor constants from website
#define TM003_MIN_START_TIME  100000   // 100ms start pulse minimum
#define TM003_MAX_START_TIME  500000   // 500ms start pulse maximum

// Bit manipulation constants from original code
#define TM003_SET_MSB         0x00800000  // Set most significant bit
#define TM003_CLEAR_MSB       0xFF7FFFFF  // Clear most significant bit  
#define TM003_SIGN_MASK       0x00100000  // Check sign bit (bit 20)
#define TM003_DATA_MASK       0x000FFFFF  // Extract 20-bit data

// TM003 specifications
#define TM003_TOTAL_BITS      24      // 24 bits total transmission
#define TM003_DATA_BITS       20      // First 20 bits are measurement data
#define TM003_FLAG_BITS       4       // Last 4 bits are flags
#define TM003_RESOLUTION      0.01    // 0.01mm resolution
#define TM003_DISPLAY_RATE    8       // 8 times/second

// Sensor data structure
struct TM003SensorData {
  float displacement_mm;       // Displacement in millimeters (relative to zero position)
  float absolute_displacement; // Absolute displacement from sensor
  unsigned long raw_data;      // Complete 24-bit raw data
  unsigned long result_data;   // 20-bit measurement data
  bool negative_flag;          // Sign of measurement
  bool data_valid;            // Reading validity
  unsigned long timestamp;    // Reading timestamp
};

// Zero reference variables
static float zero_reference_mm = 0.0;
static bool zero_reference_set = false;

// Function declarations
void tm003_init();
bool tm003_check_start();
void tm003_get_data(unsigned long* raw_data);
bool tm003_read_measurement(TM003SensorData* sensor_data);
bool tm003_set_zero_reference();
void tm003_reset_zero_reference();
void tm003_print_data(const TM003SensorData* data);

// Initialize TM003 sensor
void tm003_init() {
  Serial.println("[TM003] Initializing TM003 capacitive displacement sensor...");
  
  // Configure GPIO pins as inputs (sensor actively transmits)
  pinMode(TM003_CLOCK_PIN, INPUT);   // SCLK from sensor
  pinMode(TM003_DATA_PIN, INPUT);    // SDATA from sensor
  
  // Allow sensor to stabilize
  delay(200);
  
  Serial.printf("[TM003] ✅ Sensor initialized\n");
  Serial.printf("[TM003] Clock pin (SCLK): GPIO%d (INPUT)\n", TM003_CLOCK_PIN);
  Serial.printf("[TM003] Data pin (SDATA): GPIO%d (INPUT)\n", TM003_DATA_PIN);
  Serial.printf("[TM003] Resolution: %.2f mm\n", TM003_RESOLUTION);
  Serial.printf("[TM003] Display rate: %d Hz\n", TM003_DISPLAY_RATE);
  Serial.println("[TM003] Waiting for start pulse...");
}

// Check for valid start pulse (100-500ms HIGH on SCLK) with timeout
bool tm003_check_start() {
  unsigned long check_timeout = millis() + 2000; // 2 second timeout
  
  while (millis() < check_timeout) {
    unsigned long start_duration = pulseIn(TM003_CLOCK_PIN, HIGH, 200000); // 200ms timeout per attempt
    
    if (start_duration >= TM003_MIN_START_TIME && start_duration <= TM003_MAX_START_TIME) {
      return true; // Valid start pulse found
    }
    
    if (start_duration == 0) {
      // No pulse detected, try again
      delay(10);
    }
  }
  
  return false; // Timeout - no valid start pulse found
}

// Get 24-bit data using exact algorithm from website
void tm003_get_data(unsigned long* raw_data) {
  if (!raw_data) return;
  
  *raw_data = 0;
  
  for (int i = 0; i < TM003_TOTAL_BITS; i++) {
    // Right shift first (key difference from my previous implementation)
    *raw_data = *raw_data >> 1;
    
    // Wait for clock to go HIGH
    bool tmp_clk = digitalRead(TM003_CLOCK_PIN);
    while (tmp_clk == false) {
      tmp_clk = digitalRead(TM003_CLOCK_PIN);
    }
    
    // Read data when clock is HIGH
    bool tmp_data = digitalRead(TM003_DATA_PIN);
    if (tmp_data == true) {
      *raw_data = *raw_data | TM003_SET_MSB;     // Set MSB if data is 1
    } else {
      *raw_data = *raw_data & TM003_CLEAR_MSB;   // Clear MSB if data is 0
    }
    
    // Wait for clock to go LOW
    while (tmp_clk == true) {
      tmp_clk = digitalRead(TM003_CLOCK_PIN);
    }
  }
}

// Read complete measurement from TM003 sensor
bool tm003_read_measurement(TM003SensorData* sensor_data) {
  if (!sensor_data) return false;
  
  // Check for valid start pulse with timeout
  if (!tm003_check_start()) {
    sensor_data->data_valid = false;
    return false;
  }
  
  // Get 24-bit data
  tm003_get_data(&sensor_data->raw_data);
  
  // Process the data exactly like the website code
  sensor_data->negative_flag = (sensor_data->raw_data & TM003_SIGN_MASK) != 0;
  sensor_data->result_data = sensor_data->raw_data & TM003_DATA_MASK;
  
  // Convert to absolute displacement
  sensor_data->absolute_displacement = (float)sensor_data->result_data * TM003_RESOLUTION;
  if (sensor_data->negative_flag) {
    sensor_data->absolute_displacement = -sensor_data->absolute_displacement;
  }
  
  // Calculate relative displacement from zero reference
  if (zero_reference_set) {
    sensor_data->displacement_mm = sensor_data->absolute_displacement - zero_reference_mm;
  } else {
    sensor_data->displacement_mm = sensor_data->absolute_displacement;
  }
  
  sensor_data->data_valid = true;
  sensor_data->timestamp = millis();
  
  return true;
}

// Set current position as zero reference
bool tm003_set_zero_reference() {
  TM003SensorData temp_data;
  
  Serial.println("[TM003] Setting zero reference position...");
  
  // Take several readings to get stable reference
  float readings[5];
  int valid_readings = 0;
  
  for (int i = 0; i < 5; i++) {
    if (tm003_read_measurement(&temp_data)) {
      readings[valid_readings] = temp_data.absolute_displacement;
      valid_readings++;
      Serial.printf("[TM003] Reference reading %d: %.2f mm\n", i+1, temp_data.absolute_displacement);
    }
    delay(150); // Wait between readings
  }
  
  if (valid_readings >= 3) {
    // Calculate average of valid readings
    float sum = 0;
    for (int i = 0; i < valid_readings; i++) {
      sum += readings[i];
    }
    zero_reference_mm = sum / valid_readings;
    zero_reference_set = true;
    
    Serial.printf("[TM003] ✅ Zero reference set to: %.2f mm (avg of %d readings)\n", 
                  zero_reference_mm, valid_readings);
    return true;
  } else {
    Serial.println("[TM003] ❌ Failed to set zero reference - insufficient valid readings");
    return false;
  }
}

// Reset zero reference
void tm003_reset_zero_reference() {
  zero_reference_mm = 0.0;
  zero_reference_set = false;
  Serial.println("[TM003] Zero reference reset");
}

// Print sensor data to serial monitor
void tm003_print_data(const TM003SensorData* data) {
  if (!data) return;
  
  if (data->data_valid) {
    if (zero_reference_set) {
      Serial.printf("[TM003] Relative: %+.2f mm | Absolute: %+.2f mm | Raw: 0x%06lX | Zero: %.2f mm\n",
                    data->displacement_mm,
                    data->absolute_displacement,
                    data->raw_data,
                    zero_reference_mm);
    } else {
      Serial.printf("[TM003] Displacement: %+.2f mm | Raw: 0x%06lX | Data: 0x%05lX | Sign: %s\n",
                    data->displacement_mm,
                    data->raw_data,
                    data->result_data,
                    data->negative_flag ? "NEG" : "POS");
    }
  } else {
    Serial.println("[TM003] ❌ Failed to read sensor data");
  }
}

#endif // TM003_SENSOR_HPP