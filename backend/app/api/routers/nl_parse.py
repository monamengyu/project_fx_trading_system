"""NL trade entry endpoint: parse plain-English instructions into a validated trade."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.nl_parse.models import available_models
from app.services.nl_parse.parser import ParseError, parse_trade

router = APIRouter(prefix="/nl-parse", tags=["nl-parse"])


class NLParseRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str = "rule-based"


class NLParseResponse(BaseModel):
    model: str
    draft: dict[str, Any]
    trade: dict[str, Any]
    raw: dict[str, Any] | None = None


@router.get("/models")
async def list_models() -> list[dict[str, str]]:
    """Models selectable for NL parsing (baseline always; LLMs when keyed)."""
    return [
        {"id": m.id, "label": m.label, "kind": m.kind} for m in available_models()
    ]


@router.post("", response_model=NLParseResponse)
async def parse_natural_language(req: NLParseRequest) -> NLParseResponse:
    try:
        result = await parse_trade(req.text, req.model)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc  # unknown model
    except Exception as exc:  # upstream LLM/network failure
        raise HTTPException(status_code=502, detail=f"parsing failed: {exc}") from exc

    return NLParseResponse(
        model=result.model,
        draft=result.draft.model_dump(mode="json"),
        trade=result.trade.model_dump(mode="json"),
        raw=result.raw,
    )
