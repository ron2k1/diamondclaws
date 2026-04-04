from pydantic import BaseModel
from typing import List, Optional


class StockInfo(BaseModel):
    ticker: str
    name: str
    sector: str
    current_price: float
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    volume: Optional[int] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    description: Optional[str] = None


class Persona(BaseModel):
    id: str
    name: str
    description: str
    biases: List[str]
    style: str
    catchphrase: str
    avatar_color: str


class AnalysisRequest(BaseModel):
    ticker: str
    persona_id: str


class ParallelAnalysisRequest(BaseModel):
    ticker: str


class ConsensusAttackRequest(BaseModel):
    ticker: str


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    persona_id: str
    ticker: Optional[str] = None
    messages: List[ChatMessage]


class AnalysisResponse(BaseModel):
    ticker: str
    stock_name: str
    current_price: float
    persona: str
    persona_id: str
    analysis: str
    biases_used: List[str]
    confidence_level: float
    hallucinations: List[str]
    references: List[dict]
    distortions_applied: Optional[List[dict]] = None
    source: Optional[str] = None
    agent_id: Optional[str] = None
    openclaw_model: Optional[str] = None
    stock_data: Optional[dict] = None
