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

// Button configuration
int btnGPIO = 0;           // Boot button for array data re-fetch
int btnState = false;
int compareBtnGPIO = 42;   // Comparison button connected to 3.3V
int compareBtnState = false;
int lastCompareBtnState = false;
unsigned long lastDebounceTime = 0;
unsigned long debounceDelay = 50;  // 50ms debounce delay

// Dual-color LED configuration (Red/Green LED)
int ledCommonGPIO = 4;     // Common pin (connect to VCC for common anode)
int ledControlGPIO = 5;    // Control pin (LOW=Red, HIGH=Green)

// LED states
enum LEDState {
  LED_OFF,
  LED_RED,      // Measurement failed
  LED_GREEN,    // Measurement success
  LED_BLINK_RED // Cycle restart due to failure
};

// Comparison data
bool comparisonActive = false;
float lastMeasuredValue = 0.0;
float lastTargetValue = 0.0;
int lastMeasurementIndex = -1;

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
  
  // Set GPIO42 as input for comparison button (connected to 3.3V, so INPUT_PULLDOWN)
  pinMode(compareBtnGPIO, INPUT_PULLDOWN);
  
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
  Serial.println("[SETUP] Press GPIO42 button to compare measurement with target");
  
  // Initialize LED pins
  pinMode(ledCommonGPIO, OUTPUT);
  pinMode(ledControlGPIO, OUTPUT);
  digitalWrite(ledCommonGPIO, HIGH);  // Common anode - HIGH to enable
  setLED(LED_OFF);  // Start with LED off
  
  Serial.printf("[SETUP] Dual-color LED initialized - Common: GPIO%d, Control: GPIO%d\n", 
                ledCommonGPIO, ledControlGPIO);
  
  currentMeasurementIndex = 0;
}

// LED control functions
void setLED(LEDState state) {
  switch (state) {
    case LED_OFF:
      digitalWrite(ledCommonGPIO, LOW);   // Turn off LED
      break;
    case LED_RED:
      digitalWrite(ledCommonGPIO, HIGH);  // Enable LED
      digitalWrite(ledControlGPIO, LOW);  // Red color
      break;
    case LED_GREEN:
      digitalWrite(ledCommonGPIO, HIGH);  // Enable LED
      digitalWrite(ledControlGPIO, HIGH); // Green color
      break;
    case LED_BLINK_RED:
      // Blink red 3 times
      for (int i = 0; i < 3; i++) {
        digitalWrite(ledCommonGPIO, HIGH);
        digitalWrite(ledControlGPIO, LOW);  // Red
        delay(200);
        digitalWrite(ledCommonGPIO, LOW);   // Off
        delay(200);
      }
      break;
  }
}

// Function to perform comparison between measured and target values
void performComparison() {
  // Only perform comparison if we're in an active measurement sequence
  if (!(arrayDataLoaded && currentMeasurementIndex < arrayColumns)) {
    Serial.println("[COMPARE] ❌ No active measurement sequence");
    return;
  }
  
  if (!sensorData.data_valid) {
    Serial.println("[COMPARE] ❌ No valid sensor data");
    return;
  }
  
  // Get current values
  float measured = sensorData.displacement_mm;
  float target = arrayData[0][currentMeasurementIndex];
  float difference = measured - target;
  float tolerance = 0.05; // 0.05mm tolerance
  
  // Store comparison data
  lastMeasuredValue = measured;
  lastTargetValue = target;
  lastMeasurementIndex = currentMeasurementIndex;
  comparisonActive = true;
  
  // Determine result
  bool within_tolerance = abs(difference) <= tolerance;
  
  Serial.println("=== MEASUREMENT COMPARISON ===");
  Serial.printf("[COMPARE] Point: P%d\n", currentMeasurementIndex + 1);
  Serial.printf("[COMPARE] Target:   %.2f mm\n", target);
  Serial.printf("[COMPARE] Measured: %.2f mm\n", measured);
  Serial.printf("[COMPARE] Difference: %+.2f mm\n", difference);
  Serial.printf("[COMPARE] Tolerance: ±%.2f mm\n", tolerance);
  Serial.printf("[COMPARE] Result: %s\n", within_tolerance ? "✅ PASS" : "❌ FAIL");
  Serial.println("==============================");
  
  // Display comparison result on OLED
  oled_display_comparison_result(measured, target, difference, within_tolerance);
  
  // Wait briefly to show the result
  delay(500); // Show result for 0.5 seconds
  
  // Handle measurement result and LED indication
  if (within_tolerance) {
    // Show green LED for success
    setLED(LED_GREEN);
    
    currentMeasurementIndex++;
    if (currentMeasurementIndex >= arrayColumns) {
      Serial.println("[COMPARE] 🎉 All measurements completed successfully!");
      currentMeasurementIndex = 0; // Reset for next cycle
      // Keep green LED on for completed cycle
    } else {
      Serial.printf("[COMPARE] ✅ Moving to next point: P%d\n", currentMeasurementIndex + 1);
      // Turn off LED after 1 second to prepare for next measurement
      delay(500);
      setLED(LED_OFF);
    }
  } else {
    // Show blinking red LED for failure and cycle restart
    setLED(LED_RED);
    
    Serial.printf("[COMPARE] ❌ Measurement failed at P%d - restarting cycle from P1\n", currentMeasurementIndex + 1);
    currentMeasurementIndex = 0; // Reset to start of cycle
    
    // Turn off LED after showing failure
    delay(500);
    setLED(LED_OFF);
  }
}

void loop() {
  // Read button state for manual re-fetch
  // btnState = digitalRead(btnGPIO);
  // if (btnState == LOW) {
  //   Serial.println("[MAIN] 🔘 Boot button pressed - fetching latest array data...");
  //   fetch_array_from_oss();
  //   delay(1000);  // Debounce
  // }
  
  // Handle comparison button with debouncing
  int reading = digitalRead(compareBtnGPIO);
  
  if (reading != lastCompareBtnState) {
    lastDebounceTime = millis();
  }
  
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != compareBtnState) {
      compareBtnState = reading;
      
      // Button pressed (HIGH because connected to 3.3V)
      if (compareBtnState == HIGH) {
        Serial.println("[MAIN] 🔘 Comparison button pressed!");
        performComparison();
      }
    }
  }
  
  lastCompareBtnState = reading;
  
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
      
      lastSensorRead = millis();
    } else {
      Serial.println("[MAIN] ⚠️  Failed to read TM003 sensor");
    }
  }  
  delay(50);  // Small delay for main loop
}
