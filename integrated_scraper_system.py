# integrated_scraper.py - Main scraper with advanced IP rotation integration
import asyncio
import aiohttp
import json
import logging
import os
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse
import random

from proxy_rotation_manager import (
    EnhancedProxyManager, ProxyConfig, ProxyType, 
    ProxyRotationStrategy, BrightDataProvider, SmartProxyProvider
)
from free_proxy_fetcher import FreeProxyFetcher, ProxyRotator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IntegratedIntelligentScraper:
    """Enhanced scraper with advanced IP rotation capabilities"""
    
    def __init__(self, config_path: str = "scraper_config.json"):
        self.config = self.load_config(config_path)
        self.proxy_manager = EnhancedProxyManager()
        self.free_fetcher = FreeProxyFetcher()
        self.rotator = None
        self.session = None
        self.user_agents = self.load_user_agents()
        self.request_count = 0
        self.rotation_threshold = 10  # Rotate IP after N requests
        self.domain_request_count = {}
        self.last_rotation_time = {}
        
    def load_config(self, config_path: str) -> Dict:
        """Load configuration from file"""
        default_config = {
            "proxy_providers": {
                "use_free_proxies": True,
                "use_premium_proxies": False,
                "brightdata": {
                    "enabled": False,
                    "customer_id": "",
                    "password": "",
                    "zone": "static"
                },
                "smartproxy": {
                    "enabled": False,
                    "username": "",
                    "password": ""
                }
            },
            "rotation_settings": {
                "strategy": "weighted_random",  # round_robin, weighted_random, least_used
                "rotation_interval": 300,  # seconds
                "requests_per_proxy": 10,
                "min_healthy_proxies": 10,
                "auto_refresh": True
            },
            "performance": {
                "max_concurrent_requests": 10,
                "timeout": 30,
                "max_retries": 3,
                "backoff_factor": 1.5
            },
            "validation": {
                "validate_on_add": True,
                "validation_url": "http://httpbin.org/ip",
                "health_check_interval": 600
            }
        }
        
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                loaded_config = json.load(f)
                # Merge with defaults
                self.merge_dict(default_config, loaded_config)
        
        return default_config
    
    def merge_dict(self, default: Dict, override: Dict):
        """Recursively merge override dict into default dict"""
        for key, value in override.items():
            if key in default:
                if isinstance(default[key], dict) and isinstance(value, dict):
                    self.merge_dict(default[key], value)
                else:
                    default[key] = value
    
    def load_user_agents(self) -> List[str]:
        """Load user agent strings"""
        return [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        ]
    
    async def initialize(self):
        """Initialize the scraper system"""
        logger.info("Initializing Integrated Intelligent Scraper...")
        
        # Create session
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(connector=connector)
        
        # Set rotation strategy
        strategy_map = {
            'round_robin': ProxyRotationStrategy.round_robin,
            'weighted_random': ProxyRotationStrategy.weighted_random,
            'least_used': ProxyRotationStrategy.least_used
        }
        self.proxy_manager.rotation_strategy = strategy_map.get(
            self.config['rotation_settings']['strategy'],
            ProxyRotationStrategy.weighted_random
        )
        
        # Initialize premium proxy providers if configured
        await self.initialize_premium_providers()
        
        # Initialize free proxies if enabled
        if self.config['proxy_providers']['use_free_proxies']:
            await self.initialize_free_proxies()
        
        # Start automatic rotation if enabled
        if self.config['rotation_settings']['auto_refresh']:
            self.rotator = ProxyRotator(self.proxy_manager, self.free_fetcher)
            asyncio.create_task(self.rotator.start())
        
        # Perform initial health check
        await self.proxy_manager.health_check_all_proxies()
        
        logger.info(f"Initialization complete. {len(self.proxy_manager.proxies)} proxies available")
    
    async def initialize_premium_providers(self):
        """Initialize premium proxy providers"""
        provider_configs = {}
        
        if self.config['proxy_providers']['brightdata']['enabled']:
            provider_configs['brightdata'] = {
                'customer_id': self.config['proxy_providers']['brightdata']['customer_id'],
                'password': self.config['proxy_providers']['brightdata']['password'],
                'zone': self.config['proxy_providers']['brightdata']['zone']
            }
        
        if self.config['proxy_providers']['smartproxy']['enabled']:
            provider_configs['smartproxy'] = {
                'username': self.config['proxy_providers']['smartproxy']['username'],
                'password': self.config['proxy_providers']['smartproxy']['password']
            }
        
        if provider_configs:
            await self.proxy_manager.initialize_providers(provider_configs)
            await self.proxy_manager.fetch_proxies_from_providers()
    
    async def initialize_free_proxies(self):
        """Initialize free proxy sources"""
        logger.info("Fetching free proxies...")
        
        async with self.free_fetcher as fetcher:
            proxies = await fetcher.fetch_all_proxies()
            logger.info(f"Fetched {len(proxies)} free proxies")
            
            if self.config['validation']['validate_on_add']:
                # Validate proxies before adding
                valid_proxies = await fetcher.validate_proxies_batch(
                    proxies[:100],  # Limit validation for speed
                    max_concurrent=50
                )
                logger.info(f"Validated {len(valid_proxies)} working proxies")
                
                for proxy in valid_proxies:
                    self.proxy_manager.add_proxy(proxy)
            else:
                # Add all without validation
                for proxy in proxies[:100]:  # Limit for performance
                    self.proxy_manager.add_proxy(proxy)
    
    async def get_proxy_for_request(self, url: str) -> Optional[ProxyConfig]:
        """Get appropriate proxy for a request with rotation logic"""
        domain = urlparse(url).netloc
        
        # Check if we need to rotate based on request count
        if domain in self.domain_request_count:
            if self.domain_request_count[domain] >= self.config['rotation_settings']['requests_per_proxy']:
                # Force rotation
                if domain in self.proxy_manager.domain_proxy_map:
                    old_proxy = self.proxy_manager.domain_proxy_map[domain]
                    new_proxy = await self.proxy_manager.rotate_proxy(old_proxy, "request_limit")
                    self.proxy_manager.domain_proxy_map[domain] = new_proxy
                    self.domain_request_count[domain] = 0
                    logger.info(f"Rotated proxy for {domain} due to request limit")
        
        # Check if we need to rotate based on time
        if domain in self.last_rotation_time:
            time_since_rotation = (datetime.now() - self.last_rotation_time[domain]).seconds
            if time_since_rotation > self.config['rotation_settings']['rotation_interval']:
                if domain in self.proxy_manager.domain_proxy_map:
                    old_proxy = self.proxy_manager.domain_proxy_map[domain]
                    new_proxy = await self.proxy_manager.rotate_proxy(old_proxy, "time_limit")
                    self.proxy_manager.domain_proxy_map[domain] = new_proxy
                    self.last_rotation_time[domain] = datetime.now()
                    logger.info(f"Rotated proxy for {domain} due to time limit")
        
        # Get proxy for domain
        proxy = await self.proxy_manager.get_proxy_for_domain(domain)
        
        if proxy:
            # Update counters
            if domain not in self.domain_request_count:
                self.domain_request_count[domain] = 0
                self.last_rotation_time[domain] = datetime.now()
            
            self.domain_request_count[domain] += 1
            self.request_count += 1
        
        return proxy
    
    def get_random_headers(self) -> Dict[str, str]:
        """Get randomized headers for request"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': random.choice([
                'en-US,en;q=0.9',
                'en-GB,en;q=0.8',
                'en-US,en;q=0.5'
            ]),
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': random.choice(['1', None]),
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': random.choice(['max-age=0', 'no-cache', None]),
            'Pragma': random.choice(['no-cache', None])
        }
    
    async def scrape_with_rotation(self, url: str, **kwargs) -> Tuple[Optional[str], Dict]:
        """Scrape URL with automatic proxy rotation"""
        max_retries = kwargs.get('max_retries', self.config['performance']['max_retries'])
        timeout = kwargs.get('timeout', self.config['performance']['timeout'])
        
        for attempt in range(max_retries):
            proxy = await self.get_proxy_for_request(url)
            
            if not proxy:
                logger.error(f"No proxy available for {url}")
                if attempt < max_retries - 1:
                    # Try to fetch more proxies
                    await self.initialize_free_proxies()
                    continue
                return None, {'error': 'No proxies available'}
            
            try:
                # Build proxy URL
                proxy_url = f"{proxy.protocol}://"
                if proxy.username:
                    proxy_url += f"{proxy.username}:{proxy.password}@"
                proxy_url += f"{proxy.ip}:{proxy.port}"
                
                # Make request
                headers = self.get_random_headers()
                headers.update(kwargs.get('headers', {}))
                
                start_time = datetime.now()
                
                async with self.session.get(
                    url,
                    proxy=proxy_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=False  # Disable SSL verification for proxies
                ) as response:
                    response_time = (datetime.now() - start_time).total_seconds()
                    content = await response.text()
                    
                    # Update proxy statistics
                    self.proxy_manager.update_proxy_stats(
                        proxy, True, response_time, 
                        urlparse(url).netloc, response.status
                    )
                    
                    metadata = {
                        'proxy_used': f"{proxy.ip}:{proxy.port}",
                        'response_time': response_time,
                        'status_code': response.status,
                        'attempt': attempt + 1,
                        'proxy_type': proxy.proxy_type.value,
                        'proxy_provider': proxy.provider
                    }
                    
                    logger.info(f"Successfully scraped {url} using {proxy.ip}:{proxy.port}")
                    return content, metadata
                    
            except asyncio.TimeoutError:
                logger.warning(f"Timeout with proxy {proxy.ip}:{proxy.port} for {url}")
                self.proxy_manager.update_proxy_stats(
                    proxy, False, timeout, urlparse(url).netloc, error="Timeout"
                )
                
                # Rotate proxy on timeout
                if attempt < max_retries - 1:
                    await self.proxy_manager.rotate_proxy(proxy, "timeout")
                    
            except aiohttp.ClientProxyConnectionError as e:
                logger.warning(f"Proxy connection error {proxy.ip}:{proxy.port}: {e}")
                self.proxy_manager.update_proxy_stats(
                    proxy, False, 0, urlparse(url).netloc, error=str(e)
                )
                
                # Remove bad proxy from pool
                if proxy.consecutive_failures > 3:
                    self.proxy_manager.blacklist_proxy(proxy, "Connection failures")
                    
            except Exception as e:
                logger.error(f"Error with proxy {proxy.ip}:{proxy.port}: {e}")
                self.proxy_manager.update_proxy_stats(
                    proxy, False, 0, urlparse(url).netloc, error=str(e)
                )
            
            # Exponential backoff between retries
            if attempt < max_retries - 1:
                wait_time = self.config['performance']['backoff_factor'] ** attempt
                await asyncio.sleep(wait_time)
        
        return None, {'error': f'Failed after {max_retries} attempts'}
    
    async def batch_scrape_with_rotation(self, urls: List[str], **kwargs) -> Dict[str, Dict]:
        """Scrape multiple URLs with rotation and concurrency control"""
        max_concurrent = kwargs.get(
            'max_concurrent', 
            self.config['performance']['max_concurrent_requests']
        )
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_single(url: str) -> Tuple[str, Dict]:
            async with semaphore:
                content, metadata = await self.scrape_with_rotation(url, **kwargs)
                return url, {
                    'success': content is not None,
                    'content': content,
                    'metadata': metadata
                }
        
        tasks = [scrape_single(url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        return dict(results)
    
    async def smart_scrape(self, url: str, **kwargs) -> Tuple[Optional[str], Dict]:
        """Intelligent scraping with automatic strategy selection"""
        domain = urlparse(url).netloc
        
        # Determine best pool based on domain characteristics
        pool = 'general'
        
        # Use high-performance proxies for important domains
        if any(d in domain for d in ['api.', 'data.', 'cdn.']):
            pool = 'high_performance'
        
        # Use residential proxies for protected sites
        elif any(d in domain for d in ['amazon', 'google', 'facebook', 'linkedin']):
            pool = 'residential'
        
        # Get appropriate proxy
        proxy = await self.proxy_manager.get_proxy_for_domain(domain, pool)
        
        if not proxy:
            # Fallback to any available proxy
            proxy = await self.proxy_manager.get_proxy_for_domain(domain, 'general')
        
        if proxy:
            kwargs['proxy'] = proxy
            return await self.scrape_with_rotation(url, **kwargs)
        
        return None, {'error': 'No suitable proxy found'}
    
    async def get_statistics(self) -> Dict:
        """Get comprehensive statistics"""
        proxy_stats = self.proxy_manager.get_statistics()
        
        return {
            'total_requests': self.request_count,
            'domain_stats': dict(self.domain_request_count),
            'proxy_statistics': proxy_stats,
            'active_proxies': len([
                p for p in self.proxy_manager.proxies 
                if p.health_score > 50
            ]),
            'blacklisted_ips': len(self.proxy_manager.blacklisted_ips),
            'config': {
                'rotation_strategy': self.config['rotation_settings']['strategy'],
                'auto_refresh': self.config['rotation_settings']['auto_refresh'],
                'using_free_proxies': self.config['proxy_providers']['use_free_proxies']
            }
        }
    
    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up scraper resources...")
        
        if self.rotator:
            await self.rotator.stop()
        
        if self.session:
            await self.session.close()
        
        # Save proxy states
        for proxy in self.proxy_manager.proxies:
            self.proxy_manager.save_proxy(proxy)
        
        logger.info("Cleanup complete")
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()


# Configuration generator
def generate_config_file(filename: str = "scraper_config.json"):
    """Generate a configuration file template"""
    config = {
        "proxy_providers": {
            "use_free_proxies": True,
            "use_premium_proxies": False,
            "brightdata": {
                "enabled": False,
                "customer_id": "YOUR_CUSTOMER_ID",
                "password": "YOUR_PASSWORD",
                "zone": "static"
            },
            "smartproxy": {
                "enabled": False,
                "username": "YOUR_USERNAME",
                "password": "YOUR_PASSWORD"
            }
        },
        "rotation_settings": {
            "strategy": "weighted_random",
            "rotation_interval": 300,
            "requests_per_proxy": 10,
            "min_healthy_proxies": 10,
            "auto_refresh": True
        },
        "performance": {
            "max_concurrent_requests": 10,
            "timeout": 30,
            "max_retries": 3,
            "backoff_factor": 1.5
        },
        "validation": {
            "validate_on_add": True,
            "validation_url": "http://httpbin.org/ip",
            "health_check_interval": 600
        }
    }
    
    with open(filename, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Configuration file generated: {filename}")


# Example usage and testing
async def test_integrated_scraper():
    """Test the integrated scraper system"""
    
    # Generate config if not exists
    if not os.path.exists("scraper_config.json"):
        generate_config_file()
    
    # Test URLs
    test_urls = [
        "http://httpbin.org/ip",
        "http://httpbin.org/user-agent",
        "http://httpbin.org/headers",
        "https://example.com",
        "https://www.wikipedia.org"
    ]
    
    # Initialize and run scraper
    async with IntegratedIntelligentScraper() as scraper:
        print("\n=== Testing Single URL Scraping ===")
        content, metadata = await scraper.scrape_with_rotation(test_urls[0])
        if content:
            print(f"Success! Response length: {len(content)}")
            print(f"Metadata: {json.dumps(metadata, indent=2)}")
        
        print("\n=== Testing Batch Scraping ===")
        results = await scraper.batch_scrape_with_rotation(test_urls)
        for url, result in results.items():
            status = "✓" if result['success'] else "✗"
            print(f"{status} {url}: {result['metadata']}")
        
        print("\n=== Testing Smart Scraping ===")
        content, metadata = await scraper.smart_scrape("https://api.example.com/data")
        print(f"Smart scrape metadata: {json.dumps(metadata, indent=2)}")
        
        print("\n=== Scraper Statistics ===")
        stats = await scraper.get_statistics()
        print(json.dumps(stats, indent=2))


# Command-line interface
async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Integrated Intelligent Scraper with IP Rotation")
    parser.add_argument('command', choices=['test', 'scrape', 'batch', 'stats', 'config'])
    parser.add_argument('--url', help='URL to scrape')
    parser.add_argument('--urls', nargs='+', help='Multiple URLs to scrape')
    parser.add_argument('--output', help='Output file for results')
    parser.add_argument('--config', default='scraper_config.json', help='Configuration file')
    
    args = parser.parse_args()
    
    if args.command == 'config':
        generate_config_file(args.config)
        return
    
    async with IntegratedIntelligentScraper(args.config) as scraper:
        if args.command == 'test':
            await test_integrated_scraper()
            
        elif args.command == 'scrape' and args.url:
            content, metadata = await scraper.scrape_with_rotation(args.url)
            result = {
                'url': args.url,
                'success': content is not None,
                'content_length': len(content) if content else 0,
                'metadata': metadata
            }
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(result, f, indent=2)
            else:
                print(json.dumps(result, indent=2))
                
        elif args.command == 'batch' and args.urls:
            results = await scraper.batch_scrape_with_rotation(args.urls)
            
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(results, f, indent=2)
            else:
                print(json.dumps(results, indent=2))
                
        elif args.command == 'stats':
            stats = await scraper.get_statistics()
            print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    # Run with: python integrated_scraper.py test
    # Or: python integrated_scraper.py scrape --url https://example.com
    asyncio.run(main())