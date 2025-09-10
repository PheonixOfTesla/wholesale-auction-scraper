#!/bin/bash

# setup_ip_rotation.sh - Complete setup script for IP rotation system

echo "🚀 Setting up Intelligent Scraper with Advanced IP Rotation..."

# Create project structure
mkdir -p intelligent_scraper/{config,logs,data,temp,proxies}
cd intelligent_scraper

# Create requirements.txt
cat > requirements.txt << 'EOF'
# Core dependencies
aiohttp==3.8.4
asyncio==3.4.3
aiofiles==23.1.0

# Web scraping
beautifulsoup4==4.12.2
lxml==4.9.2
html5lib==1.1
pyquery==2.0.0

# API Framework
flask==2.3.2
flask-cors==4.0.0
flask-limiter==3.3.1
gunicorn==20.1.0

# Database
sqlite3-python==1.0.0
sqlalchemy==2.0.15
alembic==1.11.1

# Task Queue
celery==5.2.7
redis==4.5.5
flower==1.2.0

# Proxy validation
python-socks==2.3.0
aiohttp-socks==0.8.0
proxy-checker==0.6

# Data processing
pandas==2.0.2
numpy==1.24.3

# Utilities
python-dotenv==1.0.0
fake-useragent==1.2.1
user-agent==0.1.10
validators==0.20.0

# Monitoring and logging
loguru==0.7.0
prometheus-client==0.16.0
sentry-sdk==1.25.1

# Testing
pytest==7.3.1
pytest-asyncio==0.21.0
pytest-cov==4.1.0
aioresponses==0.7.4

# Development
ipython==8.14.0
black==23.3.0
flake8==6.0.0
mypy==1.3.0
EOF

# Create Python virtual environment
echo "📦 Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Create environment configuration
cat > .env << 'EOF'
# Scraper Configuration
SCRAPER_MODE=production
DEBUG=False

# Proxy Configuration
USE_FREE_PROXIES=true
USE_PREMIUM_PROXIES=false
VALIDATE_PROXIES_ON_ADD=true
PROXY_VALIDATION_URL=http://httpbin.org/ip
PROXY_ROTATION_INTERVAL=300
REQUESTS_PER_PROXY=10
MIN_HEALTHY_PROXIES=10

# Premium Proxy Providers (add your credentials)
BRIGHTDATA_ENABLED=false
BRIGHTDATA_CUSTOMER_ID=
BRIGHTDATA_PASSWORD=
BRIGHTDATA_ZONE=static

SMARTPROXY_ENABLED=false
SMARTPROXY_USERNAME=
SMARTPROXY_PASSWORD=

# Performance Settings
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT=30
MAX_RETRIES=3
BACKOFF_FACTOR=1.5

# Database
DATABASE_PATH=data/proxies.db
RULES_DATABASE_PATH=data/rules.db

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0

# API Server
API_HOST=0.0.0.0
API_PORT=5000
API_WORKERS=4

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/scraper.log
LOG_MAX_SIZE=10MB
LOG_BACKUP_COUNT=5

# Monitoring
ENABLE_METRICS=true
METRICS_PORT=9090
SENTRY_DSN=
EOF

# Create default configuration
cat > config/scraper_config.json << 'EOF'
{
  "proxy_providers": {
    "use_free_proxies": true,
    "use_premium_proxies": false,
    "brightdata": {
      "enabled": false,
      "customer_id": "",
      "password": "",
      "zone": "static"
    },
    "smartproxy": {
      "enabled": false,
      "username": "",
      "password": ""
    }
  },
  "rotation_settings": {
    "strategy": "weighted_random",
    "rotation_interval": 300,
    "requests_per_proxy": 10,
    "min_healthy_proxies": 10,
    "auto_refresh": true
  },
  "performance": {
    "max_concurrent_requests": 10,
    "timeout": 30,
    "max_retries": 3,
    "backoff_factor": 1.5
  },
  "validation": {
    "validate_on_add": true,
    "validation_url": "http://httpbin.org/ip",
    "health_check_interval": 600
  },
  "free_proxy_sources": {
    "proxylist_geonode": true,
    "free_proxy_list": true,
    "sslproxies": true,
    "proxy_list_download": true,
    "proxyscrape": true,
    "github_lists": true,
    "hidemy": false,
    "spys_one": false
  }
}
EOF

