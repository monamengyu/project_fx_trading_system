from datetime import date
from typing import List

from pydantic import BaseModel


class RateResponse(BaseModel):
    pair: str
    rate: float
    as_of: date


class PairsResponse(BaseModel):
    pairs: List[str]
