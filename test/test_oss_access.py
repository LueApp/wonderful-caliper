# Quick OSS test
import oss2

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Import configuration
try:
    import config
    CONFIG_AVAILABLE = True
    print("✅ Using config.py for configuration")
except ImportError:
    CONFIG_AVAILABLE = False
    print("⚠️  config.py not found. Using hardcoded configuration.")

def get_emqx_oss_config():
    """
    Get EMQX Cloud + OSS configuration
    Uses config.py if available, otherwise falls back to hardcoded values
    """
    if CONFIG_AVAILABLE:
        try:
            # Use config.py
            return config.get_config()
        except Exception as e:
            print(f"⚠️  Error loading config.py: {e}")
            print("Falling back to hardcoded configuration...")
    
    # Fallback hardcoded configuration
    return {
        'emqx': {
            'broker': 'your-deployment.emqxsl.com',
            'port': 1883,
            'username': 'python_app',
            'password': 'python_secure_pass_2024',
            'keepalive': 60,
            'client_id_prefix': 'python_uploader'
        },
        'oss': {
            'access_key_id': 'YOUR_OSS_ACCESS_KEY_ID',
            'access_key_secret': 'YOUR_OSS_ACCESS_KEY_SECRET', 
            'endpoint': 'oss-cn-beijing.aliyuncs.com',
            'bucket_name': 'your-iot-project-photos'
        },
        'topics': {
            'esp32_data': 'devices/esp32-001/data',
            'esp32_array': 'devices/esp32-001/array',
            'esp32_status': 'devices/esp32-001/status', 
            'esp32_control': 'devices/esp32-001/control',
            'app_notifications': 'app/notifications',
            'app_file_uploaded': 'app/file-uploaded',
            'app_esp32_data': 'app/esp32-data',
            'system_processing': 'system/processing-status',
            'system_logs': 'system/logs'
        },
        'device': {
            'esp32_id': 'esp32-001',
            'location': 'home-lab'
        }
    }


def main():
    config = get_emqx_oss_config()
    auth = oss2.Auth(config['oss']['access_key_id'], config['oss']['access_key_secret'])
    bucket = oss2.Bucket(auth, config['oss']['endpoint'], config['oss']['bucket_name'])
    for obj in bucket.list_objects().object_list:
        print(f"File: {obj.key}, Size: {obj.size}")

if __name__ == "__main__":
    main()