# main.py - Intelligent Self-Learning Backend Scraper
import asyncio
import aiohttp
import json
import random
import time
import sqlite3
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse
import hashlib
import logging
from datetime import datetime, timedelta
import subprocess
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ProxyConfig:
    ip: str
    port: int
    protocol: str = 'http'
    username: Optional[str] = None
    password: Optional[str] = None
    success_rate: float = 1.0
    last_used: Optional[datetime] = None
    failures: int = 0
    avg_response_time: float = 0.0

@dataclass
class ScrapingRule:
    domain: str
    selectors: Dict[str, str]
    rate_limit: float
    headers: Dict[str, str]
    success_patterns: List[str]
    failure_patterns: List[str]
    last_updated: datetime
    success_count: int = 0
    failure_count: int = 0

class ProxyManager:
    def __init__(self, db_path: str = "proxies.db"):
        self.db_path = db_path
        self.proxies: List[ProxyConfig] = []
        self.init_db()
        self.load_proxies()

    def init_db(self):
        """Initialize SQLite database for proxy management"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxies (
                ip TEXT,
                port INTEGER,
                protocol TEXT,
                username TEXT,
                password TEXT,
                success_rate REAL,
                last_used TEXT,
                failures INTEGER,
                avg_response_time REAL,
                PRIMARY KEY (ip, port)
            )
        ''')
        conn.commit()
        conn.close()

    def add_proxy(self, proxy: ProxyConfig):
        """Add new proxy to pool"""
        self.proxies.append(proxy)
        self.save_proxy(proxy)

    def save_proxy(self, proxy: ProxyConfig):
        """Save proxy to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO proxies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (proxy.ip, proxy.port, proxy.protocol, proxy.username, proxy.password,
              proxy.success_rate, proxy.last_used.isoformat() if proxy.last_used else None,
              proxy.failures, proxy.avg_response_time))
        conn.commit()
        conn.close()

    def load_proxies(self):
        """Load proxies from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM proxies')
        rows = cursor.fetchall()
        
        for row in rows:
            proxy = ProxyConfig(
                ip=row[0], port=row[1], protocol=row[2],
                username=row[3], password=row[4], success_rate=row[5],
                last_used=datetime.fromisoformat(row[6]) if row[6] else None,
                failures=row[7], avg_response_time=row[8]
            )
            self.proxies.append(proxy)
        conn.close()

    def get_best_proxy(self) -> Optional[ProxyConfig]:
        """Select best proxy based on success rate and last usage"""
        if not self.proxies:
            return None
        
        # Filter out proxies with too many failures
        viable_proxies = [p for p in self.proxies if p.failures < 5]
        if not viable_proxies:
            # Reset failure counts if all proxies are blocked
            for proxy in self.proxies:
                proxy.failures = 0
            viable_proxies = self.proxies

        # Sort by success rate and last used time
        viable_proxies.sort(key=lambda p: (
            p.success_rate,
            -(time.time() - p.last_used.timestamp()) if p.last_used else float('inf')
        ), reverse=True)

        return viable_proxies[0]

    def update_proxy_stats(self, proxy: ProxyConfig, success: bool, response_time: float):
        """Update proxy statistics"""
        if success:
            proxy.success_rate = min(1.0, proxy.success_rate + 0.01)
        else:
            proxy.failures += 1
            proxy.success_rate = max(0.1, proxy.success_rate - 0.05)
        
        proxy.avg_response_time = (proxy.avg_response_time + response_time) / 2
        proxy.last_used = datetime.now()
        self.save_proxy(proxy)

class RuleEngine:
    def __init__(self, db_path: str = "rules.db"):
        self.db_path = db_path
        self.rules: Dict[str, ScrapingRule] = {}
        self.init_db()
        self.load_rules()

    def init_db(self):
        """Initialize rules database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rules (
                domain TEXT PRIMARY KEY,
                selectors TEXT,
                rate_limit REAL,
                headers TEXT,
                success_patterns TEXT,
                failure_patterns TEXT,
                last_updated TEXT,
                success_count INTEGER,
                failure_count INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    def save_rule(self, rule: ScrapingRule):
        """Save rule to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (rule.domain, json.dumps(rule.selectors), rule.rate_limit,
              json.dumps(rule.headers), json.dumps(rule.success_patterns),
              json.dumps(rule.failure_patterns), rule.last_updated.isoformat(),
              rule.success_count, rule.failure_count))
        conn.commit()
        conn.close()

    def load_rules(self):
        """Load rules from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rules')
        rows = cursor.fetchall()
        
        for row in rows:
            rule = ScrapingRule(
                domain=row[0], selectors=json.loads(row[1]), rate_limit=row[2],
                headers=json.loads(row[3]), success_patterns=json.loads(row[4]),
                failure_patterns=json.loads(row[5]), 
                last_updated=datetime.fromisoformat(row[6]),
                success_count=row[7], failure_count=row[8]
            )
            self.rules[rule.domain] = rule
        conn.close()

    def get_rule(self, domain: str) -> ScrapingRule:
        """Get rule for domain, create default if not exists"""
        if domain not in self.rules:
            self.rules[domain] = ScrapingRule(
                domain=domain,
                selectors={'title': 'title', 'content': 'body'},
                rate_limit=1.0,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive'
                },
                success_patterns=['<html', '<title', '<body'],
                failure_patterns=['403', '404', '429', 'captcha', 'blocked'],
                last_updated=datetime.now()
            )
            self.save_rule(self.rules[domain])
        return self.rules[domain]

    def update_rule_success(self, domain: str, selectors_found: Dict[str, bool]):
        """Update rule based on scraping results"""
        rule = self.rules.get(domain)
        if not rule:
            return

        if any(selectors_found.values()):
            rule.success_count += 1
            # Reduce rate limit on success
            rule.rate_limit = max(0.5, rule.rate_limit * 0.95)
        else:
            rule.failure_count += 1
            # Increase rate limit on failure
            rule.rate_limit = min(10.0, rule.rate_limit * 1.1)

        rule.last_updated = datetime.now()
        self.save_rule(rule)

