"""The runner: play the corpus against one model and record what happened.

The runner is the only part of the evaluation that touches a model, and it does
as little thinking as possible. It asks the same parser the API asks (through
:func:`parse_trade`), one item at a time, and writes down what came back: the
outcome, the trade if there was one, the tokens, the dollars and the wall-clock
time. It does not decide whether an answer was good -- that is
:mod:`evaluation.scoring` -- and it never discards a failure. A crash is
recorded as a crash, so a run that is only half measured cannot pass for a run
that scored half.

Two things make a recorded run replayable
-----------------------------------------
*The trade date is pinned.* Every date in the corpus is relative to
``corpus.TRADE_DATE``, but the parser reads the ambient date, so the same text
resolves differently a week later. The runner holds
``business_calendar.override_trade_date(TRADE_DATE)`` for the whole run, which
also freezes the system prompt, since that prompt states today's date.

*The market is frozen.* ``rate_provider`` is always the frozen snapshot rather
than the live rate feed, so a rate quoted at run time cannot move a settlement
date out from under a comparison.

The evidence file
-----------------
``runs.jsonl`` is append-only, one JSON object per line, and it is the only
irreplaceable artifact in the evaluation: every later statistic is derived from
it. The first line of each run is a ``kind: "run"`` header naming the corpus
digest, the git commit, the system-prompt digest and the settings the run used;
the lines after it are one ``kind: "item"`` record each. Re-running a scorer does
not make a new run and must not append one.

Usage::

    cd backend
    python -m evaluation.runner --model rule-based --run-id free-1
    python -m evaluation.runner --model openai/gpt-5.6-luna --run-id r002-gpt56luna --output evaluation/results/runs.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from app.services import business_calendar
from app.services.nl_parse.baseline import ParseError
from app.services.nl_parse.models import ModelInfo, get_model_info
from app.services.nl_parse.parser import parse_trade
from app.services.nl_parse.prompts import build_system_prompt
from evaluation import corpus, scoring
from evaluation.frozen_rates import FrozenRateProvider

#: Bumped whenever the record shape or the run protocol changes, so an old file
#: is never read as if it were written to the current rules.
RUNNER_VERSION = 1

DEFAULT_RESULTS_PATH = Path(__file__).with_name("results") / "runs.jsonl"

#: An item is a single call, so this only has to catch a provider that hangs; it
#: is not a performance target.
DEFAULT_ITEM_TIMEOUT_S = 120.0

KIND_RUN = "run"
KIND_ITEM = "item"


class RunnerError(RuntimeError):
    """A run could not be recorded without corrupting the evidence."""


async def run_model(
    payload: dict,
    model_id: str,
    *,
    run_id: str,
    snapshot: FrozenRateProvider | None = None,
    splits: tuple[str, ...] | None = None,
    limit: int | None = None,
    item_timeout_s: float = DEFAULT_ITEM_TIMEOUT_S,
    notes: str | None = None,
) -> list[dict]:
    """Run ``model_id`` over ``payload`` and return the records, header first.

    ``limit`` caps the items taken per split, for a smoke test or a spend cap; the
    header records it, so a truncated run says so rather than looking small.
    """
    provider = snapshot or FrozenRateProvider.from_file()
    info = get_model_info(model_id)
    wanted = tuple(splits or corpus.SPLIT_SIZES)
    items: list[dict] = []
    for split in wanted:
        selected = corpus.items_of(payload, split)
        items.extend(selected if limit is None else selected[:limit])

    with business_calendar.override_trade_date(corpus.TRADE_DATE):
        records = [_header(payload, info, run_id, wanted, len(items), limit, item_timeout_s, notes)]
        for item in items:
            records.append(
                await _attempt(item, model_id, provider, run_id, item_timeout_s)
            )
    return records


async def _attempt(
    item: dict,
    model_id: str,
    provider: FrozenRateProvider,
    run_id: str,
    item_timeout_s: float,
) -> dict:
    """Call the parser once and record everything it did, including how it failed.

    The trade date is already pinned by :func:`run_model`; this only observes.
    """
    started = time.perf_counter()
    outcome = scoring.PARSED
    draft: dict | None = None
    error: str | None = None
    error_type: str | None = None
    defaulted: list[str] = []
    usage: dict | None = None
    served_model: str | None = None
    raw: dict | None = None

    try:
        result = await asyncio.wait_for(
            parse_trade(item["text"], model_id, rate_provider=provider),
            item_timeout_s,
        )
        draft = result.draft.model_dump(mode="json")
        defaulted = list(result.defaulted_fields)
        usage = result.usage
        served_model = result.served_model
        raw = result.raw
    except TimeoutError:
        outcome = scoring.TIMEOUT
        error_type = "TimeoutError"
        error = f"item did not finish within {item_timeout_s:g}s"
    except ParseError as exc:
        outcome = scoring.REFUSED
        error_type = type(exc).__name__
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        # Anything else is a fault in the system, not an answer from the model --
        # a missing frozen rate, a KeyError from an unhandled draft, a dead
        # provider. It is recorded as a crash so it stays visible in the numbers
        # instead of being counted as a miss.
        outcome = scoring.CRASHED
        error_type = type(exc).__name__
        error = f"{type(exc).__name__}: {exc}"

    decided = scoring.verdict(item, outcome=outcome, draft=draft, error=error)
    return {
        "kind": KIND_ITEM,
        "run_id": run_id,
        "item_id": item["item_id"],
        "split": item["split"],
        "capability": item["capability"],
        "instrument_type": item["instrument_type"],
        "pair_id": item.get("pair_id"),
        "reason": item.get("reason"),
        "outcome": outcome,
        "correct": decided.correct,
        "wrong": list(decided.wrong),
        "detail": decided.detail,
        "error_type": error_type,
        "error": error,
        "defaulted_fields": defaulted,
        "default_count": len(defaulted),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "prompt_tokens": _token_count(usage, "prompt_tokens"),
        "completion_tokens": _token_count(usage, "completion_tokens"),
        "total_tokens": _token_count(usage, "total_tokens"),
        "usd": _usd(usage),
        "served_model": served_model,
        "raw": raw,
    }


def _header(
    payload: dict,
    info: ModelInfo,
    run_id: str,
    splits: tuple[str, ...],
    item_count: int,
    limit: int | None,
    item_timeout_s: float,
    notes: str | None,
) -> dict:
    """The provenance of a run: what was measured, by what, and from which commit.

    Called with the trade date already pinned, so the prompt digest below is the
    prompt the run actually sent.
    """
    git_sha, git_dirty = _git_state()
    return {
        "kind": KIND_RUN,
        "run_id": run_id,
        "runner_version": RUNNER_VERSION,
        "scorer_version": scoring.SCORER_VERSION,
        "model_id": info.id,
        "model_kind": info.kind,
        "provider_model": info.model,
        "corpus_sha256": payload["corpus_sha256"],
        "trade_date": payload["trade_date"],
        "system_prompt_sha256": sha256(
            build_system_prompt().encode("utf-8")
        ).hexdigest(),
        "splits": list(splits),
        "item_limit": limit,
        "item_count": item_count,
        "item_timeout_s": item_timeout_s,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes,
    }


def _token_count(usage: dict | None, key: str) -> int | None:
    value = (usage or {}).get(key)
    return value if isinstance(value, int) else None


def _usd(usage: dict | None) -> float | None:
    """The dollars a reply cost, when the provider states them.

    OpenRouter reports ``cost`` (credits); a local model reports nothing, and an
    unknown cost stays ``None`` rather than becoming a zero that would average in.
    """
    usage = usage or {}
    for key in ("cost", "total_cost"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _git_state() -> tuple[str | None, bool | None]:
    """The commit a run was made from, and whether the tree was dirty.

    ``None`` when git is unavailable: a missing label is better than an invented
    one, since a wrong commit is worse than no commit.
    """
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return sha or None, bool(status.strip())


def write_records(
    records: list[dict], path: Path | str | None = None, *, append: bool = True
) -> Path:
    """Write (or append) records to a JSONL file, merging with what is there.

    Appending refuses a ``run_id`` the file already holds: a duplicated run would
    double-weight itself in every statistic derived from the file.
    """
    target = Path(path or DEFAULT_RESULTS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    if append and target.exists():
        known = {record.get("run_id") for record in read_records(target)}
        clash = sorted(
            {record["run_id"] for record in records if record.get("kind") == KIND_RUN}
            & known
        )
        if clash:
            raise RunnerError(
                f"{target} already holds run {clash[0]!r}; a run is evidence and is "
                "written once. Use a new run_id, or re-score the existing run."
            )
    lines = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    with target.open("a" if append else "w", encoding="utf-8") as handle:
        handle.write(lines)
    return target


def read_records(path: Path | str | None = None) -> list[dict]:
    """Every record in the file, in order, as plain dicts."""
    target = Path(path or DEFAULT_RESULTS_PATH)
    if not target.exists():
        return []
    return [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the corpus against one model.")
    parser.add_argument("--model", required=True, help="a model id from models.py")
    parser.add_argument("--run-id", required=True, help="names this run, once and for all")
    parser.add_argument(
        "--splits",
        default="".join(corpus.SPLIT_SIZES),
        help="which splits to run (default: all)",
    )
    parser.add_argument("--limit", type=int, default=None, help="items per split")
    parser.add_argument("--timeout", type=float, default=DEFAULT_ITEM_TIMEOUT_S)
    parser.add_argument("--output", default=None, help="defaults to results/runs.jsonl")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args(argv)

    payload = corpus.load()
    records = asyncio.run(
        run_model(
            payload,
            args.model,
            run_id=args.run_id,
            splits=tuple(args.splits),
            limit=args.limit,
            item_timeout_s=args.timeout,
            notes=args.notes,
        )
    )
    written = write_records(records, args.output)

    for split, counts in scoring.counts_by_split(records).items():
        print(
            f"{split}: {counts['correct']}/{counts['n']} correct, "
            f"{counts['refused']} refused, {counts['crashed']} crashed, "
            f"{counts['timeout']} timed out"
        )
    print(f"{written}: appended run {args.run_id!r} ({args.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
