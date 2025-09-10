# api_server.py - Flask REST API for the Intelligent Scraper
from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import threading
import json
import os
from datetime import datetime
from intelligent_scraper import IntelligentScraper, ScraperAPI, ProxyConfig
import logging

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scraper instance
scraper_api = ScraperAPI()

def run_async(coro):
    """Helper to run async functions in sync context"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)

@app.before_first_request
def initialize_scraper():
    """Initialize the scraper when the app starts"""
    try:
        run_async(scraper_api.start())
        logger.info("Scraper API initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize scraper: {e}")

@app.teardown_appcontext
def cleanup_scraper(exception):
    """Cleanup scraper on app shutdown"""
    try:
        run_async(scraper_api.stop())
        logger.info("Scraper API cleaned up")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# API Routes

@app.route('/api/scrape', methods=['POST'])
def scrape_single():
    """Scrape a single URL"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url']
        max_retries = data.get('max_retries', 3)
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'Invalid URL format'}), 400
        
        result = run_async(scraper_api.scrape_url(url))
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in scrape_single: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/scrape/batch', methods=['POST'])
def scrape_batch():
    """Scrape multiple URLs"""
    try:
        data = request.get_json()
        
        if not data or 'urls' not in data:
            return jsonify({'error': 'URLs list is required'}), 400
        
        urls = data['urls']
        max_concurrent = data.get('max_concurrent', 5)
        
        if not isinstance(urls, list) or len(urls) == 0:
            return jsonify({'error': 'URLs must be a non-empty list'}), 400
        
        # Validate URLs
        for url in urls:
            if not url.startswith(('http://', 'https://')):
                return jsonify({'error': f'Invalid URL format: {url}'}), 400
        
        if not scraper_api.scraper:
            return jsonify({'error': 'Scraper not initialized'}), 500
        
        results = run_async(scraper_api.scraper.batch_scrape(urls, max_concurrent))
        
        # Format results
        formatted_results = []
        for url, content in results.items():
            formatted_results.append({
                'url': url,
                'success': bool(content),
                'content': content,
                'timestamp': datetime.now().isoformat()
            })
        
        return jsonify({
            'results': formatted_results,
            'total': len(urls),
            'successful': len([r for r in formatted_results if r['success']])
        })
        
    except Exception as e:
        logger.error(f"Error in scrape_batch: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/proxies', methods=['GET'])
def get_proxies():
    """Get all proxies and their stats"""
    try:
        stats = scraper_api.get_stats()
        return jsonify(stats.get('proxies', []))
    except Exception as e:
        logger.error(f"Error getting proxies: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/proxies', methods=['POST'])
def add_proxy():
    """Add a new proxy"""
    try:
        data = request.get_json()
        
        required_fields = ['ip', 'port']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        ip = data['ip']
        port = int(data['port'])
        protocol = data.get('protocol', 'http')
        username = data.get('username')
        password = data.get('password')
        
        result = run_async(scraper_api.add_proxy(ip, port, protocol, username, password))
        return jsonify(result)
        
    except ValueError:
        return jsonify({'error': 'Port must be a valid integer'}), 400
    except Exception as e:
        logger.error(f"Error adding proxy: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/proxies/<proxy_id>', methods=['DELETE'])
def remove_proxy(proxy_id):
    """Remove a proxy"""
    try:
        # Parse proxy_id (format: ip:port)
        if ':' not in proxy_id:
            return jsonify({'error': 'Invalid proxy ID format (use ip:port)'}), 400
        
        ip, port = proxy_id.split(':', 1)
        port = int(port)
        
        if scraper_api.scraper:
            # Remove from proxy list
            scraper_api.scraper.proxy_manager.proxies = [
                p for p in scraper_api.scraper.proxy_manager.proxies 
                if not (p.ip == ip and p.port == port)
            ]
            return jsonify({'message': f'Proxy {proxy_id} removed successfully'})
        else:
            return jsonify({'error': 'Scraper not initialized'}), 500
            
    except ValueError:
        return jsonify({'error': 'Invalid port in proxy ID'}), 400
    except Exception as e:
        logger.error(f"Error removing proxy: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rules', methods=['GET'])
def get_rules():
    """Get all scraping rules"""
    try:
        stats = scraper_api.get_stats()
        return jsonify(stats.get('rules', []))
    except Exception as e:
        logger.error(f"Error getting rules: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rules/<domain>', methods=['PUT'])
def update_rule(domain):
    """Update scraping rule for domain"""
    try:
        data = request.get_json()
        
        if not scraper_api.scraper:
            return jsonify({'error': 'Scraper not initialized'}), 500
        
        rule = scraper_api.scraper.rule_engine.get_rule(domain)
        
        # Update rule properties
        if 'rate_limit' in data:
            rule.rate_limit = float(data['rate_limit'])
        if 'headers' in data:
            rule.headers.update(data['headers'])
        if 'selectors' in data:
            rule.selectors.update(data['selectors'])
        if 'success_patterns' in data:
            rule.success_patterns = data['success_patterns']
        if 'failure_patterns' in data:
            rule.failure_patterns = data['failure_patterns']
        
        rule.last_updated = datetime.now()
        scraper_api.scraper.rule_engine.save_rule(rule)
        
        return jsonify({'message': f'Rule for {domain} updated successfully'})
        
    except Exception as e:
        logger.error(f"Error updating rule: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get scraper statistics"""
    try:
        stats = scraper_api.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'scraper_initialized': scraper_api.scraper is not None
    })

@app.route('/api/test', methods=['POST'])
def test_scraper():
    """Test scraper with a simple request"""
    try:
        test_url = "http://httpbin.org/ip"
        result = run_async(scraper_api.scrape_url(test_url))
        return jsonify({
            'test_result': result,
            'status': 'test_completed'
        })
    except Exception as e:
        logger.error(f"Error in test: {e}")
        return jsonify({'error': str(e)}), 500

# Error handlers

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(400)
def bad_request(error):
    return jsonify({'error': 'Bad request'}), 400

# Configuration management

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    try:
        if not scraper_api.scraper:
            return jsonify({'error': 'Scraper not initialized'}), 500
        
        config = {
            'proxy_count': len(scraper_api.scraper.proxy_manager.proxies),
            'rule_count': len(scraper_api.scraper.rule_engine.rules),
            'active_proxies': len([p for p in scraper_api.scraper.proxy_manager.proxies if p.success_rate > 0.5]),
            'default_rate_limit': 1.0,
            'max_retries': 3,
            'timeout': 30
        }
        
        return jsonify(config)
        
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/reset', methods=['POST'])
def reset_config():
    """Reset scraper configuration"""
    try:
        if not scraper_api.scraper:
            return jsonify({'error': 'Scraper not initialized'}), 500
        
        # Reset proxy failure counts
        for proxy in scraper_api.scraper.proxy_manager.proxies:
            proxy.failures = 0
            proxy.success_rate = 1.0
            scraper_api.scraper.proxy_manager.save_proxy(proxy)
        
        # Reset rule statistics
        for rule in scraper_api.scraper.rule_engine.rules.values():
            rule.success_count = 0
            rule.failure_count = 0
            rule.rate_limit = 1.0
            scraper_api.scraper.rule_engine.save_rule(rule)
        
        return jsonify({'message': 'Configuration reset successfully'})
        
    except Exception as e:
        logger.error(f"Error resetting config: {e}")
        return jsonify({'error': str(e)}), 500

# Monitoring and logging

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get recent log entries"""
    try:
        # This is a simplified version - in production you'd want proper log management
        log_entries = []
        
        # Get query parameters
        limit = request.args.get('limit', 100, type=int)
        level = request.args.get('level', 'INFO')
        
        # In a real implementation, you'd read from log files or a logging service
        # For now, return a mock response
        log_entries = [
            {
                'timestamp': datetime.now().isoformat(),
                'level': 'INFO',
                'message': 'Scraper API is running',
                'component': 'api_server'
            }
        ]
        
        return jsonify({
            'logs': log_entries[-limit:],
            'total': len(log_entries)
        })
        
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Development server
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)

# Production deployment with Gunicorn
"""
To run in production:

pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 api_server:app

Or with Docker:

FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "120", "api_server:app"]
"""