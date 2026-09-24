"""Exit tests for the corpus.

The corpus is the measuring instrument of the whole evaluation, so its own
correctness has to be established before any model is run against it. These
tests prove four independent things:

* it is frozen -- the committed file is what the code builds, and an edit to it
  is detected rather than silently measured against;
* it says what it means -- every rendered sentence reads back as its golden, and
  the dates a convention supplies are stated rather than left null, so a wrong
  score cannot be blamed on the labels;
* the familiar arm is answerable -- the rule-based baseline reproduces it
  exactly, which makes the baseline the floor a model has to beat;
* the shifted and invalid arms bite -- no shifted item is accidentally already
  correct, and no invalid item is accidentally parseable.

Nothing here needs a network, a model, or a token.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import date

import pytest

from app.models.enums import Currency, CurrencyPair
from app.schemas.trade import TradeCreate
from app.services import business_calendar
from app.services.nl_parse.baseline import ParseError, parse_rule_based
from app.services.nl_parse.parser import parse_trade, resolve_draft
from app.services.nl_parse.schemas import NLTradeDraft
from evaluation import corpus
from evaluation.frozen_rates import FrozenRateProvider
from evaluation.scoring import stated_problems

FAMILIAR = ("A", "B")
VALID = ("A", "B", "C")

#: Where each way of being unsalvageable is caught, as a fragment of the message.
#: Pinning the reason keeps the split honest: an item that starts failing for a
#: different reason has stopped measuring what its ``reason`` claims.
_REFUSAL_FRAGMENTS = {
    "missing_pair": "could not determine currency pair",
    "missing_direction": "could not determine direction",
    "unsupported_pair": "could not determine currency pair",
    "option_missing_expiry": "option is missing an expiry date",
    "vague_notional": "could not determine notional",
    "missing_notional": "could not determine notional",
    "nonpositive_notional": "notional_1",
    "past_settlement_forward": "settlement",
}


@pytest.fixture(autouse=True)
def pinned_clock():
    """Pin the trade date for every test in this module.

    Every date in the corpus is stated relative to ``corpus.TRADE_DATE``, and the
    parser reads the ambient trade date, so a test that forgets to pin it would
    compare two different weeks and blame the corpus.
    """
    with business_calendar.override_trade_date(corpus.TRADE_DATE):
        yield


@pytest.fixture(scope="module")
def snapshot() -> FrozenRateProvider:
    return FrozenRateProvider.from_file()


@pytest.fixture(scope="module")
def payload() -> dict:
    return corpus.load()


def _draft(value: dict) -> dict:
    """A draft dict as JSON, so dates and floats compare by value."""
    return NLTradeDraft.model_validate(value).model_dump(mode="json")


def _key(golden: dict) -> str:
    return json.dumps(golden, sort_keys=True)


# --------------------------------------------------------------------------- #
# Frozen: the file is the build, and an edit is noticed
# --------------------------------------------------------------------------- #


def test_committed_corpus_is_the_current_build(payload, snapshot):
    """The file on disk equals what the code builds, byte for byte."""
    rebuilt = corpus.build(snapshot)
    assert rebuilt == payload

    fresh = corpus.dumps(rebuilt)
    on_disk = corpus.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8")
    assert on_disk == fresh, "corpus.json is stale; run `python -m evaluation.corpus`"

    # The layout is assembled by hand, so prove it reads back as the payload,
    # and that a cell holds one line rather than the four an indented
    # two-element list takes.
    assert json.loads(fresh) == payload
    block = fresh.partition('"cells": [')[2].partition("\n  ],")[0]
    rows = [row.strip().removesuffix(",") for row in block.strip().splitlines()]
    assert rows == [json.dumps(cell) for cell in rebuilt["cells"]]


def test_rebuild_is_deterministic(snapshot):
    """The build is deterministic, so a change to the code or data is noticed."""
    assert corpus.build(snapshot) == corpus.build(snapshot)


def test_digest_covers_every_field(payload):
    """No field can change without the digest changing."""
    # The digest is the value the file must carry, and it is canonical: how the
    # file is laid out cannot move it, only a different value can.
    assert corpus.digest(payload) == payload["corpus_sha256"]
    assert corpus.digest(json.loads(json.dumps(payload, indent=4))) == corpus.digest(payload)
    
    mutations = {
        "text": lambda p: p["items"][0].__setitem__("text", p["items"][0]["text"] + " "),
        "golden": lambda p: p["items"][0]["golden"].__setitem__("notional_1", 1.0),
        "capability": lambda p: p["items"][0].__setitem__("capability", "pair_words"),
        "pair_id": lambda p: p["items"][120].__setitem__("pair_id", "P-999"),
        "reason": lambda p: p["items"][-1].__setitem__("reason", "missing_pair"),
        "split": lambda p: p["items"][0].__setitem__("split", "B"),
        "variant": lambda p: p["items"][200].__setitem__("variant", "nonsense"),
        "trade_date": lambda p: p.__setitem__("trade_date", "2026-09-12"),
        "counts": lambda p: p["counts"].__setitem__("A", 121),
        "cells": lambda p: p["cells"][0].__setitem__(0, "pair_code"),
        "item_names": lambda p: p["items"][0].__setitem__("item_id", "A-999"),
        "drop": lambda p: p["items"].pop(),
    }
    original = corpus.digest(payload)
    for label, mutate in mutations.items():
        clone = copy.deepcopy(payload)
        mutate(clone)
        assert corpus.digest(clone) != original, f"a change to {label} went unnoticed"


def test_a_hand_edited_file_is_rejected(payload, tmp_path):
    """Tampering with the file fails the load instead of skewing a measurement."""
    tampered = copy.deepcopy(payload)
    tampered["items"][0]["golden"]["currency_pair"] = "GBPUSD"
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(tampered, indent=2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(corpus.CorpusError, match="does not match its own digest"):
        corpus.load(path)

    stripped = copy.deepcopy(payload)
    del stripped["corpus_sha256"]
    path.write_text(json.dumps(stripped, indent=2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(corpus.CorpusError, match="no corpus_sha256"):
        corpus.load(path)


# --------------------------------------------------------------------------- #
# Shape and composition
# --------------------------------------------------------------------------- #


def test_split_sizes_and_item_ids_are_exact(payload):
    assert payload["counts"] == {"A": 112, "B": 112, "C": 112, "D": 40}

    expected = [
        f"{split}-{index:03d}"
        for split, count in corpus.SPLIT_SIZES.items()
        for index in range(count)
    ]
    assert [item["item_id"] for item in payload["items"]] == expected


def test_a_new_cell_appends_items_without_moving_the_old_ones(monkeypatch, snapshot):
    """Enlarging the cell table adds items; it does not re-draw the corpus.

    Because the sizes follow from the table, one more cell lengthens every split.
    The items already there have to keep their cell, their text and their id, or
    an unrelated addition would silently invalidate a recorded run.
    """
    before = corpus.build(snapshot)
    grown = [*corpus.CELLS, corpus.CELLS[0]]
    monkeypatch.setattr(corpus, "CELLS", grown)
    monkeypatch.setattr(corpus, "SPLIT_SIZES", corpus._sizes_for(len(grown)))
    after = corpus.build(snapshot)

    for split in corpus.REPLICATES:
        kept = corpus.items_of(before, split)
        assert after["counts"][split] == len(kept) + corpus.REPLICATES[split]
        assert corpus.items_of(after, split)[: len(kept)] == kept, (
            f"the {split} items moved when the table grew"
        )
    assert corpus.items_of(after, "D") == corpus.items_of(before, "D")


def test_trade_date_matches_the_snapshot(payload, snapshot):
    assert payload["trade_date"] == corpus.TRADE_DATE.isoformat()
    assert business_calendar.is_business_day(corpus.TRADE_DATE)
    assert {as_of for _, as_of in snapshot.rates.values()} == {corpus.TRADE_DATE}


def test_pools_match_the_enums(snapshot):
    """Enum drift must break the corpus rather than quietly shrink it."""
    assert corpus.PAIRS == [pair.value for pair in CurrencyPair]
    assert set(corpus.PAIRS) == snapshot.pairs
    assert set(corpus.CURRENCY_WORDS) == {currency.value for currency in Currency}

    words = list(corpus.CURRENCY_WORDS.values())
    assert len(set(words)) == len(words), "two currencies share a spoken name"


def test_cells_and_tags_cover_the_design(payload):
    assert len(corpus.CELLS) == 28
    assert len(set(corpus.CELLS)) == 28
    assert len(corpus.CAPABILITIES) == 11
    assert len(set(corpus.CAPABILITIES)) == 11, "a tag with two cells is still one tag"
    assert set(corpus.CAPABILITIES) == {capability for capability, _ in corpus.CELLS}
    assert [capability for capability, _ in corpus.CELLS[:3]] == [
        "tenor_form",
        "date_written",
        "option_terms",
    ]

    used = Counter(
        (item["capability"], item["instrument_type"]) for item in payload["items"]
    )
    for cell, count in used.items():
        if cell[0] == corpus.NO_VALID_TICKET:
            assert cell == (corpus.NO_VALID_TICKET, None)
            assert count == corpus.SPLIT_SIZES["D"]
        else:
            assert cell in set(corpus.CELLS), f"{cell} is not a designed cell"
    for cell in corpus.CELLS:
        assert used[cell] > 0, f"{cell} is designed but never used"

    # Round-robin over 27 cells leaves every cell within one instance of the
    # others, so no capability is measured on a handful of items.
    per_split = {
        split: Counter(
            (item["capability"], item["instrument_type"])
            for item in corpus.items_of(payload, split)
        )
        for split in VALID
    }
    for split, counts in per_split.items():
        assert max(counts.values()) - min(counts.values()) <= 1, split


def test_twins_are_symmetric_and_identical(payload):
    """``B[i]`` and ``C[i]`` are one ticket said two ways."""
    by_id: dict[str, list[dict]] = {}
    for item in payload["items"]:
        if item["pair_id"] is not None:
            by_id.setdefault(item["pair_id"], []).append(item)

    assert len(by_id) == corpus.SPLIT_SIZES["B"] == corpus.SPLIT_SIZES["C"]
    for pair_id, pair in by_id.items():
        assert len(pair) == 2, f"{pair_id} has {len(pair)} items"
        left, right = pair
        assert {left["split"], right["split"]} == {"B", "C"}
        left_index = left["item_id"].split("-")[1]
        assert left_index == right["item_id"].split("-")[1]
        assert left["golden"] == right["golden"], pair_id
        assert left["capability"] == right["capability"]
        assert left["instrument_type"] == right["instrument_type"]
        assert left["text"] != right["text"], f"{pair_id} is not said differently"

    for item in payload["items"]:
        if item["split"] not in ("B", "C"):
            assert item["pair_id"] is None, item["item_id"]


def test_only_valid_items_carry_a_golden(payload):
    for item in payload["items"]:
        if item["split"] == "D":
            assert item["golden"] is None
            assert item["reason"] in corpus._D_KIND_NAMES
            assert item["variant"] is None
        else:
            assert item["golden"] is not None
            assert item["reason"] is None
            assert item["variant"], item["item_id"]


def test_familiar_items_use_familiar_spellings(payload):
    """The arms that must be answerable say only what the rules already read.

    ``variant`` is the record of which spelling an item was rendered with, so the
    familiar arms saying ``familiar`` is what makes them a floor rather than a
    second shifted arm.
    """
    for split in FAMILIAR:
        for item in corpus.items_of(payload, split):
            assert item["variant"].split()[0] == "familiar", item["item_id"]


def test_every_shifted_spelling_is_exercised(payload):
    """A spelling no item uses is a claim the corpus does not actually test.

    Each shifted item carries the ``variant`` it was rendered with, so this checks
    the rotation really happens: a tag with more spellings than its cell has items
    leaves the surplus declared but never measured.
    """
    assert set(corpus._SHIFTED_SPELLINGS) == set(corpus.CAPABILITIES), (
        "a tag declares no shifted spellings, or a spelling has no tag"
    )
    for capability, spellings in corpus._SHIFTED_SPELLINGS.items():
        assert len(set(spellings)) == len(spellings), f"{capability} repeats itself"

    shifted = corpus.items_of(payload, "C")
    for capability, spellings in corpus._SHIFTED_SPELLINGS.items():
        used = {
            item["variant"].split()[0]
            for item in shifted
            if item["capability"] == capability
        }
        missing = set(spellings) - used
        assert not missing, f"{capability} declares unused spellings: {sorted(missing)}"


def test_invalid_items_cover_every_kind_equally(payload):
    reasons = Counter(item["reason"] for item in corpus.items_of(payload, "D"))
    assert set(reasons) == set(corpus._D_KIND_NAMES)
    assert set(reasons.values()) == {corpus.SPLIT_SIZES["D"] // len(reasons)}


def test_familiar_and_shifted_pools_share_no_ticket(payload):
    """A familiar answer is never the answer to a shifted item.

    ``A`` and ``C`` have to be disjoint tickets, otherwise the familiar arm
    contains the shifted arm's answer and the comparison is meaningless. ``B``
    and ``C`` are deliberately the same 112 tickets said two ways, so for them
    the overlap must be exactly the pairs, item by item.
    """
    a = {_key(item["golden"]): item["item_id"] for item in corpus.items_of(payload, "A")}
    b = {_key(item["golden"]): item["item_id"] for item in corpus.items_of(payload, "B")}
    c = {_key(item["golden"]): item["item_id"] for item in corpus.items_of(payload, "C")}

    assert len(a) == corpus.SPLIT_SIZES["A"], "the A pool repeats a ticket"
    assert len(b) == corpus.SPLIT_SIZES["B"], "the B pool repeats a ticket"
    assert not set(a) & set(c), "a shifted item reuses a familiar answer"

    shared = set(b) & set(c)
    assert len(shared) == corpus.SPLIT_SIZES["B"]
    for golden in shared:
        assert b[golden].split("-")[1] == c[golden].split("-")[1]


# --------------------------------------------------------------------------- #
# The labels describe the text
# --------------------------------------------------------------------------- #


def test_every_rendered_sentence_reads_back_as_its_golden(payload):
    """The round-trip invariant: text and golden cannot silently disagree."""
    for item in payload["items"]:
        if item["golden"] is None:
            continue
        assert corpus.read_ticket(item["text"]) == item["golden"], item["item_id"]


def test_an_option_states_a_delivery_and_no_settlement(payload):
    """The option convention: a delivery two business days past expiry, no settlement."""
    for item in payload["items"]:
        if item["instrument_type"] != "OPTION" or item["golden"] is None:
            continue
        instrument = item["golden"]["instrument"]
        expiry = date.fromisoformat(instrument["expiry_date"])
        assert instrument["settlement_date"] is None
        assert (
            instrument["delivery_date"]
            == business_calendar.add_business_days(expiry, 2).isoformat()
        )


def test_goldens_are_exact_drafts(payload):
    """A golden has the draft's fields and nothing else."""
    for item in payload["items"]:
        golden = item["golden"]
        if golden is None:
            continue
        assert _draft(golden) == golden, item["item_id"]


