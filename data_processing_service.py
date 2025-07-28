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
import io
from datetime import datetime, timedelta
from collections import deque
import numpy as np
import pandas as pd
import oss2
import paho.mqtt.client as mqtt

# Statistical analysis and visualization
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import seaborn as sns
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

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
            'alerts': [],
            'quality_analysis': {},
            'charts': {},
            'process_capability': {}
        }
        
        # Quality control parameters
        self.target_value = 0.0  # Target dimension value
        self.tolerance = 0.05    # ±0.05mm tolerance
        self.usl = self.target_value + self.tolerance  # Upper Specification Limit
        self.lsl = self.target_value - self.tolerance  # Lower Specification Limit
        
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
        """Comprehensive statistical analysis of measurement data"""
        with self.analysis_lock:
            if len(self.realtime_buffer) < 10:
                return
            
            # Convert to pandas for analysis
            df = pd.DataFrame(list(self.realtime_buffer))
            
            try:
                # Extract measurement data (float_value = measurement, bool_value = pass/fail)
                measurements = df['float_value'].values
                pass_fail = df['bool_value'].values
                
                # 1. Descriptive Statistics (描述性统计分析)
                descriptive_stats = self.calculate_descriptive_statistics(measurements)
                
                # 2. Dimension Deviation Distribution (尺寸偏差分布)
                deviation_analysis = self.calculate_deviation_analysis(measurements)
                
                # 3. Pass Rate Analysis (合格率的分析)
                pass_rate_analysis = self.calculate_pass_rate_analysis(pass_fail, measurements)
                
                # 4. Process Capability Indices (过程能力指数 CPK/PPK)
                process_capability = self.calculate_process_capability(measurements)
                
                # 5. Tolerance Utilization (公差利用率)
                tolerance_utilization = self.calculate_tolerance_utilization(measurements)
                
                # 6. Correlation Analysis (尺寸间的相关性)
                correlation_analysis = self.calculate_correlation_analysis(df)
                
                # 7. Time Series Analysis (X-bar图、R图)
                time_series_analysis = self.calculate_time_series_analysis(df)
                
                # 8. Clustering Analysis (聚类分析)
                clustering_analysis = self.calculate_clustering_analysis(measurements)
                
                # 9. AI Anomaly Detection (AI异常检测模型)
                anomaly_detection = self.detect_anomalies(measurements)
                
                # Generate charts and save as base64
                charts = self.generate_all_charts(df, measurements)
                
                # Update analysis results
                self.analysis_results = {
                    'last_analysis': datetime.now().isoformat(),
                    'data_count': len(self.historical_data),
                    'descriptive_statistics': descriptive_stats,
                    'deviation_analysis': deviation_analysis,
                    'pass_rate_analysis': pass_rate_analysis,
                    'process_capability': process_capability,
                    'tolerance_utilization': tolerance_utilization,
                    'correlation_analysis': correlation_analysis,
                    'time_series_analysis': time_series_analysis,
                    'clustering_analysis': clustering_analysis,
                    'anomaly_detection': anomaly_detection,
                    'charts': charts,
                    'alerts': self.generate_quality_alerts(measurements, pass_fail)
                }
                
                # Print brief status
                if len(df) % 5 == 0:  # Print every 5th analysis
                    pass_rate = pass_rate_analysis.get('pass_rate', 0)
                    mean_val = descriptive_stats.get('mean', 0)
                    cpk = process_capability.get('cpk', 0)
                    print(f"📈 Analysis: {len(df)} points, Mean: {mean_val:.3f}mm, Pass Rate: {pass_rate:.1f}%, CPK: {cpk:.2f}")
                    print(f"Int avg: {stats['int_stats']['mean']:.1f}, Bool: {stats['bool_stats']['true_percentage']:.0f}%")
                
            except Exception as e:
                print(f"❌ Analysis error: {e}")
    
    def calculate_descriptive_statistics(self, measurements):
        """1. 描述性统计分析 (Descriptive Statistics)"""
        if len(measurements) == 0:
            return {}
        
        return {
            'count': len(measurements),
            'mean': float(np.mean(measurements)),
            'median': float(np.median(measurements)),
            'std': float(np.std(measurements, ddof=1)),
            'variance': float(np.var(measurements, ddof=1)),
            'min': float(np.min(measurements)),
            'max': float(np.max(measurements)),
            'range': float(np.max(measurements) - np.min(measurements)),
            'q25': float(np.percentile(measurements, 25)),
            'q75': float(np.percentile(measurements, 75)),
            'iqr': float(np.percentile(measurements, 75) - np.percentile(measurements, 25)),
            'skewness': float(stats.skew(measurements)),
            'kurtosis': float(stats.kurtosis(measurements))
        }
    
    def calculate_deviation_analysis(self, measurements):
        """2. 尺寸偏差分布 (Dimension Deviation Distribution)"""
        deviations = measurements - self.target_value
        
        return {
            'mean_deviation': float(np.mean(deviations)),
            'std_deviation': float(np.std(deviations, ddof=1)),
            'max_positive_deviation': float(np.max(deviations)),
            'max_negative_deviation': float(np.min(deviations)),
            'deviation_range': float(np.max(deviations) - np.min(deviations)),
            'within_tolerance_count': int(np.sum(np.abs(deviations) <= self.tolerance)),
            'outside_tolerance_count': int(np.sum(np.abs(deviations) > self.tolerance))
        }
    
    def calculate_pass_rate_analysis(self, pass_fail, measurements):
        """3. 合格率的分析 (Pass Rate Analysis)"""
        total_count = len(pass_fail)
        if total_count == 0:
            return {}
        
        pass_count = np.sum(pass_fail)
        fail_count = total_count - pass_count
        
        # Calculate pass rate by tolerance
        within_tolerance = np.abs(measurements - self.target_value) <= self.tolerance
        tolerance_pass_rate = np.sum(within_tolerance) / total_count * 100
        
        return {
            'total_measurements': total_count,
            'pass_count': int(pass_count),
            'fail_count': int(fail_count),
            'pass_rate': float(pass_count / total_count * 100),
            'fail_rate': float(fail_count / total_count * 100),
            'tolerance_pass_rate': float(tolerance_pass_rate),
            'tolerance_fail_rate': float(100 - tolerance_pass_rate)
        }
    
    def calculate_process_capability(self, measurements):
        """4. 过程能力指数 CPK/PPK (Process Capability Indices)"""
        if len(measurements) < 2:
            return {}
        
        mean = np.mean(measurements)
        std = np.std(measurements, ddof=1)
        
        if std == 0:
            return {'cpk': float('inf'), 'ppk': float('inf'), 'cp': float('inf'), 'pp': float('inf')}
        
        # Process Capability (Cp, Cpk)
        cp = (self.usl - self.lsl) / (6 * std)
        cpu = (self.usl - mean) / (3 * std)
        cpl = (mean - self.lsl) / (3 * std)
        cpk = min(cpu, cpl)
        
        # Process Performance (Pp, Ppk) - using overall std
        pp = (self.usl - self.lsl) / (6 * std)
        ppu = (self.usl - mean) / (3 * std)
        ppl = (mean - self.lsl) / (3 * std)
        ppk = min(ppu, ppl)
        
        return {
            'cp': float(cp),
            'cpk': float(cpk),
            'cpu': float(cpu),
            'cpl': float(cpl),
            'pp': float(pp),
            'ppk': float(ppk),
            'ppu': float(ppu),
            'ppl': float(ppl),
            'process_mean': float(mean),
            'process_std': float(std),
            'capability_assessment': self.assess_capability(cpk)
        }
    
    def assess_capability(self, cpk):
        """Assess process capability based on CPK value"""
        if cpk >= 2.0:
            return "Excellent"
        elif cpk >= 1.67:
            return "Good"
        elif cpk >= 1.33:
            return "Adequate"
        elif cpk >= 1.0:
            return "Marginal"
        else:
            return "Poor"
    
    def calculate_tolerance_utilization(self, measurements):
        """5. 公差利用率 (Tolerance Utilization)"""
        if len(measurements) < 2:
            return {}
        
        process_spread = 6 * np.std(measurements, ddof=1)  # 6σ spread
        tolerance_spread = self.usl - self.lsl
        
        utilization = process_spread / tolerance_spread * 100
        
        return {
            'tolerance_spread': float(tolerance_spread),
            'process_spread': float(process_spread),
            'utilization_percentage': float(utilization),
            'utilization_assessment': self.assess_utilization(utilization)
        }
    
    def assess_utilization(self, utilization):
        """Assess tolerance utilization"""
        if utilization <= 50:
            return "Under-utilized"
        elif utilization <= 75:
            return "Well-utilized"
        elif utilization <= 90:
            return "Efficiently-utilized"
        else:
            return "Over-utilized"
    
    def calculate_correlation_analysis(self, df):
        """6. 尺寸间的相关性 (Correlation Analysis)"""
        numeric_cols = ['int_value', 'float_value']
        if len(df) < 3:
            return {}
        
        # Calculate correlation matrix
        correlation_matrix = df[numeric_cols].corr()
        
        return {
            'correlation_matrix': correlation_matrix.to_dict(),
            'int_float_correlation': float(correlation_matrix.loc['int_value', 'float_value']),
            'correlation_strength': self.assess_correlation(correlation_matrix.loc['int_value', 'float_value'])
        }
    
    def assess_correlation(self, corr_value):
        """Assess correlation strength"""
        abs_corr = abs(corr_value)
        if abs_corr >= 0.8:
            return "Very Strong"
        elif abs_corr >= 0.6:
            return "Strong"
        elif abs_corr >= 0.4:
            return "Moderate"
        elif abs_corr >= 0.2:
            return "Weak"
        else:
            return "Very Weak"
    
    def calculate_time_series_analysis(self, df):
        """7. 时间序列分析 X-bar图、R图 (Time Series Analysis)"""
        if len(df) < 5:
            return {}
        
        measurements = df['float_value'].values
        subgroup_size = 5
        
        # Create subgroups
        subgroups = []
        for i in range(0, len(measurements) - subgroup_size + 1, subgroup_size):
            subgroups.append(measurements[i:i+subgroup_size])
        
        if len(subgroups) < 2:
            return {}
        
        # Calculate X-bar (subgroup means) and R (subgroup ranges)
        xbar_values = [np.mean(subgroup) for subgroup in subgroups]
        r_values = [np.max(subgroup) - np.min(subgroup) for subgroup in subgroups]
        
        # Control limits
        xbar_mean = np.mean(xbar_values)
        r_mean = np.mean(r_values)
        
        # Constants for control limits (for subgroup size 5)
        A2 = 0.577
        D3 = 0.0
        D4 = 2.114
        
        xbar_ucl = xbar_mean + A2 * r_mean
        xbar_lcl = xbar_mean - A2 * r_mean
        r_ucl = D4 * r_mean
        r_lcl = D3 * r_mean
        
        return {
            'xbar_values': xbar_values,
            'r_values': r_values,
            'xbar_mean': float(xbar_mean),
            'r_mean': float(r_mean),
            'xbar_ucl': float(xbar_ucl),
            'xbar_lcl': float(xbar_lcl),
            'r_ucl': float(r_ucl),
            'r_lcl': float(r_lcl),
            'subgroup_count': len(subgroups),
            'process_stability': self.assess_process_stability(xbar_values, r_values, xbar_ucl, xbar_lcl, r_ucl, r_lcl)
        }
    
    def assess_process_stability(self, xbar_values, r_values, xbar_ucl, xbar_lcl, r_ucl, r_lcl):
        """Assess process stability based on control charts"""
        xbar_out_of_control = sum(1 for x in xbar_values if x > xbar_ucl or x < xbar_lcl)
        r_out_of_control = sum(1 for r in r_values if r > r_ucl or r < r_lcl)
        
        if xbar_out_of_control == 0 and r_out_of_control == 0:
            return "Stable"
        elif xbar_out_of_control <= 1 and r_out_of_control <= 1:
            return "Marginally Stable"
        else:
            return "Unstable"
    
    def calculate_clustering_analysis(self, measurements):
        """8. 聚类分析 (Clustering Analysis)"""
        if len(measurements) < 6:
            return {}
        
        # Prepare data for clustering
        data = measurements.reshape(-1, 1)
        scaler = StandardScaler()
        scaled_data = scaler.fit_transform(data)
        
        # K-means clustering with 2-3 clusters
        optimal_clusters = min(3, len(measurements) // 3)
        if optimal_clusters < 2:
            optimal_clusters = 2
        
        kmeans = KMeans(n_clusters=optimal_clusters, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(scaled_data)
        
        # Analyze clusters
        cluster_info = {}
        for i in range(optimal_clusters):
            cluster_data = measurements[cluster_labels == i]
            if len(cluster_data) > 0:
                cluster_info[f'cluster_{i}'] = {
                    'count': len(cluster_data),
                    'mean': float(np.mean(cluster_data)),
                    'std': float(np.std(cluster_data, ddof=1)) if len(cluster_data) > 1 else 0.0,
                    'min': float(np.min(cluster_data)),
                    'max': float(np.max(cluster_data))
                }
        
        return {
            'cluster_count': optimal_clusters,
            'cluster_labels': cluster_labels.tolist(),
            'cluster_info': cluster_info,
            'silhouette_score': float(self.calculate_silhouette_score(scaled_data, cluster_labels))
        }
    
    def calculate_silhouette_score(self, data, labels):
        """Calculate silhouette score for clustering quality"""
        try:
            from sklearn.metrics import silhouette_score
            return silhouette_score(data, labels)
        except:
            return 0.0
    
    def detect_anomalies(self, measurements):
        """9. AI异常检测模型 (AI Anomaly Detection using Isolation Forest)"""
        if len(measurements) < 10:
            return {}
        
        # Prepare data
        data = measurements.reshape(-1, 1)
        
        # Isolation Forest for anomaly detection
        iso_forest = IsolationForest(contamination=0.1, random_state=42)
        anomaly_labels = iso_forest.fit_predict(data)
        
        # Identify anomalies (-1 = anomaly, 1 = normal)
        anomaly_indices = np.where(anomaly_labels == -1)[0]
        anomaly_values = measurements[anomaly_indices]
        
        return {
            'total_points': len(measurements),
            'anomaly_count': len(anomaly_indices),
            'anomaly_rate': float(len(anomaly_indices) / len(measurements) * 100),
            'anomaly_indices': anomaly_indices.tolist(),
            'anomaly_values': anomaly_values.tolist(),
            'anomaly_threshold': float(np.percentile(measurements, 10)),  # Approximate threshold
            'model_type': 'Isolation Forest'
        }
    
    def generate_quality_alerts(self, measurements, pass_fail):
        """Generate quality control alerts"""
        alerts = []
        
        if len(measurements) < 5:
            return alerts
        
        # Alert: Low pass rate
        pass_rate = np.mean(pass_fail) * 100
        if pass_rate < 80:
            alerts.append({
                'type': 'low_pass_rate',
                'message': f"Pass rate below 80%: {pass_rate:.1f}%",
                'severity': 'critical',
                'timestamp': datetime.now().isoformat()
            })
        
        # Alert: High process variation
        std = np.std(measurements, ddof=1)
        if std > self.tolerance / 3:  # If std > 1/3 of tolerance
            alerts.append({
                'type': 'high_variation',
                'message': f"High process variation: σ={std:.4f}mm",
                'severity': 'warning',
                'timestamp': datetime.now().isoformat()
            })
        
        # Alert: Process mean shift
        mean = np.mean(measurements)
        if abs(mean - self.target_value) > self.tolerance / 2:
            alerts.append({
                'type': 'mean_shift',
                'message': f"Process mean shift detected: {mean:.4f}mm (target: {self.target_value:.4f}mm)",
                'severity': 'warning',
                'timestamp': datetime.now().isoformat()
            })
        
        return alerts
    
    def generate_all_charts(self, df, measurements):
        """Generate all visualization charts as base64 encoded images"""
        charts = {}
        
        try:
            # Set style for better looking plots
            plt.style.use('seaborn-v0_8')
            
            # 1. Histogram (直方图)
            charts['histogram'] = self.create_histogram(measurements)
            
            # 2. Box Plot (箱型图)
            charts['boxplot'] = self.create_boxplot(measurements)
            
            # 3. Correlation Heatmap (热力图)
            charts['heatmap'] = self.create_correlation_heatmap(df)
            
            # 4. X-bar Chart (X-bar图)
            charts['xbar_chart'] = self.create_xbar_chart(measurements)
            
            # 5. R Chart (R图)
            charts['r_chart'] = self.create_r_chart(measurements)
            
            # 6. Scatter Plot for Clustering (散点图)
            charts['clustering_scatter'] = self.create_clustering_scatter(measurements)
            
            # 7. Time Series Plot (时间序列)
            charts['time_series'] = self.create_time_series_plot(df)
            
        except Exception as e:
            print(f"❌ Error generating charts: {e}")
        
        return charts
    
    def create_histogram(self, measurements):
        """Create histogram chart"""
        try:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.hist(measurements, bins=20, alpha=0.7, color='skyblue', edgecolor='black')
            ax.axvline(self.target_value, color='red', linestyle='--', label=f'Target ({self.target_value})')
            ax.axvline(self.usl, color='orange', linestyle='--', label=f'USL ({self.usl})')
            ax.axvline(self.lsl, color='orange', linestyle='--', label=f'LSL ({self.lsl})')
            ax.set_xlabel('Measurement Value (mm)')
            ax.set_ylabel('Frequency')
            ax.set_title('Measurement Distribution Histogram')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'histogram')
        except Exception as e:
            print(f"Error creating histogram: {e}")
            return ""
    
    def create_boxplot(self, measurements):
        """Create box plot chart"""
        try:
            fig, ax = plt.subplots(figsize=(10, 6))
            bp = ax.boxplot(measurements, patch_artist=True)
            bp['boxes'][0].set_facecolor('lightblue')
            
            ax.axhline(self.target_value, color='red', linestyle='--', label=f'Target ({self.target_value})')
            ax.axhline(self.usl, color='orange', linestyle='--', label=f'USL ({self.usl})')
            ax.axhline(self.lsl, color='orange', linestyle='--', label=f'LSL ({self.lsl})')
            ax.set_ylabel('Measurement Value (mm)')
            ax.set_title('Measurement Distribution Box Plot')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'boxplot')
        except Exception as e:
            print(f"Error creating boxplot: {e}")
            return ""
    
    def create_correlation_heatmap(self, df):
        """Create correlation heatmap"""
        try:
            numeric_cols = ['int_value', 'float_value']
            if len(df) < 3:
                return ""
            
            fig, ax = plt.subplots(figsize=(8, 6))
            correlation_matrix = df[numeric_cols].corr()
            sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0, ax=ax)
            ax.set_title('Correlation Heatmap')
            
            return self.save_chart_to_oss(fig, 'heatmap')
        except Exception as e:
            print(f"Error creating heatmap: {e}")
            return ""
    
    def create_xbar_chart(self, measurements):
        """Create X-bar control chart"""
        try:
            if len(measurements) < 10:
                return ""
            
            subgroup_size = 5
            subgroups = []
            for i in range(0, len(measurements) - subgroup_size + 1, subgroup_size):
                subgroups.append(measurements[i:i+subgroup_size])
            
            xbar_values = [np.mean(subgroup) for subgroup in subgroups]
            r_values = [np.max(subgroup) - np.min(subgroup) for subgroup in subgroups]
            
            xbar_mean = np.mean(xbar_values)
            r_mean = np.mean(r_values)
            A2 = 0.577
            
            xbar_ucl = xbar_mean + A2 * r_mean
            xbar_lcl = xbar_mean - A2 * r_mean
            
            fig, ax = plt.subplots(figsize=(12, 6))
            x_points = range(len(xbar_values))
            ax.plot(x_points, xbar_values, 'bo-', label='X-bar values')
            ax.axhline(xbar_mean, color='green', linestyle='-', label=f'Mean ({xbar_mean:.4f})')
            ax.axhline(xbar_ucl, color='red', linestyle='--', label=f'UCL ({xbar_ucl:.4f})')
            ax.axhline(xbar_lcl, color='red', linestyle='--', label=f'LCL ({xbar_lcl:.4f})')
            
            ax.set_xlabel('Subgroup Number')
            ax.set_ylabel('Subgroup Mean (mm)')
            ax.set_title('X-bar Control Chart')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'xbar_chart')
        except Exception as e:
            print(f"Error creating X-bar chart: {e}")
            return ""
    
    def create_r_chart(self, measurements):
        """Create R control chart"""
        try:
            if len(measurements) < 10:
                return ""
            
            subgroup_size = 5
            subgroups = []
            for i in range(0, len(measurements) - subgroup_size + 1, subgroup_size):
                subgroups.append(measurements[i:i+subgroup_size])
            
            r_values = [np.max(subgroup) - np.min(subgroup) for subgroup in subgroups]
            r_mean = np.mean(r_values)
            
            D3 = 0.0
            D4 = 2.114
            r_ucl = D4 * r_mean
            r_lcl = D3 * r_mean
            
            fig, ax = plt.subplots(figsize=(12, 6))
            x_points = range(len(r_values))
            ax.plot(x_points, r_values, 'ro-', label='R values')
            ax.axhline(r_mean, color='green', linestyle='-', label=f'Mean ({r_mean:.4f})')
            ax.axhline(r_ucl, color='red', linestyle='--', label=f'UCL ({r_ucl:.4f})')
            ax.axhline(r_lcl, color='red', linestyle='--', label=f'LCL ({r_lcl:.4f})')
            
            ax.set_xlabel('Subgroup Number')
            ax.set_ylabel('Subgroup Range (mm)')
            ax.set_title('R Control Chart')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'r_chart')
        except Exception as e:
            print(f"Error creating R chart: {e}")
            return ""
    
    def create_clustering_scatter(self, measurements):
        """Create clustering scatter plot"""
        try:
            if len(measurements) < 6:
                return ""
            
            # Prepare data
            data = measurements.reshape(-1, 1)
            scaler = StandardScaler()
            scaled_data = scaler.fit_transform(data)
            
            optimal_clusters = min(3, len(measurements) // 3)
            if optimal_clusters < 2:
                optimal_clusters = 2
            
            kmeans = KMeans(n_clusters=optimal_clusters, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(scaled_data)
            
            fig, ax = plt.subplots(figsize=(10, 6))
            colors = ['red', 'blue', 'green', 'orange', 'purple']
            
            for i in range(optimal_clusters):
                cluster_data = measurements[cluster_labels == i]
                y_values = np.ones(len(cluster_data)) * i  # Spread vertically by cluster
                ax.scatter(cluster_data, y_values, c=colors[i % len(colors)], 
                          label=f'Cluster {i+1}', alpha=0.7, s=50)
            
            ax.set_xlabel('Measurement Value (mm)')
            ax.set_ylabel('Cluster')
            ax.set_title('Clustering Analysis Scatter Plot')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'clustering_scatter')
        except Exception as e:
            print(f"Error creating clustering scatter: {e}")
            return ""
    
    def create_time_series_plot(self, df):
        """Create time series plot"""
        try:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
            
            # Measurement values over time
            ax1.plot(df.index, df['float_value'], 'b-', alpha=0.7, label='Measurements')
            ax1.axhline(self.target_value, color='red', linestyle='--', label=f'Target ({self.target_value})')
            ax1.axhline(self.usl, color='orange', linestyle='--', label=f'USL ({self.usl})')
            ax1.axhline(self.lsl, color='orange', linestyle='--', label=f'LSL ({self.lsl})')
            ax1.set_ylabel('Measurement Value (mm)')
            ax1.set_title('Time Series - Measurement Values')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # Pass/Fail over time
            ax2.plot(df.index, df['bool_value'].astype(int), 'go-', alpha=0.7, label='Pass/Fail')
            ax2.set_ylabel('Pass (1) / Fail (0)')
            ax2.set_xlabel('Sample Number')
            ax2.set_title('Time Series - Pass/Fail Status')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            ax2.set_ylim(-0.1, 1.1)
            
            plt.tight_layout()
            return self.save_chart_to_oss(fig, 'time_series')
        except Exception as e:
            print(f"Error creating time series plot: {e}")
            return ""
    
    def save_chart_to_oss(self, fig, chart_name):
        """Save matplotlib figure as PNG file to OSS and return URL"""
        try:
            buffer = io.BytesIO()
            fig.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
            buffer.seek(0)
            
            # Generate OSS key for chart (latest version, no timestamp)
            oss_key = f"charts/latest_{chart_name}.png"
            
            # Upload to OSS (overwrites previous version)
            self.oss_bucket.put_object(oss_key, buffer.getvalue())
            buffer.close()
            plt.close(fig)  # Close figure to free memory
            
            # Return the OSS key (desktop app will construct full URL)
            return oss_key
        except Exception as e:
            print(f"Error saving chart {chart_name} to OSS: {e}")
            if fig:
                plt.close(fig)
            return ""
    
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