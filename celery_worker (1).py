# celery_worker.py - Background task processing with Celery
from celery import Celery, Task
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import redis
import pickle
from main import IntelligentScraper
from dataclasses import asdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery
app = Celery('intelligent_scraper')
app.conf.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/0',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_routes={
        'scraper.scrape_single': {'queue': 'scraping'},
        'scraper.scrape_batch': {'queue': 'batch'},
        'scraper.proxy_health_check': {'queue': 'maintenance'},
        'scraper.update_rules': {'queue': 'maintenance'},
    },
    task_annotations={
        'scraper.scrape_single': {'rate_limit': '10/s'},
        'scraper.scrape_batch': {'rate_limit': '2/s'},
    },
    beat_schedule={
        'proxy-health-check': {
            'task': 'scraper.proxy_health_check',
            'schedule': 300.0,  # Every 5 minutes
        },
        'cleanup-old-results': {
            'task': 'scraper.cleanup_old_results',
            'schedule': 3600.0,  # Every hour
        },
        'update-proxy-pool': {
            'task': 'scraper.update_proxy_pool',
            'schedule': 1800.0,  # Every 30 minutes
        },
    },
)

# Redis client for caching
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)

class AsyncTask(Task):
    """Custom task class to handle async functions"""
    
    def run_async(self, coro):
        """Run async function in sync context"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(coro)

# Task definitions

@app.task(bind=True, base=AsyncTask)
def scrape_single(self, url: str, options: Dict = None) -> Dict:
    """Scrape a single URL asynchronously"""
    task_id = self.request.id
    logger.info(f"Starting scrape task {task_id} for URL: {url}")
    
    options = options or {}
    max_retries = options.get('max_retries', 3)
    
    try:
        # Update task status
        self.update_state(
            state='PROGRESS',
            meta={'status': 'initializing', 'url': url}
        )
        
        async def scrape():
            async with IntelligentScraper() as scraper:
                self.update_state(
                    state='PROGRESS',
                    meta={'status': 'scraping', 'url': url}
                )
                
                result = await scraper.adaptive_scrape(url, max_retries)
                return result
        
        content = self.run_async(scrape())
        
        result = {
            'task_id': task_id,
            'url': url,
            'success': bool(content),
            'content': content,
            'content_length': len(content) if content else 0,
            'timestamp': datetime.now().isoformat(),
            'options': options
        }
        
        # Cache result
        cache_key = f"scrape_result:{task_id}"
        redis_client.setex(cache_key, 3600, json.dumps(result))
        
        logger.info(f"Completed scrape task {task_id}: {'success' if result['success'] else 'failed'}")
        return result
        
    except Exception as e:
        logger.error(f"Error in scrape task {task_id}: {str(e)}")
        self.update_state(
            state='FAILURE',
            meta={'status': 'failed', 'error': str(e), 'url': url}
        )
        raise

@app.task(bind=True, base=AsyncTask)
def scrape_batch(self, urls: List[str], options: Dict = None) -> Dict:
    """Scrape multiple URLs in batch"""
    task_id = self.request.id
    logger.info(f"Starting batch scrape task {task_id} for {len(urls)} URLs")
    
    options = options or {}
    max_concurrent = options.get('max_concurrent', 5)
    
    try:
        self.update_state(
            state='PROGRESS',
            meta={'status': 'initializing', 'total_urls': len(urls), 'completed': 0}
        )
        
        async def batch_scrape():
            async with IntelligentScraper() as scraper:
                results = await scraper.batch_scrape(urls, max_concurrent)
                return results
        
        results = self.run_async(batch_scrape())
        
        # Process results
        successful = sum(1 for content in results.values() if content)
        failed = len(urls) - successful
        
        batch_result = {
            'task_id': task_id,
            'total_urls': len(urls),
            'successful': successful,
            'failed': failed,
            'results': {url: {'success': bool(content), 'content_length': len(content) if content else 0} 
                       for url, content in results.items()},
            'timestamp': datetime.now().isoformat(),
            'options': options
        }
        
        # Cache batch results
        cache_key = f"batch_result:{task_id}"
        redis_client.setex(cache_key, 7200, json.dumps(batch_result))  # 2 hours
        
        # Cache individual results
        for url, content in results.items():
            url_hash = hash(url)
            individual_result = {
                'url': url,
                'success': bool(content),
                'content': content,
                'timestamp': datetime.now().isoformat()
            }
            redis_client.setex(f"url_result:{url_hash}", 3600, json.dumps(individual_result))
        
        logger.info(f"Completed batch task {task_id}: {successful}/{len(urls)} successful")
        return batch_result
        
    except Exception as e:
        logger.error(f"Error in batch scrape task {task_id}: {str(e)}")
        self.update_state(
            state='FAILURE',
            meta={'status': 'failed', 'error': str(e), 'total_urls': len(urls)}
        )
        raise

@app.task(bind=True, base=AsyncTask)
def proxy_health_check(self):
    """Check health of all proxies"""
    task_id = self.request.id
    logger.info(f"Starting proxy health check task {task_id}")
    
    try:
        async def check_proxies():
            async with IntelligentScraper() as scraper:
                proxy_manager = scraper.proxy_manager
                test_url = "http://httpbin.org/ip"
                
                healthy_proxies = []
                unhealthy_proxies = []
                
                for proxy in proxy_manager.proxies:
                    try:
                        content, success, response_time = await scraper.scrape_with_proxy(test_url, proxy)
                        
                        if success:
                            healthy_proxies.append({
                                'ip': proxy.ip,
                                'port': proxy.port,
                                'response_time': response_time,
                                'success_rate': proxy.success_rate
                            })
                        else:
                            unhealthy_proxies.append({
                                'ip': proxy.ip,
                                'port': proxy.port,
                                'failures': proxy.failures,
                                'success_rate': proxy.success_rate
                            })
                    except Exception as e:
                        logger.warning(f"Proxy {proxy.ip}:{proxy.port} check failed: {e}")
                        unhealthy_proxies.append({
                            'ip': proxy.ip,
                            'port': proxy.port,
                            'error': str(e)
                        })
                
                return healthy_proxies, unhealthy_proxies
        
        healthy, unhealthy = self.run_async(check_proxies())
        
        result = {
            'task_id': task_id,
            'healthy_proxies': len(healthy),
            'unhealthy_proxies': len(unhealthy),
            'healthy_details': healthy,
            'unhealthy_details': unhealthy,
            'timestamp': datetime.now().isoformat()
        }
        
        # Cache health check results
        redis_client.setex('proxy_health_check', 300, json.dumps(result))
        
        logger.info(f"Proxy health check completed: {len(healthy)} healthy, {len(unhealthy)} unhealthy")
        return result
        
    except Exception as e:
        logger.error(f"Error in proxy health check: {str(e)}")
        raise

@app.task
def update_proxy_pool():
    """Update proxy pool from external sources"""
    logger.info("Starting proxy pool update")
    
    try:
        # This would integrate with proxy providers
        # For now, we'll implement a basic rotation strategy
        
        # Get current proxy stats
        health_data = redis_client.get('proxy_health_check')
        if not health_data:
            logger.warning("No health check data available")
            return {'status': 'no_health_data'}
        
        health_info = json.loads(health_data)
        
        # Mark consistently failing proxies for replacement
        unhealthy_proxies = health_info.get('unhealthy_details', [])
        replacement_needed = len([p for p in unhealthy_proxies if p.get('failures', 0) > 10])
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'proxies_needing_replacement': replacement_needed,
            'status': 'completed'
        }
        
        logger.info(f"Proxy pool update completed: {replacement_needed} proxies need replacement")
        return result
        
    except Exception as e:
        logger.error(f"Error updating proxy pool: {str(e)}")
        raise

@app.task
def cleanup_old_results():
    """Clean up old cached results"""
    logger.info("Starting cleanup of old results")
    
    try:
        # Get all cached result keys
        result_keys = redis_client.keys('scrape_result:*')
        result_keys.extend(redis_client.keys('batch_result:*'))
        result_keys.extend(redis_client.keys('url_result:*'))
        
        cleaned = 0
        for key in result_keys:
            ttl = redis_client.ttl(key)
            if ttl < 0:  # Key has no expiration or expired
                redis_client.delete(key)
                cleaned += 1
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'keys_cleaned': cleaned,
            'total_keys_checked': len(result_keys)
        }
        
        logger.info(f"Cleanup completed: {cleaned} old results removed")
        return result
        
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        raise

@app.task(bind=True, base=AsyncTask)
def scheduled_scrape(self, urls: List[str], schedule: str, options: Dict = None):
    """Schedule recurring scraping tasks"""
    task_id = self.request.id
    logger.info(f"Starting scheduled scrape task {task_id}")
    
    options = options or {}
    
    try:
        # Parse schedule (simple format: "hourly", "daily", etc.)
        schedule_mapping = {
            'hourly': 3600,
            'daily': 86400,
            'weekly': 604800
        }
        
        interval = schedule_mapping.get(schedule, 3600)
        
        # Execute scraping
        results = scrape_batch.delay(urls, options)
        
        # Schedule next execution
        scheduled_scrape.apply_async(
            args=[urls, schedule, options],
            countdown=interval
        )
        
        result = {
            'task_id': task_id,
            'batch_task_id': results.id,
            'next_run': (datetime.now() + timedelta(seconds=interval)).isoformat(),
            'schedule': schedule,
            'urls_count': len(urls)
        }
        
        logger.info(f"Scheduled scrape task {task_id} completed, next run in {interval} seconds")
        return result
        
    except Exception as e:
        logger.error(f"Error in scheduled scrape: {str(e)}")
        raise

@app.task(bind=True, base=AsyncTask)
def intelligent_discovery(self, seed_urls: List[str], depth: int = 1, options: Dict = None):
    """Intelligently discover new URLs to scrape"""
    task_id = self.request.id
    logger.info(f"Starting intelligent discovery task {task_id}")
    
    options = options or {}
    max_urls_per_domain = options.get('max_urls_per_domain', 10)
    
    try:
        discovered_urls = set()
        
        async def discover():
            async with IntelligentScraper() as scraper:
                for seed_url in seed_urls:
                    try:
                        content = await scraper.adaptive_scrape(seed_url)
                        if content:
                            # Simple URL extraction (in production, use proper HTML parsing)
                            import re
                            from urllib.parse import urljoin, urlparse
                            
                            # Extract links
                            link_pattern = r'href=[\'"]?([^\'" >]+)'
                            links = re.findall(link_pattern, content, re.IGNORECASE)
                            
                            base_domain = urlparse(seed_url).netloc
                            domain_count = 0
                            
                            for link in links:
                                if domain_count >= max_urls_per_domain:
                                    break
                                    
                                full_url = urljoin(seed_url, link)
                                parsed = urlparse(full_url)
                                
                                # Only include HTTP/HTTPS URLs from same domain
                                if (parsed.scheme in ['http', 'https'] and 
                                    parsed.netloc == base_domain):
                                    discovered_urls.add(full_url)
                                    domain_count += 1
                                    
                    except Exception as e:
                        logger.warning(f"Failed to discover from {seed_url}: {e}")
                        continue
                
                return list(discovered_urls)
        
        urls = self.run_async(discover())
        
        result = {
            'task_id': task_id,
            'seed_urls': seed_urls,
            'discovered_urls': urls,
            'discovered_count': len(urls),
            'depth': depth,
            'timestamp': datetime.now().isoformat()
        }
        
        # Cache discovered URLs
        cache_key = f"discovered_urls:{task_id}"
        redis_client.setex(cache_key, 1800, json.dumps(urls))  # 30 minutes
        
        logger.info(f"Discovery task {task_id} completed: {len(urls)} URLs discovered")
        return result
        
    except Exception as e:
        logger.error(f"Error in intelligent discovery: {str(e)}")
        raise

# Utility functions for task management

def get_task_result(task_id: str) -> Optional[Dict]:
    """Get task result from cache"""
    result = redis_client.get(f"scrape_result:{task_id}")
    if result:
        return json.loads(result)
    
    batch_result = redis_client.get(f"batch_result:{task_id}")
    if batch_result:
        return json.loads(batch_result)
    
    return None

def get_active_tasks() -> Dict:
    """Get information about active tasks"""
    active_tasks = app.control.active()
    scheduled_tasks = app.control.scheduled()
    
    return {
        'active': active_tasks,
        'scheduled': scheduled_tasks,
        'timestamp': datetime.now().isoformat()
    }

def cancel_task(task_id: str) -> bool:
    """Cancel a running task"""
    try:
        app.control.revoke(task_id, terminate=True)
        return True
    except Exception as e:
        logger.error(f"Error canceling task {task_id}: {e}")
        return False

# Task monitoring and statistics

@app.task
def generate_task_stats():
    """Generate statistics about task execution"""
    try:
        # Get task execution stats from Redis
        stats_key = 'task_stats'
        current_stats = redis_client.get(stats_key)
        
        if current_stats:
            stats = json.loads(current_stats)
        else:
            stats = {
                'total_tasks': 0,
                'successful_tasks': 0,
                'failed_tasks': 0,
                'avg_execution_time': 0,
                'task_types': {},
                'last_updated': None
            }
        
        # Update stats (this would be more comprehensive in production)
        stats['last_updated'] = datetime.now().isoformat()
        
        # Cache updated stats
        redis_client.setex(stats_key, 300, json.dumps(stats))
        
        return stats
        
    except Exception as e:
        logger.error(f"Error generating task stats: {e}")
        raise

# Custom error handling

class ScrapingError(Exception):
    """Custom exception for scraping errors"""
    pass

class ProxyError(Exception):
    """Custom exception for proxy-related errors"""
    pass

# Task result handler
@app.task(bind=True)
def handle_task_result(self, task_id: str, result: Dict):
    """Handle and process task results"""
    try:
        # Update task statistics
        generate_task_stats.delay()
        
        # Send notifications if needed
        if result.get('success', False):
            logger.info(f"Task {task_id} completed successfully")
        else:
            logger.warning(f"Task {task_id} failed: {result.get('error', 'Unknown error')}")
        
        return {'status': 'handled', 'task_id': task_id}
        
    except Exception as e:
        logger.error(f"Error handling task result: {e}")
        raise

if __name__ == '__main__':
    # Start Celery worker
    app.start()