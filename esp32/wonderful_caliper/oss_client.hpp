/*
 * OSS Client for ESP32-S3
 * Fetches array data from Alibaba Cloud OSS
 */

#ifndef OSS_CLIENT_HPP
#define OSS_CLIENT_HPP

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "oss_config.hpp"

// External variables (defined in main .ino file)
extern double arrayData[ARRAY_ROWS][MAX_ARRAY_COLS];
extern int arrayColumns;
extern bool arrayDataLoaded;
extern unsigned long lastArrayUpdate;

// Function declarations
bool fetch_array_from_oss();
bool parse_array_data(const String& jsonString);
void print_array_data();
double get_array_value(int row, int col);
int get_array_columns();
bool is_array_loaded();
bool fetch_latest_array_file();

// Function implementations

// Parse JSON array data
bool parse_array_data(const String& jsonString) {
  Serial.println("[OSS] Parsing JSON array data...");
  Serial.println("[OSS] JSON: " + jsonString);
  
  // Create JSON document
  DynamicJsonDocument doc(2048);
  
  // Parse JSON
  DeserializationError error = deserializeJson(doc, jsonString);
  if (error) {
    Serial.println("[OSS] JSON parsing failed: " + String(error.c_str()));
    return false;
  }
  
  // Check if it's an array
  if (!doc.is<JsonArray>()) {
    Serial.println("[OSS] JSON is not an array");
    return false;
  }
  
  JsonArray array = doc.as<JsonArray>();
  
  // Check array dimensions (should be 1 row)
  if (array.size() != ARRAY_ROWS) {
    Serial.println("[OSS] Invalid array rows: " + String(array.size()) + " (expected 1)");
    return false;
  }
  
  // Parse the single row
  JsonArray rowArray = array[0];  // First (and only) row
  
  int cols = rowArray.size();
  if (cols > MAX_ARRAY_COLS) {
    Serial.println("[OSS] Too many columns: " + String(cols) + " (max " + String(MAX_ARRAY_COLS) + ")");
    return false;
  }
  arrayColumns = cols;
  
  // Copy data to array (row 0)
  for (int col = 0; col < cols; col++) {
    if (rowArray[col].is<float>() || rowArray[col].is<double>() || rowArray[col].is<int>()) {
      arrayData[0][col] = rowArray[col].as<double>();
    } else {
      Serial.println("[OSS] Invalid data type at [0][" + String(col) + "]");
      return false;
    }
  }
  
  Serial.println("[OSS] Array parsed successfully: " + String(ARRAY_ROWS) + "×" + String(arrayColumns));
  return true;
}

// Function to fetch array data from OSS
bool fetch_array_from_oss() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[OSS] WiFi not connected");
    return false;
  }
  
  Serial.println("[OSS] Fetching array data from OSS...");
  Serial.println("[OSS] Bucket: " + String(OSS_BUCKET_NAME));
  Serial.println("[OSS] File: " + String(OSS_LATEST_ARRAY_FILE));
  
  HTTPClient http;
  WiFiClientSecure client;
  
  // Skip SSL certificate verification for simplicity
  client.setInsecure();
  
  // Construct OSS URL
  String url = "https://" + String(OSS_BUCKET_NAME) + "." + String(OSS_ENDPOINT) + "/" + String(OSS_LATEST_ARRAY_FILE);
  Serial.println("[OSS] URL: " + url);
  
  // Start HTTP request
  http.begin(client, url);
  http.setTimeout(OSS_TIMEOUT);
  
  // Add User-Agent header
  http.addHeader("User-Agent", "ESP32-OSS-Client/1.0");
  
  int httpCode = http.GET();
  
  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();
    Serial.println("[OSS] ✅ File downloaded successfully");
    Serial.println("[OSS] File size: " + String(payload.length()) + " bytes");
    
    // Parse the JSON array data
    bool parseSuccess = parse_array_data(payload);
    
    http.end();
    
    if (parseSuccess) {
      arrayDataLoaded = true;
      lastArrayUpdate = millis();
      Serial.println("[OSS] ✅ Array data parsed and loaded");
      return true;
    } else {
      Serial.println("[OSS] ❌ Failed to parse array data");
      return false;
    }
    
  } else if (httpCode == HTTP_CODE_NOT_FOUND) {
    Serial.println("[OSS] ❌ Array file not found (404)");
    Serial.println("[OSS] Make sure the algorithm service has created the file");
    
  } else if (httpCode == HTTP_CODE_FORBIDDEN) {
    Serial.println("[OSS] ❌ Access forbidden (403)");
    Serial.println("[OSS] Check OSS bucket permissions");
    
  } else {
    Serial.println("[OSS] ❌ HTTP error: " + String(httpCode));
    if (httpCode > 0) {
      String errorResponse = http.getString();
      Serial.println("[OSS] Response: " + errorResponse);
    }
  }
  
  http.end();
  return false;
}

// Print array data to serial
void print_array_data() {
  if (!arrayDataLoaded || arrayColumns == 0) {
    Serial.println("[ARRAY] No array data loaded");
    return;
  }
  
  Serial.println("[ARRAY] Current array data (" + String(ARRAY_ROWS) + "×" + String(arrayColumns) + "):");
  
  // Print the single row
  Serial.print("[ARRAY] Data: [");
  for (int col = 0; col < arrayColumns; col++) {
    Serial.print(String(arrayData[0][col], 6));
    if (col < arrayColumns - 1) Serial.print(", ");
  }
  Serial.println("]");
  
  Serial.println("[ARRAY] Last updated: " + String(lastArrayUpdate / 1000) + " seconds ago");
}

// Get specific value from array
double get_array_value(int row, int col) {
  if (!arrayDataLoaded || row >= ARRAY_ROWS || col >= arrayColumns || row < 0 || col < 0) {
    Serial.println("[ARRAY] Invalid array access: [" + String(row) + "][" + String(col) + "]");
    return 0.0;
  }
  return arrayData[row][col];
}

// Get array column count
int get_array_columns() {
  return arrayColumns;
}

// Check if array data is loaded
bool is_array_loaded() {
  return arrayDataLoaded;
}

// Alternative: Fetch latest array file by scanning the arrays/ folder
bool fetch_latest_array_file() {
  // This would require listing OSS objects and finding the newest one
  // For simplicity, we assume a fixed filename for now
  return fetch_array_from_oss();
}

#endif // OSS_CLIENT_HPP