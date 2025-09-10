from celery import Celery
import os
import asyncio
from datetime import datetime
from intelligent_scraper import IntelligentScraper, ScraperAPI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery
app = Celery('tasks', 
    broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/New_York',
    enable_utc=True,
    task_routes={
        'celery_worker.scrape_county_auctions': {'queue': 'scraping'},
        'celery_worker.scheduled_morning_scan': {'queue': 'scheduled'},
    }
)

# County auction URLs
COUNTY_URLS = {
    'sarasota': [
        'https://www.sarasotaclerk.com/foreclosures',
        'https://www.sarasota.realforeclose.com/',
    ],
    'manatee': [
        'https://www.manateeclerk.com/foreclosure-sales',
        'https://www.manatee.realforeclose.com/',
    ],
    'charlotte': [
        'https://www.charlotteclerk.com/foreclosures',
        'https://www.charlotte.realforeclose.com/',
    ],
    'lee': [
        'https://www.leeclerk.org/foreclosures',
        'https://www.lee.realforeclose.com/',
    ],
    'collier': [
        'https://www.collierclerk.com/foreclosures',
        'https://www.collier.realforeclose.com/',
    ],
    'pinellas': [
        'https://www.pinellasclerk.org/foreclosures',
        'https://www.pinellas.realforeclose.com/',
    ],
    'hillsborough': [
        'https://www.hillsclerk.com/foreclosures',
        'https://www.hillsborough.realforeclose.com/',
    ]
}

@app.task(name='celery_worker.scrape_county_auctions')
def scrape_county_auctions(county_name):
    """Scrape auctions for a specific county"""
    try:
        urls = COUNTY_URLS.get(county_name, [])
        if not urls:
            return {'error': f'No URLs configured for county: {county_name}'}
        
        # Run async scraping in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_scraping():
            scraper_api = ScraperAPI()
            await scraper_api.start()
            
            results = []
            for url in urls:
                result = await scraper_api.scrape_url(url)
                results.append(result)
            
            await scraper_api.stop()
            return results
        
        results = loop.run_until_complete(run_scraping())
        loop.close()
        
        return {
            'county': county_name,
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'success': True
        }
        
    except Exception as e:
        logger.error(f"Error scraping {county_name}: {str(e)}")
        return {
            'county': county_name,
            'error': str(e),
            'success': False
        }

@app.task(name='celery_worker.scheduled_morning_scan')
def scheduled_morning_scan():
    """Scheduled task to scan all counties"""
    results = {}
    for county in COUNTY_URLS.keys():
        task = scrape_county_auctions.delay(county)
        results[county] = task.id
    
    return {
        'scan_time': datetime.now().isoformat(),
        'counties_queued': list(COUNTY_URLS.keys()),
        'task_ids': results
    }

# Beat schedule for periodic tasks
from celery.schedules import crontab

app.conf.beat_schedule = {
    'morning-auction-scan': {
        'task': 'celery_worker.scheduled_morning_scan',
        'schedule': crontab(hour=5, minute=45),  # 5:45 AM daily
    },
}
