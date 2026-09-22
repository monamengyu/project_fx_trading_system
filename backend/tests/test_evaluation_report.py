"""Tests for the report.

Two things are established here: that every figure is checked against
``scoring.counts_by_split`` over the same records, so a report that drifts from the
verdicts it summarises fails here rather than in a written conclusion; and that it
refuses to say more than the file supports -- incomparable runs are not
differenced, an unexplained miss is shown, and a rate with no denominator prints a
dash rather than a zero.
"""

from __future__ import annotations

import io
import shutil
import sys

import pytest

from evaluation import corpus, report, runner, scoring

# --------------------------------------------------------------------------- #
# Building records by hand, to place a fault where it is wanted
# --------------------------------------------------------------------------- #


def _header(run_id: str = "synthetic", **overrides) -> dict:
    header = {
        "kind": runner.KIND_RUN,
        "run_id": run_id,
        "model_id": "rule-based",
        "model_kind": "baseline",
        "provider_model": None,
        "corpus_sha256": "0" * 64,
        "runner_version": runner.RUNNER_VERSION,
        "scorer_version": scoring.SCORER_VERSION,
        "splits": ["A", "B", "C", "D"],
        "item_count": 4,
        "item_limit": None,
        "item_timeout_s": 120.0,
        "started_at": "2026-01-01T00:00:00+00:00",
        "trade_date": "2026-09-11",
        "system_prompt_sha256": "1" * 64,
        "git_sha": "2" * 40,
        "git_dirty": False,
        "notes": None,
    }
    header.update(overrides)
    return header


