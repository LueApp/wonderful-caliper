#!/usr/bin/env python3
"""
Test Complete IoT System

Tests the complete data flow:
ESP32 Simulator → MQTT → Data Processing Service → OSS

This script helps verify all components work together.
"""

import os
import sys
import time
import subprocess
import threading
from datetime import datetime

def run_service(script_path, service_name):
    """Run a service in a separate process"""
    print(f"🚀 Starting {service_name}...")
    try:
        # Run the script
        process = subprocess.Popen([
            sys.executable, script_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Print output
        for line in iter(process.stdout.readline, ''):
            if line.strip():
                print(f"[{service_name}] {line.strip()}")
        
        process.wait()
        print(f"❌ {service_name} stopped")
        
    except Exception as e:
        print(f"💥 Error running {service_name}: {e}")

def main():
    """Main test function"""
    print("🧪 Complete IoT System Test")
    print("=" * 50)
    print()
    print("This test will:")
    print("1. Start Data Processing Service")
    print("2. Start ESP32 Simulator") 
    print("3. Monitor data flow for 2 minutes")
    print("4. Check OSS for analysis results")
    print()
    
    input("Press Enter to start the test...")
    print()
    
    # Get parent directory paths
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_processing_script = os.path.join(parent_dir, "data_processing_service.py")
    esp32_simulator_script = os.path.join(parent_dir, "esp32_simulator.py")
    
    # Check if scripts exist
    if not os.path.exists(data_processing_script):
        print(f"❌ Data processing script not found: {data_processing_script}")
        return
    
    if not os.path.exists(esp32_simulator_script):
        print(f"❌ ESP32 simulator script not found: {esp32_simulator_script}")
        return
    
    # Start data processing service in background
    processing_thread = threading.Thread(
        target=run_service, 
        args=(data_processing_script, "DataProcessor"),
        daemon=True
    )
    processing_thread.start()
    
    # Wait a bit for processing service to start
    time.sleep(5)
    
    # Start ESP32 simulator in background
    simulator_thread = threading.Thread(
        target=run_service,
        args=(esp32_simulator_script, "ESP32Simulator"),
        daemon=True
    )
    simulator_thread.start()
    
    print("🔄 Both services started. Monitoring for 2 minutes...")
    print("📍 Press Ctrl+C to stop early")
    
    try:
        # Monitor for 2 minutes
        for i in range(24):  # 2 minutes = 24 * 5 seconds
            time.sleep(5)
            minutes = (i + 1) * 5 / 60
            print(f"⏰ Running for {minutes:.1f} minutes...")
    
    except KeyboardInterrupt:
        print("\n🛑 Test stopped by user")
    
    print()
    print("✅ Test completed!")
    print()
    print("🔍 Check results:")
    print("1. OSS Console → rbcc-project bucket → analysis/ folder")
    print("2. Look for latest_analysis.json file")
    print("3. OSS Console → rbcc-project bucket → data/ folder") 
    print("4. Look for historical_data.json file")
    print()
    print("Expected data flow:")
    print("ESP32 Simulator → MQTT → Data Processing → OSS Analysis")

if __name__ == "__main__":
    main()