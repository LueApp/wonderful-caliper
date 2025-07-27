#!/usr/bin/env python3
"""
Data Processing Service for ESP32 IoT System

This service:
1. Loads existing data from OSS 
2. Listens for ESP32 MQTT messages (int, float, bool)
3. Performs real-time data analysis
4. Uploads analysis results to OSS every 10 seconds
"""

import os
import sys
import json
import time
import threading
import uuid
from datetime import datetime, timedelta
from collections import deque
import numpy as np
import pandas as pd
import oss2
import paho.mqtt.client as mqtt

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import get_config

class DataProcessingService:
    def __init__(self):
        self.config = get_config('data_processing')
        self.client_id = f"data_processor_{uuid.uuid4().hex[:8]}"
        
        # MQTT client
        self.mqtt_client = None
        
        # OSS client
        self.oss_bucket = None
        
        # Data storage
        self.historical_data = []  # List of {timestamp, int_val, float_val, bool_val}
        self.realtime_buffer = deque(maxlen=1000)  # Recent data buffer
        
        # Analysis results
        self.analysis_results = {
            'last_analysis': None,
            'data_count': 0,
            'statistics': {},
            'trends': {},
            'alerts': []
        }
        
        # Timing
        self.last_upload = time.time()
        self.upload_interval = 10  # seconds
        
        # Threading
        self.running = True
        self.analysis_lock = threading.Lock()
        
    def setup_oss(self):
        """Initialize OSS client"""
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
            return True
        except Exception as e:
            print(f"❌ OSS setup failed: {e}")
            return False
    
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
            self.mqtt_client.on_message = self.on_message
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
            print("🔗 Connected to MQTT broker")
            # Subscribe to ESP32 data topic
            client.subscribe(self.config['topics']['esp32_data'])
            print(f"📡 Subscribed to: {self.config['topics']['esp32_data']}")
        else:
            print(f"❌ MQTT connection failed with code {rc}")
    
    def on_message(self, client, userdata, msg):
        """Handle incoming ESP32 data"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            print(f"📨 ESP32 data received: {payload}")
            
            # Extract data
            timestamp = payload.get('timestamp', time.time() * 1000)
            int_val = payload.get('int_value', 0)
            float_val = payload.get('float_value', 0.0)
            bool_val = payload.get('bool_value', False)
            device_id = payload.get('device_id', 'unknown')
            
            # Store data
            data_point = {
                'timestamp': timestamp,
                'datetime': datetime.fromtimestamp(timestamp / 1000),
                'int_value': int(int_val),
                'float_value': float(float_val),
                'bool_value': bool(bool_val),
                'device_id': device_id
            }
            
            with self.analysis_lock:
                self.realtime_buffer.append(data_point)
                self.historical_data.append(data_point)
            
            print(f"📊 Data stored: int={int_val}, float={float_val:.2f}, bool={bool_val}")
            
            # Trigger immediate analysis for new data
            self.analyze_data()
            
        except Exception as e:
            print(f"❌ Error processing ESP32 data: {e}")
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        print(f"🔌 Disconnected from MQTT broker (code: {rc})")
    
    def load_historical_data(self):
        """Load existing data from OSS"""
        try:
            data_file = "data/historical_data.json"
            print(f"📥 Loading historical data from OSS: {data_file}")
            
            obj = self.oss_bucket.get_object(data_file)
            content = obj.read().decode('utf-8')
            data = json.loads(content)
            
            # Convert to our format
            for item in data:
                if isinstance(item.get('timestamp'), (int, float)):
                    item['datetime'] = datetime.fromtimestamp(item['timestamp'] / 1000)
                
            self.historical_data = data
            print(f"✅ Loaded {len(self.historical_data)} historical data points")
            
            # Fill realtime buffer with recent data
            recent_data = sorted(data, key=lambda x: x['timestamp'])[-100:]
            self.realtime_buffer.extend(recent_data)
            
        except oss2.exceptions.NoSuchKey:
            print("📝 No historical data found, starting fresh")
        except Exception as e:
            print(f"❌ Error loading historical data: {e}")
    
    def analyze_data(self):
        """Perform data analysis on current dataset"""
        with self.analysis_lock:
            if len(self.realtime_buffer) < 2:
                return
            
            # Convert to pandas for analysis
            df = pd.DataFrame(list(self.realtime_buffer))
            
            try:
                # Basic statistics
                stats = {
                    'data_points': len(df),
                    'time_range': {
                        'start': df['datetime'].min().isoformat(),
                        'end': df['datetime'].max().isoformat(),
                        'duration_minutes': (df['datetime'].max() - df['datetime'].min()).total_seconds() / 60
                    },
                    'int_stats': {
                        'mean': float(df['int_value'].mean()),
                        'min': int(df['int_value'].min()),
                        'max': int(df['int_value'].max()),
                        'std': float(df['int_value'].std()) if len(df) > 1 else 0.0
                    },
                    'float_stats': {
                        'mean': float(df['float_value'].mean()),
                        'min': float(df['float_value'].min()),
                        'max': float(df['float_value'].max()),
                        'std': float(df['float_value'].std()) if len(df) > 1 else 0.0
                    },
                    'bool_stats': {
                        'true_count': int(df['bool_value'].sum()),
                        'false_count': int((~df['bool_value']).sum()),
                        'true_percentage': float(df['bool_value'].mean() * 100)
                    }
                }
                
                # Trend analysis (if enough data)
                trends = {}
                if len(df) >= 5:
                    # Calculate moving averages
                    df['float_ma5'] = df['float_value'].rolling(window=5, min_periods=1).mean()
                    df['int_ma5'] = df['int_value'].rolling(window=5, min_periods=1).mean()
                    
                    trends = {
                        'float_trend': 'increasing' if df['float_value'].tail(3).mean() > df['float_value'].head(3).mean() else 'decreasing',
                        'int_trend': 'increasing' if df['int_value'].tail(3).mean() > df['int_value'].head(3).mean() else 'decreasing',
                        'recent_float_avg': float(df['float_value'].tail(5).mean()),
                        'recent_int_avg': float(df['int_value'].tail(5).mean())
                    }
                
                # Generate alerts
                alerts = []
                
                # Alert: High float values
                if stats['float_stats']['max'] > 80:
                    alerts.append({
                        'type': 'high_float_value',
                        'message': f"Float value exceeded 80: {stats['float_stats']['max']:.2f}",
                        'severity': 'warning',
                        'timestamp': datetime.now().isoformat()
                    })
                
                # Alert: All boolean values are same
                if len(df) > 5 and (stats['bool_stats']['true_percentage'] == 100 or stats['bool_stats']['true_percentage'] == 0):
                    alerts.append({
                        'type': 'boolean_stuck',
                        'message': f"Boolean values stuck at {stats['bool_stats']['true_percentage']:.0f}%",
                        'severity': 'info',
                        'timestamp': datetime.now().isoformat()
                    })
                
                # Alert: High variability in int values
                if len(df) > 10 and stats['int_stats']['std'] > 50:
                    alerts.append({
                        'type': 'high_variability',
                        'message': f"High int value variability: std={stats['int_stats']['std']:.2f}",
                        'severity': 'info',
                        'timestamp': datetime.now().isoformat()
                    })
                
                # Update analysis results
                self.analysis_results = {
                    'last_analysis': datetime.now().isoformat(),
                    'data_count': len(self.historical_data),
                    'statistics': stats,
                    'trends': trends,
                    'alerts': alerts
                }
                
                # Print brief status
                if len(df) % 5 == 0:  # Print every 5th analysis
                    print(f"📈 Analysis: {len(df)} points, Float avg: {stats['float_stats']['mean']:.2f}, "
                          f"Int avg: {stats['int_stats']['mean']:.1f}, Bool: {stats['bool_stats']['true_percentage']:.0f}%")
                
            except Exception as e:
                print(f"❌ Analysis error: {e}")
    
    def upload_analysis_results(self):
        """Upload analysis results to OSS"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Upload current analysis
            analysis_file = f"analysis/analysis_{timestamp}.json"
            analysis_json = json.dumps(self.analysis_results, indent=2, ensure_ascii=False)
            self.oss_bucket.put_object(analysis_file, analysis_json)
            
            # Update latest analysis file
            latest_analysis_file = "analysis/latest_analysis.json"
            self.oss_bucket.put_object(latest_analysis_file, analysis_json)
            
            # Upload current dataset
            data_file = "data/historical_data.json"
            data_json = json.dumps(self.historical_data, indent=2, default=str, ensure_ascii=False)
            self.oss_bucket.put_object(data_file, data_json)
            
            stats = self.analysis_results.get('statistics', {})
            data_count = stats.get('data_points', 0)
            alert_count = len(self.analysis_results.get('alerts', []))
            
            print(f"✅ Analysis uploaded: {data_count} points, {alert_count} alerts → {latest_analysis_file}")
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
    
    def periodic_upload_worker(self):
        """Background worker for periodic uploads"""
        while self.running:
            try:
                current_time = time.time()
                if current_time - self.last_upload >= self.upload_interval:
                    if len(self.historical_data) > 0:  # Only upload if we have data
                        self.upload_analysis_results()
                    self.last_upload = current_time
                
                time.sleep(1)  # Check every second
                
            except Exception as e:
                print(f"❌ Upload worker error: {e}")
                time.sleep(5)
    
    def start_service(self):
        """Start the data processing service"""
        print("🚀 Starting Data Processing Service...")
        print("=" * 50)
        
        # Initialize connections
        if not self.setup_oss():
            return False
        if not self.setup_mqtt():
            return False
        
        # Load historical data
        self.load_historical_data()
        
        # Start periodic upload worker
        upload_thread = threading.Thread(target=self.periodic_upload_worker, daemon=True)
        upload_thread.start()
        
        print("📊 Data Processing Service is running...")
        print("🔄 Listening for ESP32 data and analyzing every 10 seconds")
        print("📍 Press Ctrl+C to stop")
        
        try:
            while True:
                time.sleep(30)  # Print status every 30 seconds
                
                with self.analysis_lock:
                    total_points = len(self.historical_data)
                    buffer_points = len(self.realtime_buffer)
                    alert_count = len(self.analysis_results.get('alerts', []))
                    
                    print(f"📈 Status: {total_points} total, {buffer_points} in buffer, {alert_count} alerts")
                
        except KeyboardInterrupt:
            print("\n🛑 Service stopped by user")
        
        self.stop_service()
        return True
    
    def stop_service(self):
        """Stop the service gracefully"""
        print("🔄 Stopping service...")
        self.running = False
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        # Final upload
        if len(self.historical_data) > 0:
            self.upload_analysis_results()
        print("✅ Service stopped")

def main():
    """Main function"""
    service = DataProcessingService()
    
    try:
        service.start_service()
    except Exception as e:
        print(f"💥 Service error: {e}")
    finally:
        service.stop_service()

if __name__ == "__main__":
    main()