async def test_every_golden_resolves_to_a_valid_trade(payload, snapshot):
    """The corpus only asks for trades the application actually accepts."""
    for item in payload["items"]:
        golden = item["golden"]
        if golden is None:
            continue
        resolved = await resolve_draft(
            NLTradeDraft.model_validate(golden), rate_provider=snapshot
        )
        assert isinstance(resolved.trade, TradeCreate), item["item_id"]
        assert resolved.trade.instrument_type == item["instrument_type"]


# --------------------------------------------------------------------------- #
# The arms behave as designed
# --------------------------------------------------------------------------- #


def test_baseline_reproduces_every_familiar_item(payload):
    """Familiar means the rules already get it right, so they are the floor."""
    for split in FAMILIAR:
        for item in corpus.items_of(payload, split):
            produced = _draft(parse_rule_based(item["text"]))
            problems = stated_problems(produced, item["golden"])
            assert not problems, f"{item['item_id']}: {problems}"


async def test_baseline_accepts_every_familiar_item_end_to_end(payload, snapshot):
    """Passing the draft schema is not enough; the trade has to book."""
    for split in FAMILIAR:
        for item in corpus.items_of(payload, split):
            result = await parse_trade(item["text"], "rule-based", rate_provider=snapshot)
            assert result.trade.currency_pair == item["golden"]["currency_pair"]


def test_every_shifted_item_is_detectably_wrong(payload):
    """Each shifted phrasing either is refused or misstates a stated field."""
    for item in corpus.items_of(payload, "C"):
        try:
            produced = _draft(parse_rule_based(item["text"]))
        except ParseError:
            continue
        problems = stated_problems(produced, item["golden"])
        assert problems, f"{item['item_id']} is shifted but still parsed correctly"


async def test_every_invalid_item_is_refused_for_the_stated_reason(payload, snapshot):
    """A ``D`` item is only valid corpus data if the refusal is the intended one."""
    for item in corpus.items_of(payload, "D"):
        with pytest.raises(ParseError) as caught:
            await parse_trade(item["text"], "rule-based", rate_provider=snapshot)
        fragment = _REFUSAL_FRAGMENTS[item["reason"]]
        assert fragment in str(caught.value), (
            f"{item['item_id']} ({item['reason']}): {caught.value}"
        )