def _item(
    item_id: str,
    split: str = "A",
    *,
    run_id: str = "synthetic",
    outcome: str = scoring.PARSED,
    correct: bool = True,
    capability: str = "pair_code",
    instrument_type: str = "SPOT",
    wrong: tuple[str, ...] = (),
    **overrides,
) -> dict:
    record = {
        "kind": runner.KIND_ITEM,
        "run_id": run_id,
        "item_id": item_id,
        "split": split,
        "capability": capability,
        "instrument_type": instrument_type,
        "pair_id": None,
        "reason": None,
        "outcome": outcome,
        "correct": correct,
        "wrong": list(wrong),
        "detail": "",
        "error_type": None,
        "error": None,
        "defaulted_fields": [],
        "default_count": 0,
        "latency_ms": 1.0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "usd": None,
        "served_model": None,
        "raw": None,
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------- #
# The evidence file and the default run
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def records() -> list[dict]:
    """The committed ledger, unmodified."""
    return runner.read_records(runner.DEFAULT_RESULTS_PATH)


@pytest.fixture(scope="module")
def baseline(records) -> tuple[dict, list[dict]]:
    return report.select_run(records, "baseline")


def test_a_selection_the_file_does_not_support_is_an_error():
    """An unknown id, no header at all, and a run written twice are all refusals."""
    records = [_header("baseline"), _item("A-000", run_id="baseline")]
    assert report.select_run(records)[0]["run_id"] == "baseline"
    assert report.known_runs(records) == ["baseline"]
    with pytest.raises(report.ReportError, match="no run 'nope'"):
        report.select_run(records, "nope")
    with pytest.raises(report.ReportError, match="no run header"):
        report.select_run([_item("A-000")])
    with pytest.raises(report.ReportError, match="2 headers"):
        report.select_run([_header("dup"), _header("dup")])


def test_items_of_another_run_are_not_counted(records, baseline):
    """Records are gathered by run id, not by position."""
    _, items = baseline
    mixed = [records[0], *items, _header("second"), _item("A-000", run_id="second")]
    _, selected = report.select_run(mixed, "second")
    assert [record["item_id"] for record in selected] == ["A-000"]


# --------------------------------------------------------------------------- #
# Rates
# --------------------------------------------------------------------------- #


def test_a_figure_is_printed_only_when_it_was_measured():
    """Zero items is not zero percent, and nearest rank prints a latency that occurred."""
    assert report.rate(1, 4) == 0.25
    assert report.percent(0.25) == "25.0%"
    assert report.rate(0, 0) is None
    assert report.percent(None) == "-"

    ordered = [1.0, 2.0, 3.0, 4.0]
    assert report.percentile(ordered, 50) == 2.0
    assert report.percentile(ordered, 95) == 4.0
    assert report.percentile([], 50) is None


# --------------------------------------------------------------------------- #
# The baseline, read back
# --------------------------------------------------------------------------- #


def test_the_baseline_reads_back_its_own_shape(baseline):
    """364 items, the corpus digest it names, and nothing self-contradictory in it."""
    header, items = baseline
    assert header["item_count"] == len(items) == 364
    assert header["corpus_sha256"] == corpus.load()["corpus_sha256"]
    assert report.integrity_problems(items) == []


def test_the_split_view_agrees_with_the_scorer(baseline):
    """The drift guard: a report may rearrange the verdicts, never re-decide them."""
    _, items = baseline
    summary = report.split_summary(items)
    counted = scoring.counts_by_split(items)
    assert set(summary) == set(counted)
    for split, row in summary.items():
        assert row["n"] == counted[split]["n"]
        assert row["correct"] == counted[split]["correct"]
        for outcome in scoring.OUTCOMES:
            assert row["outcomes"][outcome] == counted[split][outcome]


def test_the_misses_add_up_to_the_misses(baseline):
    """No miss may hide in a column the report does not print."""
    _, items = baseline
    for row in report.split_summary(items).values():
        assert row["misses"] == (
            row["wrong_values"] + row["missed_refusal"] + row["crashed"] + row["timeout"]
        )


def test_the_familiar_arms_are_exact_and_the_shifted_arm_is_entirely_wrong(baseline):
    """A misread ticket and a denied ticket are separate faults, and both are counted."""
    _, items = baseline
    summary = report.split_summary(items)
    assert (summary["A"]["correct"], summary["B"]["correct"]) == (108, 108)
    assert summary["C"]["correct"] == 0
    assert summary["D"]["correct"] == 40
    shifted = summary["C"]
    assert shifted["wrong_values"] == 26
    assert shifted["missed_refusal"] == 82
    assert shifted["outcomes"][scoring.REFUSED] == 82


def test_the_refusal_arm_holds_only_unsalvageable_sentences(baseline):
    """D is the arm that has no ticket, so every reason there must be present."""
    _, items = baseline
    reasons = report.reason_summary(items)
    assert len(reasons) == 8
    assert all(row["n"] == 5 and row["correct"] == 5 for row in reasons.values())
    assert all(
        record["capability"] == corpus.NO_VALID_TICKET
        for record in items
        if record["split"] == "D"
    )


# --------------------------------------------------------------------------- #
# The corpus geometry the report is built on
# --------------------------------------------------------------------------- #


def test_the_two_tables_cover_the_whole_design(baseline):
    """Cells and capabilities are all present, with a gap where nothing was run."""
    _, items = baseline
    cells = report.cell_summary(items)
    assert set(cells) == set(corpus.CELLS)
    for per_split in cells.values():
        assert set(per_split) == set(report.CELL_SPLITS)
        assert all(row["n"] == corpus.REPLICATES[split] for split, row in per_split.items())

    summary = report.capability_summary([_item("A-000")])
    assert set(summary) == set(corpus.CAPABILITIES)
    assert summary["pair_code"]["A"]["n"] == 1
    assert summary["direction_verb"]["A"]["n"] == 0
    assert summary["direction_verb"]["A"]["accuracy"] is None


def test_the_shift_is_reported_worst_first(baseline):
    _, items = baseline
    rows = report.contrast(items)
    assert [row["capability"] for row in rows] != []
    drops = [row["drop"] for row in rows]
    assert drops == sorted(drops), "a tag that lost less must not be printed above one that lost more"





# --------------------------------------------------------------------------- #
# Reading the misses
# --------------------------------------------------------------------------- #


def test_both_spellings_of_a_misread_field_are_kept_apart(baseline):
    """The corpus states a field at two levels; the two lines are one defect twice."""
    _, items = baseline
    tally = report.field_tally(items)
    assert tally["instrument_type: 'SPOT' != 'FORWARD'"] == 5
    assert tally["instrument.instrument_type: 'SPOT' != 'FORWARD'"] == 5
    assert sum(tally.values()) == sum(len(record["wrong"] or []) for record in items)


def test_a_defaulted_field_is_reported_apart_from_the_accuracy(baseline):
    """A high score reached by filling in blank fields measured the defaults."""
    _, items = baseline
    defaults = report.default_summary(items)
    assert defaults["n"] == len(items)
    assert defaults["default_count"] == sum(
        record["default_count"] or 0 for record in items
    )
    assert defaults["default_count"] > 0
    assert defaults["items_with_defaults"] == sum(
        1 for record in items if record["default_count"]
    )
    assert sum(defaults["fields"].values()) == defaults["default_count"]


def test_cost_and_failures_are_read_apart_from_accuracy(baseline):
    """No dollars is not zero dollars, and a refusal is not a provider that died."""
    _, items = baseline
    cost = report.cost_summary(items)
    assert cost["n"] == len(items)
    assert cost["with_tokens"] == 0
    assert cost["total_tokens"] == 0
    assert cost["usd"] is None
    assert cost["latency_n"] == len(items)
    assert cost["latency_p50_ms"] is not None
    assert report.error_summary(items) == {scoring.REFUSED: {"ParseError": 122}}


# --------------------------------------------------------------------------- #
# Faults in the ledger itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "record, expected",
    [
        (_item("A-000", correct=True, wrong=("notional_1: x",)), "wrong field"),
        (_item("A-000", correct=False), "no field to blame"),
        (_item("A-000", outcome="melted"), "unchanged outcome"),
        (
            _item("A-000", outcome=scoring.REFUSED, correct=True, capability="pair_code"),
            "refusal counted as correct",
        ),
        (
            _item("A-000", outcome=scoring.CRASHED, correct=True),
            "crashed counted as correct",
        ),
    ],
)
def test_the_integrity_check_fires_on_a_record_that_contradicts_itself(
    record, expected
):
    problems = report.integrity_problems([record])
    assert len(problems) == 1 and expected in problems[0]


