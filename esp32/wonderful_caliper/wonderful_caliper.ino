#include "my_wifi.hpp"
#include "oss_client.hpp"

// Array data storage
double arrayData[ARRAY_ROWS][MAX_ARRAY_COLS];
int arrayColumns = 0;
bool arrayDataLoaded = false;
unsigned long lastArrayUpdate = 0;

int btnGPIO = 0;
int btnState = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("===========================================");
  Serial.println("ESP32-S3 OSS Array Data Fetcher");
  Serial.println("===========================================");
  
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
}

void loop() {
  // Read button state for manual re-fetch
  btnState = digitalRead(btnGPIO);
  if (btnState == LOW) {
    Serial.println("[MAIN] 🔘 Boot button pressed - fetching latest array data...");
    fetch_array_from_oss();
    delay(1000);  // Debounce
  }
  
  // Your main application logic here
  // For example: use arrayData for calculations, motor control, etc.
  
  delay(500);  // Main loop delay
}
