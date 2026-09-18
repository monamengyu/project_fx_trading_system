"""The corpus: natural-language tickets with known answers.

Ground truth first
------------------
A *ticket* (pair, direction, notional, counterparty and the instrument's own
parameters) is chosen deterministically, and the text is then rendered from a
template. Text is therefore a lossless encoding of the ticket, and
:func:`read_ticket` reconstructs the ticket from the text alone. That round-trip
is the corpus's main self-check: a sentence that cannot be read back into the
ticket it claims to describe is a mislabelled item.

Four splits, four test conditions
---------------------------------
``A``/``B``/``C``/``D`` are four ways of asking the
same parser the same question:

===========  ===  ==================================================================
split        n    role
===========  ===  ==================================================================
``A``        120  familiar wording, one template family per item
``B``         80  familiar wording, different tickets
``C``         80  shifted wording, each item twinned to a ``B`` item
``D``         40  no valid ticket exists; the correct answer is a refusal
===========  ===  ==================================================================

``B[i]`` and ``C[i]`` share a ``pair_id`` and carry a byte-identical ``golden``:
one ticket, said two ways. ``A`` and ``B`` draw from the same familiar pool but
never share a ticket, so the pair of them can be pooled or used one as a
held-out reference for the other.

Every item carries one ``capability`` tag naming the single skill its shifted arm
exercises, so a failure is attributable to that skill rather than to "the
sentence was hard". Only one slot differs between a tag's familiar and shifted
arm.

Scope limits (deliberate, so a failure is never miscounted)
----------------------------------------------------------
* ``rate`` is never stated in any ticket. The resolver fills it from the frozen
  snapshot, which is market data, not parsing. Rate *reading* is therefore
  untested here.
* ``comment`` and ``exercise_style`` are never stated. They exercise the
  resolver's defaulting (and hence the confidence signal), not the parser.
* ``delivery_date`` and ``premium_date`` are never stated; the resolver derives
  them from the expiry.
* SPOT tickets never state a settlement date, because a spot date is a convention
  the resolver computes rather than a value the text carries.

Regenerate the file after any change here::

    cd backend
    python -m evaluation.corpus

The committed ``corpus.json`` must equal a fresh build byte for byte, and its
``corpus_sha256`` covers every field except itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from app.models.enums import Currency, CurrencyPair
from app.services.business_calendar import effective_trade_date
from evaluation.frozen_rates import FrozenRateProvider

DEFAULT_CORPUS_PATH = Path(__file__).with_name("corpus.json")

CORPUS_VERSION = 1

#: The single pinned trade date the whole corpus is built on. Every tenor, option
#: expiry and settlement date below is relative to it, and the frozen snapshot
#: must have been recorded on it (asserted in :func:`build`).
TRADE_DATE = date(2026, 9, 11)

SPOT = "SPOT"
FORWARD = "FORWARD"
OPTION = "OPTION"

SPLIT_SIZES = {"A": 120, "B": 80, "C": 80, "D": 40}

#: Every supported pair, in ``CurrencyPair`` order. Checked against the frozen
#: snapshot at build time so a change to either side is a loud failure.
PAIRS: list[str] = [pair.value for pair in CurrencyPair]

#: Notionals in whole millions. Rendered in whichever spelling the item's
#: capability tests, so the pool is about magnitude, not formatting.
NOTIONALS: list[float] = [float(millions) * 1_000_000 for millions in range(1, 11)]

COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"]

#: Tenors with more than one spelling. Calendar days for weeks, calendar months
#: clamped to day 28 for months - both matching the rule-based parser's own
#: arithmetic, so a familiar tenor arm is exactly reproducible.
#:
#: ``(1, "month")`` is deliberately absent: one month from the trade date still
#: lands on the parser's silent default forward settlement, so a shifted
#: ``1-month forward`` would be accidentally correct and the arm undetectable.
TENORS: list[tuple[int, str]] = [(1, "week"), (2, "weeks"), (3, "months"), (6, "months")]

#: The one spoken name used for each currency when a ticket is rendered in words.
#: Each value must be an exact alternative of the parser's own ``_CURRENCY_WORDS``
#: table. USD is bare ``dollars``: the parser's spoken form needs the quote word
#: immediately after the connector, and no USD alternative starts with "US".
CURRENCY_WORDS: dict[str, str] = {
    "EUR": "euros",
    "GBP": "pounds",
    "USD": "dollars",
    "JPY": "yen",
    "CHF": "swiss francs",
    "CAD": "canadian dollars",
    "AUD": "australian dollars",
    "NZD": "new zealand dollars",
    "CNH": "yuan",
    "HKD": "hong kong dollars",
    "SGD": "singapore dollars",
    "SEK": "swedish krona",
    "NOK": "norwegian kroner",
    "MXN": "mexican pesos",
    "ZAR": "south african rand",
    "TRY": "turkish lira",
}

_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

#: Tags that apply to every instrument type, in table order.
_SHARED_CAPABILITIES = (
    "pair_code",  # the pair's ISO code, e.g. ``EURUSD``
    "pair_words", # the pair's spoken name, e.g. ``euros against dollars``
    "notional_suffix", # the notional with a ``m`` or ``mm`` suffix
    "notional_word", # the notional in words, e.g. ``five million``
    "notional_bare", # the notional as a bare number, e.g. ``5,000,000``
    "direction_verb", # the direction as a verb, e.g. ``buy`` or ``sell``
)

#: Tags that only exist for one instrument type. Listed first so their cells are
#: spread over the whole of every split instead of clustering at the end.
_INSTRUMENT_CAPABILITIES: list[tuple[str, str]] = [
    ("tenor_form", FORWARD), # the forward's tenor is stated, e.g. ``3-month forward``
    ("date_written", FORWARD), # the forward's settlement is written out, e.g. ``forward settling 2026-10-20``
    ("option_terms", OPTION), # the option's terms are stated, e.g. ``call strike of 1.2500 expiring 2026-10-20 premium of 25000 USD``
]

#: All capability tags, in cell-table order.
CAPABILITIES: list[str] = [
    capability for capability, _ in _INSTRUMENT_CAPABILITIES
] + list(_SHARED_CAPABILITIES)

#: The tag for an item whose whole point is that no valid ticket exists.
NO_VALID_TICKET = "no_valid_ticket"

#: One ``(capability, instrument_type)`` cell per row. Each split walks this table
#: from the top, so every cell recurs with nearly uniform frequency and the
#: instrument-specific cells (first) are spread across all splits.
CELLS: list[tuple[str, str]] = list(_INSTRUMENT_CAPABILITIES) + [
    (capability, instrument)
    for capability in _SHARED_CAPABILITIES
    for instrument in (SPOT, FORWARD, OPTION)
]

#: Day offsets from :data:`TRADE_DATE` for a forward whose settlement is written
#: out rather than given as a tenor. Both land on a business day after spot.
_SETTLEMENT_OFFSETS: list[int] = [45, 60]

#: Day offsets from :data:`TRADE_DATE` for an option expiry, all business days.
_EXPIRY_OFFSETS: list[int] = [38, 98, 188]

#: Strike offsets from the frozen rate, alternating above and below the market.
_STRIKE_OFFSETS: list[float] = [0.02, -0.02, 0.05, -0.05]

#: Premium as a fraction of notional.
_PREMIUM_FRACTIONS: list[float] = [0.0025, 0.005, 0.01]


class CorpusError(ValueError):
    """The corpus cannot be built because an assumption it rests on has moved."""


@dataclass(frozen=True)
class Ticket:
    """A trade stated in full, before it is rendered as text."""

    capability: str
    instrument_type: str
    pair: str
    direction: str
    notional: float
    counterparty: str
    tenor: tuple[int, str] | None = None
    settlement: date | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: date | None = None
    premium: float | None = None
    premium_currency: str | None = None


def _add_months(value: date, months: int) -> date:
    """Add calendar months, clamping a long day to the 28th.

    Mirrors the rule-based parser's own helper so a familiar tenor arm is
    reproducible exactly.
    """
    month_index = value.month - 1 + months
    return date(
        value.year + month_index // 12,
        month_index % 12 + 1,
        min(value.day, 28),
    )


def _tenor_date(tenor: tuple[int, str]) -> date:
    """The settlement date a parsed tenor must resolve to."""
    count, unit = tenor
    if unit.startswith("week"):
        return effective_trade_date(TRADE_DATE + timedelta(days=7 * count))
    return effective_trade_date(_add_months(TRADE_DATE, count))


def _ticket(cell_index: int, k: int, split: str, rates: dict[str, float]) -> Ticket:
    """Choose the ticket occupying position ``k`` of cell ``cell_index``.

    ``B`` and ``C`` walk an identical index sequence and deliberately make no use
    of ``split`` except through ``v``; that is what lets ``B[i]`` and ``C[i]`` be
    the same ticket said two ways.
    """
    capability, instrument_type = CELLS[cell_index]

    # B and C both offset into the value pools by 6; A does not. 7 is invertible
    # modulo 15 and the offset difference is at most 9, so the pair - and hence
    # the whole ticket - differs for every A/B pair of the same cell and k.
    v = k if split == "A" else k + 6

    pair = PAIRS[(4 * cell_index + 7 * v) % len(PAIRS)]
    notional = NOTIONALS[(3 * cell_index + 7 * v) % len(NOTIONALS)]

    tenor = None
    settlement = None
    if capability == "tenor_form":
        tenor = TENORS[(cell_index + v) % len(TENORS)]
        settlement = _tenor_date(tenor)
    elif instrument_type == FORWARD:
        settlement = TRADE_DATE + timedelta(
            days=_SETTLEMENT_OFFSETS[(cell_index + v) % len(_SETTLEMENT_OFFSETS)]
        )

    option_type = strike = expiry = premium = premium_currency = None
    if instrument_type == OPTION:
        option_type = ("CALL", "PUT")[(cell_index + v) % 2]
        strike = round(
            rates[pair] * (1 + _STRIKE_OFFSETS[(cell_index + v) % len(_STRIKE_OFFSETS)]),
            4,
        )
        expiry = TRADE_DATE + timedelta(
            days=_EXPIRY_OFFSETS[(cell_index + v) % len(_EXPIRY_OFFSETS)]
        )
        premium = round(
            notional * _PREMIUM_FRACTIONS[(cell_index + v) % len(_PREMIUM_FRACTIONS)], 2
        )
        # The base currency, so the stated premium currency is never the default
        # the resolver would otherwise have chosen.
        premium_currency = pair[:3]

    return Ticket(
        capability=capability,
        instrument_type=instrument_type,
        pair=pair,
        direction=("BUY", "SELL")[v % 2],
        notional=notional,
        counterparty=COUNTERPARTIES[(cell_index + v) % len(COUNTERPARTIES)],
        tenor=tenor,
        settlement=settlement,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        premium=premium,
        premium_currency=premium_currency,
    )


def _render_notional(notional: float, capability: str, shifted: bool) -> str:
    millions = int(round(notional / 1_000_000))
    if capability == "notional_suffix":
        return f"{millions}mm" if shifted else f"{millions}m"
    if capability == "notional_word":
        word = _NUMBER_WORDS[millions]
        return f"{word} mio" if shifted else f"{word} million"
    if capability == "notional_bare":
        grouped = f"{notional:,.0f}"
        return grouped.replace(",", "'") if shifted else grouped
    return f"{millions}m"


def _written_date(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _instrument_phrase(ticket: Ticket, shifted: bool) -> str:
    if ticket.instrument_type == SPOT:
        return "spot"

    if ticket.instrument_type == FORWARD:
        if ticket.capability == "tenor_form":
            count, unit = ticket.tenor
            if shifted:
                return f"{count}-{unit.rstrip('s')} forward"
            return f"forward in {count} {unit}"
        if ticket.capability == "date_written" and shifted:
            return f"forward settling {_written_date(ticket.settlement)}"
        return f"forward settling {ticket.settlement.isoformat()}"

    head = (
        f"{ticket.option_type.lower()} strike of {ticket.strike:.4f} "
        f"expiring {ticket.expiry.isoformat()}"
    )
    if ticket.capability == "option_terms" and shifted:
        return f"{head} premium {ticket.premium_currency} {ticket.premium:,.0f}"
    return f"{head} premium of {ticket.premium:.0f} {ticket.premium_currency}"


def _sentence(ticket: Ticket, *, shifted: bool) -> str:
    """Render a ticket as one sentence, in its familiar or shifted spelling."""
    if ticket.capability == "direction_verb" and shifted:
        direction = {"BUY": "Long", "SELL": "Short"}[ticket.direction]
    else:
        direction = {"BUY": "Buy", "SELL": "Sell"}[ticket.direction]

    if ticket.capability == "pair_code" and shifted:
        pair = f"{ticket.pair[:3]}-{ticket.pair[3:]}"
    elif ticket.capability == "pair_words":
        base = CURRENCY_WORDS[ticket.pair[:3]]
        quote = CURRENCY_WORDS[ticket.pair[3:]]
        pair = f"{base} {'versus' if shifted else 'against'} {quote}"
    else:
        pair = ticket.pair

    notional = _render_notional(ticket.notional, ticket.capability, shifted)
    instrument = _instrument_phrase(ticket, shifted)
    return f"{direction} {notional} {pair} {instrument} for {ticket.counterparty}"


def _golden(ticket: Ticket) -> dict:
    """The trade the text describes, in the draft shape the parser emits.

    Fields the text does not state are ``null`` here and are exempt when scoring.
    """
    return {
        "instrument_type": ticket.instrument_type,
        "currency_pair": ticket.pair,
        "direction": ticket.direction,
        "notional_1": ticket.notional,
        "counterparty": ticket.counterparty,
        "comment": None,
        "instrument": {
            "instrument_type": ticket.instrument_type,
            "rate": None,
            "settlement_date": (
                ticket.settlement.isoformat() if ticket.settlement else None
            ),
            "option_type": ticket.option_type,
            "strike_rate": ticket.strike,
            "expiry_date": ticket.expiry.isoformat() if ticket.expiry else None,
            "delivery_date": None,
            "premium_date": None,
            "premium": ticket.premium,
            "premium_currency": ticket.premium_currency,
            "exercise_style": None,
        },
    }


# --------------------------------------------------------------------------- #
# D: sentences with no valid ticket
# --------------------------------------------------------------------------- #

#: One kind per way of being unsalvageable. Only the ``d`` split uses these, and
#: each kind is refused at a different layer, so the set also documents where a
#: refusal can happen: pair and direction and notional are rule-based failures,
#: ``nonpositive_notional`` fails draft validation and
#: ``past_settlement_forward`` fails the settlement-window check.
_D_KINDS: list[tuple[str, str]] = [
    ("missing_pair", "{direction} {notional} {base} spot for {counterparty}"),
    ("missing_direction", "{notional} {pair} spot for {counterparty}"),
    ("unsupported_pair", "{direction} {notional} EURGBP spot for {counterparty}"),
    (
        "option_missing_expiry",
        "{direction} {notional} {pair} call strike of 1.2500 "
        "premium of 25000 {base} for {counterparty}",
    ),
    ("vague_notional", "{direction} a few million {pair} spot for {counterparty}"),
    ("missing_notional", "{direction} {pair} spot for {counterparty}"),
    ("nonpositive_notional", "{direction} 0m {pair} spot for {counterparty}"),
    (
        "past_settlement_forward",
        "{direction} {notional} {pair} forward settling 2026-09-01 for {counterparty}",
    ),
]

_D_KIND_NAMES: list[str] = [kind for kind, _ in _D_KINDS]


def _invalid_items() -> list[dict]:
    """The ``D`` split: familiar spellings, broken content, correct answer = refuse."""
    items = []
    for index in range(SPLIT_SIZES["D"]):
        kind_index = index % len(_D_KINDS)
        k = index // len(_D_KINDS)
        kind, template = _D_KINDS[kind_index]
        pair = PAIRS[(3 * kind_index + 2 * k) % len(PAIRS)]
        text = template.format(
            direction={"BUY": "Buy", "SELL": "Sell"}[("BUY", "SELL")[k % 2]],
            notional=f"{int(NOTIONALS[(kind_index + k) % len(NOTIONALS)] / 1_000_000)}m",
            pair=pair,
            base=pair[:3],
            counterparty=COUNTERPARTIES[(kind_index + k) % len(COUNTERPARTIES)],
        )
        items.append(
            {
                "item_id": f"D-{index:03d}",
                "split": "D",
                "capability": NO_VALID_TICKET,
                "instrument_type": None,
                "pair_id": None,
                "text": text,
                "golden": None,
                "reason": kind,
            }
        )
    return items


# --------------------------------------------------------------------------- #
# Reading a sentence back
# --------------------------------------------------------------------------- #

# The grammar is small and closed, so the reader is a strict inverse of the
# renderer rather than another parser: it understands exactly the spellings
# above, in both arms. If a sentence cannot be read back into the ticket it
# claims to describe, the item is mislabelled - which is the point of having it.

_READ_DIRECTION_SELL = re.compile(r"\bsell\b|\bshort\b")
_READ_DIRECTION_BUY = re.compile(r"\bbuy\b|\blong\b")

#: The notional always precedes the instrument phrase, so reading stops there and
#: an option's reordered premium cannot be mistaken for a notional.
_READ_INSTRUMENT_HEAD = re.compile(r"\b(?:call|put|forward|spot)\b", re.I)

_READ_PAIR_HYPHEN = re.compile(r"\b([A-Z]{3})-([A-Z]{3})\b")
_READ_PAIR_CODE = re.compile(r"\b([A-Z]{6})\b")
_READ_PAIR_WORDS = re.compile(
    r"\b(" + "|".join(sorted(CURRENCY_WORDS.values(), key=len, reverse=True)) + r")"
    r"\s+(?:against|versus)\s+"
    r"(" + "|".join(sorted(CURRENCY_WORDS.values(), key=len, reverse=True)) + r")\b"
)

_READ_COUNTERPARTY = re.compile(r"\b(BANK_[ABC])\b")

_READ_NOTIONAL_APOSTROPHE = re.compile(r"\b(\d{1,3}(?:'\d{3})+)\b")
_READ_NOTIONAL_GROUPED = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")
_READ_NOTIONAL_WORD = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS.values()) + r")\s+(?:million|mio)\b"
)
_READ_NOTIONAL_SUFFIX = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:mm|m)\b")

_READ_OPTION = re.compile(
    r"\b(call|put)\s+strike of\s+(\S+)\s+expiring\s+(\d{4}-\d{2}-\d{2})", re.I
)
_READ_PREMIUM_STATED = re.compile(r"premium of\s+(\d[\d,]*(?:\.\d+)?)\s+([A-Z]{3})")
_READ_PREMIUM_REORDERED = re.compile(r"premium\s+([A-Z]{3})\s+(\d[\d,]*(?:\.\d+)?)")

_READ_SETTLEMENT_ISO = re.compile(r"forward\s+settling\s+(\d{4}-\d{2}-\d{2})", re.I)
_READ_SETTLEMENT_WRITTEN = re.compile(
    r"forward\s+settling\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I
)
_READ_TENOR_PHRASE = re.compile(r"forward\s+in\s+(\d+)\s+(week|weeks|month|months)", re.I)
_READ_TENOR_ADJECTIVE = re.compile(r"(\d+)-(week|month)\s+forward", re.I)

_WORD_TO_CODE = {word: code for code, word in CURRENCY_WORDS.items()}
_MONTH_TO_NUMBER = {name.lower(): index for index, name in enumerate(_MONTHS, start=1)}


def _read_direction(lower: str) -> str:
    if _READ_DIRECTION_SELL.search(lower):
        return "SELL"
    if _READ_DIRECTION_BUY.search(lower):
        return "BUY"
    raise CorpusError(f"cannot read a direction from {lower!r}")


def _read_pair(text: str) -> str:
    match = _READ_PAIR_HYPHEN.search(text)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    match = _READ_PAIR_CODE.search(text)
    if match:
        return match.group(1)
    match = _READ_PAIR_WORDS.search(text)
    if match:
        return _WORD_TO_CODE[match.group(1)] + _WORD_TO_CODE[match.group(2)]
    raise CorpusError(f"cannot read a pair from {text!r}")


def _read_notional(text: str) -> float:
    for pattern in (_READ_NOTIONAL_APOSTROPHE, _READ_NOTIONAL_GROUPED):
        match = pattern.search(text)
        if match:
            return float(match.group(1).replace("'", "").replace(",", ""))
    match = _READ_NOTIONAL_WORD.search(text)
    if match:
        for value, word in _NUMBER_WORDS.items():
            if word == match.group(1):
                return float(value) * 1_000_000
    match = _READ_NOTIONAL_SUFFIX.search(text)
    if match:
        return float(match.group(1).replace(",", "")) * 1_000_000
    raise CorpusError(f"cannot read a notional from {text!r}")


def _read_premium(text: str) -> tuple[float, str]:
    match = _READ_PREMIUM_STATED.search(text) or _READ_PREMIUM_REORDERED.search(text)
    if not match:
        raise CorpusError(f"cannot read an option premium from {text!r}")
    first, second = match.group(1), match.group(2)
    if first.isdigit() or first[0].isdigit():
        return float(first.replace(",", "")), second
    return float(second.replace(",", "")), first


def _read_forward_settlement(text: str) -> date | None:
    match = _READ_SETTLEMENT_ISO.search(text)
    if match:
        return date.fromisoformat(match.group(1))
    match = _READ_SETTLEMENT_WRITTEN.search(text)
    if match:
        return date(
            int(match.group(3)),
            _MONTH_TO_NUMBER[match.group(2).lower()],
            int(match.group(1)),
        )
    match = _READ_TENOR_PHRASE.search(text)
    if match:
        return _tenor_date((int(match.group(1)), match.group(2).lower()))
    match = _READ_TENOR_ADJECTIVE.search(text)
    if match:
        unit = "weeks" if match.group(2).lower().startswith("week") else "months"
        return _tenor_date((int(match.group(1)), unit))
    return None


def _blank_instrument(instrument_type: str) -> dict:
    return {
        "instrument_type": instrument_type,
        "rate": None,
        "settlement_date": None,
        "option_type": None,
        "strike_rate": None,
        "expiry_date": None,
        "delivery_date": None,
        "premium_date": None,
        "premium": None,
        "premium_currency": None,
        "exercise_style": None,
    }


def _read_instrument(text: str) -> tuple[str, dict]:
    match = _READ_OPTION.search(text)
    if match:
        instrument = _blank_instrument(OPTION)
        premium, premium_currency = _read_premium(text)
        instrument.update(
            option_type=match.group(1).upper(),
            strike_rate=float(match.group(2)),
            expiry_date=match.group(3),
            premium=premium,
            premium_currency=premium_currency,
        )
        return OPTION, instrument

    settlement = _read_forward_settlement(text)
    if settlement is not None:
        instrument = _blank_instrument(FORWARD)
        instrument["settlement_date"] = settlement.isoformat()
        return FORWARD, instrument

    return SPOT, _blank_instrument(SPOT)


def read_ticket(text: str) -> dict:
    """Reconstruct the trade ``text`` describes, using only the text.

    The inverse of :func:`_sentence`, covering both arms. Used to prove that every
    rendered sentence is a lossless encoding of its golden: the reader shares no
    state with the generator, so agreement is evidence rather than tautology.
    """
    head = _READ_INSTRUMENT_HEAD.search(text)
    before_instrument = text[: head.start()] if head else text

    instrument_type, instrument = _read_instrument(text)
    return {
        "instrument_type": instrument_type,
        "currency_pair": _read_pair(text),
        "direction": _read_direction(text.lower()),
        "notional_1": _read_notional(before_instrument),
        "counterparty": _READ_COUNTERPARTY.search(text).group(1),
        "comment": None,
        "instrument": instrument,
    }


# --------------------------------------------------------------------------- #
# Building, writing and loading
# --------------------------------------------------------------------------- #


def _check_assumptions(rates: dict[str, tuple[float, date]]) -> None:
    """Fail loudly when something the corpus is built on has moved."""
    missing = set(PAIRS) - set(rates)
    if missing:
        raise CorpusError(
            f"the frozen snapshot cannot price {sorted(missing)}; re-record it"
        )
    extra = set(rates) - set(PAIRS)
    if extra:
        raise CorpusError(
            f"the frozen snapshot prices {sorted(extra)}, which CurrencyPair does "
            "not define; the corpus pair pool is out of date"
        )
    recorded = {as_of for _, as_of in rates.values()}
    if recorded != {TRADE_DATE}:
        raise CorpusError(
            f"the frozen snapshot was recorded for {sorted(recorded)}, not the "
            f"corpus trade date {TRADE_DATE}; move the corpus date or re-record "
            "the snapshot"
        )
    if set(CURRENCY_WORDS) != {currency.value for currency in Currency}:
        raise CorpusError(
            "CURRENCY_WORDS no longer covers the same currencies as Currency; a "
            "new currency needs its spoken name before the corpus can be built"
        )


def _payload(rates: dict[str, tuple[float, date]]) -> dict:
    """Everything the file stores except its own digest."""
    spot_rates = {code: value for code, (value, _) in rates.items()}
    items: list[dict] = []
    for split, count in SPLIT_SIZES.items():
        if split == "D":
            continue
        for index in range(count):
            cell_index = index % len(CELLS)
            ticket = _ticket(cell_index, index // len(CELLS), split, spot_rates)
            items.append(
                {
                    "item_id": f"{split}-{index:03d}",
                    "split": split,
                    "capability": ticket.capability,
                    "instrument_type": ticket.instrument_type,
                    # B[i] and C[i] are the same ticket, so they share this id.
                    "pair_id": f"P-{index:03d}" if split in ("B", "C") else None,
                    "text": _sentence(ticket, shifted=split == "C"),
                    "golden": _golden(ticket),
                    "reason": None,
                }
            )
    items.extend(_invalid_items())
    return {
        "version": CORPUS_VERSION,
        "trade_date": TRADE_DATE.isoformat(),
        "counts": dict(SPLIT_SIZES),
        "capabilities": list(CAPABILITIES),
        "cells": [list(cell) for cell in CELLS],
        "items": items,
    }


def digest(payload: dict) -> str:
    """The digest a payload must carry in its ``corpus_sha256`` field.

    It covers every field but that one, so ``digest(load())`` equals the value
    the file stores. The JSON is canonical -- sorted keys, no whitespace -- so
    reindenting the file cannot change the digest, and only a different value can.
    """
    body = {key: value for key, value in payload.items() if key != "corpus_sha256"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(blob.encode("utf-8")).hexdigest()


def build(snapshot: FrozenRateProvider | None = None) -> dict:
    """Build the corpus payload, including its digest."""
    provider = snapshot or FrozenRateProvider.from_file()
    _check_assumptions(provider.rates)
    payload = _payload(provider.rates)
    payload["corpus_sha256"] = digest(payload)
    return payload


def write(path: Path | str | None = None, snapshot: FrozenRateProvider | None = None) -> Path:
    """Build the corpus and write it out. Returns the path written."""
    target = Path(path or DEFAULT_CORPUS_PATH)
    payload = build(snapshot)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return target


def load(path: Path | str | None = None) -> dict:
    """Read a corpus file, verifying its digest before trusting its contents."""
    payload = json.loads(Path(path or DEFAULT_CORPUS_PATH).read_text(encoding="utf-8"))
    stored = payload.pop("corpus_sha256", None)
    if stored is None:
        raise CorpusError(f"{path or DEFAULT_CORPUS_PATH} has no corpus_sha256")
    actual = digest(payload)
    payload["corpus_sha256"] = stored
    if stored != actual:
        raise CorpusError(
            f"{path or DEFAULT_CORPUS_PATH} does not match its own digest: the file "
            "was edited by hand or built by different code; rebuild it"
        )
    return payload


def items_of(payload: dict, split: str) -> list[dict]:
    """The items of one split, in file order."""
    return [item for item in payload["items"] if item["split"] == split]


def twins(payload: dict, pair_id: str) -> list[dict]:
    """The two items sharing a ``pair_id`` (one ``B``, one ``C``)."""
    return [item for item in payload["items"] if item["pair_id"] == pair_id]


if __name__ == "__main__":
    written = write()
    corpus = load(written)
    print(
        f"{written.name}: {corpus['counts']} items, "
        f"sha256 {corpus['corpus_sha256'][:16]}"
    )
