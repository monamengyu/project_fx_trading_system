from datetime import date

from pydantic import BaseModel


class RateResponse(BaseModel):
    pair: str
    rate: float
    as_of: date