def test_a_sentence_that_was_never_a_ticket_is_not_a_record_fault():
    """Answered instead of refused, with no golden to blame: expected, not a fault."""
    record = _item("D-000", split="D", capability=corpus.NO_VALID_TICKET, correct=False)
    assert report.integrity_problems([record]) == []


def test_an_unexplained_miss_is_shouted_about_in_the_report():
    """The one fault that would otherwise pass silently: wrong, and unexplained."""
    header = _header("synthetic", item_count=1)
    text = report.render(header, [_item("A-000", correct=False)])
    assert "== ledger faults ==" in text
    assert "A-000: parsed, wrong, and no field to blame" in text


# --------------------------------------------------------------------------- #
# Comparing two runs
# --------------------------------------------------------------------------- #


def test_a_run_is_differenced_only_against_a_comparable_run(records):
    """A rate against another corpus is a different measurement, not a change."""
    header, items = report.select_run(records, "baseline")
    assert report.compare_headers(header, header) == []
    same = report.render_contrast(header, items, header, items)
    assert "not comparable" not in same
    assert "+0.0pp" in same

    left, right = _header("left"), _header("right", corpus_sha256="3" * 64)
    problems = report.compare_headers(left, right)
    assert len(problems) == 1 and "corpus_sha256" in problems[0]
    text = report.render_contrast(left, [_item("A-000")], right, [_item("A-000")])
    assert "not comparable, so no difference is taken:" in text


