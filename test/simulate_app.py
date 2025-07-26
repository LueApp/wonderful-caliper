#!/usr/bin/env python3
"""
Example 1: APP Simulation
Simulates Android application behavior:
1. Upload a local photo file to OSS
2. Notify algorithm service via MQTT
3. Wait for processed result (photo + array)
4. Display results
"""

import os
import sys
import json
import time
import uuid
import threading
from datetime import datetime
import oss2
import paho.mqtt.client as mqtt

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_config

class AppSimulator:
    def __init__(self):
        self.config = get_config('app')  # Use 'app' program type
        self.client_id = f"{self.config['emqx']['client_id_prefix']}_app_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = None
        self.oss_bucket = None
        self.processed_result = None
        self.waiting_for_result = False
        
    def setup_oss(self):
        """Initialize OSS client and bucket"""
        try:
            auth = oss2.Auth(
                self.config['oss']['access_key_id'],
                self.config['oss']['access_key_secret']
            )
            self.oss_bucket = oss2.Bucket(
                auth, 
                self.config['oss']['endpoint'], 
                self.config['oss']['bucket_name']
            )
            print("✅ OSS client initialized")
        except Exception as e:
            print(f"❌ OSS setup failed: {e}")
            return False
        return True
    
    def setup_mqtt(self):
        """Initialize MQTT client and callbacks"""
        try:
            self.mqtt_client = mqtt.Client(self.client_id)
            self.mqtt_client.username_pw_set(
                self.config['emqx']['username'],
                self.config['emqx']['password']
            )
            
            # Configure SSL/TLS if using port 8883
            if self.config['emqx']['port'] == 8883:
                self.mqtt_client.tls_set()
                print("🔐 SSL/TLS enabled for MQTT connection")
            
            # Set callbacks
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect
            
            # Connect to EMQX Cloud
            print(f"🔗 Connecting to {self.config['emqx']['broker']}:{self.config['emqx']['port']}")
            print(f"👤 Username: {self.config['emqx']['username']}")
            
            self.mqtt_client.connect(
                self.config['emqx']['broker'],
                self.config['emqx']['port'],
                self.config['emqx']['keepalive']
            )
            
            # Start MQTT loop in background thread
            self.mqtt_client.loop_start()
            print("✅ MQTT client initialized")
        except Exception as e:
            print(f"❌ MQTT setup failed: {e}")
            return False
        return True
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            print(f"🔗 Connected to MQTT broker")
            # Subscribe to processed result notifications
            client.subscribe(self.config['topics']['app_notifications'])
            print(f"📡 Subscribed to: {self.config['topics']['app_notifications']}")
        else:
            print(f"❌ MQTT connection failed with code {rc}")
            if rc == 1:
                print("   Error: Connection refused - incorrect protocol version")
            elif rc == 2:
                print("   Error: Connection refused - invalid client identifier")
            elif rc == 3:
                print("   Error: Connection refused - server unavailable")
            elif rc == 4:
                print("   Error: Connection refused - bad username or password")
            elif rc == 5:
                print("   Error: Connection refused - not authorized")
                print("   💡 Check your EMQX credentials in config.py")
            elif rc == 7:
                print("   Error: Connection refused - authentication failed")
                print("   💡 Verify username/password in EMQX dashboard")
    
    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            print(f"📨 Received message on topic: {topic}")
            print(f"📄 Payload: {json.dumps(payload, indent=2)}")
            
            if topic == self.config['topics']['app_notifications']:
                if payload.get('type') == 'processing_complete':
                    self.processed_result = payload
                    self.waiting_for_result = False
                    print("🎉 Processing complete notification received!")
                    
        except Exception as e:
            print(f"❌ Error processing message: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        print(f"🔌 Disconnected from MQTT broker (code: {rc})")
    
    def upload_file(self, file_path):
        """Upload file to OSS and notify algorithm service"""
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return None
        
        try:
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = os.path.splitext(file_path)[1]
            oss_key = f"uploads/{timestamp}_{uuid.uuid4().hex[:8]}{file_extension}"
            
            # Upload to OSS
            print(f"📤 Uploading {file_path} to OSS...")
            with open(file_path, 'rb') as file_obj:
                self.oss_bucket.put_object(oss_key, file_obj)
            
            print(f"✅ File uploaded successfully: {oss_key}")
            
            # Notify algorithm service via MQTT
            notification = {
                "type": "file_uploaded",
                "oss_key": oss_key,
                "original_filename": os.path.basename(file_path),
                "timestamp": timestamp,
                "client_id": self.client_id
            }
            
            self.mqtt_client.publish(
                self.config['topics']['app_file_uploaded'],
                json.dumps(notification)
            )
            
            print(f"📡 Notification sent to algorithm service")
            return oss_key
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            return None
    
    def wait_for_processing(self, timeout=60):
        """Wait for algorithm service to process the file"""
        print(f"⏳ Waiting for processing result (timeout: {timeout}s)...")
        self.waiting_for_result = True
        self.processed_result = None
        
        start_time = time.time()
        while self.waiting_for_result and (time.time() - start_time) < timeout:
            time.sleep(1)
        
        if self.processed_result:
            return self.processed_result
        else:
            print("⏰ Timeout waiting for processing result")
            return None
    
    def download_processed_files(self, result_data):
        """Download processed photo and array from OSS"""
        try:
            processed_photo_key = result_data.get('processed_photo_key')
            array_data = result_data.get('array_data')
            
            if processed_photo_key:
                # Download processed photo
                local_photo_path = f"../processed/{os.path.basename(processed_photo_key)}"
                os.makedirs("../processed", exist_ok=True)
                
                print(f"📥 Downloading processed photo...")
                self.oss_bucket.get_object_to_file(processed_photo_key, local_photo_path)
                print(f"✅ Processed photo saved: {local_photo_path}")
            
            if array_data:
                # Save array data
                array_file_path = f"../processed/array_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(array_file_path, 'w') as f:
                    json.dump(array_data, f, indent=2)
                print(f"✅ Array data saved: {array_file_path}")
                print(f"📊 Array shape: {len(array_data)} x {len(array_data[0]) if array_data else 0}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error downloading processed files: {e}")
            return False
    
    def simulate_app_workflow(self, file_path="test_image.png"):
        """Main workflow simulation"""
        print("🚀 Starting APP simulation...")
        print("=" * 50)
        
        # Initialize connections
        if not self.setup_oss():
            return False
        if not self.setup_mqtt():
            return False
        
        # Wait for MQTT connection
        time.sleep(2)
        
        # Upload file
        oss_key = self.upload_file(file_path)
        if not oss_key:
            return False
        
        # Wait for processing
        result = self.wait_for_processing(timeout=120)
        if not result:
            return False
        
        # Download processed files
        success = self.download_processed_files(result)
        
        print("=" * 50)
        if success:
            print("🎉 APP simulation completed successfully!")
        else:
            print("❌ APP simulation completed with errors")
        
        return success
    
    def cleanup(self):
        """Clean up connections"""
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        print("🧹 Cleanup completed")

def main():
    """Main function"""
    app = AppSimulator()
    
    try:
        success = app.simulate_app_workflow()
        if success:
            print("\n✨ All done! Check the 'processed' folder for results.")
        else:
            print("\n💥 Simulation failed. Check the error messages above.")
    
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    
    finally:
        app.cleanup()

if __name__ == "__main__":
    main()