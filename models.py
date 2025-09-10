from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

class AuctionProperty(Base):
    __tablename__ = 'auction_properties'
    
    id = Column(Integer, primary_key=True)
    case_number = Column(String(50), unique=True, index=True)
    address = Column(String(200))
    city = Column(String(100))
    county = Column(String(50), index=True)
    state = Column(String(2), default='FL')
    zip_code = Column(String(10))
    auction_date = Column(DateTime, index=True)
    starting_bid = Column(Float)
    assessed_value = Column(Float)
    estimated_arv = Column(Float)
    sqft = Column(Integer)
    bedrooms = Column(Integer)
    bathrooms = Column(Float)
    year_built = Column(Integer)
    property_type = Column(String(50))
    status = Column(String(20), default='active')
    scraped_at = Column(DateTime, default=datetime.now)
    source_url = Column(String(500))
    raw_data = Column(Text)  # Store raw HTML/JSON
    
    def to_dict(self):
        return {
            'id': self.id,
            'case_number': self.case_number,
            'address': self.address,
            'city': self.city,
            'county': self.county,
            'auction_date': self.auction_date.isoformat() if self.auction_date else None,
            'starting_bid': self.starting_bid,
            'estimated_arv': self.estimated_arv,
            'profit_potential': (self.estimated_arv * 0.65 - self.starting_bid) if self.estimated_arv and self.starting_bid else None
        }

class ScrapeJob(Base):
    __tablename__ = 'scrape_jobs'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String(100), unique=True)
    county = Column(String(50))
    status = Column(String(20))
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime)
    properties_found = Column(Integer, default=0)
    errors = Column(Text)
    
# Database setup
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///auction_data.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)
