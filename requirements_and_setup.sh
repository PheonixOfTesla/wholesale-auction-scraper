# requirements.txt - Python dependencies
aiohttp==3.8.4
asyncio==3.4.3
flask==2.3.2
flask-cors==4.0.0
sqlite3
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.2
fake-useragent==1.2.1
python-dotenv==1.0.0
gunicorn==20.1.0
redis==4.5.5
celery==5.2.7
scrapy==2.9.0
selenium==4.9.1
undetected-chromedriver==3.4.7

# setup.sh - Installation and setup script
#!/bin/bash

echo "🚀 Setting up Intelligent Proxy Backend Scraper..."

# Check if Python 3.8+ is installed
python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
required_version="3.8"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python $python_version detected"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 14 or higher."
    exit 1
fi

node_version=$(node --version)
echo "✅ Node.js $node_version detected"

# Create virtual environment
echo "📦 Creating Python virtual environment..."
python3 -m venv scraper_env
source scraper_env/bin/activate

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Node.js dependencies
echo "📦 Installing Node.js dependencies..."
npm init -y
npm install puppeteer@19.0.0

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p logs
mkdir -p data
mkdir -p config
mkdir -p temp

# Create configuration files
echo "⚙️ Creating configuration files..."

# Create .env file
cat > .env << EOL
# Environment Configuration
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=your-secret-key-here

# Database Configuration
DATABASE_URL=sqlite:///scraper.db

# Redis Configuration (for Celery)
REDIS_URL=redis://localhost:6379/0

# Proxy Configuration
DEFAULT_PROXY_TIMEOUT=30
MAX_PROXY_FAILURES=5
PROXY_ROTATION_INTERVAL=300

# Scraping Configuration
DEFAULT_RATE_LIMIT=1.0
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT=30
USER_AGENT_ROTATION=true

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/scraper.log

# API Configuration
API_HOST=0.0.0.0
API_PORT=5000
API_WORKERS=4
EOL

# Create Docker configuration
cat > Dockerfile << EOL
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    wget \\
    gnupg \\
    unzip \\
    curl \\
    xvfb \\
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \\
    && apt-get install -y nodejs

# Install Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \\
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \\
    && apt-get update \\
    && apt-get install -y google-chrome-stable \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and install Node.js dependencies
COPY package*.json ./
RUN npm install

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs data config temp

# Set environment variables
ENV PYTHONPATH=/app
ENV NODE_PATH=/app/node_modules

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \\
    CMD curl -f http://localhost:5000/api/health || exit 1

# Run the application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "120", "api_server:app"]
EOL

# Create docker-compose.yml
cat > docker-compose.yml << EOL
version: '3.8'

services:
  scraper:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - FLASK_ENV=production
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  worker:
    build: .
    command: celery -A celery_worker worker --loglevel=info
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped

volumes:
  redis_data:
EOL

# Create systemd service file
cat > scraper.service << EOL
[Unit]
Description=Intelligent Proxy Backend Scraper
After=network.target

[Service]
Type=forking
User=scraper
Group=scraper
WorkingDirectory=/opt/scraper
Environment=PATH=/opt/scraper/scraper_env/bin
ExecStart=/opt/scraper/scraper_env/bin/gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 --daemon --pid /var/run/scraper.pid api_server:app
ExecReload=/bin/kill -HUP \$MAINPID
PIDFile=/var/run/scraper.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Create startup script
cat > start.sh << EOL
#!/bin/bash

# Activate virtual environment
source scraper_env/bin/activate

# Set environment variables
export PYTHONPATH=\$(pwd)
export NODE_PATH=\$(pwd)/node_modules

# Start Redis if not running
if ! pgrep redis-server > /dev/null; then
    echo "Starting Redis server..."
    redis-server --daemonize yes
fi

# Start Celery worker in background
echo "Starting Celery worker..."
celery -A celery_worker worker --loglevel=info --detach

# Start the Flask API server
echo "Starting Flask API server..."
python api_server.py
EOL

chmod +x start.sh

# Create stop script
cat > stop.sh << EOL
#!/bin/bash

echo "Stopping Intelligent Proxy Backend Scraper..."

# Stop Flask server
pkill -f api_server.py

# Stop Celery worker
pkill -f celery

