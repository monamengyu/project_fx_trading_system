"""The report: read the evidence file and say what it already shows.

It counts what the runner already recorded: no model is called, no verdict is
computed and no file is written. So a report is never the evidence -- ``runs.jsonl``
is -- and it holds no thresholds: every rate is printed beside its own denominator
and none of them is called good or bad.

Two runs are differenced only when they asked the same questions under the same
rules (:func:`compare_headers`), and the familiar and shifted arms are contrasted
per capability rather than tabulated, because that difference is what the shifted
arm exists to produce.

Usage::

    cd backend
    python3 -m evaluation.report
    python3 -m evaluation.report --run-id baseline
    python3 -m evaluation.report --run-id ollama-llama32-3b
    python3 -m evaluation.report --run-id ollama-qwen25-3b
    python3 -m evaluation.report --run-id ollama-gemma2-2b
    python3 -m evaluation.report --run-id ollama-phi35
    python3 -m evaluation.report --run-id openrouter-gpt56-luna
    python3 -m evaluation.report --run-id openrouter-glm53-flash
    python3 -m evaluation.report --run-id openrouter-deepseek-v4-flash
    python3 -m evaluation.report --run-id openrouter-gemini38-flash
    python3 -m evaluation.report --run-id openrouter-gpt56-luna --against baseline
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

from evaluation import corpus, runner, scoring

KIND_RUN = runner.KIND_RUN
KIND_ITEM = runner.KIND_ITEM

#: The arms contrasted item by item. ``B`` rather than ``A`` because ``B[i]`` and
#: ``C[i]`` are one ticket in two spellings; ``A`` is a second familiar sample.
FAMILIAR_ARM = "B"
SHIFTED_ARM = "C"

#: The splits that walk the cell table.
CELL_SPLITS: tuple[str, ...] = tuple(corpus.REPLICATES)

#: What two runs must agree on before their numbers may be differenced. The model,
#: the notes and the moment it was taken are allowed to differ -- that is what a
#: comparison is about.
COMPARABLE_FIELDS: tuple[str, ...] = (
    "corpus_sha256",
    "runner_version",
    "scorer_version",
    "splits",
)


class ReportError(ValueError):
    """The evidence file cannot be read as a set of runs."""


# --------------------------------------------------------------------------- #
# Reading the file
# --------------------------------------------------------------------------- #


def known_runs(records: list[dict]) -> list[str]:
    """Every run id in the file, in the order the runs were written."""
    return [record["run_id"] for record in records if record.get("kind") == KIND_RUN]


def select_run(
    records: list[dict], run_id: str | None = None
) -> tuple[dict, list[dict]]:
    """The header and the item records of one run.

    ``run_id`` of ``None`` takes the last run written. Two headers claiming the same
    id is an error, not something to resolve: a run is written once.
    """
    headers = [record for record in records if record.get("kind") == KIND_RUN]
    if not headers:
        raise ReportError("the file holds no run header, so nothing has been run yet")
    wanted = run_id or headers[-1]["run_id"]
    found = [header for header in headers if header["run_id"] == wanted]
    if not found:
        raise ReportError(
            f"no run {wanted!r} in the file; it holds {known_runs(records)}"
        )
    if len(found) > 1:
        raise ReportError(f"{len(found)} headers claim run {wanted!r}")
    items = [
        record
        for record in records
        if record.get("kind") == KIND_ITEM and record.get("run_id") == wanted
    ]
    return found[0], items


def compare_headers(left: dict, right: dict) -> list[str]:
    """The reasons two runs cannot be contrasted; empty when they can."""
    return [
        f"{field}: {left.get(field)!r} != {right.get(field)!r}"
        for field in COMPARABLE_FIELDS
        if left.get(field) != right.get(field)
    ]


def integrity_problems(items: list[dict]) -> list[str]:
    """Records that contradict themselves, one line each.

    These cannot happen in a correct run, so a line here is a fault in the ledger
    rather than a result. Sentences that were never a ticket are exempt from the
    blame checks below: they carry no golden to disagree with, so no field can be
    to blame even when the parser answered them.
    """
    problems: list[str] = []
    for record in items:
        item_id = record.get("item_id")
        outcome = record.get("outcome")
        wrong = record.get("wrong") or []
        if outcome not in scoring.OUTCOMES:
            problems.append(f"{item_id}: unchanged outcome {outcome!r}")
        if record.get("correct") and wrong:
            problems.append(f"{item_id}: marked correct with {len(wrong)} wrong field(s)")
        if (
            outcome == scoring.PARSED
            and not record.get("correct")
            and not wrong
            and record.get("capability") != corpus.NO_VALID_TICKET
        ):
            problems.append(f"{item_id}: parsed, wrong, and no field to blame")
        if (
            outcome == scoring.REFUSED
            and record.get("correct")
            and record.get("capability") != corpus.NO_VALID_TICKET
        ):
            problems.append(f"{item_id}: a refusal counted as correct where one was required")
        if outcome in (scoring.CRASHED, scoring.TIMEOUT) and record.get("correct"):
            problems.append(f"{item_id}: a {outcome} counted as correct")
    return problems


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #


def rate(part: int, whole: int) -> float | None:
    """A share, or ``None`` when there is nothing to divide by.

    Zero items is not zero percent, and a substituted zero would read as a
    measurement.
    """
    return None if whole == 0 else part / whole


def percent(value: float | None) -> str:
    """``value`` as a percentage, or ``-`` when there is no rate to show."""
    return "-" if value is None else f"{100 * value:.1f}%"


def percentile(ordered: list[float], p: int) -> float | None:
    """The nearest-rank percentile of an already sorted list.

    Nearest rank, not interpolation: the figure printed is a latency that occurred.
    """
    if not ordered:
        return None
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _tally(rows: list[dict]) -> dict:
    """How many of ``rows`` were right, and how many there were."""
    correct = sum(1 for row in rows if row.get("correct"))
    return {"n": len(rows), "correct": correct, "accuracy": rate(correct, len(rows))}


def split_summary(
    items: list[dict], expected: dict[str, int] | None = None
) -> dict[str, dict]:
    """Per split: how many items, how many right, and how the rest went.

    ``expected`` is the corpus's own count, so a run cut short says so instead of
    looking like a smaller corpus. The columns add up:
    ``misses == wrong_values + missed_refusal + crashed + timeout``, which is what
    stops a miss hiding in a column that is not printed.
    """
    groups: dict[str, list[dict]] = {}
    for record in items:
        groups.setdefault(record.get("split"), []).append(record)

    order = list(expected or {})
    order += [split for split in groups if split not in order]

    summary: dict[str, dict] = {}
    for split in order:
        rows = groups.get(split, [])
        # Counted by the scorer, not here, so this cannot drift from the verdicts
        # it claims to summarise.
        bucket = scoring.counts_by_split(rows).get(split, {})
        correct = bucket.get("correct", 0)
        missed = {
            outcome: sum(
                1
                for row in rows
                if row.get("outcome") == outcome and not row.get("correct")
            )
            for outcome in scoring.OUTCOMES
        }
        summary[split] = {
            "n": len(rows),
            "expected": (expected or {}).get(split),
            "correct": correct,
            "accuracy": rate(correct, len(rows)),
            "misses": len(rows) - correct,
            "outcomes": {
                outcome: bucket.get(outcome, 0) for outcome in scoring.OUTCOMES
            },
            "wrong_values": missed[scoring.PARSED],
            "missed_refusal": missed[scoring.REFUSED],
            "crashed": missed[scoring.CRASHED],
            "timeout": missed[scoring.TIMEOUT],
        }
    return summary


def cell_summary(items: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """Right/total per corpus cell, per split.

    Every cell holds the same number of items in every split, which is the only
    reason two cells can be read against each other.
    """
    cells: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for record in items:
        if record.get("split") not in CELL_SPLITS:
            continue
        key = (record.get("capability"), record.get("instrument_type"))
        cells.setdefault(key, {}).setdefault(record["split"], []).append(record)
    return {
        key: {split: _tally(rows) for split, rows in per_split.items()}
        for key, per_split in cells.items()
    }


def capability_summary(items: list[dict]) -> dict[str, dict[str, dict]]:
    """Right/total per capability per split, summed over the cells it owns.

    Every capability of the table is present even when the run holds none of its
    items, so a gap shows as a gap.
    """
    cells = cell_summary(items)
    summary: dict[str, dict[str, dict]] = {}
    for capability in corpus.CAPABILITIES:
        per_split: dict[str, dict] = {}
        for split in CELL_SPLITS:
            rows = [
                cells[cell][split]
                for cell in corpus.CELLS
                if cell[0] == capability and split in cells.get(cell, {})
            ]
            n = sum(row["n"] for row in rows)
            correct = sum(row["correct"] for row in rows)
            per_split[split] = {"n": n, "correct": correct, "accuracy": rate(correct, n)}
        summary[capability] = per_split
    return summary


def reason_summary(items: list[dict]) -> dict[str, dict]:
    """Right/total per refusal reason.

    Each reason is a different check, so one that is never refused points at that
    check rather than at the model as a whole.
    """
    groups: dict[str, list[dict]] = {}
    for record in items:
        if record.get("capability") != corpus.NO_VALID_TICKET:
            continue
        groups.setdefault(record.get("reason") or "unspecified", []).append(record)
    return {reason: _tally(rows) for reason, rows in groups.items()}


def contrast(items: list[dict]) -> list[dict]:
    """Per capability, the familiar arm against the shifted arm, worst first.

    Worst first so the tag carrying the loss is at the top, and one hard capability
    cannot be read as a general result.
    """
    cells = cell_summary(items)
    rows: list[dict] = []
    for capability in corpus.CAPABILITIES:
        arms = {}
        for split in (FAMILIAR_ARM, SHIFTED_ARM):
            group = [
                cells[cell][split]
                for cell in corpus.CELLS
                if cell[0] == capability and split in cells.get(cell, {})
            ]
            n = sum(row["n"] for row in group)
            correct = sum(row["correct"] for row in group)
            arms[split] = {"n": n, "correct": correct, "accuracy": rate(correct, n)}
        left, right = arms[FAMILIAR_ARM], arms[SHIFTED_ARM]
        drop = None
        if left["accuracy"] is not None and right["accuracy"] is not None:
            drop = right["accuracy"] - left["accuracy"]
        rows.append({"capability": capability, "familiar": left, "shifted": right, "drop": drop})
    return sorted(rows, key=lambda row: (row["drop"] or 0.0, row["capability"]))


def field_tally(items: list[dict]) -> Counter:
    """Every misread field, counted under the name the runner wrote.

    A bare name and its dotted counterpart are kept apart: the corpus states
    ``instrument_type`` at both levels, so the two lines are one defect recorded
    twice, and merging them would hide the second check.
    """
    tally: Counter = Counter()
    for record in items:
        tally.update(record.get("wrong") or [])
    return tally


def default_summary(items: list[dict]) -> dict:
    """How much of each answer the parser supplied rather than read.

    Read it next to the accuracy, not instead of it: a run that reaches a high score
    while defaulting much of the draft has measured the defaults too.
    """
    fields: Counter = Counter()
    for record in items:
        fields.update(record.get("defaulted_fields") or [])
    return {
        "n": len(items),
        "items_with_defaults": sum(
            1 for record in items if record.get("default_count")
        ),
        "default_count": sum(record.get("default_count") or 0 for record in items),
        "fields": fields,
    }


def cost_summary(items: list[dict]) -> dict:
    """Tokens, dollars and wall-clock, each beside the count it was taken over.

    A local model reports no usage, so the denominators are part of the result: an
    average over nothing is not a cheap run.
    """
    latencies = sorted(
        record["latency_ms"]
        for record in items
        if record.get("latency_ms") is not None
    )
    priced = [
        record["usd"] for record in items if record.get("usd") is not None
    ]
    tokenised = [
        record for record in items if record.get("total_tokens") is not None
    ]
    return {
        "n": len(items),
        "with_tokens": len(tokenised),
        "with_usd": len(priced),
        "prompt_tokens": sum(record.get("prompt_tokens") or 0 for record in tokenised),
        "completion_tokens": sum(
            record.get("completion_tokens") or 0 for record in tokenised
        ),
        "total_tokens": sum(record.get("total_tokens") or 0 for record in tokenised),
        "usd": sum(priced) if priced else None,
        "latency_n": len(latencies),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_max_ms": max(latencies) if latencies else None,
        "latency_total_s": sum(latencies) / 1000 if latencies else None,
    }


def error_summary(items: list[dict]) -> dict[str, Counter]:
    """The exception types behind each outcome.

    Kept apart by outcome so a dead provider, which shows up as crashes, cannot read
    as a model that cannot parse.
    """
    summary: dict[str, Counter] = {}
    for outcome in scoring.OUTCOMES:
        names: Counter = Counter(
            record.get("error_type") or "no reason given"
            for record in items
            if record.get("outcome") == outcome and record.get("error")
        )
        if names:
            summary[outcome] = names
    return summary


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """A fixed-width table. The first column is a name, the rest are numbers."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: list[str]) -> str:
        return "  ".join(
            cell.ljust(widths[index]) if index == 0 else cell.rjust(widths[index])
            for index, cell in enumerate(cells)
        ).rstrip()

    return (
        [line(headers), line(["-" * width for width in widths])]
        + [line(row) for row in rows]
    )


