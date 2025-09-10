# proxy_rotation_manager.py - Enhanced proxy management with IP rotation
import asyncio
import aiohttp
import json
import random
import time
import sqlite3
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime, timedelta
from enum import Enum
import base64
from urllib.parse import urlparse
import socket
import struct

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProxyType(Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"
    RESIDENTIAL = "residential"
    DATACENTER = "datacenter"
    MOBILE = "mobile"

@dataclass
class ProxyConfig:
    ip: str
    port: int
    protocol: str = 'http'
    proxy_type: ProxyType = ProxyType.DATACENTER
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    provider: Optional[str] = None
    success_rate: float = 1.0
    last_used: Optional[datetime] = None
    last_rotated: Optional[datetime] = None
    failures: int = 0
    consecutive_failures: int = 0
    avg_response_time: float = 0.0
    total_requests: int = 0
    successful_requests: int = 0
    blacklisted_domains: Set[str] = field(default_factory=set)
    sticky_session_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    health_score: float = 100.0
    
    def calculate_health_score(self):
        """Calculate proxy health score based on various metrics"""
        score = 100.0
        
        # Penalize for failures
        score -= self.failures * 2
        score -= self.consecutive_failures * 5
        
        # Reward for success rate
        score *= self.success_rate
        
        # Penalize for slow response time
        if self.avg_response_time > 5:
            score -= (self.avg_response_time - 5) * 10
        
        # Penalize if not used recently
        if self.last_used:
            hours_since_use = (datetime.now() - self.last_used).total_seconds() / 3600
            if hours_since_use > 24:
                score -= min(20, hours_since_use - 24)
        
        self.health_score = max(0, min(100, score))
        return self.health_score

class ProxyProvider:
    """Base class for proxy providers"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.name = "base_provider"
    
    async def get_proxies(self) -> List[ProxyConfig]:
        raise NotImplementedError
    
    async def rotate_ip(self, proxy: ProxyConfig) -> ProxyConfig:
        raise NotImplementedError

class BrightDataProvider(ProxyProvider):
    """BrightData (formerly Luminati) proxy provider"""
    
    def __init__(self, customer_id: str, password: str, zone: str = "static"):
        super().__init__()
        self.customer_id = customer_id
        self.password = password
        self.zone = zone
        self.name = "brightdata"
        self.base_url = "zproxy.lum-superproxy.io"
        
    async def get_proxies(self) -> List[ProxyConfig]:
        proxies = []
        
        # Datacenter proxies
        for i in range(5):
            proxy = ProxyConfig(
                ip=self.base_url,
                port=22225,
                protocol="http",
                proxy_type=ProxyType.DATACENTER,
                username=f"{self.customer_id}-zone-{self.zone}-session-{int(time.time())}_{i}",
                password=self.password,
                provider=self.name,
                country="US"
            )
            proxies.append(proxy)
        
        # Residential proxies with sticky sessions
        for i in range(3):
            session_id = f"session_{hashlib.md5(f'{time.time()}_{i}'.encode()).hexdigest()[:8]}"
            proxy = ProxyConfig(
                ip=self.base_url,
                port=22225,
                protocol="http",
                proxy_type=ProxyType.RESIDENTIAL,
                username=f"{self.customer_id}-zone-residential-session-{session_id}",
                password=self.password,
                provider=self.name,
                sticky_session_id=session_id,
                country="US"
            )
            proxies.append(proxy)
        
        return proxies
    
    async def rotate_ip(self, proxy: ProxyConfig) -> ProxyConfig:
        """Rotate IP by changing session ID"""
        new_session = f"session_{hashlib.md5(f'{time.time()}'.encode()).hexdigest()[:8]}"
        proxy.username = proxy.username.replace(proxy.sticky_session_id, new_session)
        proxy.sticky_session_id = new_session
        proxy.last_rotated = datetime.now()
        return proxy

class SmartProxyProvider(ProxyProvider):
    """SmartProxy provider"""
    
    def __init__(self, username: str, password: str):
        super().__init__()
        self.username = username
        self.password = password
        self.name = "smartproxy"
        
    async def get_proxies(self) -> List[ProxyConfig]:
        endpoints = [
            ("gate.smartproxy.com", 10000, "rotating"),
            ("gate.smartproxy.com", 10001, "sticky"),
        ]
        
        proxies = []
        for host, port, session_type in endpoints:
            proxy = ProxyConfig(
                ip=host,
                port=port,
                protocol="http",
                proxy_type=ProxyType.RESIDENTIAL,
                username=self.username,
                password=self.password,
                provider=self.name,
                sticky_session_id=session_type
            )
            proxies.append(proxy)
        
        return proxies

class ProxyRotationStrategy:
    """Different strategies for rotating proxies"""
    
    @staticmethod
    def round_robin(proxies: List[ProxyConfig]) -> ProxyConfig:
        """Simple round-robin rotation"""
        if not proxies:
            return None
        return proxies[0]  # Caller should rotate list after use
    
    @staticmethod
    def weighted_random(proxies: List[ProxyConfig]) -> ProxyConfig:
        """Select proxy based on health score"""
        if not proxies:
            return None
        
        weights = [p.health_score for p in proxies]
        total_weight = sum(weights)
        
        if total_weight == 0:
            return random.choice(proxies)
        
        r = random.uniform(0, total_weight)
        upto = 0
        for proxy, weight in zip(proxies, weights):
            upto += weight
            if upto >= r:
                return proxy
        
        return proxies[-1]
    
    @staticmethod
    def least_used(proxies: List[ProxyConfig]) -> ProxyConfig:
        """Select least recently used proxy"""
        if not proxies:
            return None
        
        return min(proxies, key=lambda p: (
            p.last_used.timestamp() if p.last_used else 0,
            p.total_requests
        ))
    
    @staticmethod
    def geo_specific(proxies: List[ProxyConfig], country: str) -> ProxyConfig:
        """Select proxy from specific country"""
        country_proxies = [p for p in proxies if p.country == country]
        if country_proxies:
            return ProxyRotationStrategy.weighted_random(country_proxies)
        return ProxyRotationStrategy.weighted_random(proxies)

class EnhancedProxyManager:
    def __init__(self, db_path: str = "proxies_enhanced.db"):
        self.db_path = db_path
        self.proxies: List[ProxyConfig] = []
        self.providers: List[ProxyProvider] = []
        self.rotation_strategy = ProxyRotationStrategy.weighted_random
        self.proxy_pools: Dict[str, List[ProxyConfig]] = {
            'general': [],
            'residential': [],
            'datacenter': [],
            'mobile': [],
            'high_performance': [],
            'backup': []
        }
        self.blacklisted_ips: Set[str] = set()
        self.domain_proxy_map: Dict[str, ProxyConfig] = {}
        self.init_db()
        self.load_proxies()
    
    def init_db(self):
        """Initialize enhanced database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Enhanced proxy table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                protocol TEXT,
                proxy_type TEXT,
                username TEXT,
                password TEXT,
                country TEXT,
                city TEXT,
                provider TEXT,
                success_rate REAL DEFAULT 1.0,
                last_used TEXT,
                last_rotated TEXT,
                failures INTEGER DEFAULT 0,
                consecutive_failures INTEGER DEFAULT 0,
                avg_response_time REAL DEFAULT 0.0,
                total_requests INTEGER DEFAULT 0,
                successful_requests INTEGER DEFAULT 0,
                sticky_session_id TEXT,
                expires_at TEXT,
                health_score REAL DEFAULT 100.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ip, port, username)
            )
        ''')
        
        # Proxy performance history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxy_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_id INTEGER,
                domain TEXT,
                success BOOLEAN,
                response_time REAL,
                status_code INTEGER,
                error_message TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(proxy_id) REFERENCES proxies(id)
            )
        ''')
        
        # Blacklisted IPs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blacklisted_ips (
                ip TEXT PRIMARY KEY,
                reason TEXT,
                blacklisted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Domain-specific proxy assignments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS domain_proxy_assignments (
                domain TEXT PRIMARY KEY,
                proxy_id INTEGER,
                assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(proxy_id) REFERENCES proxies(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    async def initialize_providers(self, provider_configs: Dict):
        """Initialize proxy providers with credentials"""
        if 'brightdata' in provider_configs:
            config = provider_configs['brightdata']
            provider = BrightDataProvider(
                config['customer_id'],
                config['password'],
                config.get('zone', 'static')
            )
            self.providers.append(provider)
        
        if 'smartproxy' in provider_configs:
            config = provider_configs['smartproxy']
            provider = SmartProxyProvider(
                config['username'],
                config['password']
            )
            self.providers.append(provider)
    
    async def fetch_proxies_from_providers(self):
        """Fetch proxies from all configured providers"""
        all_proxies = []
        
        for provider in self.providers:
            try:
                proxies = await provider.get_proxies()
                all_proxies.extend(proxies)
                logger.info(f"Fetched {len(proxies)} proxies from {provider.name}")
            except Exception as e:
                logger.error(f"Error fetching proxies from {provider.name}: {e}")
        
        # Add to proxy pool
        for proxy in all_proxies:
            self.add_proxy(proxy)
        
        return all_proxies
    
    def add_proxy(self, proxy: ProxyConfig):
        """Add proxy to appropriate pools"""
        if proxy.ip in self.blacklisted_ips:
            logger.warning(f"Skipping blacklisted IP: {proxy.ip}")
            return
        
        # Add to main list
        if proxy not in self.proxies:
            self.proxies.append(proxy)
            self.save_proxy(proxy)
        
        # Categorize into pools
        self.proxy_pools['general'].append(proxy)
        
        if proxy.proxy_type == ProxyType.RESIDENTIAL:
            self.proxy_pools['residential'].append(proxy)
        elif proxy.proxy_type == ProxyType.DATACENTER:
            self.proxy_pools['datacenter'].append(proxy)
        elif proxy.proxy_type == ProxyType.MOBILE:
            self.proxy_pools['mobile'].append(proxy)
        
        # High performance pool (health score > 80)
        if proxy.health_score > 80:
            self.proxy_pools['high_performance'].append(proxy)
        # Backup pool (health score < 50)
        elif proxy.health_score < 50:
            self.proxy_pools['backup'].append(proxy)
    
    def save_proxy(self, proxy: ProxyConfig):
        """Save proxy to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO proxies 
            (ip, port, protocol, proxy_type, username, password, country, city, 
             provider, success_rate, last_used, last_rotated, failures, 
             consecutive_failures, avg_response_time, total_requests, 
             successful_requests, sticky_session_id, expires_at, health_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            proxy.ip, proxy.port, proxy.protocol, proxy.proxy_type.value,
            proxy.username, proxy.password, proxy.country, proxy.city,
            proxy.provider, proxy.success_rate,
            proxy.last_used.isoformat() if proxy.last_used else None,
            proxy.last_rotated.isoformat() if proxy.last_rotated else None,
            proxy.failures, proxy.consecutive_failures, proxy.avg_response_time,
            proxy.total_requests, proxy.successful_requests,
            proxy.sticky_session_id,
            proxy.expires_at.isoformat() if proxy.expires_at else None,
            proxy.health_score
        ))
        
        conn.commit()
        conn.close()
    
    def load_proxies(self):
        """Load proxies from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM proxies WHERE health_score > 0')
        rows = cursor.fetchall()
        
        for row in rows:
            proxy = ProxyConfig(
                ip=row[1], port=row[2], protocol=row[3],
                proxy_type=ProxyType(row[4]) if row[4] else ProxyType.DATACENTER,
                username=row[5], password=row[6],
                country=row[7], city=row[8], provider=row[9],
                success_rate=row[10],
                last_used=datetime.fromisoformat(row[11]) if row[11] else None,
                last_rotated=datetime.fromisoformat(row[12]) if row[12] else None,
                failures=row[13], consecutive_failures=row[14],
                avg_response_time=row[15], total_requests=row[16],
                successful_requests=row[17], sticky_session_id=row[18],
                expires_at=datetime.fromisoformat(row[19]) if row[19] else None,
                health_score=row[20]
            )
            self.add_proxy(proxy)
        
        # Load blacklisted IPs
        cursor.execute('SELECT ip FROM blacklisted_ips')
        self.blacklisted_ips = {row[0] for row in cursor.fetchall()}
        
        conn.close()
        logger.info(f"Loaded {len(self.proxies)} proxies from database")
    
    async def get_proxy_for_domain(self, domain: str, pool: str = 'general') -> Optional[ProxyConfig]:
        """Get best proxy for specific domain"""
        # Check if domain has assigned proxy
        if domain in self.domain_proxy_map:
            proxy = self.domain_proxy_map[domain]
            if proxy.health_score > 30:  # Still usable
                return proxy
        
        # Get proxies from specified pool
        pool_proxies = self.proxy_pools.get(pool, self.proxy_pools['general'])
        
        # Filter out blacklisted domains for each proxy
        viable_proxies = [
            p for p in pool_proxies 
            if domain not in p.blacklisted_domains and p.health_score > 20
        ]
        
        if not viable_proxies:
            # Try backup pool
            viable_proxies = self.proxy_pools['backup']
        
        if not viable_proxies:
            logger.error(f"No viable proxies available for {domain}")
            return None
        
        # Select proxy using current strategy
        proxy = self.rotation_strategy(viable_proxies)
        
        # Assign to domain for session persistence
        self.domain_proxy_map[domain] = proxy
        
        return proxy
    
    async def rotate_proxy(self, current_proxy: ProxyConfig, reason: str = "scheduled") -> ProxyConfig:
        """Rotate to a new proxy"""
        logger.info(f"Rotating proxy {current_proxy.ip}:{current_proxy.port} - Reason: {reason}")
        
        # If provider supports rotation
        for provider in self.providers:
            if provider.name == current_proxy.provider:
                try:
                    new_proxy = await provider.rotate_ip(current_proxy)
                    self.save_proxy(new_proxy)
                    return new_proxy
                except Exception as e:
                    logger.error(f"Failed to rotate with provider: {e}")
        
        # Otherwise, select a different proxy
        other_proxies = [p for p in self.proxies if p != current_proxy]
        if other_proxies:
            return self.rotation_strategy(other_proxies)
        
        return current_proxy
    
    def update_proxy_stats(self, proxy: ProxyConfig, success: bool, 
                          response_time: float, domain: str = None, 
                          status_code: int = None, error: str = None):
        """Update proxy statistics with detailed tracking"""
        proxy.total_requests += 1
        
        if success:
            proxy.successful_requests += 1
            proxy.consecutive_failures = 0
            proxy.success_rate = proxy.successful_requests / proxy.total_requests
        else:
            proxy.failures += 1
            proxy.consecutive_failures += 1
            proxy.success_rate = proxy.successful_requests / proxy.total_requests
            
            # Blacklist domain if too many failures
            if domain and proxy.consecutive_failures > 3:
                proxy.blacklisted_domains.add(domain)
                logger.warning(f"Blacklisted {domain} for proxy {proxy.ip}:{proxy.port}")
        
        # Update average response time
        if proxy.avg_response_time == 0:
            proxy.avg_response_time = response_time
        else:
            proxy.avg_response_time = (proxy.avg_response_time * 0.7 + response_time * 0.3)
        
        proxy.last_used = datetime.now()
        proxy.calculate_health_score()
        
        # Save performance record
        self.save_performance_record(proxy, domain, success, response_time, status_code, error)
        
        # Save updated proxy
        self.save_proxy(proxy)
        
        # Check if proxy needs to be blacklisted
        if proxy.consecutive_failures > 10 or proxy.health_score < 10:
            self.blacklist_proxy(proxy, f"Too many failures: {proxy.consecutive_failures}")
    
    def save_performance_record(self, proxy: ProxyConfig, domain: str, 
                                success: bool, response_time: float, 
                                status_code: int = None, error: str = None):
        """Save detailed performance record"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get proxy ID
        cursor.execute('SELECT id FROM proxies WHERE ip = ? AND port = ?', 
                      (proxy.ip, proxy.port))
        result = cursor.fetchone()
        if result:
            proxy_id = result[0]
            cursor.execute('''
                INSERT INTO proxy_performance 
                (proxy_id, domain, success, response_time, status_code, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (proxy_id, domain, success, response_time, status_code, error))
        
        conn.commit()
        conn.close()
    
    def blacklist_proxy(self, proxy: ProxyConfig, reason: str):
        """Blacklist a proxy"""
        self.blacklisted_ips.add(proxy.ip)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO blacklisted_ips (ip, reason) VALUES (?, ?)',
                      (proxy.ip, reason))
        conn.commit()
        conn.close()
        
        # Remove from all pools
        for pool in self.proxy_pools.values():
            if proxy in pool:
                pool.remove(proxy)
        
        if proxy in self.proxies:
            self.proxies.remove(proxy)
        
        logger.warning(f"Blacklisted proxy {proxy.ip}:{proxy.port} - {reason}")
    
    async def health_check_all_proxies(self, test_url: str = "http://httpbin.org/ip"):
        """Perform health check on all proxies"""
        logger.info(f"Starting health check for {len(self.proxies)} proxies")
        
        async def check_proxy(proxy: ProxyConfig):
            try:
                proxy_url = f"{proxy.protocol}://"
                if proxy.username:
                    proxy_url += f"{proxy.username}:{proxy.password}@"
                proxy_url += f"{proxy.ip}:{proxy.port}"
                
                async with aiohttp.ClientSession() as session:
                    start_time = time.time()
                    async with session.get(
                        test_url,
                        proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        response_time = time.time() - start_time
                        success = response.status == 200
                        
                        self.update_proxy_stats(
                            proxy, success, response_time, 
                            urlparse(test_url).netloc, response.status
                        )
                        
                        return proxy, success
            except Exception as e:
                self.update_proxy_stats(
                    proxy, False, 10.0, 
                    urlparse(test_url).netloc, error=str(e)
                )
                return proxy, False
        
        # Run health checks concurrently
        tasks = [check_proxy(proxy) for proxy in self.proxies[:]]
        results = await asyncio.gather(*tasks)
        
        healthy_count = sum(1 for _, success in results if success)
        logger.info(f"Health check complete: {healthy_count}/{len(self.proxies)} proxies healthy")
        
        # Reorganize pools based on health
        self.reorganize_pools()
        
        return results
    
    def reorganize_pools(self):
        """Reorganize proxy pools based on current health scores"""
        # Clear current pools
        for pool in self.proxy_pools:
            self.proxy_pools[pool].clear()
        
        # Redistribute proxies
        for proxy in self.proxies:
            if proxy.ip not in self.blacklisted_ips:
                self.proxy_pools['general'].append(proxy)
                
                # Type-based pools
                if proxy.proxy_type == ProxyType.RESIDENTIAL:
                    self.proxy_pools['residential'].append(proxy)
                elif proxy.proxy_type == ProxyType.DATACENTER:
                    self.proxy_pools['datacenter'].append(proxy)
                elif proxy.proxy_type == ProxyType.MOBILE:
                    self.proxy_pools['mobile'].append(proxy)
                
                # Performance-based pools
                if proxy.health_score > 80:
                    self.proxy_pools['high_performance'].append(proxy)
                elif proxy.health_score < 30:
                    self.proxy_pools['backup'].append(proxy)
    
    def get_statistics(self) -> Dict:
        """Get comprehensive proxy statistics"""
        stats = {
            'total_proxies': len(self.proxies),
            'blacklisted_ips': len(self.blacklisted_ips),
            'pools': {}
        }
        
        for pool_name, pool_proxies in self.proxy_pools.items():
            if pool_proxies:
                stats['pools'][pool_name] = {
                    'count': len(pool_proxies),
                    'avg_health_score': sum(p.health_score for p in pool_proxies) / len(pool_proxies),
                    'avg_success_rate': sum(p.success_rate for p in pool_proxies) / len(pool_proxies),
                    'avg_response_time': sum(p.avg_response_time for p in pool_proxies) / len(pool_proxies)
                }
        
        # Provider statistics
        stats['providers'] = {}
        for provider_name in set(p.provider for p in self.proxies if p.provider):
            provider_proxies = [p for p in self.proxies if p.provider == provider_name]
            stats['providers'][provider_name] = {
                'count': len(provider_proxies),
                'healthy': len([p for p in provider_proxies if p.health_score > 50])
            }
        
        return stats
    
    async def auto_scale_proxy_pool(self, target_healthy_proxies: int = 10):
        """Automatically scale proxy pool based on health"""
        healthy_proxies = [p for p in self.proxies if p.health_score > 50]
        
        if len(healthy_proxies) < target_healthy_proxies:
            logger.info(f"Scaling up proxy pool. Current healthy: {len(healthy_proxies)}, Target: {target_healthy_proxies}")
            
            # Fetch more proxies from providers
            await self.fetch_proxies_from_providers()
            
            # Unblacklist some IPs if needed (with reset)
            if len(healthy_proxies) < target_healthy_proxies // 2:
                self.reset_blacklisted_proxies(limit=5)
    
    def reset_blacklisted_proxies(self, limit: int = 5):
        """Reset some blacklisted proxies for retry"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get oldest blacklisted IPs
        cursor.execute('''
            SELECT ip FROM blacklisted_ips 
            ORDER BY blacklisted_at ASC 
            LIMIT ?
        ''', (limit,))
        
        ips_to_reset = [row[0] for row in cursor.fetchall()]
        
        for ip in ips_to_reset:
            self.blacklisted_ips.discard(ip)
            cursor.execute('DELETE FROM blacklisted_ips WHERE ip = ?', (ip,))
            logger.info(f"Reset blacklisted IP: {ip}")
        
        conn.commit()
        conn.close()
        
        # Reload proxies
        self.load_proxies()

# Example usage
async def test_enhanced_proxy_manager():
    manager = EnhancedProxyManager()
    
    # Initialize with provider configs
    provider_configs = {
        'brightdata': {
            'customer_id': 'your_customer_id',
            'password': 'your_password',
            'zone': 'static'
        },
        'smartproxy': {
            'username': 'your_username',
            'password': 'your_password'
        }
    }
    
    await manager.initialize_providers(provider_configs)
    await manager.fetch_proxies_from_providers()
    
    # Get proxy for specific domain
    proxy = await manager.get_proxy_for_domain('example.com', pool='high_performance')
    print(f"Selected proxy: {proxy.ip}:{proxy.port} (Health: {proxy.health_score})")
    
    # Perform health check
    await manager.health_check_all_proxies()
    
    # Get statistics
    stats = manager.get_statistics()
    print(f"Proxy statistics: {json.dumps(stats, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test_enhanced_proxy_manager())