#!/usr/bin/env python3
"""
Example 2: Algorithm Service Simulation
Simulates algorithm service behavior:
1. Listen for file upload notifications via MQTT
2. Download the uploaded file from OSS
3. Process the file (simple modification + generate array)
4. Upload processed results back to OSS
5. Notify APP via MQTT
"""

import os
import sys
import json
import time
import uuid
import numpy as np
from datetime import datetime
from PIL import Image, ImageFilter, ImageEnhance
import oss2
import paho.mqtt.client as mqtt

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_config

class AlgorithmService:
    def __init__(self):
        self.config = get_config('algorithm')  # Use 'algorithm' program type
        self.client_id = f"{self.config['emqx']['client_id_prefix']}_algo_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = None
        self.oss_bucket = None
        self.processing_queue = []
        
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
            # Subscribe to file upload notifications
            client.subscribe(self.config['topics']['app_file_uploaded'])
            print(f"📡 Subscribed to: {self.config['topics']['app_file_uploaded']}")
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
            
            if topic == self.config['topics']['app_file_uploaded']:
                if payload.get('type') == 'file_uploaded':
                    print("🎯 New file upload detected!")
                    self.processing_queue.append(payload)
                    self.process_file(payload)
                    
        except Exception as e:
            print(f"❌ Error processing message: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        print(f"🔌 Disconnected from MQTT broker (code: {rc})")
    
    def download_file(self, oss_key):
        """Download file from OSS"""
        try:
            # Create temp directory if it doesn't exist
            os.makedirs("../temp", exist_ok=True)
            
            # Local file path
            local_path = f"../temp/{os.path.basename(oss_key)}"
            
            print(f"📥 Downloading {oss_key} from OSS...")
            self.oss_bucket.get_object_to_file(oss_key, local_path)
            print(f"✅ File downloaded: {local_path}")
            
            return local_path
            
        except Exception as e:
            print(f"❌ Download failed: {e}")
            return None
    
    def process_image(self, image_path):
        """Process the image with simple modifications"""
        try:
            print(f"🖼️ Processing image: {image_path}")
            
            # Open image
            with Image.open(image_path) as img:
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Apply simple processing effects
                # 1. Enhance contrast
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.2)
                
                # 2. Apply slight blur for smoothing
                img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
                
                # 3. Enhance brightness slightly
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(1.1)
                
                # Save processed image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                processed_filename = f"processed_{timestamp}_{os.path.basename(image_path)}"
                processed_path = f"../temp/{processed_filename}"
                
                img.save(processed_path, quality=95)
                print(f"✅ Image processed and saved: {processed_path}")
                
                return processed_path, img.size
                
        except Exception as e:
            print(f"❌ Image processing failed: {e}")
            return None, None
    
    def generate_array(self, image_size, rows=10):
        """Generate a 2*N double array based on image processing"""
        try:
            print(f"📊 Generating {2}x{rows} array...")
            
            # Generate meaningful array data based on image properties
            width, height = image_size
            aspect_ratio = width / height
            
            # Create array with two rows and N columns
            array_data = []
            
            # Row 1: Position-based values (normalized coordinates)
            row1 = []
            # Row 2: Feature-based values (simulated features)
            row2 = []
            
            for i in range(rows):
                # Row 1: Normalized position values
                pos_value = (i / (rows - 1)) * aspect_ratio
                row1.append(round(pos_value, 6))
                
                # Row 2: Simulated feature values based on image characteristics
                feature_value = np.sin(2 * np.pi * i / rows) * (width + height) / 1000
                row2.append(round(feature_value, 6))
            
            array_data = [row1, row2]
            
            print(f"✅ Array generated: {len(array_data)} x {len(array_data[0])}")
            print(f"📈 Sample values: [{array_data[0][0]:.3f}, {array_data[1][0]:.3f}] to [{array_data[0][-1]:.3f}, {array_data[1][-1]:.3f}]")
            
            return array_data
            
        except Exception as e:
            print(f"❌ Array generation failed: {e}")
            return None
    
    def upload_processed_files(self, processed_image_path, array_data):
        """Upload processed files back to OSS"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results = {}
            
            # Upload processed image
            if processed_image_path and os.path.exists(processed_image_path):
                image_key = f"processed/{timestamp}_{os.path.basename(processed_image_path)}"
                
                print(f"📤 Uploading processed image to OSS...")
                with open(processed_image_path, 'rb') as file_obj:
                    self.oss_bucket.put_object(image_key, file_obj)
                
                results['processed_photo_key'] = image_key
                print(f"✅ Processed image uploaded: {image_key}")
            
            # Upload array data as JSON
            if array_data:
                array_key = f"arrays/{timestamp}_array.json"
                array_json = json.dumps(array_data)
                
                print(f"📤 Uploading array data to OSS...")
                self.oss_bucket.put_object(array_key, array_json)
                
                results['array_key'] = array_key
                results['array_data'] = array_data
                print(f"✅ Array data uploaded: {array_key}")
            
            return results
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            return None
    
    def notify_completion(self, original_request, processing_results):
        """Notify APP that processing is complete"""
        try:
            notification = {
                "type": "processing_complete",
                "original_request": original_request,
                "timestamp": datetime.now().isoformat(),
                "processing_results": processing_results,
                "processed_photo_key": processing_results.get('processed_photo_key'),
                "array_key": processing_results.get('array_key'),
                "array_data": processing_results.get('array_data'),
                "processor_id": self.client_id
            }
            
            # Send notification to APP
            self.mqtt_client.publish(
                self.config['topics']['app_notifications'],
                json.dumps(notification)
            )
            
            print(f"📡 Processing completion notification sent to APP")
            return True
            
        except Exception as e:
            print(f"❌ Notification failed: {e}")
            return False
    
    def process_file(self, file_notification):
        """Main file processing workflow"""
        print("🔄 Starting file processing...")
        print("=" * 50)
        
        try:
            oss_key = file_notification.get('oss_key')
            if not oss_key:
                print("❌ No OSS key in notification")
                return False
            
            # Download file from OSS
            local_file_path = self.download_file(oss_key)
            if not local_file_path:
                return False
            
            # Process the image
            processed_path, image_size = self.process_image(local_file_path)
            if not processed_path:
                return False
            
            # Generate array data
            array_data = self.generate_array(image_size, rows=8)
            if array_data is None:
                return False
            
            # Upload processed results
            results = self.upload_processed_files(processed_path, array_data)
            if not results:
                return False
            
            # Notify APP of completion
            success = self.notify_completion(file_notification, results)
            
            # Cleanup temp files
            self.cleanup_temp_files([local_file_path, processed_path])
            
            print("=" * 50)
            if success:
                print("🎉 File processing completed successfully!")
            else:
                print("❌ File processing completed with errors")
            
            return success
            
        except Exception as e:
            print(f"❌ Processing workflow failed: {e}")
            return False
    
    def cleanup_temp_files(self, file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"🧹 Cleaned up: {file_path}")
            except Exception as e:
                print(f"⚠️ Could not clean up {file_path}: {e}")
    
    def start_listening(self):
        """Start listening for file upload notifications"""
        print("🚀 Starting Algorithm Service...")
        print("=" * 50)
        
        # Initialize connections
        if not self.setup_oss():
            return False
        if not self.setup_mqtt():
            return False
        
        print("👂 Listening for file upload notifications...")
        print("📍 Press Ctrl+C to stop")
        
        try:
            # Keep the service running
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n🛑 Service stopped by user")
        
        return True
    
    def cleanup(self):
        """Clean up connections"""
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        print("🧹 Cleanup completed")

def main():
    """Main function"""
    service = AlgorithmService()
    
    try:
        service.start_listening()
    
    except Exception as e:
        print(f"💥 Service error: {e}")
    
    finally:
        service.cleanup()

if __name__ == "__main__":
    main()