def _section(head: list[str], lines: list[str]) -> list[str]:
    """One titled section, or nothing when there is nothing to show."""
    return [*head, *lines, ""] if lines else []


def _counts_lines(counts: Counter, *, empty: str) -> list[str]:
    if not counts:
        return [f"  {empty}"]
    width = max(len(str(count)) for count in counts.values())
    return [
        f"  {str(count).rjust(width)}  {name}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _header_lines(header: dict, path: Path | None) -> list[str]:
    git_sha = header.get("git_sha")
    if git_sha is None:
        code = "no git"
    else:
        code = f"{git_sha[:12]} ({'dirty' if header.get('git_dirty') else 'clean'})"
    fields = [
        ("file", str(path) if path else "-"),
        ("run", str(header.get("run_id"))),
        ("model", _model_line(header)),
        (
            "corpus",
            f"sha256 {(header.get('corpus_sha256') or '-')[:12]}, "
            f"trade date {header.get('trade_date')}",
        ),
        ("code", code),
        (
            "rules",
            f"runner v{header.get('runner_version')}, scorer v{header.get('scorer_version')}",
        ),
        (
            "prompt",
            f"sha256 {(header.get('system_prompt_sha256') or '-')[:12]}",
        ),
        ("started", str(header.get("started_at"))),
        (
            "scope",
            f"splits {''.join(header.get('splits') or [])}, "
            f"{header.get('item_count')} items, "
            f"limit {header.get('item_limit') or 'none'}, "
            f"timeout {header.get('item_timeout_s')}s",
        ),
        ("notes", str(header.get("notes"))),
    ]
    width = max(len(name) for name, _ in fields)
    return [f"  {name.ljust(width)}  {value}" for name, value in fields]


def _model_line(header: dict) -> str:
    """Which model answered and which name it was asked under, when they differ."""
    asked = header.get("model_id")
    served = header.get("provider_model")
    line = f"{asked} ({header.get('model_kind')})"
    return line if served in (None, asked) else f"{line}, served as {served}"


def _split_lines(summary: dict[str, dict]) -> list[str]:
    """One line per split. The size column names the corpus target only when known."""
    target_known = any(row["expected"] is not None for row in summary.values())
    rows = []
    for split, row in summary.items():
        size = str(row["n"])
        if target_known:
            size = f"{row['n']}/{row['expected'] if row['expected'] is not None else '-'}"
        rows.append(
            [
                split,
                size,
                str(row["correct"]),
                percent(row["accuracy"]),
                str(row["misses"]),
                str(row["outcomes"][scoring.PARSED]),
                str(row["outcomes"][scoring.REFUSED]),
                str(row["outcomes"][scoring.CRASHED]),
                str(row["outcomes"][scoring.TIMEOUT]),
            ]
        )
    return _table(
        [
            "split",
            "n/corpus" if target_known else "n",
            "correct",
            "accuracy",
            "misses",
            "parsed",
            "refused",
            "crashed",
            "timeout",
        ],
        rows,
    )


def _miss_lines(summary: dict[str, dict]) -> list[str]:
    rows = [
        [
            split,
            str(row["wrong_values"]),
            str(row["missed_refusal"]),
            str(row["crashed"]),
            str(row["timeout"]),
        ]
        for split, row in summary.items()
    ]
    return _table(
        ["split", "wrong-values", "refused-unasked", "crashed", "timeout"], rows
    )


def _hits(row: dict | None) -> str:
    """``correct/n`` for one split of one row, or a dash where there is no row."""
    return "-" if not row or not row["n"] else f"{row['correct']}/{row['n']}"


def _grid_lines(entries: list[tuple[str, dict[str, dict]]], first: str) -> list[str]:
    """One line per named row, one column per cell-table split."""
    return _table(
        [first, *CELL_SPLITS],
        [
            [label, *[_hits(per_split.get(split)) for split in CELL_SPLITS]]
            for label, per_split in entries
        ],
    )


def _contrast_lines(rows: list[dict]) -> list[str]:
    table = [
        [
            row["capability"],
            _hits(row["familiar"]),
            _hits(row["shifted"]),
            "-" if row["drop"] is None else f"{100 * row['drop']:+.1f}pp",
        ]
        for row in rows
    ]
    return _table(["capability", FAMILIAR_ARM, SHIFTED_ARM, "shift"], table)


def _reason_lines(items: list[dict]) -> list[str]:
    return _table(
        ["reason", "correct", "n", "accuracy"],
        [
            [reason, str(row["correct"]), str(row["n"]), percent(row["accuracy"])]
            for reason, row in reason_summary(items).items()
        ],
    )


def _cost_lines(cost: dict) -> list[str]:
    money = "-" if cost["usd"] is None else f"{cost['usd']:.4f}"
    latency = (
        f"p50 {cost['latency_p50_ms']:.0f}ms, p95 {cost['latency_p95_ms']:.0f}ms, "
        f"max {cost['latency_max_ms']:.0f}ms, total {cost['latency_total_s']:.1f}s "
        f"over {cost['latency_n']} items"
        if cost["latency_n"]
        else "nothing was timed"
    )
    return [
        f"  tokens: {cost['total_tokens']} "
        f"(prompt {cost['prompt_tokens']}, completion {cost['completion_tokens']}) "
        f"over {cost['with_tokens']}/{cost['n']} items",
        f"  dollars: {money} over {cost['with_usd']}/{cost['n']} items",
        f"  latency: {latency}",
    ]


def render(
    header: dict, items: list[dict], *, path: Path | None = None, expected: dict[str, int] | None = None
) -> str:
    """The whole report for one run, as text.

    Deterministic, so the output can be committed and diffed like anything else.
    """
    splits = split_summary(items, expected)
    capabilities = capability_summary(items)
    cells = cell_summary(items)
    problems = integrity_problems(items)

    lines: list[str] = ["== run ==", *_header_lines(header, path), ""]
    lines += _section(
        [
            "== ledger faults ==",
            "  faults in the record, not results; nothing below should be quoted",
            "  until they are explained:",
        ],
        [f"  {problem}" for problem in problems],
    )

    lines += _section(["== accuracy by split =="], _split_lines(splits))
    lines += _section(
        [
            "== how the misses broke down ==",
            "  counts only items marked wrong, so a refusal on D item is not here",
        ],
        _miss_lines(splits),
    )
    lines += _section(
        [
            "== accuracy by capability ==",
            "  correct/n over the cell-table splits; every capability meets every",
            "  instrument type the same number of times",
        ],
        _grid_lines(
            [(capability, capabilities[capability]) for capability in corpus.CAPABILITIES],
            "capability",
        ),
    )
    lines += _section(
        ["== accuracy by cell ==", "  correct/n per capability x instrument type"],
        _grid_lines(
            [
                (f"{capability} x {instrument}", cells.get((capability, instrument)) or {})
                for capability, instrument in corpus.CELLS
            ],
            "cell",
        ),
    )
    lines += _section(
        [
            f"== {FAMILIAR_ARM} against {SHIFTED_ARM} ==",
            f"  {FAMILIAR_ARM}[i] and {SHIFTED_ARM}[i] are one ticket in two spellings;",
            "  the shift is what this arm exists to produce; worst first",
        ],
        _contrast_lines(contrast(items)),
    )
    lines += _section(
        [
            "== sentences that were never a ticket ==",
            "  correct/n per refusal reason; each reason is a different check",
        ],
        _reason_lines(items),
    )
    lines += _section(
        ["== misread fields ==", "  counted under the name the runner wrote"],
        _counts_lines(field_tally(items), empty="no stated field was misread"),
    )

    defaults = default_summary(items)
    lines += _section(
        ["== fields the parser filled in =="],
        [
            f"  {defaults['default_count']} default(s) across "
            f"{defaults['items_with_defaults']}/{defaults['n']} items",
            *_counts_lines(defaults["fields"], empty="nothing was defaulted"),
        ],
    )

    lines += _section(["== cost =="], _cost_lines(cost_summary(items)))

    errors = error_summary(items)
    lines += _section(
        ["== failures by exception =="],
        [
            line
            for outcome, names in errors.items()
            for line in [f"  {outcome}:", *_counts_lines(names, empty="-")]
        ],
    )

    return "\n".join(lines).rstrip() + "\n"


def render_contrast(
    left: dict, left_items: list[dict], right: dict, right_items: list[dict]
) -> str:
    """Two runs side by side, or the reason their numbers may not be.

    The guard comes first and no flag bypasses it: a difference between two rates is
    only a difference if both were measured the same way. A shift is the left run
    minus the right one, so a positive number is the left run ahead.
    """
    lines = [
        f"== {left['run_id']} against {right['run_id']} ==",
        "  every shift is the left run minus the right",
    ]
    problems = compare_headers(left, right)
    if problems:
        lines.append("  not comparable, so no difference is taken:")
        lines += [f"    {problem}" for problem in problems]
        return "\n".join(lines) + "\n"

    def arm(pair: tuple[dict, list[dict]]) -> tuple[str, float | None]:
        header, items = pair
        counts = scoring.counts_by_split(items)
        n = sum(row["n"] for row in counts.values())
        correct = sum(row["correct"] for row in counts.values())
        return header["run_id"], rate(correct, n)

    left_id, left_rate = arm((left, left_items))
    right_id, right_rate = arm((right, right_items))
    delta = (
        "-"
        if left_rate is None or right_rate is None
        else f"{100 * (left_rate - right_rate):+.1f}pp"
    )
    lines += _table(
        ["scope", left_id, right_id, "shift"],
        [["overall", percent(left_rate), percent(right_rate), delta]],
    )

    left_splits = split_summary(left_items)
    right_splits = split_summary(right_items)
    rows = []
    for split in dict.fromkeys([*left_splits, *right_splits]):
        left_row, right_row = left_splits.get(split), right_splits.get(split)
        if left_row is None or right_row is None:
            continue
        delta = (
            "-"
            if left_row["accuracy"] is None or right_row["accuracy"] is None
            else f"{100 * (left_row['accuracy'] - right_row['accuracy']):+.1f}pp"
        )
        rows.append(
            [
                split,
                percent(left_row["accuracy"]),
                percent(right_row["accuracy"]),
                delta,
            ]
        )
    lines += _table(["split", left_id, right_id, "shift"], rows)

    left_arms = {row["capability"]: row["drop"] for row in contrast(left_items)}
    right_arms = {row["capability"]: row["drop"] for row in contrast(right_items)}
    rows = []
    for capability in corpus.CAPABILITIES:
        left_drop = left_arms[capability]
        right_drop = right_arms[capability]
        if left_drop is None and right_drop is None:
            continue

        def shown(value: float | None) -> str:
            return "-" if value is None else f"{100 * value:+.1f}pp"

        together = (
            "-"
            if left_drop is None or right_drop is None
            else f"{100 * (left_drop - right_drop):+.1f}pp"
        )
        rows.append([capability, shown(left_drop), shown(right_drop), together])
    lines += _table(["per-capability shift", FAMILIAR_ARM, SHIFTED_ARM, "difference"], rows)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    runner.use_utf8_console(sys.stdout, sys.stderr)
    parser = argparse.ArgumentParser(
        description="Read the evidence file and report what a run shows."
    )
    parser.add_argument("--results", default=None, help="defaults to results/runs.jsonl")
    parser.add_argument(
        "--run-id", default=None, help="defaults to the last run in the file"
    )
    parser.add_argument(
        "--against", default=None, help="an earlier run id to difference against"
    )
    args = parser.parse_args(argv)

    path = Path(args.results) if args.results else runner.DEFAULT_RESULTS_PATH
    records = runner.read_records(path)
    header, items = select_run(records, args.run_id)

    expected: dict[str, int] | None = None
    try:
        payload = corpus.load()
    except Exception as exc:  # noqa: BLE001
        note = f"the corpus could not be read ({exc}); per-split targets are omitted"
    else:
        if header.get("corpus_sha256") == payload["corpus_sha256"]:
            expected = dict(payload["counts"])
            note = None
        else:
            note = (
                f"run {header['run_id']} was taken against corpus "
                f"{(header.get('corpus_sha256') or '-')[:12]} and the file now holds "
                f"{payload['corpus_sha256'][:12]}; per-split targets are omitted"
            )

    if note:
        print(f"note: {note}\n")
    sys.stdout.write(render(header, items, path=path, expected=expected))

    if args.against:
        other_header, other_items = select_run(records, args.against)
        print()
        sys.stdout.write(render_contrast(header, items, other_header, other_items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
