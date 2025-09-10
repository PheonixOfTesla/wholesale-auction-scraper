#!/usr/bin/env python3
"""Test script to verify deployment readiness"""

import sys
import os

def test_imports():
    """Test all critical imports"""
    try:
        import flask
        import aiohttp
        import redis
        import celery
        import sqlalchemy
        print("✅ All core imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_files_exist():
    """Check if all required files exist"""
    required_files = [
        'flask_api_server.py',
        'intelligent_scraper.py',
        'celery_worker.py',
        'models.py',
        'requirements.txt',
        'Procfile',
        '.env'
    ]
    
    all_exist = True
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file} exists")
        else:
            print(f"❌ {file} missing")
            all_exist = False
    
    return all_exist

if __name__ == "__main__":
    print("Testing deployment readiness...")
    imports_ok = test_imports()
    files_ok = test_files_exist()
    
    if imports_ok and files_ok:
        print("\n✅ Ready for deployment!")
        sys.exit(0)
    else:
        print("\n❌ Issues found. Please fix before deploying.")
        sys.exit(1)
