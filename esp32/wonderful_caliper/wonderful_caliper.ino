#include "my_wifi.hpp"

int btnGPIO = 0;
int btnState = false;

void setup() {
  Serial.begin(115200);
  delay(10);
  wifi_init();

  // Set GPIO0 Boot button as input
  //   pinMode(btnGPIO, INPUT);
}

void loop() {
  // Read the button state
  //   btnState = digitalRead(btnGPIO);

  //   if (btnState == LOW) {
  //     // Disconnect from WiFi
  //     Serial.println("[WiFi] Disconnecting from WiFi!");
  //     // This function will disconnect and turn off the WiFi (NVS WiFi data
  //     is kept) if (WiFi.disconnect(true, false)) {
  //       Serial.println("[WiFi] Disconnected from WiFi!");
  //     }
  //     delay(1000);
  //   }
}