# Stop Redis (if started by us)
# pkill redis-server

echo "All services stopped."
EOL

chmod +x stop.sh

# Create test script
cat > test.sh << EOL
#!/bin/bash

echo "🧪 Running tests for Intelligent Proxy Backend Scraper..."

# Activate virtual environment
source scraper_env/bin/activate

# Test Python imports
echo "Testing Python imports..."
python -c "
import asyncio
import aiohttp
import json
import sqlite3
from main import IntelligentScraper, ProxyManager, RuleEngine
from api_server import app
print('✅ All Python imports successful')
"

# Test Node.js setup
echo "Testing Node.js setup..."
node -e "
const puppeteer = require('puppeteer');
const { JSRenderer } = require('./js_renderer.js');
console.log('✅ Node.js setup successful');
"

# Test basic functionality
echo "Testing basic scraper functionality..."
python -c "
import asyncio
from main import IntelligentScraper

async def test():
    async with IntelligentScraper() as scraper:
        result = await scraper.adaptive_scrape('http://httpbin.org/ip')
        if result:
            print('✅ Basic scraping test passed')
        else:
            print('❌ Basic scraping test failed')

asyncio.run(test())
"

# Test API endpoints
echo "Testing API endpoints..."
python -c "
import requests
import time
import subprocess
import signal
import os

# Start server in background
server_process = subprocess.Popen(['python', 'api_server.py'], 
                                stdout=subprocess.DEVNULL, 
                                stderr=subprocess.DEVNULL)

# Wait for server to start
time.sleep(3)

try:
    # Test health endpoint
    response = requests.get('http://localhost:5000/api/health', timeout=5)
    if response.status_code == 200:
        print('✅ API health check passed')
    else:
        print('❌ API health check failed')
        
except Exception as e:
    print(f'❌ API test failed: {e}')
finally:
    # Stop server
    server_process.terminate()
    server_process.wait()
"

echo "🎉 Tests completed!"
EOL

chmod +x test.sh

# Create monitoring script
cat > monitor.sh << EOL
#!/bin/bash

# Monitor script for the scraper
echo "📊 Monitoring Intelligent Proxy Backend Scraper..."

while true; do
    clear
    echo "=== Scraper Status ==="
    echo "Time: \$(date)"
    echo
    
    # Check if processes are running
    if pgrep -f "api_server.py" > /dev/null; then
        echo "✅ API Server: Running"
    else
        echo "❌ API Server: Stopped"
    fi
    
    if pgrep -f "celery.*worker" > /dev/null; then
        echo "✅ Celery Worker: Running"
    else
        echo "❌ Celery Worker: Stopped"
    fi
    
    if pgrep redis-server > /dev/null; then
        echo "✅ Redis: Running"
    else
        echo "❌ Redis: Stopped"
    fi
    
    echo
    echo "=== System Resources ==="
    echo "CPU Usage: \$(top -bn1 | grep "Cpu(s)" | awk '{print \$2}' | sed 's/%us,//')"
    echo "Memory Usage: \$(free | grep Mem | awk '{printf \"%.2f%%\", \$3/\$2 * 100.0}')"
    echo "Disk Usage: \$(df -h . | tail -1 | awk '{print \$5}')"
    
    echo
    echo "=== Recent Logs ==="
    tail -n 5 logs/scraper.log 2>/dev/null || echo "No logs available"
    
    echo
    echo "Press Ctrl+C to exit monitoring"
    sleep 10
done
EOL

chmod +x monitor.sh

echo "✅ Setup completed successfully!"
echo
echo "📋 Next steps:"
echo "1. Activate virtual environment: source scraper_env/bin/activate"
echo "2. Run tests: ./test.sh"
echo "3. Start scraper: ./start.sh"
echo "4. Monitor status: ./monitor.sh"
echo "5. Access API at: http://localhost:5000"
echo
echo "📚 Available commands:"
echo "  ./start.sh    - Start all services"
echo "  ./stop.sh     - Stop all services"
echo "  ./test.sh     - Run tests"
echo "  ./monitor.sh  - Monitor system"
echo
echo "🐳 Docker deployment:"
echo "  docker-compose up -d"
echo
echo "🔧 Configuration:"
echo "  Edit .env file for environment settings"
echo "  Check config/ directory for advanced options"