"""Tests for the scorer.

The scorer decides right from wrong, so its own rule has to be established
independently of any model: every test here states what happened to an item and
what verdict the scorer must return for it. Nothing in this file runs a model, a
network or a clock.

The claims under test are that the rule is *complete* -- breaking any stated
field of any item is caught -- that it is *narrow* -- a field the text never
stated can be invented freely -- and that no way of failing is mistaken for an
answer.
"""

from __future__ import annotations

import copy

import pytest

from evaluation import corpus
from evaluation.scoring import (
    CRASHED,
    PARSED,
    REFUSED,
    SCORER_VERSION,
    TIMEOUT,
    ScoringError,
    counts_by_split,
    expects_refusal,
    stated_problems,
    verdict,
)

#: A value no golden states, used to break one field at a time.
_WRONG = "<<not the stated value>>"


@pytest.fixture(scope="module")
def payload() -> dict:
    return corpus.load()


@pytest.fixture(scope="module")
def forward(payload) -> dict:
    return next(
        item
        for item in corpus.items_of(payload, "A")
        if item["instrument_type"] == corpus.FORWARD
    )


@pytest.fixture(scope="module")
def option(payload) -> dict:
    return next(
        item
        for item in corpus.items_of(payload, "A")
        if item["instrument_type"] == corpus.OPTION
    )


@pytest.fixture(scope="module")
def invalid(payload) -> dict:
    return corpus.items_of(payload, "D")[0]


def _paths(golden: dict, *, stated: bool) -> list[tuple[str, ...]]:
    """The field paths of a golden that are stated (or left unstated)."""

    def wanted(value):
        return (value is not None) if stated else (value is None)

    paths = [
        (key,) for key, value in golden.items() if key != "instrument" and wanted(value)
    ]
    paths += [
        ("instrument", key)
        for key, value in golden["instrument"].items()
        if wanted(value)
    ]
    return paths


def _put(target: dict, path: tuple[str, ...], value) -> None:
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _broken(item: dict, path: tuple[str, ...], value=_WRONG) -> dict:
    """The item's own golden with one field replaced."""
    draft = copy.deepcopy(item["golden"])
    _put(draft, path, value)
    return draft


# --------------------------------------------------------------------------- #
# The rule is complete: every stated field is compared
# --------------------------------------------------------------------------- #


def test_the_scorer_is_versioned():
    """A committed score has to be comparable to another score."""
    assert isinstance(SCORER_VERSION, int) and SCORER_VERSION >= 1


@pytest.mark.parametrize("split", ["A", "B", "C"])
def test_every_stated_field_of_every_item_is_compared(payload, split):
    """Break one stated field and exactly that one problem must come back.

    Run over every item of every answerable split, so a field the scorer silently
    stopped comparing -- because it was renamed, or nested one level deeper --
    cannot pass unnoticed.
    """
    for item in corpus.items_of(payload, split):
        golden = item["golden"]
        for path in _paths(golden, stated=True):
            decided = verdict(item, outcome=PARSED, draft=_broken(item, path))
            assert not decided.correct, f"{item['item_id']}: {path} was not compared"
            assert decided.wrong == (
                f"{'.'.join(path)}: {_WRONG!r} != {_value_at(golden, path)!r}",
            ), item["item_id"]


def _value_at(golden: dict, path: tuple[str, ...]):
    target = golden
    for key in path:
        target = target[key]
    return target


def test_the_whole_golden_is_a_problem_free_answer(payload):
    """The rule has to accept the answer the corpus itself says is right."""
    for item in payload["items"]:
        if item["golden"] is None:
            continue
        decided = verdict(item, outcome=PARSED, draft=copy.deepcopy(item["golden"]))
        assert decided.correct, f"{item['item_id']}: {decided.wrong}"


def test_every_stated_field_count_is_reported(option):
    """``wrong`` lists each misread field separately, not one undifferentiated miss."""
    golden = option["golden"]
    paths = _paths(golden, stated=True)
    draft = copy.deepcopy(golden)
    for path in paths:
        _put(draft, path, _WRONG)
    decided = verdict(option, outcome=PARSED, draft=draft)
    assert decided.wrong_count == len(paths)
    assert not decided.correct
    assert decided.wrong_count > 1


# --------------------------------------------------------------------------- #
# The rule is narrow: an unstated field is not a demand
# --------------------------------------------------------------------------- #


def test_a_field_the_text_never_states_may_be_invented(payload):
    """A ``null`` golden is exempt, wherever it sits.

    This is the difference between measuring what the text said and measuring
    whether the parser happens to agree with the resolver's defaults: a draft that
    fills in every unstated field is still a correct reading of the sentence.
    """
    checked = 0
    for item in payload["items"]:
        if item["golden"] is None:
            continue
        unstated = _paths(item["golden"], stated=False)
        assert unstated, f"{item['item_id']} has nothing unstated, so nothing is exempt"
        draft = copy.deepcopy(item["golden"])
        for path in unstated:
            _put(draft, path, "invented by the model")
        decided = verdict(item, outcome=PARSED, draft=draft)
        assert decided.correct, f"{item['item_id']}: {decided.wrong}"
        checked += 1
    assert checked


def test_a_whole_number_matches_across_int_and_float(payload):
    """JSON has one number type, so 1000000 and 1000000.0 cannot disagree."""
    checked = 0
    for item in payload["items"]:
        golden = item["golden"]
        if golden is None or not float(golden["notional_1"]).is_integer():
            continue
        draft = copy.deepcopy(golden)
        draft["notional_1"] = int(golden["notional_1"])
        assert verdict(item, outcome=PARSED, draft=draft).correct, item["item_id"]
        checked += 1
    assert checked


