"""Tests for the runner.

Two things are being established here. 
The first is that the rule-based baseline lands exactly where the corpus alone 
said it would -- every familiar item right, every shifted item wrong, every 
invalid item refused -- which is only true if the runner pins the trade date 
and freezes the market, and which makes the runner's own plumbing the thing 
under test rather than the parser.

The second is that nothing a run can do goes unrecorded. The runner touches a
model, so it has to survive a refusal, a crash, a hang and a missing frozen rate
without losing the item: a run that is only partly measured must not look like a
run that scored part marks.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import date
from hashlib import sha256

import pytest

from app.services import business_calendar
from app.services.nl_parse.baseline import ParseError
from app.services.nl_parse.prompts import build_system_prompt
from evaluation import corpus, runner, scoring
from evaluation.frozen_rates import MissingFrozenRate

#: The field names a scored record has to carry, whatever the outcome was.
_RECORD_FIELDS = {
    "kind",
    "run_id",
    "item_id",
    "split",
    "capability",
    "instrument_type",
    "outcome",
    "correct",
    "wrong",
    "detail",
    "error_type",
    "error",
    "defaulted_fields",
    "default_count",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "usd",
    "served_model",
    "raw",
}


@pytest.fixture(scope="module")
def payload() -> dict:
    return corpus.load()


@pytest.fixture(scope="module")
def run(payload) -> list[dict]:
    """One full rule-based run, shared by every test that only reads records.

    Run from a plain fixture rather than on the event loop because the corpus is
    small and offline; nothing here may need a network.
    """
    return asyncio.run(runner.run_model(payload, "rule-based", run_id="rule-based"))


def _items(records: list[dict]) -> list[dict]:
    assert records and records[0]["kind"] == runner.KIND_RUN, "no run header"
    return records[1:]


def _golden_of(item_id: str) -> dict:
    return next(
        item["golden"] for item in corpus.load()["items"] if item["item_id"] == item_id
    )


# --------------------------------------------------------------------------- #
# The calibration the corpus alone predicted
# --------------------------------------------------------------------------- #


def test_the_rule_based_baseline_lands_on_its_calibration(run):
    """A+B exact, C entirely wrong, D entirely refused.

    These four numbers were derived from the corpus alone, before any run
    existed. Reproducing them end to end is what says the runner, the frozen
    snapshot and the pinned date are all doing their jobs.
    """
    counts = scoring.counts_by_split(run)
    assert set(counts) == set(corpus.SPLIT_SIZES)

    for split in ("A", "B"):
        assert counts[split]["n"] == corpus.SPLIT_SIZES[split]
        assert counts[split]["correct"] == corpus.SPLIT_SIZES[split], (
            f"{split} is familiar wording and the rules must reproduce it exactly"
        )

    assert counts["C"]["n"] == corpus.SPLIT_SIZES["C"]
    assert counts["C"]["correct"] == 0, "a shifted item was parsed correctly"

    assert counts["D"]["n"] == corpus.SPLIT_SIZES["D"]
    assert counts["D"]["correct"] == corpus.SPLIT_SIZES["D"]
    assert counts["D"]["refused"] == corpus.SPLIT_SIZES["D"]


def test_nothing_crashed_or_timed_out(run):
    """No fault is hiding inside the calibration above.

    Without this, a crashed item and a wrong item would both just be subtracting
    from ``correct``, and the numbers above would be right for the wrong reason.
    """
    faults = [
        record
        for record in _items(run)
        if record["outcome"] in (scoring.CRASHED, scoring.TIMEOUT)
    ]
    assert not faults, faults[:3]


def test_the_rule_based_baseline_fails_the_shifted_split_both_ways(run):
    """``C`` misses are a mix of refusals and silent misreads, and both count.

    Dealer shorthand (``USD-SGD``, ``3mm``, ``Long``, ``3-month forward``) is not
    in the rule set, so most shifted items are refused outright. The rest are
    read into the wrong answer -- the resolver's silent one-month forward default
    reads plausible and is wrong. Neither is a fault, and a split that reached
    zero one way only would be measuring something narrower than intended.
    """
    counts = scoring.counts_by_split(run)["C"]
    assert counts["n"] == corpus.SPLIT_SIZES["C"]
    assert counts["correct"] == 0
    assert counts[scoring.PARSED] > 0, "the shifted split was never misread, only refused"
    assert counts[scoring.REFUSED] > 0, "the shifted split was never refused, only misread"
    assert counts[scoring.PARSED] + counts[scoring.REFUSED] == counts["n"]
    assert counts[scoring.CRASHED] == 0
    assert counts[scoring.TIMEOUT] == 0


def test_every_shifted_miss_is_attributable_to_a_field_or_a_reason(run):
    """A miss says which field was wrong, or why no answer came -- never just 'wrong'.

    The scorer is not allowed to produce an unexplained zero: the difference
    between "read it as a different trade" and "would not read it at all" is the
    whole point of the split.
    """
    shifted = [record for record in _items(run) if record["split"] == "C"]
    assert shifted
    for record in shifted:
        assert record["detail"], record["item_id"]
        if record["outcome"] == scoring.PARSED:
            assert record["wrong"], record["item_id"]
            golden = _golden_of(record["item_id"])
            for problem in record["wrong"]:
                block, _, field = problem.partition(": ")[0].rpartition(".")
                assert field in (golden if not block else golden["instrument"]), problem
        else:
            assert record["outcome"] == scoring.REFUSED, record["item_id"]
            assert record["error_type"] == "ParseError"
            assert record["error"]


# --------------------------------------------------------------------------- #
# The run pins what has to be pinned
# --------------------------------------------------------------------------- #


def test_the_runner_pins_the_trade_date_over_the_ambient_one(payload):
    """The corpus date wins while the run is in progress, and is not left behind.

    The parser reads the ambient trade date, so an unpinned run would resolve
    every relative date against today and score the corpus as broken.
    """
    ambient = date(2027, 3, 4)
    with business_calendar.override_trade_date(ambient):
        records = asyncio.run(
            runner.run_model(
                payload, "rule-based", run_id="pinned", splits=("A", "B")
            )
        )
        assert business_calendar.current_trade_date() == ambient

    counts = scoring.counts_by_split(records)
    for split in ("A", "B"):
        assert counts[split]["correct"] == corpus.SPLIT_SIZES[split]
    assert business_calendar.current_trade_date() != corpus.TRADE_DATE


def test_the_header_digests_the_prompt_the_run_actually_sent(payload):
    """The system prompt states today's date, so its digest only means something
    if it was taken with the date pinned to the corpus."""
    records = asyncio.run(
        runner.run_model(payload, "rule-based", run_id="prompt", splits=("D",), limit=1)
    )
    with business_calendar.override_trade_date(corpus.TRADE_DATE):
        expected = sha256(build_system_prompt().encode("utf-8")).hexdigest()
    assert records[0]["system_prompt_sha256"] == expected


# --------------------------------------------------------------------------- #
# The header says what was measured and from which code
# --------------------------------------------------------------------------- #


def test_the_header_identifies_the_instrument_the_model_and_the_code(run, payload):
    header = run[0]
    assert header["run_id"] == "rule-based"
    assert header["runner_version"] == runner.RUNNER_VERSION
    assert header["scorer_version"] == scoring.SCORER_VERSION
    assert header["corpus_sha256"] == payload["corpus_sha256"]
    assert header["trade_date"] == corpus.TRADE_DATE.isoformat()
    assert header["model_id"] == "rule-based"
    assert header["model_kind"] == "baseline"
    assert header["splits"] == list(corpus.SPLIT_SIZES)
    assert header["item_limit"] is None
    assert header["item_count"] == sum(corpus.SPLIT_SIZES.values())
    assert header["started_at"].endswith("+00:00")
    assert len(header["system_prompt_sha256"]) == 64
    assert header["git_sha"] is None or len(header["git_sha"]) == 40
    assert header["git_dirty"] in (True, False, None)


def test_every_item_record_carries_the_scored_fields(run):
    for record in _items(run):
        assert _RECORD_FIELDS <= set(record), sorted(_RECORD_FIELDS - set(record))
        assert record["run_id"] == "rule-based"
        assert record["outcome"] in scoring.OUTCOMES
        assert isinstance(record["correct"], bool)
        assert isinstance(record["wrong"], list)
        assert record["default_count"] == len(record["defaulted_fields"])
        assert record["latency_ms"] >= 0
        assert record["item_id"].startswith(record["split"])


def test_the_items_are_recorded_in_corpus_order(run):
    """Deterministic order, so two runs of the file line up for a diff."""
    assert [record["item_id"] for record in _items(run)] == [
        item["item_id"] for item in corpus.load()["items"]
    ]


def test_the_raw_model_output_is_kept_as_evidence(run):
    """A verdict has to be arguable, so the answer it was reached from is kept."""
    answered = [record for record in _items(run) if record["outcome"] == scoring.PARSED]
    assert answered
    for record in answered:
        assert isinstance(record["raw"], dict)
        assert "currency_pair" in record["raw"]


def test_the_baseline_reports_no_tokens_and_no_cost(run):
    """Unreported is ``None``, never zero: a zero would average in as free."""
    for record in _items(run):
        assert record["prompt_tokens"] is None
        assert record["completion_tokens"] is None
        assert record["total_tokens"] is None
        assert record["usd"] is None
        assert record["served_model"] is None


def test_the_defaulting_signal_is_recorded(run):
    """Which fields the resolver had to invent is the only signal available for
    selective prediction, so it has to survive the run."""
    counts = {record["item_id"]: record["default_count"] for record in _items(run)}
    assert counts
    assert all(isinstance(value, int) for value in counts.values())
    assert any(value == 0 for value in counts.values())


# --------------------------------------------------------------------------- #
# Failing loudly
# --------------------------------------------------------------------------- #


def test_a_limited_run_says_so(payload):
    records = asyncio.run(
        runner.run_model(
            payload, "rule-based", run_id="limited", splits=("A", "D"), limit=1
        )
    )
    header = records[0]
    assert header["item_limit"] == 1
    assert header["item_count"] == 2
    assert [record["split"] for record in _items(records)] == ["A", "D"]


def test_an_unknown_model_is_rejected(payload):
    with pytest.raises(ValueError):
        asyncio.run(
            runner.run_model(
                payload, "no-such-model", run_id="x", splits=("A",), limit=1
            )
        )


async def test_a_refusal_is_recorded_as_a_refusal(payload, monkeypatch):
    async def refuse(*args, **kwargs):
        raise ParseError("could not determine currency pair")

    monkeypatch.setattr(runner, "parse_trade", refuse)
    records = await runner.run_model(
        payload, "rule-based", run_id="refusing", splits=("A",), limit=1
    )
    item = _items(records)[0]
    assert item["outcome"] == scoring.REFUSED
    assert item["error_type"] == "ParseError"
    assert item["error"] == "could not determine currency pair"
    assert item["correct"] is False
    assert scoring.counts_by_split(records)["A"]["refused"] == 1


async def test_a_refusal_on_an_impossible_item_is_correct(payload, monkeypatch):
    async def refuse(*args, **kwargs):
        raise ParseError("could not determine notional")

    monkeypatch.setattr(runner, "parse_trade", refuse)
    records = await runner.run_model(
        payload, "rule-based", run_id="refusing-d", splits=("D",), limit=1
    )
    assert _items(records)[0]["correct"] is True


async def test_a_crash_is_recorded_rather_than_swallowed(payload, monkeypatch):
    """An uncaught fault in the parser is the case this exists for."""

    async def crash(*args, **kwargs):
        raise KeyError("USDTRY")

    monkeypatch.setattr(runner, "parse_trade", crash)
    records = await runner.run_model(
        payload, "rule-based", run_id="crashing", splits=("A",), limit=2
    )
    items = _items(records)
    assert [item["outcome"] for item in items] == [scoring.CRASHED, scoring.CRASHED]
    assert items[0]["error_type"] == "KeyError"
    assert "USDTRY" in items[0]["error"]
    assert all(item["correct"] is False for item in items)
    assert scoring.counts_by_split(records)["A"]["crashed"] == 2


async def test_a_missing_frozen_rate_is_a_crash_not_a_miss(payload, monkeypatch):
    """A gap in the instrument is a fault in the measurement, not a model error.

    It has to stay visible: silently scoring it as a miss would report a broken
    snapshot as a parser that cannot parse.
    """

    async def gap(*args, **kwargs):
        raise MissingFrozenRate("no frozen rate for USDTRY")

    monkeypatch.setattr(runner, "parse_trade", gap)
    records = await runner.run_model(
        payload, "rule-based", run_id="gapped", splits=("A",), limit=1
    )
    item = _items(records)[0]
    assert item["outcome"] == scoring.CRASHED
    assert item["error_type"] == "MissingFrozenRate"


async def test_a_hung_item_is_recorded_as_a_timeout(payload, monkeypatch):
    async def hang(*args, **kwargs):
        await asyncio.sleep(10)
        raise AssertionError("the item should have been abandoned")

    monkeypatch.setattr(runner, "parse_trade", hang)
    records = await runner.run_model(
        payload,
        "rule-based",
        run_id="hanging",
        splits=("A",),
        limit=1,
        item_timeout_s=0.05,
    )
    item = _items(records)[0]
    assert item["outcome"] == scoring.TIMEOUT
    assert item["error_type"] == "TimeoutError"
    assert item["correct"] is False
    assert records[0]["item_timeout_s"] == 0.05


async def test_a_timed_out_item_does_not_take_the_run_with_it(payload, monkeypatch):
    """A slow item must cost one record, not the whole run.

    httpx leaves an extra cancel set on the task it was cancelled in, and a
    cancellation that escapes that way cannot be caught and recovered from. When
    it landed on the run's own task the run died on the first slow item and
    wrote nothing at all, so the fix is to keep the deadline's cancel in a task
    of its own. The second item here is what proves the run carried on.
    """
    calls = {"n": 0}

    async def slow_then_refusing(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ParseError("could not determine notional")
        task = asyncio.current_task()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            task.cancel()
            raise

    monkeypatch.setattr(runner, "parse_trade", slow_then_refusing)
    records = await runner.run_model(
        payload,
        "rule-based",
        run_id="slow-first",
        splits=("A",),
        limit=2,
        item_timeout_s=0.05,
    )
    items = _items(records)
    assert [item["outcome"] for item in items] == [scoring.TIMEOUT, scoring.REFUSED]
    assert scoring.counts_by_split(records)["A"][scoring.TIMEOUT] == 1


async def test_an_outer_cancellation_is_not_swallowed(payload, monkeypatch):
    """Someone else cancelling the run is not the same as an item timing out."""

    async def hang(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(runner, "parse_trade", hang)
    task = asyncio.create_task(
        runner.run_model(
            payload,
            "rule-based",
            run_id="cancelled",
            splits=("A",),
            limit=1,
            item_timeout_s=30,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --------------------------------------------------------------------------- #
# The evidence file
# --------------------------------------------------------------------------- #


def test_records_round_trip_through_the_file(payload, tmp_path):
    records = asyncio.run(
        runner.run_model(payload, "rule-based", run_id="round-trip", splits=("D",), limit=2)
    )
    path = runner.write_records(records, tmp_path / "runs.jsonl")
    assert runner.read_records(path) == records
    assert len(path.read_text(encoding="utf-8").splitlines()) == len(records)


def test_a_duplicate_run_id_is_refused(payload, tmp_path):
    """A run is evidence and is written once; a silent duplicate would double
    its weight in every statistic derived from the file."""
    records = asyncio.run(
        runner.run_model(payload, "rule-based", run_id="once", splits=("D",), limit=2)
    )
    path = runner.write_records(records, tmp_path / "runs.jsonl")
    before = runner.read_records(path)

    with pytest.raises(runner.RunnerError):
        runner.write_records(records, path)
    assert runner.read_records(path) == before


def test_a_new_run_appends_to_the_file(payload, tmp_path):
    path = tmp_path / "runs.jsonl"
    first = asyncio.run(
        runner.run_model(payload, "rule-based", run_id="one", splits=("D",), limit=1)
    )
    second = asyncio.run(
        runner.run_model(payload, "rule-based", run_id="two", splits=("D",), limit=1)
    )
    runner.write_records(first, path)
    runner.write_records(second, path)

    stored = runner.read_records(path)
    assert [record["run_id"] for record in stored if record["kind"] == runner.KIND_RUN] == [
        "one",
        "two",
    ]
    assert scoring.counts_by_split(stored)["D"]["n"] == 2


def test_reading_a_file_that_is_not_there_is_empty(tmp_path):
    assert runner.read_records(tmp_path / "absent.jsonl") == []


def test_the_file_is_one_json_object_per_line(run, tmp_path):
    path = runner.write_records(run, tmp_path / "runs.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(run)
    for line, record in zip(lines, run):
        assert json.loads(line) == record


def test_the_runner_module_is_runnable_as_a_command():
    """Every committed run is made from this command, not from a helper."""
    assert callable(runner.main)
    assert runner.DEFAULT_RESULTS_PATH.name == "runs.jsonl"
    assert runner.DEFAULT_RESULTS_PATH.parent.name == "results"


def test_a_copy_of_the_payload_with_fewer_items_still_runs(payload):
    """A payload is data; only the items in it are run."""
    small = copy.deepcopy(payload)
    small["items"] = small["items"][:1]
    records = asyncio.run(runner.run_model(small, "rule-based", run_id="small"))
    assert len(records) == 2
    assert records[0]["item_count"] == 1
