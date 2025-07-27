#!/usr/bin/env python3
"""
Desktop IoT Control Application

PyQt5 desktop application that replaces the mobile app functionality:
1. File upload and processing management
2. Real-time data monitoring from data processing service
3. Display processed results and analysis
"""

import os
import sys
import json
import time
import uuid
import threading
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QLabel, QTextEdit, QFileDialog, 
                             QTabWidget, QTableWidget, QTableWidgetItem, QProgressBar,
                             QGroupBox, QGridLayout, QScrollArea, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QPixmap, QFont, QTextCursor

import oss2
import paho.mqtt.client as mqtt

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import get_config

class DataMonitorThread(QThread):
    """Thread for monitoring real-time data from data processing service"""
    data_updated = pyqtSignal(dict)  # Signal to emit when data is updated
    
    def __init__(self, oss_bucket):
        super().__init__()
        self.oss_bucket = oss_bucket
        self.running = True
        
    def run(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Fetch latest analysis from OSS
                obj = self.oss_bucket.get_object("analysis/latest_analysis.json")
                content = obj.read().decode('utf-8')
                analysis_data = json.loads(content)
                
                # Emit signal with updated data
                self.data_updated.emit(analysis_data)
                
            except Exception as e:
                # Handle missing file or connection errors gracefully
                pass
            
            # Wait 5 seconds before next check
            self.msleep(5000)
    
    def stop(self):
        """Stop the monitoring thread"""
        self.running = False

class MQTTWorker(QThread):
    """Thread for handling MQTT communications"""
    message_received = pyqtSignal(dict)  # Signal for received messages
    connection_status = pyqtSignal(bool, str)  # Signal for connection status
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.client_id = f"desktop_app_{uuid.uuid4().hex[:8]}"
        self.mqtt_client = None
        self.connected = False
        
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
            
            return True
        except Exception as e:
            self.connection_status.emit(False, f"MQTT setup failed: {e}")
            return False
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.connected = True
            # Subscribe to app notifications
            client.subscribe(self.config['topics']['app_notifications'])
            self.connection_status.emit(True, "Connected to MQTT broker")
        else:
            self.connected = False
            self.connection_status.emit(False, f"MQTT connection failed: {rc}")
    
    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            # Emit signal with received message
            self.message_received.emit({
                'topic': topic,
                'payload': payload,
                'timestamp': time.time()
            })
            
        except Exception as e:
            pass
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        self.connected = False
        self.connection_status.emit(False, "Disconnected from MQTT broker")
    
    def publish_file_notification(self, oss_key, filename):
        """Publish file upload notification"""
        if not self.connected:
            return False
        
        try:
            notification = {
                "type": "file_uploaded",
                "oss_key": oss_key,
                "original_filename": filename,
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "client_id": self.client_id
            }
            
            self.mqtt_client.publish(
                self.config['topics']['app_file_uploaded'],
                json.dumps(notification)
            )
            return True
        except Exception as e:
            return False
    
    def run(self):
        """Start MQTT loop"""
        if self.setup_mqtt():
            self.mqtt_client.loop_forever()

class DesktopApp(QMainWindow):
    """Main desktop application window"""
    
    def __init__(self):
        super().__init__()
        self.config = get_config('app')
        
        # Initialize OSS client
        self.setup_oss()
        
        # Initialize UI
        self.setup_ui()
        
        # Initialize MQTT worker
        self.mqtt_worker = MQTTWorker(self.config)
        self.mqtt_worker.message_received.connect(self.handle_mqtt_message)
        self.mqtt_worker.connection_status.connect(self.update_connection_status)
        self.mqtt_worker.start()
        
        # Initialize data monitoring
        self.data_monitor = DataMonitorThread(self.oss_bucket)
        self.data_monitor.data_updated.connect(self.update_analysis_display)
        self.data_monitor.start()
        
        # State tracking
        self.waiting_for_result = False
        self.current_upload = None
        
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
        except Exception as e:
            QMessageBox.critical(self, "OSS Error", f"Failed to initialize OSS: {e}")
    
    def setup_ui(self):
        """Setup the user interface"""
        self.setWindowTitle("IoT Desktop Control Center")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Status bar
        self.status_label = QLabel("Status: Initializing...")
        main_layout.addWidget(self.status_label)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Tab 1: File Processing
        self.setup_file_processing_tab()
        
        # Tab 2: Real-time Data Monitor
        self.setup_data_monitor_tab()
        
        # Tab 3: Analysis Results
        self.setup_analysis_tab()
    
    def setup_file_processing_tab(self):
        """Setup file processing tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # File upload section
        upload_group = QGroupBox("File Upload & Processing")
        upload_layout = QVBoxLayout(upload_group)
        
        # Upload button
        self.upload_btn = QPushButton("Select and Upload File")
        self.upload_btn.clicked.connect(self.upload_file)
        upload_layout.addWidget(self.upload_btn)
        
        # Upload progress
        self.upload_progress = QProgressBar()
        self.upload_progress.setVisible(False)
        upload_layout.addWidget(self.upload_progress)
        
        # Upload status
        self.upload_status = QLabel("No file selected")
        upload_layout.addWidget(self.upload_status)
        
        layout.addWidget(upload_group)
        
        # Processing results section
        results_group = QGroupBox("Processing Results")
        results_layout = QVBoxLayout(results_group)
        
        # Results display
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(200)
        results_layout.addWidget(self.results_text)
        
        # Processed image display (placeholder)
        self.image_label = QLabel("Processed image will appear here")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid gray; min-height: 200px;")
        results_layout.addWidget(self.image_label)
        
        layout.addWidget(results_group)
        
        self.tab_widget.addTab(tab, "File Processing")
    
    def setup_data_monitor_tab(self):
        """Setup real-time data monitoring tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # ESP32 data section
        esp32_group = QGroupBox("ESP32 Real-time Data")
        esp32_layout = QVBoxLayout(esp32_group)
        
        # Data table
        self.data_table = QTableWidget()
        self.data_table.setColumnCount(4)
        self.data_table.setHorizontalHeaderLabels(["Timestamp", "Index", "Value", "Status"])
        self.data_table.setMaximumHeight(300)
        esp32_layout.addWidget(self.data_table)
        
        layout.addWidget(esp32_group)
        
        # Statistics section
        stats_group = QGroupBox("Data Statistics")
        stats_layout = QGridLayout(stats_group)
        
        self.stats_labels = {}
        stats = ["Total Points", "Success Rate", "Avg Value", "Last Update"]
        for i, stat in enumerate(stats):
            label = QLabel(f"{stat}:")
            value = QLabel("--")
            value.setStyleSheet("font-weight: bold;")
            stats_layout.addWidget(label, i//2, (i%2)*2)
            stats_layout.addWidget(value, i//2, (i%2)*2+1)
            self.stats_labels[stat] = value
        
        layout.addWidget(stats_group)
        
        self.tab_widget.addTab(tab, "Real-time Data")
    
    def setup_analysis_tab(self):
        """Setup analysis results tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Analysis display
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        layout.addWidget(self.analysis_text)
        
        self.tab_widget.addTab(tab, "Analysis Results")
    
    def upload_file(self):
        """Handle file upload"""
        if self.waiting_for_result:
            QMessageBox.information(self, "Info", "Please wait for current processing to complete")
            return
        
        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Upload", "", 
            "Image Files (*.png *.jpg *.jpeg);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Show progress
            self.upload_progress.setVisible(True)
            self.upload_progress.setRange(0, 0)  # Indeterminate progress
            self.upload_btn.setEnabled(False)
            self.upload_status.setText("Uploading...")
            
            # Upload to OSS
            filename = os.path.basename(file_path)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            oss_key = f"uploads/{timestamp}_{filename}"
            
            with open(file_path, 'rb') as file_obj:
                self.oss_bucket.put_object(oss_key, file_obj)
            
            # Notify algorithm service via MQTT
            if self.mqtt_worker.publish_file_notification(oss_key, filename):
                self.upload_status.setText(f"Uploaded: {filename}")
                self.current_upload = oss_key
                self.waiting_for_result = True
                self.results_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] File uploaded: {filename}")
                self.results_text.append("Waiting for processing results...")
            else:
                self.upload_status.setText("Upload succeeded, but MQTT notification failed")
            
        except Exception as e:
            QMessageBox.critical(self, "Upload Error", f"Failed to upload file: {e}")
            self.upload_status.setText("Upload failed")
        
        finally:
            self.upload_progress.setVisible(False)
            self.upload_btn.setEnabled(True)
    
    def handle_mqtt_message(self, message):
        """Handle received MQTT messages"""
        try:
            topic = message['topic']
            payload = message['payload']
            
            if topic == self.config['topics']['app_notifications']:
                if payload.get('type') == 'processing_complete':
                    self.handle_processing_complete(payload)
        
        except Exception as e:
            pass
    
    def handle_processing_complete(self, payload):
        """Handle processing completion notification"""
        try:
            self.waiting_for_result = False
            
            # Update results display
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.results_text.append(f"[{timestamp}] Processing completed!")
            
            # Display processed image key
            processed_key = payload.get('processed_photo_key')
            if processed_key:
                self.results_text.append(f"Processed image: {processed_key}")
            
            # Display array data
            array_data = payload.get('array_data')
            if array_data:
                self.results_text.append(f"Array data: {array_data}")
            
            # Scroll to bottom
            cursor = self.results_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.results_text.setTextCursor(cursor)
            
        except Exception as e:
            self.results_text.append(f"Error processing result: {e}")
    
    def update_connection_status(self, connected, message):
        """Update connection status display"""
        if connected:
            self.status_label.setText(f"Status: Connected - {message}")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText(f"Status: Disconnected - {message}")
            self.status_label.setStyleSheet("color: red;")
    
    def update_analysis_display(self, analysis_data):
        """Update analysis results display"""
        try:
            # Update analysis text
            formatted_analysis = json.dumps(analysis_data, indent=2, ensure_ascii=False)
            self.analysis_text.setPlainText(formatted_analysis)
            
            # Update statistics
            stats = analysis_data.get('statistics', {})
            if stats:
                self.stats_labels["Total Points"].setText(str(stats.get('data_points', '--')))
                
                bool_stats = stats.get('bool_stats', {})
                success_rate = bool_stats.get('true_percentage', 0)
                self.stats_labels["Success Rate"].setText(f"{success_rate:.1f}%")
                
                float_stats = stats.get('float_stats', {})
                avg_value = float_stats.get('mean', 0)
                self.stats_labels["Avg Value"].setText(f"{avg_value:.2f}")
                
                self.stats_labels["Last Update"].setText(
                    analysis_data.get('last_analysis', '--')[:19] if analysis_data.get('last_analysis') else '--'
                )
        
        except Exception as e:
            pass
    
    def closeEvent(self, event):
        """Handle application close"""
        # Stop threads
        if hasattr(self, 'data_monitor'):
            self.data_monitor.stop()
            self.data_monitor.wait()
        
        if hasattr(self, 'mqtt_worker'):
            self.mqtt_worker.quit()
            self.mqtt_worker.wait()
        
        event.accept()

def main():
    """Main function"""
    app = QApplication(sys.argv)
    app.setApplicationName("IoT Desktop Control Center")
    
    # Set application style
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f0f0f0;
        }
        QGroupBox {
            font-weight: bold;
            border: 2px solid #cccccc;
            border-radius: 5px;
            margin: 3px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QPushButton {
            background-color: #4CAF50;
            border: none;
            color: white;
            padding: 8px 16px;
            text-align: center;
            font-size: 14px;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
        QPushButton:disabled {
            background-color: #cccccc;
        }
    """)
    
    # Create and show main window
    window = DesktopApp()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()