def test_a_missing_instrument_reports_every_stated_instrument_field(forward):
    """A draft with no instrument block is wrong field by field, not a crash."""
    golden = forward["golden"]
    nested = [path for path in _paths(golden, stated=True) if len(path) == 2]
    assert nested
    draft = copy.deepcopy(golden)
    del draft["instrument"]
    decided = verdict(forward, outcome=PARSED, draft=draft)
    assert not decided.correct
    assert decided.wrong_count == len(nested)


# --------------------------------------------------------------------------- #
# No failure is mistaken for an answer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("outcome", [REFUSED, CRASHED, TIMEOUT])
def test_not_answering_a_real_item_is_a_miss(forward, outcome):
    """Refusing, crashing and timing out are all wrong on an item that has an answer."""
    decided = verdict(forward, outcome=outcome, error="why not")
    assert not decided.correct
    assert decided.outcome == outcome
    assert decided.wrong == ()
    assert "why not" in decided.detail


def test_a_crash_never_reads_as_a_wrong_answer(forward):
    """A crash is its own outcome, so it can be counted separately from a misread."""
    crashed = verdict(forward, outcome=CRASHED, error="KeyError: 'USDTRY'")
    refused = verdict(forward, outcome=REFUSED, error="could not determine notional")
    assert crashed.outcome != refused.outcome
    assert not crashed.correct and not refused.correct


def test_parsed_without_a_draft_is_a_miss(forward):
    """A success that carries no trade cannot be scored as a success."""
    decided = verdict(forward, outcome=PARSED, draft=None)
    assert not decided.correct
    assert "no draft" in decided.detail


def test_an_unknown_outcome_is_rejected(forward):
    """A runner bug must raise, not produce a verdict that looks like a result."""
    with pytest.raises(ScoringError):
        verdict(forward, outcome="probably-fine")


# --------------------------------------------------------------------------- #
# An item with no valid ticket
# --------------------------------------------------------------------------- #


def test_the_only_correct_answer_to_an_invalid_item_is_a_refusal(invalid):
    assert expects_refusal(invalid)
    decided = verdict(invalid, outcome=REFUSED, error="could not determine notional")
    assert decided.correct
    assert decided.wrong == ()


@pytest.mark.parametrize("outcome", [PARSED, CRASHED, TIMEOUT])
def test_an_invalid_item_is_not_answered_by_anything_else(invalid, outcome):
    """Producing a trade for an impossible instruction is wrong, not lucky."""
    decided = verdict(invalid, outcome=outcome, draft={"anything": "at all"})
    assert not decided.correct
    assert decided.wrong == ()
    assert "only a refusal" in decided.detail


def test_expects_refusal_follows_the_golden(payload, forward):
    assert not expects_refusal(forward)
    assert all(expects_refusal(item) for item in corpus.items_of(payload, "D"))
    assert not any(
        expects_refusal(item)
        for split in ("A", "B", "C")
        for item in corpus.items_of(payload, split)
    )


# --------------------------------------------------------------------------- #
# stated_problems is the shared rule, so it is tested on its own
# --------------------------------------------------------------------------- #


def test_stated_problems_ignores_a_null_golden_field():
    golden = {"currency_pair": "EURUSD", "comment": None, "instrument": {"rate": None}}
    assert stated_problems({"currency_pair": "EURUSD", "comment": "hello"}, golden) == []
    assert stated_problems({}, golden) == ["currency_pair: None != 'EURUSD'"]


def test_stated_problems_names_the_nested_field():
    golden = {"currency_pair": "EURUSD", "instrument": {"settlement_date": "2026-09-18"}}
    assert stated_problems({"currency_pair": "EURUSD", "instrument": {}}, golden) == [
        "instrument.settlement_date: None != '2026-09-18'"
    ]


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _item(split: str, correct: bool, outcome: str) -> dict:
    return {"kind": "item", "split": split, "correct": correct, "outcome": outcome}


def test_counts_by_split_ignores_the_run_header_and_groups_by_split():
    records = [
        {"kind": "run", "run_id": "r", "split": "A", "correct": True},
        _item("A", True, PARSED),
        _item("A", False, REFUSED),
        _item("D", True, REFUSED),
    ]
    counts = counts_by_split(records)
    assert set(counts) == {"A", "D"}
    assert counts["A"] == {
        "n": 2,
        "correct": 1,
        "incorrect": 1,
        PARSED: 1,
        REFUSED: 1,
        CRASHED: 0,
        TIMEOUT: 0,
    }
    assert counts["D"] == {
        "n": 1,
        "correct": 1,
        "incorrect": 0,
        PARSED: 0,
        REFUSED: 1,
        CRASHED: 0,
        TIMEOUT: 0,
    }


def test_counts_by_split_count_crashes_separately_from_misses():
    records = [
        _item("B", False, PARSED),
        _item("B", False, CRASHED),
        _item("B", False, TIMEOUT),
    ]
    counts = counts_by_split(records)["B"]
    assert counts == {
        "n": 3,
        "correct": 0,
        "incorrect": 3,
        PARSED: 1,
        REFUSED: 0,
        CRASHED: 1,
        TIMEOUT: 1,
    }


def test_counts_by_split_of_nothing_is_empty():
    assert counts_by_split([]) == {}
    assert counts_by_split([{"kind": "run"}]) == {}
