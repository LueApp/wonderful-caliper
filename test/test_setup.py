#!/usr/bin/env python3
"""
Test script to verify the setup before running the examples
"""

import sys
import os

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_config, validate_config

def test_imports():
    """Test if all required packages are installed"""
    print("🧪 Testing package imports...")
    
    try:
        import oss2
        print("✅ oss2 imported successfully")
    except ImportError as e:
        print(f"❌ oss2 import failed: {e}")
        return False
    
    try:
        import paho.mqtt.client as mqtt
        print("✅ paho-mqtt imported successfully")
    except ImportError as e:
        print(f"❌ paho-mqtt import failed: {e}")
        return False
    
    try:
        import numpy as np
        print("✅ numpy imported successfully")
    except ImportError as e:
        print(f"❌ numpy import failed: {e}")
        return False
    
    try:
        from PIL import Image
        print("✅ PIL (Pillow) imported successfully")
    except ImportError as e:
        print(f"❌ PIL import failed: {e}")
        return False
    
    return True

def test_config():
    """Test configuration validation"""
    print("\n🔧 Testing configuration...")
    
    try:
        # Test all program types
        program_types = ['app', 'algorithm', 'esp32']
        all_valid = True
        
        for program_type in program_types:
            print(f"   Testing {program_type} configuration...")
            config = get_config(program_type)
            is_valid = validate_config(config)
            if not is_valid:
                all_valid = False
                print(f"   ❌ {program_type} configuration invalid")
            else:
                print(f"   ✅ {program_type} configuration valid")
        
        return all_valid
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

def test_directories():
    """Create necessary directories"""
    print("\n📁 Creating necessary directories...")
    
    directories = ['../temp', '../processed']
    
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"✅ Directory created/verified: {directory}")
        except Exception as e:
            print(f"❌ Failed to create directory {directory}: {e}")
            return False
    
    return True

def test_test_image():
    """Check if test image exists"""
    print("\n🖼️ Checking test image...")
    
    if os.path.exists("test_image.png"):
        print("✅ test_image.png found")
        return True
    else:
        print("⚠️ test_image.png not found")
        print("💡 You can add any PNG image as 'test_image.png' for testing")
        return False

def main():
    """Run all tests"""
    print("🚀 Running setup tests...")
    print("=" * 50)
    
    tests = [
        ("Package imports", test_imports),
        ("Configuration", test_config),
        ("Directories", test_directories),
        ("Test image", test_test_image)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    
    all_passed = True
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {test_name}: {status}")
        if not result:
            all_passed = False
    
    print("=" * 50)
    
    if all_passed:
        print("🎉 All tests passed! You're ready to run the examples.")
        print("\n📖 Usage:")
        print("1. Run example2.py first (algorithm service): python example2.py")
        print("2. In another terminal, run example1.py (app): python example1.py")
    else:
        print("⚠️ Some tests failed. Please fix the issues before running examples.")
        print("\n🛠️ Common fixes:")
        print("- Install requirements: pip install -r requirements.txt")
        print("- Update config.py with your credentials")
        print("- Add test_image.png to the project directory")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)