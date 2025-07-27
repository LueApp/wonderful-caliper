#include "my_wifi.hpp"
#include "oss_client.hpp"
#include "tm003_sensor.hpp"
#include "oled_display.hpp"

// Array data storage
double arrayData[ARRAY_ROWS][MAX_ARRAY_COLS];
int arrayColumns = 0;
bool arrayDataLoaded = false;
unsigned long lastArrayUpdate = 0;

// TM003 sensor data
TM003SensorData sensorData;
unsigned long lastSensorRead = 0;
int currentMeasurementIndex = 0;

int btnGPIO = 0;
int btnState = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("===========================================");
  Serial.println("ESP32-S3 Wonderful Caliper with TM003 Sensor");
  Serial.println("===========================================");
  
  // Initialize OLED display first
  oled_init();
  
  // Initialize TM003 sensor
  tm003_init();
  
  // Initialize WiFi
  wifi_init();
  
  // Fetch array data from OSS after WiFi is connected
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[SETUP] WiFi connected, fetching array data from OSS...");
    fetch_array_from_oss();
  } else {
    Serial.println("[SETUP] WiFi connection failed, cannot fetch array data");
  }

  // Set GPIO0 Boot button as input (for manual re-fetch)
  pinMode(btnGPIO, INPUT);
  
  Serial.println("[SETUP] Initialization complete!");
  if (arrayDataLoaded) {
    Serial.println("[SETUP] ✅ Array data loaded successfully");
    print_array_data();
  } else {
    Serial.println("[SETUP] ❌ No array data loaded");
  }
  
  // Set zero reference position at startup
  Serial.println("[SETUP] Setting initial zero reference position...");
  if (tm003_set_zero_reference()) {
    Serial.println("[SETUP] ✅ Zero reference set successfully");
  } else {
    Serial.println("[SETUP] ⚠️  Failed to set zero reference, continuing with absolute readings");
  }
  
  Serial.println("[SETUP] TM003 sensor ready for relative measurements");
  currentMeasurementIndex = 0;
}

void loop() {
  // Read button state for manual re-fetch
  // btnState = digitalRead(btnGPIO);
  // if (btnState == LOW) {
  //   Serial.println("[MAIN] 🔘 Boot button pressed - fetching latest array data...");
  //   fetch_array_from_oss();
  //   delay(1000);  // Debounce
  // }
  
  // Read TM003 sensor measurements
  if (millis() - lastSensorRead > 125) {  // 8 Hz rate (125ms interval)
    if (tm003_read_measurement(&sensorData)) {
      // Print sensor data to serial
      tm003_print_data(&sensorData);
      
      // Prepare display data
      int display_index = -1;
      double target_value = 0.0;
      
      // Get current measurement info if array data is available
      if (arrayDataLoaded && currentMeasurementIndex < arrayColumns) {
        display_index = currentMeasurementIndex;
        target_value = arrayData[0][currentMeasurementIndex];
      }
      
      // Display measurement data on OLED with index and target
      oled_display_measurement(&sensorData, display_index, target_value);
      
      // Process measurement with array data if available
      if (arrayDataLoaded && currentMeasurementIndex < arrayColumns) {
        double expected_value = arrayData[0][currentMeasurementIndex];
        double measured_value = sensorData.displacement_mm;
        double difference = measured_value - expected_value;
        
        Serial.printf("[MEASUREMENT] Index: %d | Expected: %.2f mm | Measured: %.2f mm | Diff: %.2f mm\n",
                      currentMeasurementIndex + 1, expected_value, measured_value, difference);
        
        // Move to next measurement point
        currentMeasurementIndex++;
        if (currentMeasurementIndex >= arrayColumns) {
          Serial.println("[MEASUREMENT] ✅ Measurement sequence completed!");
          currentMeasurementIndex = 0;  // Reset for next cycle
        }
      }
      
      lastSensorRead = millis();
    } else {
      Serial.println("[MAIN] ⚠️  Failed to read TM003 sensor");
    }
  }  
  delay(50);  // Small delay for main loop
}
