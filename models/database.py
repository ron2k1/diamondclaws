import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import Column, Float, Integer, String, Text, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, unique=True, index=True)
    name = Column(String)
    sector = Column(String)
    current_price = Column(Float)
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    dividend_yield = Column(Float)
    volume = Column(Integer)
    avg_volume = Column(Integer)
    high_52w = Column(Float)
    low_52w = Column(Float)
    price_history = Column(Text)
    description = Column(String)
    last_updated = Column(String)

    # New fundamental columns
    forward_pe = Column(Float, nullable=True)
    trailing_eps = Column(Float, nullable=True)
    forward_eps = Column(Float, nullable=True)
    beta = Column(Float, nullable=True)
    revenue_growth = Column(Float, nullable=True)
    earnings_growth = Column(Float, nullable=True)
    profit_margins = Column(Float, nullable=True)
    short_ratio = Column(Float, nullable=True)
    short_pct_float = Column(Float, nullable=True)
    target_mean_price = Column(Float, nullable=True)
    target_high_price = Column(Float, nullable=True)
    target_low_price = Column(Float, nullable=True)
    analyst_count = Column(Integer, nullable=True)

    # New string columns
    recommendation = Column(String, nullable=True)
    long_description = Column(Text, nullable=True)
    earnings_date = Column(String, nullable=True)
    news_json = Column(Text, nullable=True)

    # Staleness tracking
    fundamentals_updated = Column(String, nullable=True)


_DB_PATH = os.getenv("DIAMONDCLAWS_DB", "data/diamondclaws.db")
DATABASE_URL = f"sqlite:///{_DB_PATH}"
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    # Ensure data directory exists (for Docker volume mounts)
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    # Migration: drop and recreate if new schema detected
    inspector = inspect(engine)
    if inspector.has_table("stocks"):
        existing_cols = {c["name"] for c in inspector.get_columns("stocks")}
        if "fundamentals_updated" not in existing_cols:
            print("Detected schema upgrade - dropping and recreating stocks table...")
            Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    return SessionLocal()


def get_all_stocks() -> List[Dict[str, Any]]:
    with get_db() as db:
        stocks = db.query(Stock).all()
        return [
            {
                "id": s.id,
                "ticker": s.ticker,
                "name": s.name,
                "sector": s.sector,
                "current_price": s.current_price,
                "market_cap": s.market_cap,
                "pe_ratio": s.pe_ratio,
                "dividend_yield": s.dividend_yield,
                "volume": s.volume,
                "high_52w": s.high_52w,
                "low_52w": s.low_52w,
            }
            for s in stocks
        ]


def get_stock_by_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        stock = db.query(Stock).filter(Stock.ticker == ticker.upper()).first()
        if stock:
            return {
                "id": stock.id,
                "ticker": stock.ticker,
                "name": stock.name,
                "sector": stock.sector,
                "current_price": stock.current_price,
                "market_cap": stock.market_cap,
                "pe_ratio": stock.pe_ratio,
                "dividend_yield": stock.dividend_yield,
                "volume": stock.volume,
                "avg_volume": stock.avg_volume,
                "high_52w": stock.high_52w,
                "low_52w": stock.low_52w,
                "price_history": stock.price_history,
                "description": stock.description,
                # New fundamental fields
                "forward_pe": stock.forward_pe,
                "trailing_eps": stock.trailing_eps,
                "forward_eps": stock.forward_eps,
                "beta": stock.beta,
                "revenue_growth": stock.revenue_growth,
                "earnings_growth": stock.earnings_growth,
                "profit_margins": stock.profit_margins,
                "short_ratio": stock.short_ratio,
                "short_pct_float": stock.short_pct_float,
                "target_mean_price": stock.target_mean_price,
                "target_high_price": stock.target_high_price,
                "target_low_price": stock.target_low_price,
                "analyst_count": stock.analyst_count,
                "recommendation": stock.recommendation,
                "long_description": stock.long_description,
                "earnings_date": stock.earnings_date,
                "news_json": stock.news_json,
                "fundamentals_updated": stock.fundamentals_updated,
            }
        return None


def search_stocks(query: str) -> List[Dict[str, Any]]:
    with get_db() as db:
        q = f"%{query}%"
        stocks = (
            db.query(Stock)
            .filter((Stock.ticker.like(q)) | (Stock.name.like(q)))
            .limit(10)
            .all()
        )
        return [
            {"ticker": s.ticker, "name": s.name, "sector": s.sector} for s in stocks
        ]


def get_popular_stocks() -> List[Dict[str, Any]]:
    # Ordered by sector so the UI can group them visually
    sectored = [
        ("Tech",       ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX", "CRM", "ADBE", "PLTR", "SNOW", "CRWD"]),
        ("Finance",    ["JPM", "BAC", "GS", "V", "MA", "BX", "ICE"]),
        ("Healthcare", ["JNJ", "UNH", "LLY", "PFE", "ABBV", "REGN", "BMY"]),
        ("Consumer",   ["WMT", "MCD", "NKE", "HD", "SBUX", "LULU"]),
        ("Energy",     ["XOM", "CVX", "COP", "MPC", "PSX", "OXY"]),
        ("Industrial", ["BA", "CAT", "LMT", "GE", "MMM"]),
        ("Crypto",     ["COIN", "RIOT", "MARA"]),
        ("Meme",       ["GME", "AMC"]),
        ("Fintech",    ["PYPL", "SQ"]),
    ]
    all_tickers = [t for _, tickers in sectored for t in tickers]
    with get_db() as db:
        stock_map = {
            s.ticker: s
            for s in db.query(Stock).filter(Stock.ticker.in_(all_tickers)).all()
        }
    result = []
    for sector, tickers in sectored:
        for t in tickers:
            if t in stock_map:
                s = stock_map[t]
                result.append({"ticker": s.ticker, "name": s.name, "sector": sector})
    return result


def upsert_stock(data: Dict[str, Any]) -> None:
    with get_db() as db:
        ticker = data["ticker"].upper()
        stock = db.query(Stock).filter(Stock.ticker == ticker).first()
        if stock:
            for key, value in data.items():
                if hasattr(stock, key):
                    setattr(stock, key, value)
        else:
            stock = Stock(**data)
            db.add(stock)
        db.commit()
