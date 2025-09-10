#!/usr/bin/env python3
"""
Startup script to ensure all modules are properly initialized
"""
import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import all modules to check for errors
try:
    import flask
    import flask_cors
    import aiohttp
    import redis
    import celery
    from flask_api_server import app
    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

if __name__ == "__main__":
    # Run the Flask app
    from flask_api_server import app
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
