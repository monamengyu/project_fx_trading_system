"""Scoring: one item, one verdict, no free parameters.

This module answers a single question -- *did the parser get this item right?*. 
A number produced here does not indicate how good the parser is overall, only 
how good it is on this one item.

What "right" means
------------------
The corpus states some fields and leaves others ``null``. A ``null`` in a golden
means the text never said it, so the parser is free to invent it -- those fields
are *exempt*. Every stated field must match exactly. That rule lives in
:func:`stated_problems` and nowhere else: it is imported by the corpus's own exit
tests, so the sanity checks on the instrument and the verdicts on the runs cannot
drift apart.

An item whose golden is ``null`` has no right answer to match; the only correct
answer is a clean refusal, which is what :func:`verdict` checks for.

Outcomes
--------
The runner reports what happened, this module decides whether it counts:

=============  =============================================================
``parsed``     the model produced a trade that validated end to end
``refused``    the model (or the resolver) rejected the text cleanly
``crashed``    an unhandled fault -- a bug, a missing frozen rate, a dead
               provider. Never silently treated as a miss, because a run that
               is only 60% measured must not look like a run that scored 60%
``timeout``    the item did not finish inside its budget
=============  =============================================================

Only ``refused`` can be correct, and only on an item whose text has no valid
ticket. Correctness never rewards a crash.

Usage
-----
:func:`stated_problems` and :func:`verdict` are pure: two dicts in, a verdict
out, no clock, no network, no state. Drafts must be in JSON mode
(``NLTradeDraft.model_dump(mode="json")``), so dates are ISO strings on both
sides of the comparison; a ``date`` object would not equal its own ISO string.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bumped whenever a verdict could change for the same evidence. A committed
#: score is only comparable to another score carrying the same version.
SCORER_VERSION = 1

PARSED = "parsed"
REFUSED = "refused"
CRASHED = "crashed"
TIMEOUT = "timeout"

#: Every outcome a run may report. Anything else is a runner bug, not a result.
OUTCOMES = (PARSED, REFUSED, CRASHED, TIMEOUT)


class ScoringError(ValueError):
    """A run reported something that cannot be scored."""


@dataclass(frozen=True)
class Verdict:
    """The verdict on one item.

    ``correct`` is the only number this module produces. The rest is the evidence
    that makes it arguable: ``wrong`` names the stated fields that were
    misread, and ``detail`` says, in words, what the outcome was.
    """

    correct: bool
    outcome: str
    wrong: tuple[str, ...]
    detail: str

    @property
    def wrong_count(self) -> int:
        """How many stated fields the model misread."""
        return len(self.wrong)


def expects_refusal(item: dict) -> bool:
    """Whether the correct answer to this item is a refusal.

    A golden of ``null`` is the corpus's way of saying no valid ticket exists.
    """
    return item["golden"] is None


def stated_problems(produced: dict, golden: dict) -> list[str]:
    """The stated fields ``produced`` got wrong, as ``"[instrument.]key: got != want"``.

    Fields the golden leaves ``null`` are not stated in the text, so the parser
    is free to invent them and they are exempt from the comparison. A field the
    golden states is compared exactly.

    This is the whole of the correctness rule. It is deliberately a plain
    function of two dicts so a verdict can be argued with by looking at it.
    """
    problems: list[str] = []
    for key, want in golden.items():
        if key == "instrument" or want is None:
            continue
        if produced.get(key) != want:
            problems.append(f"{key}: {produced.get(key)!r} != {want!r}")
    produced_instrument = produced.get("instrument") or {}
    for key, want in golden["instrument"].items():
        if want is None:
            continue
        got = produced_instrument.get(key)
        if got != want:
            problems.append(f"instrument.{key}: {got!r} != {want!r}")
    return problems


def verdict(
    item: dict,
    *,
    outcome: str,
    draft: dict | None = None,
    error: str | None = None,
) -> Verdict:
    """Turn what happened to one item into a verdict.

    ``item`` is a corpus item, ``outcome`` one of :data:`OUTCOMES`, ``draft`` the
    model's trade as a JSON-mode dict (only for ``parsed``), and ``error`` the
    message that came with a refusal or a crash.
    """
    if outcome not in OUTCOMES:
        raise ScoringError(f"unknown outcome {outcome!r}; expected one of {OUTCOMES}")

    if expects_refusal(item):
        if outcome == REFUSED:
            return Verdict(True, outcome, (), "refused as required")
        return Verdict(
            False,
            outcome,
            (),
            f"no valid ticket exists, so only a refusal is correct; got {outcome}",
        )

    if outcome != PARSED:
        return Verdict(
            False, outcome, (), f"expected a trade, got {outcome}: {error or 'no reason given'}"
        )

    if draft is None:
        return Verdict(False, outcome, (), "parsed, but no draft was recorded")

    wrong = stated_problems(draft, item["golden"])
    if wrong:
        return Verdict(False, outcome, tuple(wrong), "; ".join(wrong))
    return Verdict(True, outcome, (), "every stated field matches")


def counts_by_split(records: list[dict]) -> dict[str, dict[str, int]]:
    """Correct/incorrect and outcome counts per split, ignoring the run header.

    Raw counts, not rates: a rate is a statistic to be computed where it is
    reported, with the denominator visible next to it.
    """
    counts: dict[str, dict[str, int]] = {}
    for record in records:
        if record.get("kind") != "item":
            continue
        bucket = counts.setdefault(
            record["split"],
            {"n": 0, "correct": 0, "incorrect": 0, **{outcome: 0 for outcome in OUTCOMES}},
        )
        bucket["n"] += 1
        bucket["correct" if record["correct"] else "incorrect"] += 1
        bucket[record["outcome"]] += 1
    return counts