# Create Docker setup
cat > Dockerfile << 'EOF'
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs data config temp proxies

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose ports
EXPOSE 5000 9090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Run the application
CMD ["python", "integrated_scraper.py", "test"]
EOF

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  scraper:
    build: .
    ports:
      - "5000:5000"
      - "9090:9090"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
    command: python api_server.py

  worker:
    build: .
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
    command: celery -A celery_worker worker --loglevel=info

  flower:
    build: .
    ports:
      - "5555:5555"
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped
    command: celery -A celery_worker flower

volumes:
  redis_data:
EOF

# Create main run script
cat > run_scraper.py << 'EOF'
#!/usr/bin/env python3
"""
Main entry point for the Intelligent Scraper with IP Rotation
"""
import asyncio
import sys
import os
import json
import argparse
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from integrated_scraper import IntegratedIntelligentScraper, generate_config_file
from proxy_rotation_manager import EnhancedProxyManager
from free_proxy_fetcher import FreeProxyFetcher

async def run_interactive():
    """Run interactive scraper session"""
    print("\n🌐 Intelligent Scraper with IP Rotation")
    print("=" * 50)
    
    # Initialize scraper
    print("Initializing scraper...")
    async with IntegratedIntelligentScraper() as scraper:
        print(f"✅ Scraper ready with {len(scraper.proxy_manager.proxies)} proxies")
        
        while True:
            print("\n" + "=" * 50)
            print("Commands:")
            print("1. Scrape single URL")
            print("2. Batch scrape URLs")
            print("3. Show statistics")
            print("4. Refresh proxy pool")
            print("5. Test all proxies")
            print("6. Exit")
            
            choice = input("\nEnter choice (1-6): ").strip()
            
            if choice == '1':
                url = input("Enter URL to scrape: ").strip()
                if url:
                    print(f"Scraping {url}...")
                    content, metadata = await scraper.scrape_with_rotation(url)
                    if content:
                        print(f"✅ Success! Content length: {len(content)} bytes")
                        print(f"Proxy used: {metadata.get('proxy_used')}")
                        print(f"Response time: {metadata.get('response_time'):.2f}s")
                    else:
                        print(f"❌ Failed: {metadata.get('error')}")
            
            elif choice == '2':
                urls_input = input("Enter URLs (comma-separated): ").strip()
                urls = [u.strip() for u in urls_input.split(',') if u.strip()]
                if urls:
                    print(f"Batch scraping {len(urls)} URLs...")
                    results = await scraper.batch_scrape_with_rotation(urls)
                    success_count = sum(1 for r in results.values() if r['success'])
                    print(f"Results: {success_count}/{len(urls)} successful")
                    for url, result in results.items():
                        status = "✅" if result['success'] else "❌"
                        print(f"  {status} {url}")
            
            elif choice == '3':
                stats = await scraper.get_statistics()
                print("\n📊 Statistics:")
                print(f"Total requests: {stats['total_requests']}")
                print(f"Active proxies: {stats['active_proxies']}")
                print(f"Blacklisted IPs: {stats['blacklisted_ips']}")
                print(f"Proxy pools:")
                for pool_name, pool_stats in stats['proxy_statistics']['pools'].items():
                    print(f"  {pool_name}: {pool_stats['count']} proxies")
            
            elif choice == '4':
                print("Refreshing proxy pool...")
                await scraper.initialize_free_proxies()
                print(f"✅ Pool refreshed. Total proxies: {len(scraper.proxy_manager.proxies)}")
            
            elif choice == '5':
                print("Testing all proxies...")
                await scraper.proxy_manager.health_check_all_proxies()
                healthy = len([p for p in scraper.proxy_manager.proxies if p.health_score > 50])
                print(f"✅ Test complete. Healthy proxies: {healthy}/{len(scraper.proxy_manager.proxies)}")
            
            elif choice == '6':
                print("Exiting...")
                break
            
            else:
                print("Invalid choice. Please try again.")

async def main():
    parser = argparse.ArgumentParser(description="Intelligent Scraper with IP Rotation")
    parser.add_argument('--mode', choices=['interactive', 'test', 'server'], 
                       default='interactive', help='Run mode')
    parser.add_argument('--config', default='config/scraper_config.json', 
                       help='Configuration file path')
    
    args = parser.parse_args()
    
    if args.mode == 'interactive':
        await run_interactive()
    elif args.mode == 'test':
        # Run tests
        from integrated_scraper import test_integrated_scraper
        await test_integrated_scraper()
    elif args.mode == 'server':
        # Start API server
        print("Starting API server...")
        os.system("python flask_api_server.py")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown requested. Cleaning up...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
