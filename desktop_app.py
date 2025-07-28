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
                             QGroupBox, QGridLayout, QScrollArea, QMessageBox, QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QPixmap, QFont, QTextCursor, QPalette

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
        self.current_upload_file = None  # Store original file path for display
        
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
        
        # Tab 3: Statistical Analysis
        self.setup_statistical_analysis_tab()
        
        # Tab 4: Analysis Results (Raw Data)
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
        
        # Image display section
        image_layout = QHBoxLayout()
        
        # Original image display
        original_group = QGroupBox("Original Image")
        original_layout = QVBoxLayout(original_group)
        self.original_image_label = QLabel("Original image will appear here")
        self.original_image_label.setAlignment(Qt.AlignCenter)
        self.original_image_label.setStyleSheet("border: 1px solid gray; min-height: 250px; min-width: 300px;")
        self.original_image_label.setScaledContents(False)  # Don't stretch image
        original_layout.addWidget(self.original_image_label)
        image_layout.addWidget(original_group)
        
        # Processed image display
        processed_group = QGroupBox("Processed Image")
        processed_layout = QVBoxLayout(processed_group)
        self.processed_image_label = QLabel("Processed image will appear here")
        self.processed_image_label.setAlignment(Qt.AlignCenter)
        self.processed_image_label.setStyleSheet("border: 1px solid gray; min-height: 250px; min-width: 300px;")
        self.processed_image_label.setScaledContents(False)  # Don't stretch image
        processed_layout.addWidget(self.processed_image_label)
        image_layout.addWidget(processed_group)
        
        results_layout.addLayout(image_layout)
        
        # Array data display section
        array_group = QGroupBox("Array Data")
        array_layout = QVBoxLayout(array_group)
        
        self.array_text = QTextEdit()
        self.array_text.setReadOnly(True)
        self.array_text.setMaximumHeight(100)
        self.array_text.setPlaceholderText("Array data will appear here after processing...")
        array_layout.addWidget(self.array_text)
        
        results_layout.addWidget(array_group)
        
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
    
    def setup_statistical_analysis_tab(self):
        """Setup comprehensive statistical analysis tab"""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        
        # Create horizontal splitter for left (metrics/alerts) and right (AI insights) sections
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)
        
        # Left section: Key metrics and alerts
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Key Metrics Panel
        metrics_group = QGroupBox("📊 Key Process Metrics")
        metrics_grid = QGridLayout(metrics_group)
        
        self.statistical_metrics = {
            'Pass Rate': QLabel("--"),
            'Cpk (Process Capability)': QLabel("--"),
            'Mean Value': QLabel("--"),
            'Std Deviation': QLabel("--"),
            'Tolerance Utilization': QLabel("--"),
            'Process Status': QLabel("--")
        }
        
        for i, (label_text, value_label) in enumerate(self.statistical_metrics.items()):
            label = QLabel(f"{label_text}:")
            value_label.setStyleSheet("font-weight: bold; color: #2E86AB;")
            metrics_grid.addWidget(label, i//3, (i%3)*2)
            metrics_grid.addWidget(value_label, i//3, (i%3)*2+1)
        
        left_layout.addWidget(metrics_group)
        
        # Alerts Panel
        alerts_group = QGroupBox("🚨 Quality Alerts")
        alerts_layout = QVBoxLayout(alerts_group)
        
        self.alerts_text = QTextEdit()
        self.alerts_text.setReadOnly(True)
        self.alerts_text.setMaximumHeight(100)
        self.alerts_text.setPlaceholderText("No quality alerts...")
        alerts_layout.addWidget(self.alerts_text)
        
        left_layout.addWidget(alerts_group)
        
        # Add left widget to splitter
        main_splitter.addWidget(left_widget)
        
        # Right section: AI Insights Panel (takes right side of splitter)
        ai_insights_group = QGroupBox("🤖 AI Quality Insights")
        ai_insights_layout = QVBoxLayout(ai_insights_group)
        
        # AI Insights text area (larger on right side)
        self.ai_insights_text = QTextEdit()
        self.ai_insights_text.setReadOnly(True)
        self.ai_insights_text.setMinimumHeight(200)
        self.ai_insights_text.setPlaceholderText("AI insights will appear here... Click 'Full Screen' for detailed view")
        self.ai_insights_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 12px; font-size: 10pt;")
        ai_insights_layout.addWidget(self.ai_insights_text)
        
        # Full screen button
        self.fullscreen_insights_btn = QPushButton("🔍 View AI Insights Full Screen")
        self.fullscreen_insights_btn.setStyleSheet("background-color: #007bff; color: white; padding: 8px; border-radius: 4px; font-weight: bold;")
        self.fullscreen_insights_btn.clicked.connect(self.show_fullscreen_insights)
        ai_insights_layout.addWidget(self.fullscreen_insights_btn)
        
        # Full screen AI insights window (initially hidden)
        self.fullscreen_insights_window = None
        self.current_ai_insights = ""
        
        # Add AI insights as right widget to splitter
        main_splitter.addWidget(ai_insights_group)
        
        # Bottom section: Charts
        charts_widget = QWidget()
        charts_layout = QVBoxLayout(charts_widget)
        
        # Charts tabs
        self.charts_tab_widget = QTabWidget()
        
        # Create chart display areas
        self.chart_displays = {}
        chart_types = [
            ('histogram', '📊 Histogram'),
            ('boxplot', '📦 Box Plot'),
            ('heatmap', '🔥 Correlation Heatmap'),
            ('xbar_chart', '📈 X-bar Chart'),
            ('r_chart', '📉 R Chart'),
            ('clustering_scatter', '🎯 Clustering'),
            ('time_series', '⏰ Time Series')
        ]
        
        for chart_key, chart_name in chart_types:
            chart_tab = QWidget()
            chart_layout = QVBoxLayout(chart_tab)
            
            chart_label = QLabel(f"Loading {chart_name.split(' ', 1)[1]}...")
            chart_label.setAlignment(Qt.AlignCenter)
            chart_label.setStyleSheet("border: 1px solid gray; min-height: 300px; min-width: 400px;")
            chart_label.setScaledContents(False)
            
            chart_layout.addWidget(chart_label)
            self.chart_displays[chart_key] = chart_label
            
            self.charts_tab_widget.addTab(chart_tab, chart_name)
        
        charts_layout.addWidget(self.charts_tab_widget)
        # Create vertical splitter for top (metrics/AI) and bottom (charts)
        vertical_splitter = QSplitter(Qt.Vertical)
        vertical_splitter.addWidget(main_splitter)
        vertical_splitter.addWidget(charts_widget)
        
        # Set splitter proportions
        main_splitter.setSizes([400, 300])  # Left metrics vs right AI insights
        vertical_splitter.setSizes([300, 500])  # Top info vs bottom charts
        
        # Update main layout to use vertical splitter
        main_layout.addWidget(vertical_splitter)
        
        self.tab_widget.addTab(tab, "Statistical Analysis")
    
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
            
            # Store original file path and display original image
            self.current_upload_file = file_path
            self.display_original_image(file_path)
            
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
            
            # Display processed image key and download image
            processed_key = payload.get('processed_photo_key')
            if processed_key:
                self.results_text.append(f"Processed image: {processed_key}")
                self.download_and_display_processed_image(processed_key)
            
            # Display array data
            array_data = payload.get('array_data')
            if array_data:
                self.results_text.append(f"Array data: {array_data}")
                self.display_array_data(array_data)
            
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
            # Update raw analysis text (Tab 4)
            formatted_analysis = json.dumps(analysis_data, indent=2, ensure_ascii=False)
            self.analysis_text.setPlainText(formatted_analysis)
            
            # Update Real-time Data tab statistics (Tab 2)
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
            
            # Update Statistical Analysis tab (Tab 3) - only if it exists
            if hasattr(self, 'statistical_metrics'):
                self.update_statistical_metrics(analysis_data)
                self.update_quality_alerts(analysis_data)
                self.update_ai_insights(analysis_data)
                self.update_charts_display(analysis_data)
        
        except Exception as e:
            pass
    
    def update_statistical_metrics(self, analysis_data):
        """Update statistical metrics display"""
        try:
            # Pass Rate
            pass_rate_analysis = analysis_data.get('pass_rate_analysis', {})
            pass_rate = pass_rate_analysis.get('pass_rate', 0)
            self.statistical_metrics['Pass Rate'].setText(f"{pass_rate:.1f}%")
            
            # Process Capability (Cpk)
            process_capability = analysis_data.get('process_capability', {})
            cpk = process_capability.get('cpk', 0)
            self.statistical_metrics['Cpk (Process Capability)'].setText(f"{cpk:.3f}")
            
            # Mean Value
            descriptive_stats = analysis_data.get('descriptive_statistics', {})
            mean_val = descriptive_stats.get('mean', 0)
            self.statistical_metrics['Mean Value'].setText(f"{mean_val:.4f} mm")
            
            # Standard Deviation
            std_val = descriptive_stats.get('std', 0)
            self.statistical_metrics['Std Deviation'].setText(f"{std_val:.4f} mm")
            
            # Tolerance Utilization
            tolerance_util = analysis_data.get('tolerance_utilization', {})
            util_pct = tolerance_util.get('utilization_percentage', 0)
            self.statistical_metrics['Tolerance Utilization'].setText(f"{util_pct:.1f}%")
            
            # Process Status (based on capability)
            capability_assessment = process_capability.get('capability_assessment', 'Unknown')
            status_color = self.get_status_color(capability_assessment)
            self.statistical_metrics['Process Status'].setText(capability_assessment)
            self.statistical_metrics['Process Status'].setStyleSheet(f"font-weight: bold; color: {status_color};")
            
        except Exception as e:
            pass
    
    def get_status_color(self, capability_assessment):
        """Get color based on process capability assessment"""
        if 'Excellent' in capability_assessment:
            return '#28a745'  # Green
        elif 'Good' in capability_assessment:
            return '#17a2b8'  # Blue
        elif 'Adequate' in capability_assessment:
            return '#ffc107'  # Yellow
        elif 'Poor' in capability_assessment:
            return '#fd7e14'  # Orange
        else:
            return '#dc3545'  # Red
    
    def update_quality_alerts(self, analysis_data):
        """Update quality alerts display"""
        try:
            alerts = analysis_data.get('alerts', [])
            if not alerts:
                self.alerts_text.setPlainText("✅ No quality alerts - Process is running within specifications")
                self.alerts_text.setStyleSheet("color: #28a745;")  # Green
            else:
                alert_text = ""
                for alert in alerts:
                    severity = alert.get('severity', 'info')
                    icon = '🚨' if severity == 'critical' else '⚠️' if severity == 'warning' else 'ℹ️'
                    alert_text += f"{icon} {alert.get('message', 'Unknown alert')}\n"
                
                self.alerts_text.setPlainText(alert_text.strip())
                self.alerts_text.setStyleSheet("color: #dc3545;")  # Red
        
        except Exception as e:
            pass
    
    def update_ai_insights(self, analysis_data):
        """Update AI insights display"""
        try:
            ai_insights = analysis_data.get('ai_insights', '')
            self.current_ai_insights = ai_insights  # Store for full-screen display
            
            if ai_insights:
                if ai_insights.startswith('AI insights unavailable') or ai_insights.startswith('AI insights generation failed'):
                    # Show preview in small area
                    preview = f"⚠️ {ai_insights[:200]}..." if len(ai_insights) > 200 else f"⚠️ {ai_insights}"
                    self.ai_insights_text.setPlainText(preview)
                    self.ai_insights_text.setStyleSheet("background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px; padding: 8px; color: #856404;")
                else:
                    # Show preview in small area
                    preview = ai_insights[:300] + "..." if len(ai_insights) > 300 else ai_insights
                    self.ai_insights_text.setPlainText(preview)
                    self.ai_insights_text.setStyleSheet("background-color: #d1ecf1; border: 1px solid #bee5eb; border-radius: 4px; padding: 8px; color: #0c5460;")
                
                # Enable full-screen button
                self.fullscreen_insights_btn.setEnabled(True)
                self.fullscreen_insights_btn.setText("🔍 View AI Insights Full Screen")
                
                # Update full-screen window if it's open
                if self.fullscreen_insights_window and hasattr(self, 'fullscreen_insights_text'):
                    self.fullscreen_insights_text.setPlainText(ai_insights)
            else:
                self.ai_insights_text.setPlainText("🔄 Generating AI insights...")
                self.ai_insights_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px; padding: 8px; color: #6c757d;")
                self.fullscreen_insights_btn.setEnabled(False)
                self.fullscreen_insights_btn.setText("⏳ Waiting for AI insights...")
        
        except Exception as e:
            self.ai_insights_text.setPlainText(f"❌ Error displaying AI insights: {e}")
            self.ai_insights_text.setStyleSheet("background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; padding: 8px; color: #721c24;")
    
    def show_fullscreen_insights(self):
        """Show AI insights in a full-screen window"""
        if not self.current_ai_insights:
            QMessageBox.information(self, "AI Insights", "No AI insights available yet. Please wait for analysis data.")
            return
        
        # Create or update full-screen window
        if not self.fullscreen_insights_window:
            self.fullscreen_insights_window = QMainWindow()
            self.fullscreen_insights_window.setWindowTitle("🤖 AI Quality Insights - Full Screen")
            self.fullscreen_insights_window.setWindowState(Qt.WindowMaximized)
            
            # Create central widget
            central_widget = QWidget()
            self.fullscreen_insights_window.setCentralWidget(central_widget)
            layout = QVBoxLayout(central_widget)
            
            # Header
            header_label = QLabel("🤖 AI-Powered Manufacturing Quality Analysis")
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #2c3e50; padding: 15px; background-color: #ecf0f1; border-radius: 8px; margin-bottom: 10px;")
            layout.addWidget(header_label)
            
            # Full AI insights text area
            self.fullscreen_insights_text = QTextEdit()
            self.fullscreen_insights_text.setReadOnly(True)
            self.fullscreen_insights_text.setStyleSheet("""
                QTextEdit {
                    font-size: 12pt;
                    line-height: 1.5;
                    padding: 20px;
                    background-color: #ffffff;
                    color: #2c3e50;
                    border: 2px solid #3498db;
                    border-radius: 8px;
                }
            """)
            layout.addWidget(self.fullscreen_insights_text)
            
            # Close button
            close_btn = QPushButton("❌ Close Full Screen")
            close_btn.setStyleSheet("background-color: #e74c3c; color: white; padding: 12px; font-size: 12pt; font-weight: bold; border-radius: 6px;")
            close_btn.clicked.connect(self.fullscreen_insights_window.hide)
            layout.addWidget(close_btn)
        
        # Update content and show
        self.fullscreen_insights_text.setPlainText(self.current_ai_insights)
        self.fullscreen_insights_window.show()
        self.fullscreen_insights_window.raise_()
        self.fullscreen_insights_window.activateWindow()
    
    def update_charts_display(self, analysis_data):
        """Update charts display from latest OSS chart images"""
        try:
            charts = analysis_data.get('charts', {})
            
            for chart_key, chart_label in self.chart_displays.items():
                oss_key = charts.get(chart_key)
                
                # Fallback to expected latest filename if not provided in analysis data
                if not oss_key:
                    oss_key = f"charts/latest_{chart_key}.png"
                
                if oss_key:
                    # Download latest chart image from OSS and display
                    try:
                        obj = self.oss_bucket.get_object(oss_key)
                        image_data = obj.read()
                        
                        pixmap = QPixmap()
                        if pixmap.loadFromData(image_data):
                            # Scale to fit while maintaining aspect ratio
                            scaled_pixmap = pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            chart_label.setPixmap(scaled_pixmap)
                            chart_label.setText("")  # Clear loading text
                        else:
                            chart_label.setText(f"Failed to load {chart_key} chart")
                    except Exception as download_error:
                        # Try fallback filename if the provided key failed
                        if not oss_key.startswith("charts/latest_"):
                            fallback_key = f"charts/latest_{chart_key}.png"
                            try:
                                obj = self.oss_bucket.get_object(fallback_key)
                                image_data = obj.read()
                                
                                pixmap = QPixmap()
                                if pixmap.loadFromData(image_data):
                                    scaled_pixmap = pixmap.scaled(600, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                    chart_label.setPixmap(scaled_pixmap)
                                    chart_label.setText("")
                                else:
                                    chart_label.setText(f"Failed to load {chart_key} chart")
                            except:
                                chart_label.setText(f"No {chart_key} chart available")
                        else:
                            chart_label.setText(f"Chart {chart_key} not found: {download_error}")
                else:
                    chart_label.setText(f"No {chart_key} data available")
        
        except Exception as e:
            pass
    
    def display_original_image(self, file_path):
        """Display original image in the UI"""
        try:
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                # Scale image to fit the label while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(300, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.original_image_label.setPixmap(scaled_pixmap)
                self.original_image_label.setText("")  # Clear placeholder text
            else:
                self.original_image_label.setText("Failed to load original image")
        except Exception as e:
            self.original_image_label.setText(f"Error loading image: {e}")
    
    def download_and_display_processed_image(self, oss_key):
        """Download processed image from OSS and display it"""
        try:
            # Download image from OSS
            obj = self.oss_bucket.get_object(oss_key)
            image_data = obj.read()
            
            # Create QPixmap from image data
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data):
                # Scale image to fit the label while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(300, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.processed_image_label.setPixmap(scaled_pixmap)
                self.processed_image_label.setText("")  # Clear placeholder text
                self.results_text.append(f"✅ Processed image displayed")
            else:
                self.processed_image_label.setText("Failed to load processed image")
                self.results_text.append("❌ Failed to load processed image")
                
        except Exception as e:
            self.processed_image_label.setText(f"Error loading processed image: {e}")
            self.results_text.append(f"❌ Error downloading processed image: {e}")
    
    def display_array_data(self, array_data):
        """Display array data in the array text area"""
        try:
            if isinstance(array_data, list):
                # Format array data nicely
                if len(array_data) > 0 and isinstance(array_data[0], list):
                    # 2D array format
                    formatted_text = "Array Data (2D):\n"
                    for i, row in enumerate(array_data):
                        formatted_text += f"Row {i+1}: [{', '.join([f'{val:.2f}' if isinstance(val, (int, float)) else str(val) for val in row])}]\n"
                else:
                    # 1D array format
                    formatted_text = "Array Data (1D):\n"
                    formatted_text += f"[{', '.join([f'{val:.2f}' if isinstance(val, (int, float)) else str(val) for val in array_data])}]\n"
                
                formatted_text += f"\nTotal elements: {len(array_data)}"
                if len(array_data) > 0 and isinstance(array_data[0], list):
                    formatted_text += f" rows, {len(array_data[0])} columns"
                
            elif isinstance(array_data, str):
                # String representation of array
                formatted_text = f"Array Data:\n{array_data}"
            else:
                # Other format
                formatted_text = f"Array Data:\n{str(array_data)}"
            
            self.array_text.setPlainText(formatted_text)
            
        except Exception as e:
            self.array_text.setPlainText(f"Error displaying array data: {e}")
    
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