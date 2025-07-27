/*
 * OSS Configuration for ESP32-S3
 * Alibaba Cloud Object Storage Service access
 */

#ifndef OSS_CONFIG_HPP
#define OSS_CONFIG_HPP

// OSS Configuration (from your config.py)
const char* OSS_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com";
const char* OSS_BUCKET_NAME = "rbcc-project";

// OSS File paths for array data
const char* OSS_LATEST_ARRAY_FILE = "arrays/latest_array.json";  // Latest array file
const char* OSS_ARRAY_FOLDER = "arrays/";                       // Array files folder

// HTTP settings
const int OSS_TIMEOUT = 10000;        // 10 seconds timeout
const int MAX_FILE_SIZE = 8192;       // Maximum file size (8KB should be enough for array data)

// Array data constraints
const int MAX_ARRAY_COLS = 20;        // Maximum N for 1×N array  
const int ARRAY_ROWS = 1;             // Always 1 row

#endif // OSS_CONFIG_HPP