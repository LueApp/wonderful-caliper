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

# LLM integration for analysis insights
try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    print("⚠️ anthropic package not installed. Run: pip install anthropic")

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
        self.target_values = {}  # Target dimension values for each step
        self.tolerance = 0.05    # ±0.05mm tolerance
        self.target_value = 0.0  # Default fallback value
        self.usl = self.target_value + self.tolerance  # Upper Specification Limit
        self.lsl = self.target_value - self.tolerance  # Lower Specification Limit
        
        # Timing
        self.last_upload = time.time()
        self.upload_interval = 10  # seconds
        
        # Claude API for insights generation
        self.claude_client = None
        if CLAUDE_AVAILABLE:
            try:
                # Configure for proxy if needed
                import httpx
                
                # Option 1: Use without proxy (try first)
                try:
                    self.claude_client = anthropic.Anthropic()
                    print("✅ Claude API initialized for insights generation")
                except Exception as proxy_error:
                    print(f"⚠️ Direct connection failed: {proxy_error}")
                    
                    # Option 2: Configure custom HTTP client without proxy
                    print("🔄 Trying without proxy...")
                    http_client = httpx.Client(proxies={})
                    self.claude_client = anthropic.Anthropic(http_client=http_client)
                    print("✅ Claude API initialized (no proxy)")
                    
            except Exception as e:
                print(f"⚠️ Claude API initialization failed: {e}")
                print("💡 Solutions:")
                print("   1. Install SOCKS support: pip install httpx[socks]")
                print("   2. Set API key: export ANTHROPIC_API_KEY='your-key'")
                print("   3. Check network/proxy settings")
        
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
    
    def load_target_values(self):
        """Load target values from OSS latest_array.json"""
        try:
            array_file = "arrays/latest_array.json"
            print(f"📥 Loading target values from OSS: {array_file}")
            
            # Check if OSS bucket is available
            if not self.oss_bucket:
                print("❌ OSS bucket not initialized, cannot load target values")
                return
            
            obj = self.oss_bucket.get_object(array_file)
            content = obj.read().decode('utf-8')
            print(f"🔍 Raw OSS content: {content}")
            
            array_data = json.loads(content)[0]
            print(f"🔍 Parsed array data: {array_data}, type: {type(array_data)}")
            
            # Extract target values for each step
            if isinstance(array_data, list) and len(array_data) > 0:
                self.target_values = {}
                for i, target_val in enumerate(array_data, 1):
                    try:
                        self.target_values[i] = float(target_val)
                        print(f"  Step {i}: {target_val} -> {float(target_val)}")
                    except (ValueError, TypeError) as e:
                        print(f"  ⚠️ Invalid target value for step {i}: {target_val} ({e})")
                        self.target_values[i] = 0.0
                
                # Set default target_value to first step's value
                self.target_value = self.target_values.get(1, 0.0)
                self.update_tolerance_limits()
                
                print(f"✅ Loaded target values for {len(self.target_values)} steps: {self.target_values}")
                print(f"✅ Default target value set to: {self.target_value}")
            else:
                print(f"⚠️ Invalid array data format (type: {type(array_data)}, len: {len(array_data) if hasattr(array_data, '__len__') else 'N/A'})")
                print("🔄 Using default target value 0.0")
                
        except oss2.exceptions.NoSuchKey:
            print("📝 No target array found on OSS, using default target value 0.0")
        except Exception as e:
            print(f"❌ Error loading target values: {e}")
            print("🔄 Using default target value 0.0")
    
    def update_tolerance_limits(self):
        """Update tolerance limits based on current target value"""
        self.usl = self.target_value + self.tolerance
        self.lsl = self.target_value - self.tolerance
    
    def get_target_value_for_step(self, step_num):
        """Get target value for specific step"""
        target_val = self.target_values.get(step_num, self.target_value)
        print(f"🎯 Getting target for step {step_num}: {target_val} (available steps: {list(self.target_values.keys())})")
        return target_val
    
    def analyze_data(self):
        """Comprehensive statistical analysis of measurement data by steps"""
        with self.analysis_lock:
            if len(self.realtime_buffer) < 1:  # Allow even single data points
                print(f"⚠️ No data available for analysis (buffer has {len(self.realtime_buffer)} points)")
                return
            
            # Convert to pandas for analysis
            df = pd.DataFrame(list(self.realtime_buffer))
            print(f"🔍 Analyzing {len(df)} data points from buffer")
            
            try:
                # Group data by step (int_value) for separate analysis
                step_groups = df.groupby('int_value')
                step_analysis = {}
                overall_charts = {}
                overall_alerts = []
                
                # Analyze each step separately
                for step_num, step_df in step_groups:
                    print(f"  Step {step_num}: {len(step_df)} data points")
                    if len(step_df) < 1:  # Allow single data points per step
                        print(f"  Skipping step {step_num} (insufficient data)")
                        continue
                    
                    # Extract measurement data for this step
                    measurements = step_df['float_value'].values
                    pass_fail = step_df['bool_value'].values
                    
                    # Get step-specific target value
                    print(f"📊 Processing step {step_num} (type: {type(step_num)})")
                    step_target = self.get_target_value_for_step(step_num)
                    
                    # Perform analysis for this step
                    step_results = {
                        'step_number': int(step_num),
                        'data_count': len(step_df),
                        'target_value': step_target,
                        'descriptive_statistics': self.calculate_descriptive_statistics(measurements),
                        'deviation_analysis': self.calculate_deviation_analysis(measurements, step_target),
                        'pass_rate_analysis': self.calculate_pass_rate_analysis(pass_fail, measurements, step_target),
                        'process_capability': self.calculate_process_capability(measurements, step_target),
                        'tolerance_utilization': self.calculate_tolerance_utilization(measurements),
                        'time_series_analysis': self.calculate_time_series_analysis(step_df),
                        'clustering_analysis': self.calculate_clustering_analysis(measurements),
                        'anomaly_detection': self.detect_anomalies(measurements),
                        'charts': self.generate_step_charts(step_df, measurements, step_num, step_target),
                        'alerts': self.generate_quality_alerts(measurements, pass_fail, step_num, step_target)
                    }
                    
                    step_analysis[f'step_{step_num}'] = step_results
                    overall_alerts.extend(step_results['alerts'])
                
                # Calculate overall correlation analysis (across all steps)
                correlation_analysis = self.calculate_correlation_analysis(df)
                
                # If no steps had enough data, fall back to legacy analysis
                if not step_analysis:
                    print("⚠️ No steps with sufficient data, falling back to legacy analysis")
                    self.perform_legacy_analysis(df)
                    return
                
                # Generate overall summary
                overall_summary = self.calculate_overall_summary(step_analysis, df)
                
                # Final analysis results
                temp_results = {
                    'last_analysis': datetime.now().isoformat(),
                    'total_data_count': len(df),
                    'step_count': len(step_analysis),
                    'step_analysis': step_analysis,
                    'overall_summary': overall_summary,
                    'correlation_analysis': correlation_analysis,
                    'overall_charts': self.generate_overall_charts(df),
                    'alerts': overall_alerts
                }
                
                # Generate AI insights based on multi-step analysis
                ai_insights = self.generate_ai_insights(temp_results)
                
                # Final analysis results including AI insights
                self.analysis_results = temp_results
                self.analysis_results['ai_insights'] = ai_insights
                
                # Print brief status
                if len(df) % 5 == 0:  # Print every 5th analysis
                    step_count = len(step_analysis)
                    total_alerts = len(overall_alerts)
                    avg_pass_rate = overall_summary.get('average_pass_rate', 0)
                    print(f"📈 Multi-step Analysis: {len(df)} total points across {step_count} steps")
                    print(f"   Average Pass Rate: {avg_pass_rate:.1f}%, Total Alerts: {total_alerts}")
                
            except Exception as e:
                print(f"❌ Analysis error: {e}")
    
    def perform_legacy_analysis(self, df):
        """Fallback to legacy single-dataset analysis when multi-step analysis fails"""
        try:
            # Extract measurement data (float_value = measurement, bool_value = pass/fail)
            measurements = df['float_value'].values
            pass_fail = df['bool_value'].values
            
            # Generate basic analysis
            descriptive_stats = self.calculate_descriptive_statistics(measurements)
            pass_rate_analysis = self.calculate_pass_rate_analysis(pass_fail, measurements)
            process_capability = self.calculate_process_capability(measurements)
            
            # Generate all expected charts
            charts = {
                'histogram': self.create_histogram(measurements, "Overall"),
                'boxplot': self.create_boxplot(measurements, "Overall"),
                'heatmap': self.create_correlation_heatmap(df),
                'xbar_chart': self.create_xbar_chart(measurements, "Overall"),
                'r_chart': self.create_r_chart(measurements, "Overall"),
                'clustering_scatter': self.create_clustering_scatter(measurements, "Overall"),
                'time_series': self.create_time_series_plot(df, "Overall")
            }
            
            # Simple results structure
            temp_results = {
                'last_analysis': datetime.now().isoformat(),
                'data_count': len(df),
                'descriptive_statistics': descriptive_stats,
                'pass_rate_analysis': pass_rate_analysis,
                'process_capability': process_capability,
                'charts': charts,
                'alerts': self.generate_quality_alerts(measurements, pass_fail)
            }
            
            # Store results
            self.analysis_results = temp_results
            self.analysis_results['ai_insights'] = "Legacy analysis mode - limited insights available"
            
            # Print status
            pass_rate = pass_rate_analysis.get('pass_rate', 0)
            mean_val = descriptive_stats.get('mean', 0)
            cpk = process_capability.get('cpk', 0)
            print(f"📈 Legacy Analysis: {len(df)} points, Mean: {mean_val:.3f}mm, Pass Rate: {pass_rate:.1f}%, CPK: {cpk:.2f}")
            
        except Exception as e:
            print(f"❌ Legacy analysis error: {e}")
    
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
    
    def calculate_deviation_analysis(self, measurements, target_value=None):
        """2. 尺寸偏差分布 (Dimension Deviation Distribution)"""
        if target_value is None:
            target_value = self.target_value
        deviations = measurements - target_value
        
        return {
            'mean_deviation': float(np.mean(deviations)),
            'std_deviation': float(np.std(deviations, ddof=1)),
            'max_positive_deviation': float(np.max(deviations)),
            'max_negative_deviation': float(np.min(deviations)),
            'deviation_range': float(np.max(deviations) - np.min(deviations)),
            'within_tolerance_count': int(np.sum(np.abs(deviations) <= self.tolerance)),
            'outside_tolerance_count': int(np.sum(np.abs(deviations) > self.tolerance))
        }
    
    def calculate_pass_rate_analysis(self, pass_fail, measurements, target_value=None):
        """3. 合格率的分析 (Pass Rate Analysis)"""
        if target_value is None:
            target_value = self.target_value
            
        total_count = len(pass_fail)
        if total_count == 0:
            return {}
        
        pass_count = np.sum(pass_fail)
        fail_count = total_count - pass_count
        
        # Calculate pass rate by tolerance
        within_tolerance = np.abs(measurements - target_value) <= self.tolerance
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
    
    def calculate_process_capability(self, measurements, target_value=None):
        """4. 过程能力指数 CPK/PPK (Process Capability Indices)"""
        if target_value is None:
            target_value = self.target_value
            
        if len(measurements) < 2:
            return {}
        
        mean = np.mean(measurements)
        std = np.std(measurements, ddof=1)
        
        # Calculate USL/LSL for this step
        usl = target_value + self.tolerance
        lsl = target_value - self.tolerance
        
        if std == 0:
            return {'cpk': float('inf'), 'ppk': float('inf'), 'cp': float('inf'), 'pp': float('inf')}
        
        # Process Capability (Cp, Cpk)
        cp = (usl - lsl) / (6 * std)
        cpu = (usl - mean) / (3 * std)
        cpl = (mean - lsl) / (3 * std)
        cpk = min(cpu, cpl)
        
        # Process Performance (Pp, Ppk) - using overall std
        pp = (usl - lsl) / (6 * std)
        ppu = (usl - mean) / (3 * std)
        ppl = (mean - lsl) / (3 * std)
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
            return "优秀"
        elif cpk >= 1.67:
            return "良好"
        elif cpk >= 1.33:
            return "充分"
        elif cpk >= 1.0:
            return "临界"
        else:
            return "不足"
    
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
    
    def generate_quality_alerts(self, measurements, pass_fail, step_num=None, target_value=None):
        
        """Generate quality control alerts for a specific step"""
        if target_value is None:
            target_value = self.get_target_value_for_step(step_num) if step_num else self.target_value
            
        alerts = []
        
        if len(measurements) < 5:
            return alerts
        
        step_prefix = f"步骤{step_num}: " if step_num is not None else ""
        
        # Alert: Low pass rate
        pass_rate = np.mean(pass_fail) * 100
        if pass_rate < 80:
            alerts.append({
                'type': 'low_pass_rate',
                'step': step_num,
                'message': f"{step_prefix}合格率低于80%: {pass_rate:.1f}%",
                'severity': 'critical',
                'timestamp': datetime.now().isoformat()
            })
        
        # Alert: High process variation
        std = np.std(measurements, ddof=1)
        if std > self.tolerance / 3:  # If std > 1/3 of tolerance
            alerts.append({
                'type': 'high_variation',
                'step': step_num,
                'message': f"{step_prefix}过程变异过大: σ={std:.4f}mm",
                'severity': 'warning',
                'timestamp': datetime.now().isoformat()
            })
        
        # Alert: Process mean shift
        mean = np.mean(measurements)
        if abs(mean - target_value) > self.tolerance / 2:
            alerts.append({
                'type': 'mean_shift',
                'step': step_num,
                'message': f"{step_prefix}过程均值偏移: {mean:.4f}mm (目标: {target_value:.4f}mm)",
                'severity': 'warning',
                'timestamp': datetime.now().isoformat()
            })
        
        return alerts
    
    def generate_step_charts(self, step_df, measurements, step_num, target_value=None):
        """Generate visualization charts for a specific step"""
        if target_value is None:
            target_value = self.get_target_value_for_step(step_num)
        charts = {}
        
        try:
            # Set style for better looking plots
            plt.style.use('seaborn-v0_8')
            
            # 1. Histogram for this step
            charts['histogram'] = self.create_histogram(measurements, f"步骤{step_num}", target_value)
            
            # 2. Box Plot for this step
            charts['boxplot'] = self.create_boxplot(measurements, f"步骤{step_num}", target_value)
            
            # 3. X-bar Chart for this step
            charts['xbar_chart'] = self.create_xbar_chart(measurements, f"步骤{step_num}")
            
            # 4. R Chart for this step
            charts['r_chart'] = self.create_r_chart(measurements, f"步骤{step_num}")
            
            # 5. Clustering scatter for this step
            charts['clustering_scatter'] = self.create_clustering_scatter(measurements, f"步骤{step_num}")
            
            # 6. Time Series for this step
            charts['time_series'] = self.create_time_series_plot(step_df, f"步骤{step_num}", target_value)
            
        except Exception as e:
            print(f"❌ Error generating step {step_num} charts: {e}")
        
        return charts
    
    def generate_overall_charts(self, df):
        """Generate overall charts across all steps"""
        charts = {}
        
        try:
            # Set style for better looking plots
            plt.style.use('seaborn-v0_8')
            
            # Overall correlation heatmap
            charts['correlation_heatmap'] = self.create_correlation_heatmap(df)
            
            # Step comparison charts
            charts['step_comparison'] = self.create_step_comparison_chart(df)
            
        except Exception as e:
            print(f"❌ Error generating overall charts: {e}")
        
        return charts
    
    def create_histogram(self, measurements, step_label="", target_value=None):
        """Create histogram chart"""
        if target_value is None:
            target_value = self.target_value
        usl = target_value + self.tolerance
        lsl = target_value - self.tolerance
        
        try:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.hist(measurements, bins=20, alpha=0.7, color='skyblue', edgecolor='black')
            ax.axvline(target_value, color='red', linestyle='--', label=f'Target ({target_value})')
            ax.axvline(usl, color='orange', linestyle='--', label=f'USL ({usl})')
            ax.axvline(lsl, color='orange', linestyle='--', label=f'LSL ({lsl})')
            ax.set_xlabel('Measurement Value (mm)')
            ax.set_ylabel('Frequency')
            title = f'{step_label} Measurement Distribution Histogram' if step_label else 'Measurement Distribution Histogram'
            ax.set_title(title)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'histogram')
        except Exception as e:
            print(f"Error creating histogram: {e}")
            return ""
    
    def create_boxplot(self, measurements, step_label="", target_value=None):
        """Create box plot chart"""
        if target_value is None:
            target_value = self.target_value
        usl = target_value + self.tolerance
        lsl = target_value - self.tolerance
        
        try:
            fig, ax = plt.subplots(figsize=(10, 6))
            bp = ax.boxplot(measurements, patch_artist=True)
            bp['boxes'][0].set_facecolor('lightblue')
            
            ax.axhline(target_value, color='red', linestyle='--', label=f'Target ({target_value})')
            ax.axhline(usl, color='orange', linestyle='--', label=f'USL ({usl})')
            ax.axhline(lsl, color='orange', linestyle='--', label=f'LSL ({lsl})')
            ax.set_ylabel('Measurement Value (mm)')
            title = f'{step_label} Measurement Distribution Box Plot' if step_label else 'Measurement Distribution Box Plot'
            ax.set_title(title)
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
    
    def create_xbar_chart(self, measurements, step_label=""):
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
            title = f'{step_label} X-bar Control Chart' if step_label else 'X-bar Control Chart'
            ax.set_title(title)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'xbar_chart')
        except Exception as e:
            print(f"Error creating X-bar chart: {e}")
            return ""
    
    def create_r_chart(self, measurements, step_label=""):
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
            title = f'{step_label} R Control Chart' if step_label else 'R Control Chart'
            ax.set_title(title)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'r_chart')
        except Exception as e:
            print(f"Error creating R chart: {e}")
            return ""
    
    def create_clustering_scatter(self, measurements, step_label=""):
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
            title = f'{step_label} Clustering Analysis Scatter Plot' if step_label else 'Clustering Analysis Scatter Plot'
            ax.set_title(title)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            return self.save_chart_to_oss(fig, 'clustering_scatter')
        except Exception as e:
            print(f"Error creating clustering scatter: {e}")
            return ""
    
    def create_time_series_plot(self, df, step_label="", target_value=None):
        """Create time series plot"""
        if target_value is None:
            target_value = self.target_value
        usl = target_value + self.tolerance
        lsl = target_value - self.tolerance
        
        try:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
            
            # Measurement values over time
            ax1.plot(df.index, df['float_value'], 'b-', alpha=0.7, label='Measurements')
            ax1.axhline(target_value, color='red', linestyle='--', label=f'Target ({target_value})')
            ax1.axhline(usl, color='orange', linestyle='--', label=f'USL ({usl})')
            ax1.axhline(lsl, color='orange', linestyle='--', label=f'LSL ({lsl})')
            ax1.set_ylabel('Measurement Value (mm)')
            title1 = f'{step_label} Time Series - Measurement Values' if step_label else 'Time Series - Measurement Values'
            ax1.set_title(title1)
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # Pass/Fail over time
            ax2.plot(df.index, df['bool_value'].astype(int), 'go-', alpha=0.7, label='Pass/Fail')
            ax2.set_ylabel('Pass (1) / Fail (0)')
            ax2.set_xlabel('Sample Number')
            title2 = f'{step_label} Time Series - Pass/Fail Status' if step_label else 'Time Series - Pass/Fail Status'
            ax2.set_title(title2)
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            ax2.set_ylim(-0.1, 1.1)
            
            plt.tight_layout()
            return self.save_chart_to_oss(fig, 'time_series')
        except Exception as e:
            print(f"Error creating time series plot: {e}")
            return ""
    
    def calculate_overall_summary(self, step_analysis, df):
        """Calculate overall summary across all steps"""
        try:
            if not step_analysis:
                return {}
            
            # Collect metrics from all steps
            pass_rates = []
            cpk_values = []
            data_counts = []
            
            for step_key, step_data in step_analysis.items():
                pass_rate_info = step_data.get('pass_rate_analysis', {})
                if 'pass_rate' in pass_rate_info:
                    pass_rates.append(pass_rate_info['pass_rate'])
                
                capability_info = step_data.get('process_capability', {})
                if 'cpk' in capability_info:
                    cpk_values.append(capability_info['cpk'])
                
                data_counts.append(step_data.get('data_count', 0))
            
            # Calculate overall metrics
            summary = {
                'total_steps': len(step_analysis),
                'total_measurements': sum(data_counts),
                'average_pass_rate': float(np.mean(pass_rates)) if pass_rates else 0.0,
                'average_cpk': float(np.mean(cpk_values)) if cpk_values else 0.0,
                'worst_performing_step': self.find_worst_step(step_analysis),
                'best_performing_step': self.find_best_step(step_analysis),
                'step_consistency': self.assess_step_consistency(pass_rates, cpk_values)
            }
            
            return summary
            
        except Exception as e:
            print(f"Error calculating overall summary: {e}")
            return {}
    
    def find_worst_step(self, step_analysis):
        """Find the step with worst performance"""
        if not step_analysis:
            return None
            
        worst_step = None
        lowest_score = float('inf')
        
        for step_key, step_data in step_analysis.items():
            if not step_data:
                continue
                
            pass_rate_info = step_data.get('pass_rate_analysis') or {}
            pass_rate = pass_rate_info.get('pass_rate', 100)
            capability_info = step_data.get('process_capability') or {}
            cpk = capability_info.get('cpk', 2.0)
            
            # Combined score (lower is worse)
            score = (pass_rate / 100) * min(cpk, 2.0)
            
            if score < lowest_score:
                lowest_score = score
                worst_step = {
                    'step': step_key,
                    'pass_rate': pass_rate,
                    'cpk': cpk,
                    'performance_score': score
                }
        
        return worst_step
    
    def find_best_step(self, step_analysis):
        """Find the step with best performance"""
        if not step_analysis:
            return None
            
        best_step = None
        highest_score = 0.0
        
        for step_key, step_data in step_analysis.items():
            if not step_data:
                continue
                
            pass_rate_info = step_data.get('pass_rate_analysis') or {}
            pass_rate = pass_rate_info.get('pass_rate', 0)
            capability_info = step_data.get('process_capability') or {}
            cpk = capability_info.get('cpk', 0)
            
            # Combined score (higher is better)
            score = (pass_rate / 100) * min(cpk, 2.0)
            
            if score > highest_score:
                highest_score = score
                best_step = {
                    'step': step_key,
                    'pass_rate': pass_rate,
                    'cpk': cpk,
                    'performance_score': score
                }
        
        return best_step
    
    def assess_step_consistency(self, pass_rates, cpk_values):
        """Assess consistency across steps"""
        if not pass_rates or not cpk_values:
            return "Unknown"
        
        pass_rate_cv = np.std(pass_rates) / np.mean(pass_rates) if np.mean(pass_rates) > 0 else 0
        cpk_cv = np.std(cpk_values) / np.mean(cpk_values) if np.mean(cpk_values) > 0 else 0
        
        # Average coefficient of variation
        avg_cv = (pass_rate_cv + cpk_cv) / 2
        
        if avg_cv <= 0.05:
            return "Highly Consistent"
        elif avg_cv <= 0.10:
            return "Consistent"
        elif avg_cv <= 0.20:
            return "Moderately Consistent"
        else:
            return "Inconsistent"
    
    def create_step_comparison_chart(self, df):
        """Create chart comparing performance across steps"""
        try:
            step_groups = df.groupby('int_value')
            steps = []
            pass_rates = []
            means = []
            
            for step_num, step_df in step_groups:
                if len(step_df) < 3:
                    continue
                
                steps.append(f"Step {step_num}")
                pass_rates.append(np.mean(step_df['bool_value']) * 100)
                means.append(np.mean(step_df['float_value']))
            
            if len(steps) < 2:
                return ""
            
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
            
            # Pass rates by step
            ax1.bar(steps, pass_rates, color='lightblue', alpha=0.7)
            ax1.set_ylabel('Pass Rate (%)')
            ax1.set_title('Pass Rate by Step')
            ax1.grid(True, alpha=0.3)
            
            # Mean values by step
            ax2.bar(steps, means, color='lightgreen', alpha=0.7)
            ax2.axhline(self.target_value, color='red', linestyle='--', label='Target')
            ax2.set_ylabel('Mean Value (mm)')
            ax2.set_title('Mean Measurement by Step')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            return self.save_chart_to_oss(fig, 'step_comparison')
            
        except Exception as e:
            print(f"Error creating step comparison chart: {e}")
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
    
    def generate_ai_insights(self, analysis_data):
        """Generate AI-powered insights using Claude API for multi-step measurement analysis"""
        if not self.claude_client:
            return "AI insights unavailable - Claude API not configured"
        
        try:
            # Extract overall summary and step-specific data
            overall_summary = analysis_data.get('overall_summary', {})
            step_analysis = analysis_data.get('step_analysis', {})
            total_data_count = analysis_data.get('total_data_count', 0)
            step_count = analysis_data.get('step_count', 0)
            alerts = analysis_data.get('alerts', [])
            
            # Validate data structure
            if not overall_summary or not step_analysis:
                return "AI insights unavailable - insufficient analysis data"
            
            # Build step performance summary
            step_performance = []
            for step_key, step_data in step_analysis.items():
                if not step_data:
                    continue
                    
                step_num = step_data.get('step_number', 'Unknown')
                pass_rate_info = step_data.get('pass_rate_analysis') or {}
                pass_rate = pass_rate_info.get('pass_rate', 0)
                capability_info = step_data.get('process_capability') or {}
                cpk = capability_info.get('cpk', 0)
                data_count = step_data.get('data_count', 0)
                step_alerts = len(step_data.get('alerts', []))
                
                step_performance.append(f"  • 步骤{step_num}: 合格率{pass_rate:.1f}%, CPK={cpk:.3f}, {data_count}次测量, {step_alerts}个警报")
            
            worst_step = overall_summary.get('worst_performing_step') or {}
            best_step = overall_summary.get('best_performing_step') or {}
            consistency = overall_summary.get('step_consistency', 'Unknown')
            avg_pass_rate = overall_summary.get('average_pass_rate', 0)
            avg_cpk = overall_summary.get('average_cpk', 0)
            
            # Build comprehensive prompt for multi-step analysis (Chinese output)
            prompt = f"""
作为专业的制造质量控制专家，请分析我们多步骤生产线上的零件长度测量数据：

🏭 生产背景：
• 测量对象：使用电容式位移传感器(TM003)进行多步骤零件长度检测
• 生产工艺：多工位制造精密零件，每个步骤都有严格的长度要求
• 测量系统：基于ESP32的实时多步骤尺寸检测
• 关键质量参数：每个制造步骤的零件长度都必须满足公差要求

📊 多步骤分析结果：
• 总测量次数：{total_data_count}次，覆盖{step_count}个制造步骤
• 平均合格率：{avg_pass_rate:.1f}%
• 平均过程能力指数(CPK)：{avg_cpk:.3f}
• 步骤间一致性：{consistency}
• 质量警报总数：{len(alerts)}个

🔍 各步骤详细表现：
{chr(10).join(step_performance)}

📈 关键发现：
• 最佳表现步骤：{best_step.get('step', 'N/A')} (合格率{best_step.get('pass_rate', 0):.1f}%, CPK={best_step.get('cpk', 0):.3f})
• 最差表现步骤：{worst_step.get('step', 'N/A')} (合格率{worst_step.get('pass_rate', 0):.1f}%, CPK={worst_step.get('cpk', 0):.3f})

🎯 规格要求：
• 目标长度：{self.target_value:.4f}mm
• 公差带：±{self.tolerance:.3f}mm
• 上限规格(USL)：{self.usl:.4f}mm
• 下限规格(LSL)：{self.lsl:.4f}mm

请针对多步骤制造过程提供专业分析，包括：

1. **多步骤质量状态** - 整体制造过程是否稳定可控？
2. **步骤间关联分析** - 不同步骤间的质量传递和影响
3. **工艺优化建议** - 针对表现差的步骤的具体改进措施
4. **质量控制策略** - 多步骤质量监控和预防措施
5. **根因分析** - 导致步骤间差异的可能原因

请重点关注多步骤制造过程的系统性质量控制，为制造工程师和质量管理人员提供实用的多工位质量改进指导。请用中文回答。
"""

            # Call Claude API
            response = self.claude_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=700,
                temperature=0.3,
                messages=[
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ]
            )
            
            return response.content[0].text
            
        except Exception as e:
            return f"AI insights generation failed: {str(e)}"
    
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
            
            data_count = self.analysis_results.get('data_count', 0)
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
        
        # Load target values from OSS
        self.load_target_values()
        
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