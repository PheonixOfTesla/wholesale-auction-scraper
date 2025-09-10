# free_proxy_fetcher.py - Fetch free proxies from multiple sources
import asyncio
import aiohttp
import re
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import base64
from bs4 import BeautifulSoup
from proxy_rotation_manager import ProxyConfig, ProxyType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FreeProxyFetcher:
    """Fetch free proxies from various public sources"""
    
    def __init__(self):
        self.sources = {
            'proxylist_geonode': self.fetch_geonode,
            'free_proxy_list': self.fetch_free_proxy_list,
            'sslproxies': self.fetch_ssl_proxies,
            'proxy_list_download': self.fetch_proxy_list_download,
            'proxyscrape': self.fetch_proxyscrape,
            'proxylist_github': self.fetch_github_proxies,
            'hidemy': self.fetch_hidemy_proxies,
            'spys_one': self.fetch_spys_proxies,
        }
        self.session = None
        self.validated_proxies = []
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_all_proxies(self) -> List[ProxyConfig]:
        """Fetch proxies from all sources"""
        all_proxies = []
        
        tasks = []
        for source_name, fetch_func in self.sources.items():
            tasks.append(self.fetch_with_error_handling(source_name, fetch_func))
        
        results = await asyncio.gather(*tasks)
        
        for proxies in results:
            if proxies:
                all_proxies.extend(proxies)
        
        # Remove duplicates
        unique_proxies = {}
        for proxy in all_proxies:
            key = f"{proxy.ip}:{proxy.port}"
            if key not in unique_proxies:
                unique_proxies[key] = proxy
        
        logger.info(f"Fetched total {len(unique_proxies)} unique proxies from all sources")
        return list(unique_proxies.values())
    
    async def fetch_with_error_handling(self, source_name: str, fetch_func):
        """Wrapper to handle errors for each source"""
        try:
            logger.info(f"Fetching from {source_name}...")
            proxies = await fetch_func()
            logger.info(f"Got {len(proxies)} proxies from {source_name}")
            return proxies
        except Exception as e:
            logger.error(f"Error fetching from {source_name}: {e}")
            return []
    
    async def fetch_geonode(self) -> List[ProxyConfig]:
        """Fetch from Geonode API"""
        proxies = []
        try:
            url = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    for item in data.get('data', []):
                        proxy = ProxyConfig(
                            ip=item.get('ip'),
                            port=int(item.get('port')),
                            protocol=item.get('protocols', ['http'])[0],
                            proxy_type=ProxyType.DATACENTER,
                            country=item.get('country'),
                            city=item.get('city'),
                            provider='geonode',
                            success_rate=float(item.get('upTime', 0)) / 100,
                            avg_response_time=float(item.get('responseTime', 0)) / 1000
                        )
                        proxies.append(proxy)
        except Exception as e:
            logger.error(f"Geonode error: {e}")
        
        return proxies
    
    async def fetch_free_proxy_list(self) -> List[ProxyConfig]:
        """Fetch from free-proxy-list.net"""
        proxies = []
        try:
            url = "https://www.free-proxy-list.net/"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, 'html.parser')
                    
                    # Find the table with proxies
                    table = soup.find('table', {'class': 'table'})
                    if table:
                        rows = table.find_all('tr')[1:]  # Skip header
                        
                        for row in rows[:100]:  # Limit to 100
                            cells = row.find_all('td')
                            if len(cells) >= 7:
                                proxy = ProxyConfig(
                                    ip=cells[0].text.strip(),
                                    port=int(cells[1].text.strip()),
                                    protocol='https' if cells[6].text.strip() == 'yes' else 'http',
                                    proxy_type=ProxyType.DATACENTER,
                                    country=cells[3].text.strip(),
                                    provider='free-proxy-list'
                                )
                                proxies.append(proxy)
        except Exception as e:
            logger.error(f"Free-proxy-list error: {e}")
        
        return proxies
    
    async def fetch_ssl_proxies(self) -> List[ProxyConfig]:
        """Fetch SSL proxies from sslproxies.org"""
        proxies = []
        try:
            url = "https://www.sslproxies.org/"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, 'html.parser')
                    
                    table = soup.find('table', {'class': 'table'})
                    if table:
                        rows = table.find_all('tr')[1:]
                        
                        for row in rows[:50]:
                            cells = row.find_all('td')
                            if len(cells) >= 7:
                                proxy = ProxyConfig(
                                    ip=cells[0].text.strip(),
                                    port=int(cells[1].text.strip()),
                                    protocol='https',
                                    proxy_type=ProxyType.DATACENTER,
                                    country=cells[3].text.strip(),
                                    provider='sslproxies'
                                )
                                proxies.append(proxy)
        except Exception as e:
            logger.error(f"SSLProxies error: {e}")
        
        return proxies
    
    async def fetch_proxy_list_download(self) -> List[ProxyConfig]:
        """Fetch from proxy-list.download"""
        proxies = []
        try:
            urls = [
                "https://www.proxy-list.download/api/v1/get?type=http",
                "https://www.proxy-list.download/api/v1/get?type=https",
                "https://www.proxy-list.download/api/v1/get?type=socks4",
                "https://www.proxy-list.download/api/v1/get?type=socks5"
            ]
            
            for url in urls:
                protocol = url.split('type=')[1]
                
                async with self.session.get(url, timeout=10) as response:
                    if response.status == 200:
                        text = await response.text()
                        proxy_list = text.strip().split('\n')
                        
                        for proxy_str in proxy_list[:30]:  # Limit per type
                            if ':' in proxy_str:
                                ip, port = proxy_str.strip().split(':')
                                proxy = ProxyConfig(
                                    ip=ip,
                                    port=int(port),
                                    protocol=protocol,
                                    proxy_type=ProxyType.DATACENTER,
                                    provider='proxy-list-download'
                                )
                                proxies.append(proxy)
        except Exception as e:
            logger.error(f"Proxy-list-download error: {e}")
        
        return proxies
    
    async def fetch_proxyscrape(self) -> List[ProxyConfig]:
        """Fetch from ProxyScrape API"""
        proxies = []
        try:
            base_url = "https://api.proxyscrape.com/v2/"
            
            params_list = [
                {"request": "get", "protocol": "http", "timeout": 10000, "country": "all"},
                {"request": "get", "protocol": "socks4", "timeout": 10000, "country": "all"},
                {"request": "get", "protocol": "socks5", "timeout": 10000, "country": "all"}
            ]
            
            for params in params_list:
                async with self.session.get(base_url, params=params, timeout=10) as response:
                    if response.status == 200:
                        text = await response.text()
                        proxy_list = text.strip().split('\n')
                        
                        for proxy_str in proxy_list[:50]:
                            if ':' in proxy_str:
                                ip, port = proxy_str.strip().split(':')[:2]
                                proxy = ProxyConfig(
                                    ip=ip,
                                    port=int(port),
                                    protocol=params['protocol'],
                                    proxy_type=ProxyType.DATACENTER,
                                    provider='proxyscrape'
                                )
                                proxies.append(proxy)
        except Exception as e:
            logger.error(f"ProxyScrape error: {e}")
        
        return proxies
    
    async def fetch_github_proxies(self) -> List[ProxyConfig]:
        """Fetch from various GitHub proxy lists"""
        proxies = []
        
        github_urls = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"
        ]
        
        for url in github_urls:
            try:
                protocol = 'socks5' if 'socks5' in url else 'http'
                
                async with self.session.get(url, timeout=10) as response:
                    if response.status == 200:
                        text = await response.text()
                        proxy_list = text.strip().split('\n')
                        
                        for proxy_str in proxy_list[:30]:
                            if ':' in proxy_str:
                                parts = proxy_str.strip().split(':')
                                if len(parts) >= 2:
                                    ip = parts[0]
                                    port = parts[1].split()[0]  # Remove any extra info
                                    
                                    proxy = ProxyConfig(
                                        ip=ip,
                                        port=int(port),
                                        protocol=protocol,
                                        proxy_type=ProxyType.DATACENTER,
                                        provider='github'
                                    )
                                    proxies.append(proxy)
            except Exception as e:
                logger.error(f"GitHub proxy list error for {url}: {e}")
        
        return proxies
    
    async def fetch_hidemy_proxies(self) -> List[ProxyConfig]:
        """Fetch from hidemy.name (requires parsing)"""
        proxies = []
        try:
            # Note: hidemy.name has anti-bot protection
            # This is a simplified version - in production you'd need more sophisticated handling
            url = "https://hidemy.name/en/proxy-list/?type=hs&anon=34#list"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    
                    # Parse with regex (simplified)
                    pattern = r'(\d+\.\d+\.\d+\.\d+)</td><td>(\d+)'
                    matches = re.findall(pattern, text)
                    
                    for ip, port in matches[:30]:
                        proxy = ProxyConfig(
                            ip=ip,
                            port=int(port),
                            protocol='http',
                            proxy_type=ProxyType.DATACENTER,
                            provider='hidemy'
                        )
                        proxies.append(proxy)
        except Exception as e:
            logger.error(f"Hidemy error: {e}")
        
        return proxies
    
    async def fetch_spys_proxies(self) -> List[ProxyConfig]:
        """Fetch from spys.one"""
        proxies = []
        try:
            url = "https://spys.me/proxy.txt"
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    lines = text.strip().split('\n')
                    
                    for line in lines[3:]:  # Skip header lines
                        if ' ' in line:
                            parts = line.split()
                            if len(parts) >= 2:
                                proxy_addr = parts[0]
                                if ':' in proxy_addr:
                                    ip, port = proxy_addr.split(':')
                                    
                                    # Parse proxy type from the line
                                    proxy_type_str = parts[1] if len(parts) > 1 else 'HTTP'
                                    protocol = 'socks5' if 'SOCKS5' in proxy_type_str else 'http'
                                    
                                    proxy = ProxyConfig(
                                        ip=ip,
                                        port=int(port),
                                        protocol=protocol,
                                        proxy_type=ProxyType.DATACENTER,
                                        provider='spys'
                                    )
                                    proxies.append(proxy)
        except Exception as e:
            logger.error(f"Spys error: {e}")
        
        return proxies
    
    async def validate_proxy(self, proxy: ProxyConfig, test_url: str = "http://httpbin.org/ip") -> bool:
        """Validate if a proxy is working"""
        try:
            proxy_url = f"{proxy.protocol}://{proxy.ip}:{proxy.port}"
            
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, proxy=proxy_url, timeout=timeout) as response:
                    if response.status == 200:
                        return True
        except:
            pass
        return False
    
    async def validate_proxies_batch(self, proxies: List[ProxyConfig], max_concurrent: int = 50) -> List[ProxyConfig]:
        """Validate multiple proxies concurrently"""
        logger.info(f"Validating {len(proxies)} proxies...")
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def validate_with_semaphore(proxy):
            async with semaphore:
                is_valid = await self.validate_proxy(proxy)
                return proxy if is_valid else None
        
        tasks = [validate_with_semaphore(proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks)
        
        valid_proxies = [p for p in results if p is not None]
        logger.info(f"Validation complete: {len(valid_proxies)}/{len(proxies)} proxies are valid")
        
        return valid_proxies

class ProxyRotator:
    """Automatic proxy rotation service"""
    
    def __init__(self, manager, fetcher):
        self.manager = manager
        self.fetcher = fetcher
        self.rotation_interval = 300  # 5 minutes
        self.min_healthy_proxies = 10
        self.running = False
    
    async def start(self):
        """Start automatic proxy rotation service"""
        self.running = True
        
        # Initial fetch
        await self.refresh_proxy_pool()
        
        # Start rotation loop
        while self.running:
            await asyncio.sleep(self.rotation_interval)
            await self.rotate_proxies()
    
    async def stop(self):
        """Stop the rotation service"""
        self.running = False
    
    async def refresh_proxy_pool(self):
        """Refresh the proxy pool with new proxies"""
        logger.info("Refreshing proxy pool...")
        
        async with self.fetcher as fetcher:
            # Fetch new proxies
            new_proxies = await fetcher.fetch_all_proxies()
            
            # Validate them
            valid_proxies = await fetcher.validate_proxies_batch(new_proxies[:100])  # Limit validation
            
            # Add to manager
            for proxy in valid_proxies:
                self.manager.add_proxy(proxy)
        
        logger.info(f"Added {len(valid_proxies)} new valid proxies to pool")
    
    async def rotate_proxies(self):
        """Perform proxy rotation"""
        logger.info("Performing proxy rotation...")
        
        # Check health
        await self.manager.health_check_all_proxies()
        
        # Get statistics
        stats = self.manager.get_statistics()
        healthy_count = len([p for p in self.manager.proxies if p.health_score > 50])
        
        # Refresh if needed
        if healthy_count < self.min_healthy_proxies:
            logger.warning(f"Low healthy proxy count: {healthy_count}")
            await self.refresh_proxy_pool()
        
        # Rotate sticky sessions for old proxies
        for proxy in self.manager.proxies:
            if proxy.last_rotated:
                time_since_rotation = (datetime.now() - proxy.last_rotated).seconds
                if time_since_rotation > 3600:  # 1 hour
                    await self.manager.rotate_proxy(proxy, "scheduled_rotation")

# Example usage
async def test_free_proxy_system():
    from proxy_rotation_manager import EnhancedProxyManager
    
    # Initialize components
    manager = EnhancedProxyManager()
    fetcher = FreeProxyFetcher()
    rotator = ProxyRotator(manager, fetcher)
    
    # Fetch and validate free proxies
    async with fetcher as f:
        proxies = await f.fetch_all_proxies()
        print(f"Fetched {len(proxies)} total proxies")
        
        # Validate a sample
        valid_proxies = await f.validate_proxies_batch(proxies[:20])
        print(f"Valid proxies: {len(valid_proxies)}")
        
        # Add to manager
        for proxy in valid_proxies:
            manager.add_proxy(proxy)
    
    # Test rotation
    domain = "example.com"
    proxy = await manager.get_proxy_for_domain(domain)
    if proxy:
        print(f"Got proxy for {domain}: {proxy.ip}:{proxy.port}")
    
    # Get statistics
    stats = manager.get_statistics()
    print(f"Manager stats: {json.dumps(stats, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test_free_proxy_system())