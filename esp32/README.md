# ESP32-S3 Development Setup

This folder contains ESP32-S3 Arduino code for the IoT project.

## Hardware Requirements

- **Board**: ESP32-S3-DevKitC-1 (N16R8) or compatible
- **Built-in LED**: GPIO 48 (RGB LED)
- **External LED**: Connect to GPIO 2 with 220Ω resistor

## Circuit Diagram (Optional External LED)

```
ESP32-S3 GPIO 2 ----[220Ω]----[LED]----GND
```

## VS Code Setup Instructions

### 1. Install Required Extensions

1. Open VS Code
2. Install these extensions:
   - **Arduino** (by Microsoft)
   - **C/C++** (by Microsoft) 
   - **Serial Monitor** (by Microsoft)

### 2. Install Arduino CLI (if not already installed)

```bash
# Download and install Arduino CLI
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

# Add to PATH (add to ~/.bashrc)
export PATH=$PATH:~/bin
```

### 3. Install ESP32 Board Package

1. Open Command Palette (Ctrl+Shift+P)
2. Run: `Arduino: Board Manager`
3. Search for "ESP32" 
4. Install "esp32 by Espressif Systems"

Or via Arduino CLI:
```bash
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### 4. Configure Board Settings

1. Open Command Palette (Ctrl+Shift+P)
2. Run: `Arduino: Board Config`
3. Select: **ESP32S3 Dev Module**
4. Configure settings:
   - **PSRAM**: Enabled
   - **Flash Size**: 16MB
   - **Partition Scheme**: Huge APP (3MB No OTA/1MB SPIFFS)
   - **CPU Frequency**: 240MHz
   - **Upload Speed**: 921600

### 5. Select Port

1. Connect ESP32-S3 via USB
2. Open Command Palette (Ctrl+Shift+P)
3. Run: `Arduino: Select Serial Port`
4. Choose your ESP32 port (usually `/dev/ttyACM0` or `/dev/ttyUSB0`)

## Quick Test

1. Open `led_blink_test.ino` in VS Code
2. Press **Ctrl+Shift+P** → `Arduino: Verify`
3. Press **Ctrl+Shift+P** → `Arduino: Upload`
4. Open Serial Monitor to see output

## Expected Behavior

- Built-in RGB LED blinks every 500ms
- External LED (if connected) blinks alternately
- Serial output shows LED status at 115200 baud

## Troubleshooting

### Upload Issues
- Try holding BOOT button while uploading
- Check USB cable (data cable, not charge-only)
- Verify port selection

### LED Not Working
- Built-in LED pin may vary (try GPIO 21, 47, or 48)
- Check external LED polarity and resistor

### Serial Monitor Issues
- Ensure baud rate is 115200
- Press EN (reset) button to restart output

## Next Steps

After verifying the LED blink works:
1. Add WiFi connectivity
2. Add MQTT client
3. Integrate with IoT system