class JSRenderer:
    """Handle JavaScript rendering using Puppeteer via subprocess"""
    
    @staticmethod
    async def render_page(url: str, proxy: Optional[ProxyConfig] = None) -> Optional[str]:
        """Render JavaScript page using Node.js subprocess"""
        js_script = f"""
        const puppeteer = require('puppeteer');
        
        (async () => {{
            const browser = await puppeteer.launch({{
                args: ['--no-sandbox', '--disable-setuid-sandbox'
                {f", '--proxy-server={proxy.protocol}://{proxy.ip}:{proxy.port}'" if proxy else ''}]
            }});
            
            const page = await browser.newPage();
            
            {f'''
            if ('{proxy and proxy.username}') {{
                await page.authenticate({{
                    username: '{proxy.username}',
                    password: '{proxy.password}'
                }});
            }}
            ''' if proxy and proxy.username else ''}
            
            try {{
                await page.goto('{url}', {{ waitUntil: 'networkidle2', timeout: 30000 }});
                await page.waitForTimeout(2000);
                const content = await page.content();
                console.log(content);
            }} catch (e) {{
                console.error('Error:', e.message);
            }} finally {{
                await browser.close();
            }}
        }})();
        """
        
        try:
            # Save JS script to temp file
            with open('/tmp/render.js', 'w') as f:
                f.write(js_script)
            
            # Execute with Node.js
            process = await asyncio.create_subprocess_exec(
                'node', '/tmp/render.js',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return stdout.decode('utf-8')
            else:
                logger.error(f"JS rendering failed: {stderr.decode('utf-8')}")
                return None
                
        except Exception as e:
            logger.error(f"JS rendering error: {e}")
            return None

class IntelligentScraper:
    def __init__(self):
        self.proxy_manager = ProxyManager()
        self.rule_engine = RuleEngine()
        self.session = None
        self.js_renderer = JSRenderer()
        
        # Add some default proxies (you'd populate these with real proxy services)
        default_proxies = [
            ProxyConfig("127.0.0.1", 8080),  # Local proxy example
            ProxyConfig("proxy1.example.com", 3128),
            ProxyConfig("proxy2.example.com", 8080),
        ]
        
        for proxy in default_proxies:
            if proxy not in self.proxy_manager.proxies:
                self.proxy_manager.add_proxy(proxy)

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    def get_proxy_url(self, proxy: ProxyConfig) -> str:
        """Format proxy URL"""
        if proxy.username:
            return f"{proxy.protocol}://{proxy.username}:{proxy.password}@{proxy.ip}:{proxy.port}"
        return f"{proxy.protocol}://{proxy.ip}:{proxy.port}"

    async def scrape_with_proxy(self, url: str, proxy: ProxyConfig) -> Tuple[Optional[str], bool, float]:
        """Scrape URL using specific proxy"""
        start_time = time.time()
        domain = urlparse(url).netloc
        rule = self.rule_engine.get_rule(domain)
        
        try:
            # Wait for rate limit
            await asyncio.sleep(rule.rate_limit)
            
            proxy_url = self.get_proxy_url(proxy)
            
            async with self.session.get(
                url,
                proxy=proxy_url,
                headers=rule.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response_time = time.time() - start_time
                content = await response.text()
                
                # Check for failure patterns
                content_lower = content.lower()
                for pattern in rule.failure_patterns:
                    if pattern in content_lower:
                        return None, False, response_time
                
                # Check for success patterns
                success = any(pattern in content_lower for pattern in rule.success_patterns)
                
                if success:
                    return content, True, response_time
                else:
                    # Try JS rendering if regular request seems to fail
                    js_content = await self.js_renderer.render_page(url, proxy)
                    if js_content:
                        return js_content, True, time.time() - start_time
                    return content, False, response_time
                    
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Scraping error with proxy {proxy.ip}:{proxy.port}: {e}")
            return None, False, response_time

    async def adaptive_scrape(self, url: str, max_retries: int = 3) -> Optional[str]:
        """Intelligently scrape URL with proxy rotation and adaptation"""
        domain = urlparse(url).netloc
        
        for attempt in range(max_retries):
            proxy = self.proxy_manager.get_best_proxy()
            if not proxy:
                logger.error("No available proxies")
                return None
            
            logger.info(f"Attempt {attempt + 1}: Scraping {url} with proxy {proxy.ip}:{proxy.port}")
            
            content, success, response_time = await self.scrape_with_proxy(url, proxy)
            
            # Update proxy statistics
            self.proxy_manager.update_proxy_stats(proxy, success, response_time)
            
            if success and content:
                # Update rule success
                selectors_found = {'content': bool(content)}
                self.rule_engine.update_rule_success(domain, selectors_found)
                return content
            
            # If failed, try different proxy
            logger.warning(f"Failed with proxy {proxy.ip}:{proxy.port}, trying next...")
            
        logger.error(f"Failed to scrape {url} after {max_retries} attempts")
        return None

    async def batch_scrape(self, urls: List[str], max_concurrent: int = 5) -> Dict[str, Optional[str]]:
        """Scrape multiple URLs concurrently"""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_single(url: str) -> Tuple[str, Optional[str]]:
            async with semaphore:
                result = await self.adaptive_scrape(url)
                return url, result
        
        tasks = [scrape_single(url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        return dict(results)

# Example usage and API
async def main():
    """Example usage of the intelligent scraper"""
    urls = [
        "http://httpbin.org/ip",
        "https://httpbin.org/user-agent",
        "https://example.com",
    ]
    
    async with IntelligentScraper() as scraper:
        # Single URL scraping
        result = await scraper.adaptive_scrape(urls[0])
        print(f"Single scrape result: {result[:200] if result else 'Failed'}")
        
        # Batch scraping
        batch_results = await scraper.batch_scrape(urls)
        print(f"\nBatch results: {len([r for r in batch_results.values() if r])} successful")
        
        for url, content in batch_results.items():
            print(f"{url}: {'✓' if content else '✗'}")

if __name__ == "__main__":
    asyncio.run(main())

# Additional utility functions for the API

class ScraperAPI:
    """REST API wrapper for the scraper"""
    
    def __init__(self):
        self.scraper = None
    
    async def start(self):
        """Start the scraper"""
        self.scraper = IntelligentScraper()
        await self.scraper.__aenter__()
    
    async def stop(self):
        """Stop the scraper"""
        if self.scraper:
            await self.scraper.__aexit__(None, None, None)
    
    async def scrape_url(self, url: str) -> Dict:
        """API endpoint for single URL scraping"""
        if not self.scraper:
            return {"error": "Scraper not initialized"}
        
        start_time = time.time()
        result = await self.scraper.adaptive_scrape(url)
        end_time = time.time()
        
        return {
            "url": url,
            "success": bool(result),
            "content": result,
            "response_time": end_time - start_time,
            "timestamp": datetime.now().isoformat()
        }
    
    async def add_proxy(self, ip: str, port: int, protocol: str = "http", 
                       username: str = None, password: str = None) -> Dict:
        """API endpoint for adding new proxy"""
        if not self.scraper:
            return {"error": "Scraper not initialized"}
        
        proxy = ProxyConfig(ip, port, protocol, username, password)
        self.scraper.proxy_manager.add_proxy(proxy)
        
        return {"message": f"Proxy {ip}:{port} added successfully"}
    
    def get_stats(self) -> Dict:
        """Get scraper statistics"""
        if not self.scraper:
            return {"error": "Scraper not initialized"}
        
        proxy_stats = []
        for proxy in self.scraper.proxy_manager.proxies:
            proxy_stats.append({
                "ip": proxy.ip,
                "port": proxy.port,
                "success_rate": proxy.success_rate,
                "failures": proxy.failures,
                "avg_response_time": proxy.avg_response_time
            })
        
        rule_stats = []
        for domain, rule in self.scraper.rule_engine.rules.items():
            rule_stats.append({
                "domain": domain,
                "success_count": rule.success_count,
                "failure_count": rule.failure_count,
                "rate_limit": rule.rate_limit
            })
        
        return {
            "proxies": proxy_stats,
            "rules": rule_stats,
            "total_proxies": len(self.scraper.proxy_manager.proxies),
            "total_rules": len(self.scraper.rule_engine.rules)
        }