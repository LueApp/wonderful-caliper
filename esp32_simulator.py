#!/usr/bin/env python3
"""
ESP32 Simulator for Sequential Measurement System

Simple simulation:
- Measures 8 data points sequentially (index 1-8)
- Each measurement takes 5 seconds
- Publishes (index, measurement_value, success_status) via MQTT
- If measurement fails, restarts from index 1
- If all 8 measurements succeed, starts next cycle from index 1
"""

import os
import sys
import json
import time
import uuid
import random
import paho.mqtt.client as mqtt

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import get_config

class ESP32Simulator:
    def __init__(self):
        self.config = get_config('esp32')
        self.client_id = f"esp32_sim_{uuid.uuid4().hex[:8]}"
        
        # MQTT client
        self.mqtt_client = None
        
        # Measurement parameters
        self.running = True
        self.measurement_interval = 5  # seconds
        self.max_measurement_index = 8  # 8 data points to measure
        
        # Current measurement state
        self.current_index = 1  # Start from index 1
        
        # Simulation parameters
        self.failure_probability = 0.15  # 15% chance of measurement failure
        self.measurement_range = (10.0, 100.0)  # Measurement value range
        
    def setup_mqtt(self):
        """Initialize MQTT client"""
        try:
            self.mqtt_client = mqtt.Client(self.client_id)
            self.mqtt_client.username_pw_set(
                self.config['emqx']['username'],
                self.config['emqx']['password']
            )
            
            # Configure SSL
            self.mqtt_client.tls_set()
            
            # Set callbacks
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_disconnect = self.on_disconnect
            
            # Connect
            self.mqtt_client.connect(
                self.config['emqx']['broker'],
                self.config['emqx']['port'],
                self.config['emqx']['keepalive']
            )
            
            self.mqtt_client.loop_start()
            print("✅ MQTT client initialized")
            return True
        except Exception as e:
            print(f"❌ MQTT setup failed: {e}")
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            print(f"🔗 ESP32 Simulator connected to MQTT broker")
            print(f"📡 Publishing to: {self.config['topics']['esp32_data']}")
        else:
            print(f"❌ MQTT connection failed with code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        print(f"🔌 ESP32 Simulator disconnected (code: {rc})")
    
    def perform_measurement(self, index):
        """Simulate a measurement at given index"""
        # Simulate measurement process
        measurement_value = round(random.uniform(*self.measurement_range), 2)
        
        # Determine if measurement is successful
        is_successful = random.random() > self.failure_probability
        
        return measurement_value, is_successful
    
    def publish_measurement_data(self, index, measurement_value, is_successful):
        """Publish measurement data to MQTT"""
        try:
            # Simple data packet with only essential data
            data_packet = {
                "device_id": self.client_id,
                "timestamp": int(time.time() * 1000),
                "int_value": index,                    # Index (1-8)
                "float_value": measurement_value,      # Measurement value
                "bool_value": is_successful            # Success status
            }
            
            # Convert to JSON
            json_data = json.dumps(data_packet)
            
            # Publish to ESP32 data topic
            result = self.mqtt_client.publish(
                self.config['topics']['esp32_data'],
                json_data,
                qos=1
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                status = "✅ OK" if is_successful else "❌ FAIL"
                print(f"📤 Index {index}/8: {measurement_value:.2f} - {status}")
                
                if not is_successful:
                    print("🔄 Measurement failed! Restarting from index 1...")
                elif index == self.max_measurement_index:
                    print("🎉 Cycle completed! Starting new cycle...")
                    
            else:
                print(f"❌ Publish failed: {result.rc}")
                
        except Exception as e:
            print(f"❌ Error publishing data: {e}")
    
    def simulate_measurement_sequence(self):
        """Main measurement simulation loop"""
        print(f"🔬 Starting measurement sequence (1-8)...")
        print(f"⏰ Measurement every {self.measurement_interval} seconds")
        print()
        
        while self.running:
            try:
                print(f"📏 Measuring data point {self.current_index}/8...")
                
                # Perform measurement
                measurement_value, is_successful = self.perform_measurement(self.current_index)
                
                # Publish measurement data
                self.publish_measurement_data(self.current_index, measurement_value, is_successful)
                
                # Update measurement index based on result
                if is_successful:
                    if self.current_index == self.max_measurement_index:
                        # Completed full cycle successfully
                        self.current_index = 1  # Start new cycle
                    else:
                        # Move to next measurement
                        self.current_index += 1
                else:
                    # Measurement failed, restart from index 1
                    self.current_index = 1
                
                # Wait for next measurement
                time.sleep(self.measurement_interval)
                
            except Exception as e:
                print(f"❌ Measurement error: {e}")
                time.sleep(5)
    
    def start_simulation(self):
        """Start the ESP32 simulation"""
        print("🚀 Starting ESP32 Sequential Measurement Simulator...")
        print("=" * 50)
        
        # Initialize MQTT connection
        if not self.setup_mqtt():
            return False
        
        # Wait for connection
        time.sleep(2)
        
        print("🤖 ESP32 Measurement Simulator is running...")
        print("📍 Press Ctrl+C to stop")
        print()
        
        try:
            # Start measurement sequence
            self.simulate_measurement_sequence()
            
        except KeyboardInterrupt:
            print("\n🛑 Simulator stopped by user")
        
        self.stop_simulation()
        return True
    
    def stop_simulation(self):
        """Stop the simulation gracefully"""
        print("\n🔄 Stopping ESP32 simulator...")
        self.running = False
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        print("✅ Simulator stopped")

def main():
    """Main function"""
    print("🤖 ESP32 Sequential Measurement Simulator")
    print("Data format: (index, measurement_value, success_status)")
    print()
    
    simulator = ESP32Simulator()
    
    try:
        simulator.start_simulation()
    except Exception as e:
        print(f"💥 Simulator error: {e}")
    finally:
        simulator.stop_simulation()

if __name__ == "__main__":
    main()