def test_a_shift_is_the_left_run_minus_the_right():
    """Positive means the run being reported is ahead, not the one it is shown against."""
    ahead = [_item("A-000"), _item("A-001")]
    behind = [_item("A-000"), _item("A-001", correct=False)]

    text = report.render_contrast(_header("ahead"), ahead, _header("behind"), behind)
    assert "every shift is the left run minus the right" in text
    assert "+50.0pp" in text

    flipped = report.render_contrast(_header("behind"), behind, _header("ahead"), ahead)
    assert "-50.0pp" in flipped
    assert "+50.0pp" not in flipped


def test_only_a_change_to_how_the_run_was_measured_blocks_a_comparison():
    """The model is the thing being compared; the method is what has to match."""
    later = _header("right", model_id="other", notes="later")
    assert report.compare_headers(_header("left"), later) == []
    rescored = _header("right", scorer_version=2)
    assert "scorer_version" in report.compare_headers(_header("left"), rescored)[0]


# --------------------------------------------------------------------------- #
# The rendered text
# --------------------------------------------------------------------------- #


def test_the_report_names_its_run_and_is_the_same_text_every_time(baseline):
    """Deterministic, so it can be committed and diffed like anything else."""
    header, items = baseline
    expected = dict(corpus.load()["counts"])
    text = report.render(header, items, expected=expected)
    assert text == report.render(header, items, expected=expected)
    assert text.endswith("\n")
    assert "run      baseline" in text
    assert f"sha256 {header['corpus_sha256'][:12]}" in text
    assert "364 items" in text
    assert "108/108" in text
    assert "rule-based (baseline)" in text


def test_a_run_that_did_not_finish_is_not_shown_as_a_score():
    """An empty run is a run to fix, not a run that scored zero."""
    partial = report.render(
        _header("synthetic", item_count=3),
        [_item(f"A-{index:03d}") for index in range(3)],
        expected={"A": 108},
    )
    assert "n/corpus" in partial
    assert "3/108" in partial

    empty = report.render(_header("synthetic", item_count=0), [], expected={"A": 108})
    assert "0/108" in empty
    assert "0.0%" not in empty


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def test_the_command_reports_the_run_in_the_file_it_was_pointed_at(tmp_path, capsys):
    target = tmp_path / "runs.jsonl"
    shutil.copyfile(runner.DEFAULT_RESULTS_PATH, target)
    newest = report.known_runs(runner.read_records(target))[-1]
    assert report.main(["--results", str(target)]) == 0
    written = capsys.readouterr().out
    assert "== accuracy by split ==" in written
    assert "== B against C ==" in written
    assert any(line.split() == ["run", newest] for line in written.splitlines())

    code = report.main(
        ["--results", str(target), "--run-id", "baseline", "--against", "baseline"]
    )
    assert code == 0
    paired = capsys.readouterr().out
    assert "== baseline against baseline ==" in paired
    assert "per-capability shift" in paired


def test_the_command_survives_a_results_path_the_console_cannot_encode(tmp_path, monkeypatch):
    """A checkout can live under a non-ASCII path, and this console is cp1252."""
    nested = tmp_path / "\u6587\u6863"
    nested.mkdir()
    target = nested / "runs.jsonl"
    shutil.copyfile(runner.DEFAULT_RESULTS_PATH, target)

    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    assert report.main(["--results", str(target), "--run-id", "baseline"]) == 0
    out.flush()
    decoded = out.buffer.getvalue().decode("utf-8")
    assert "\u6587\u6863" in decoded
    assert "== accuracy by split ==" in decoded


def test_the_command_says_when_the_corpus_has_moved_on(tmp_path, capsys):
    """A stored run is only readable against the corpus it was taken against."""
    target = tmp_path / "runs.jsonl"
    records = runner.read_records(runner.DEFAULT_RESULTS_PATH)
    stale = report.known_runs(records)[-1]
    for record in records:
        if record.get("kind") == runner.KIND_RUN and record["run_id"] == stale:
            record["corpus_sha256"] = "9" * 64
    runner.write_records(records, target)

    assert report.main(["--results", str(target)]) == 0
    written = capsys.readouterr().out
    assert "per-split targets are omitted" in written
    assert "n/corpus" not in written
    assert "108/108" not in written