EOF

chmod +x run_scraper.py

# Create quick start script
cat > start.sh << 'EOF'
#!/bin/bash

# Quick start script for the scraper

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Intelligent Scraper with IP Rotation${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Check Redis
if ! pgrep -x "redis-server" > /dev/null; then
    echo -e "${YELLOW}Starting Redis server...${NC}"
    redis-server --daemonize yes
fi

# Run based on argument
case "$1" in
    "interactive")
        python run_scraper.py --mode interactive
        ;;
    "test")
        python run_scraper.py --mode test
        ;;
    "server")
        python flask_api_server.py
        ;;
    "worker")
        celery -A celery_worker worker --loglevel=info
        ;;
    "docker")
        docker-compose up -d
        ;;
    *)
        echo "Usage: $0 {interactive|test|server|worker|docker}"
        echo "  interactive - Run interactive CLI"
        echo "  test       - Run test suite"
        echo "  server     - Start API server"
        echo "  worker     - Start Celery worker"
        echo "  docker     - Start with Docker Compose"
        python run_scraper.py --mode interactive
        ;;
esac
EOF

chmod +x start.sh

# Create README
cat > README.md << 'EOF'
# Intelligent Scraper with Advanced IP Rotation

A sophisticated web scraping system with automatic IP rotation, proxy management, and self-learning capabilities.

## Features

- **Automatic IP Rotation**: Intelligent proxy rotation based on multiple strategies
- **Free Proxy Sources**: Automatically fetches and validates free proxies from multiple sources
- **Premium Proxy Support**: Integration with BrightData, SmartProxy, and other providers
- **Self-Learning**: Adapts scraping rules based on success/failure patterns
- **Health Monitoring**: Automatic proxy health checks and blacklisting
- **Concurrent Scraping**: Efficient batch scraping with configurable concurrency
- **API Server**: RESTful API for integration with other systems
- **Background Tasks**: Celery integration for scheduled and async tasks

## Quick Start

1. **Setup the environment:**
   ```bash
   ./setup_ip_rotation.sh
   ```

2. **Configure your settings:**
   - Edit `.env` for environment variables
   - Edit `config/scraper_config.json` for scraper settings

3. **Run the scraper:**
   ```bash
   # Interactive mode
   ./start.sh interactive
   
   # API server
   ./start.sh server
   
   # Docker deployment
   ./start.sh docker
   ```

## Configuration

### Free Proxies
The system automatically fetches free proxies from:
- ProxyList Geonode
- Free-Proxy-List.net
- SSLProxies.org
- ProxyScrape
- GitHub proxy lists
- And more...

### Premium Proxies
Add your credentials in `.env`:
```
BRIGHTDATA_CUSTOMER_ID=your_id
BRIGHTDATA_PASSWORD=your_password
SMARTPROXY_USERNAME=your_username
SMARTPROXY_PASSWORD=your_password
```

## API Endpoints

- `POST /api/scrape` - Scrape single URL
- `POST /api/scrape/batch` - Batch scrape multiple URLs
- `GET /api/proxies` - Get proxy statistics
- `GET /api/stats` - Get scraper statistics
- `GET /api/health` - Health check

## Proxy Rotation Strategies

1. **Weighted Random**: Select proxies based on health score
2. **Round Robin**: Cycle through proxies sequentially
3. **Least Used**: Select least recently used proxy
4. **Geographic**: Select proxies from specific countries

## Monitoring

- Prometheus metrics on port 9090
- Flower (Celery monitoring) on port 5555
- Detailed logging in `logs/scraper.log`

## Testing

Run the test suite:
```bash
./start.sh test
```

## Docker Deployment

```bash
docker-compose up -d
```

Services:
- Scraper API: http://localhost:5000
- Flower: http://localhost:5555
- Metrics: http://localhost:9090

## License

MIT License
EOF

echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Activate virtual environment: source venv/bin/activate"
echo "2. Configure settings in .env and config/scraper_config.json"
echo "3. Run the scraper: ./start.sh interactive"
echo ""
echo "🚀 Quick commands:"
echo "  ./start.sh interactive  - Interactive CLI"
echo "  ./start.sh test        - Run tests"
echo "  ./start.sh server      - Start API server"
echo "  ./start.sh docker      - Docker deployment"