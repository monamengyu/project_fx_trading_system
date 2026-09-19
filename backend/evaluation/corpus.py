"""The corpus: natural-language tickets with known answers.

Text is rendered from a deterministically chosen ticket, so every sentence is a
lossless encoding of its golden and :func:`read_ticket` can reconstruct it. That
round-trip is the self-check: a sentence that cannot be read back into the ticket
it describes is a mislabelled item.

===========  ===  ==================================================================
split        n    role
===========  ===  ==================================================================
``A``        108  familiar wording
``B``        108  familiar wording, different tickets
``C``        108  shifted wording, each item twinned to a ``B`` item
``D``         40  no valid ticket exists; the correct answer is a refusal
===========  ===  ==================================================================

``B[i]`` and ``C[i]`` share a ``pair_id`` and carry a byte-identical ``golden``:
one ticket said two ways. ``A`` and ``B`` share no ticket, so one can serve as a
held-out reference for the other.

Each item carries one ``capability`` tag naming the single skill its shifted arm
exercises, and a ``variant`` naming the spelling it used, so a failure is
attributable to a wording rather than to a hard sentence.

A tag's *familiar* arm uses a spelling the production rule-based parser already
reads, which keeps the baseline the floor; its *shifted* arm uses one that parser
cannot read. Both arms use real desk shorthand:

* ``m``/``mm``/``million``/``mio``, and ``billion``/``bn``/``bio``/``yard``/``yards``;
* ``forward``/``frd``/``fwd``, and a bare ``opt``;
* ``settling <date>``/``value <date>``/``3-month forward``/``3s``;
* ``against``/``versus``/``agst``, and ``strike of``/``K``;
* the desk names ``cable`` (GBPUSD), ``aussie`` (AUDUSD) and ``kiwi`` (NZDUSD).

Deliberately never stated, so a failure is never miscounted: ``rate`` (market
data, not parsing), ``comment`` and ``exercise_style`` (resolver defaults, hence
the confidence signal), the option's ``delivery_date`` and ``premium_date`` (the
resolver derives them), and a SPOT settlement date (a resolver convention).

Regenerate after any change here::

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

#: The single pinned trade date. Every tenor, expiry and settlement date is
#: relative to it, and the frozen snapshot must have been recorded on it.
TRADE_DATE = date(2026, 9, 11)

SPOT = "SPOT"
FORWARD = "FORWARD"
OPTION = "OPTION"

#: Every supported pair, in ``CurrencyPair`` order. Checked against the frozen
#: snapshot at build time, so a change to either side is a loud failure.
PAIRS: list[str] = [pair.value for pair in CurrencyPair]

#: Notionals in whole millions; the item's capability decides how each is spelt.
NOTIONALS: list[float] = [float(millions) * 1_000_000 for millions in range(1, 11)]

COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"]

#: Tenors with more than one spelling, using the rule-based parser's own
#: arithmetic so a familiar arm reproduces exactly. ``(1, "month")`` is absent
#: because it coincides with the parser's default forward settlement, which would
#: make a shifted ``1-month forward`` accidentally correct and the arm undetectable.
TENORS: list[tuple[int, str]] = [(1, "week"), (2, "weeks"), (3, "months"), (6, "months")]

#: The spoken name each currency is rendered as, matching the parser's own
#: ``_CURRENCY_WORDS``. USD is bare ``dollars`` because the parser needs the quote
#: word straight after the connector and no USD alternative starts with "US".
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

#: The pairs the market calls by a nickname. Pair nicknames are world knowledge
#: rather than tokenisation, so they get a tag of their own.
_NICKNAMES: dict[str, str] = {
    "GBPUSD": "cable",
    "AUDUSD": "aussie",
    "NZDUSD": "kiwi",
}

#: The nickname pairs, in a fixed order so an item's pair is reproducible.
_NICKNAME_PAIRS: list[str] = list(_NICKNAMES)

#: Ways of writing a thousand million, none of which the parser reads. Capped at
#: five because a cell holds only ``REPLICATES`` items: a longer list would declare
#: spellings that are never exercised.
_BILLION_SPELLINGS: dict[str, str] = {
    "billion": "{word} billion",
    "bn": "{n}bn",
    "bio": "{n}bio",
    "yard": "{n} yard",
    "yards": "{n} yards",
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
    "pair_nickname", # the pair's desk nickname, e.g. ``cable``
    "notional_suffix", # the notional with a ``m`` or ``mm`` suffix
    "notional_word", # the notional in words, e.g. ``five million``
    "notional_billion", # a thousand times the usual magnitude, e.g. ``five bn``
    "notional_bare", # the notional as a bare number, e.g. ``5,000,000``
    "direction_verb", # the direction as a verb, e.g. ``buy`` or ``sell``
)

#: Tags that only exist for one instrument type. Listed first so their cells
#: spread across every split instead of clustering at the end.
_INSTRUMENT_CAPABILITIES: list[tuple[str, str]] = [
    ("tenor_form", FORWARD), # the forward's tenor is stated, e.g. ``3-month forward``
    ("date_written", FORWARD), # the forward's settlement is written out, e.g. ``forward settling 2026-10-20``
    ("option_terms", OPTION), # the option's terms are stated, e.g. ``call strike of 1.2500 expiring 2026-10-20 premium of 25000 USD``
]

#: All capability tags, in cell-table order.
CAPABILITIES: list[str] = [
    capability for capability, _ in _INSTRUMENT_CAPABILITIES
] + list(_SHARED_CAPABILITIES)

#: Heads the parser already reads, so a forward can vary its wording while staying
#: familiar.
_FORWARD_HEADS: tuple[str, ...] = ("forward", "frd", "fwd")

#: Option heads. The parser skips over a bare ``opt``, so it too is familiar; the
#: empty head repeats so two items in three stay plain.
_OPTION_HEADS: tuple[str, ...] = ("", "", "opt ")

#: The spellings a tag's shifted arm rotates through, in rotation order. A tag with
#: ``n`` spellings uses position modulo ``n``, and whichever it lands on becomes
#: the item's ``variant``.
_SHIFTED_SPELLINGS: dict[str, tuple[str, ...]] = {
    "tenor_form": ("hyphenated", "attached"),
    "date_written": ("written_date", "value_date"),
    "option_terms": ("premium_reordered", "opt_strike_K"),
    "pair_code": ("hyphen",),
    "pair_words": ("versus", "agst"),
    "pair_nickname": tuple(_NICKNAMES.values()),
    "notional_suffix": ("mm",),
    "notional_word": ("mio",),
    "notional_billion": tuple(_BILLION_SPELLINGS),
    "notional_bare": ("apostrophe",),
    "direction_verb": ("long_short",),
}

#: The tag for an item whose whole point is that no valid ticket exists.
NO_VALID_TICKET = "no_valid_ticket"

#: One ``(capability, instrument_type)`` cell per row, walked from the top by every
#: split, so each cell recurs with the same frequency in all of them.
CELLS: list[tuple[str, str]] = list(_INSTRUMENT_CAPABILITIES) + [
    (capability, instrument)
    for capability in _SHARED_CAPABILITIES
    for instrument in (SPOT, FORWARD, OPTION)
]

#: How many tickets each cell contributes to a split. The split sizes follow from
#: this and :data:`CELLS`, so extending the table appends items at the end of each
#: split and leaves the ones already there on the same cell with the same text, id
#: and label, letting a recorded run be extended instead of re-taken whole.
REPLICATES: dict[str, int] = {"A": 4, "B": 4, "C": 4}

#: ``D`` is a fixed list rather than a walk of the cell table, so its size is the
#: one that does not follow from ``REPLICATES``.
_D_SIZE = 40


def _sizes_for(cell_count: int) -> dict[str, int]:
    """The split sizes a cell table of ``cell_count`` rows produces."""
    sizes = {split: count * cell_count for split, count in REPLICATES.items()}
    return {**sizes, "D": _D_SIZE}


SPLIT_SIZES: dict[str, int] = _sizes_for(len(CELLS))

#: Day offsets from :data:`TRADE_DATE` for a written-out forward settlement; both
#: land on a business day after spot.
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
    """A trade stated in full, before it is rendered as text.

    ``variant`` and ``head`` fix the wording, so the renderer only follows it.
    """

    capability: str
    instrument_type: str
    pair: str
    direction: str
    notional: float
    counterparty: str
    variant: str
    tenor: tuple[int, str] | None = None
    settlement: date | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: date | None = None
    premium: float | None = None
    premium_currency: str | None = None
    head: str | None = None


def _add_months(value: date, months: int) -> date:
    """Add calendar months, clamping a long day to the 28th.

    Mirrors the rule-based parser's helper, so a familiar tenor reproduces exactly.
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


def _shifted_variant(
    capability: str, *, position: int, pair: str, tenor: tuple[int, str] | None
) -> str:
    """The shifted spelling the item at ``position`` of its cell uses.

    Two tags need a rule rather than a rotation: a nickname tag is the nickname of
    the ticket's own pair, and only a month tenor has a glued ``3s`` form.
    """
    if capability == "pair_nickname":
        return _NICKNAMES[pair]
    if capability == "tenor_form":
        attached = tenor is not None and tenor[1].startswith("month") and position % 2
        return "attached" if attached else "hyphenated"
    spellings = _SHIFTED_SPELLINGS[capability]
    return spellings[position % len(spellings)]


def _ticket(cell_index: int, k: int, split: str, rates: dict[str, float]) -> Ticket:
    """Choose the ticket occupying position ``k`` of cell ``cell_index``.

    ``B`` and ``C`` walk an identical index sequence and use ``split`` only through
    ``v``, which is what makes ``B[i]`` and ``C[i]`` the same ticket.
    """
    capability, instrument_type = CELLS[cell_index]

    # B and C offset into the value pools by 6, A by 0. For an A and a B item of
    # the same cell and k both the pair and the notional differ; where a nickname
    # cell pins the pair pool to three entries, the notional alone keeps them apart.
    v = k if split == "A" else k + 6
    position = cell_index + v

    if capability == "pair_nickname":
        pair = _NICKNAME_PAIRS[position % len(_NICKNAME_PAIRS)]
    else:
        pair = PAIRS[(4 * cell_index + 7 * v) % len(PAIRS)]
    notional = NOTIONALS[(3 * cell_index + 7 * v) % len(NOTIONALS)]
    if capability == "notional_billion":
        notional *= 1_000

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
        # The base currency, never the resolver's default.
        premium_currency = pair[:3]

    if instrument_type == FORWARD:
        head = _FORWARD_HEADS[position % len(_FORWARD_HEADS)]
    elif instrument_type == OPTION:
        head = _OPTION_HEADS[position % len(_OPTION_HEADS)]
    else:
        head = None

    return Ticket(
        capability=capability,
        instrument_type=instrument_type,
        pair=pair,
        direction=("BUY", "SELL")[v % 2],
        notional=notional,
        counterparty=COUNTERPARTIES[(cell_index + v) % len(COUNTERPARTIES)],
        variant=_shifted_variant(capability, position=position, pair=pair, tenor=tenor),
        tenor=tenor,
        settlement=settlement,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        premium=premium,
        premium_currency=premium_currency,
        head=head,
    )


def _render_notional(ticket: Ticket, shifted: bool) -> str:
    capability = ticket.capability
    millions = int(round(ticket.notional / 1_000_000))
    if capability == "notional_suffix":
        return f"{millions}mm" if shifted else f"{millions}m"
    if capability == "notional_word":
        word = _NUMBER_WORDS[millions]
        return f"{word} mio" if shifted else f"{word} million"
    if capability == "notional_billion":
        if not shifted:
            return f"{ticket.notional:,.0f}"
        billions = int(round(ticket.notional / 1_000_000_000))
        return _BILLION_SPELLINGS[ticket.variant].format(
            n=billions, word=_NUMBER_WORDS[billions]
        )
    if capability == "notional_bare":
        grouped = f"{ticket.notional:,.0f}"
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
            if not shifted:
                return f"{ticket.head} in {count} {unit}"
            if ticket.variant == "attached":
                return f"{count}s"
            return f"{count}-{unit.rstrip('s')} forward"
        if ticket.capability == "date_written" and shifted:
            if ticket.variant == "value_date":
                return f"value {ticket.settlement.isoformat()}"
            return f"{ticket.head} settling {_written_date(ticket.settlement)}"
        return f"{ticket.head} settling {ticket.settlement.isoformat()}"

    head = (
        f"{ticket.head}{ticket.option_type.lower()} strike of {ticket.strike:.4f} "
        f"expiring {ticket.expiry.isoformat()}"
    )
    if ticket.capability == "option_terms" and shifted:
        if ticket.variant == "opt_strike_K":
            return (
                f"{ticket.head}{ticket.option_type.lower()} K {ticket.strike:.4f} "
                f"expiring {ticket.expiry.isoformat()} "
                f"premium of {ticket.premium:.0f} {ticket.premium_currency}"
            )
        return f"{head} premium {ticket.premium_currency} {ticket.premium:,.0f}"
    return f"{head} premium of {ticket.premium:.0f} {ticket.premium_currency}"


def _sentence(ticket: Ticket, *, shifted: bool) -> str:
    """Render a ticket as one sentence, in its familiar or shifted spelling."""
    if ticket.capability == "direction_verb" and shifted:
        direction = {"BUY": "Long", "SELL": "Short"}[ticket.direction]
    else:
        direction = {"BUY": "Buy", "SELL": "Sell"}[ticket.direction]

    if ticket.capability == "pair_nickname" and shifted:
        pair = ticket.variant
    elif ticket.capability == "pair_code" and shifted:
        pair = f"{ticket.pair[:3]}-{ticket.pair[3:]}"
    elif ticket.capability == "pair_words":
        base = CURRENCY_WORDS[ticket.pair[:3]]
        quote = CURRENCY_WORDS[ticket.pair[3:]]
        pair = f"{base} {ticket.variant if shifted else 'against'} {quote}"
    else:
        pair = ticket.pair

    notional = _render_notional(ticket, shifted)
    instrument = _instrument_phrase(ticket, shifted)
    return f"{direction} {notional} {pair} {instrument} for {ticket.counterparty}"


def _golden(ticket: Ticket) -> dict:
    """The trade the text describes, in the draft shape the parser emits.

    Fields the text does not state are ``null`` here and exempt when scoring.
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


def _item_variant(ticket: Ticket, split: str) -> str:
    """A readable name for the exact wording an item uses.

    The shifted spelling on the shifted arm and ``familiar`` on the other, plus the
    instrument head when it is not the plain ``forward``, so a result can be broken
    down by wording as well as by tag.
    """
    name = ticket.variant if split == "C" else "familiar"
    head = (ticket.head or "").strip()
    if head and head != "forward":
        return f"{name} {head}"
    return name


# --------------------------------------------------------------------------- #
# D: sentences with no valid ticket
# --------------------------------------------------------------------------- #

#: One kind per way of being unsalvageable. Each is refused at a different stage,
#: so the set also documents where a refusal can happen: pair, direction, notional
#: and ``vague_notional`` by the rules, ``nonpositive_notional`` by draft validation
#: and ``past_settlement_forward`` by the settlement-window check.
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
                "variant": None,
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

# The reader is the renderer's strict inverse rather than another parser: it
# understands exactly the spellings above, in both arms. If a sentence cannot be
# read back into the ticket it claims to describe, the item is mislabelled - which
# is the point of having it.

_READ_DIRECTION_SELL = re.compile(r"\bsell\b|\bshort\b")
_READ_DIRECTION_BUY = re.compile(r"\bbuy\b|\blong\b")

#: The notional always precedes the instrument phrase, so reading stops there and
#: a reordered premium cannot be mistaken for one. A shifted forward may leave only
#: ``value`` standing in for the whole instrument phrase.
_READ_INSTRUMENT_HEAD = re.compile(
    r"\b(?:call|put|forward|frd|fwd|spot|value)\b", re.I
)

_READ_PAIR_HYPHEN = re.compile(r"\b([A-Z]{3})-([A-Z]{3})\b")
_READ_PAIR_NICKNAME = re.compile(r"\b(cable|aussie|kiwi)\b", re.I)
_READ_PAIR_CODE = re.compile(r"\b([A-Z]{6})\b")
_READ_PAIR_WORDS = re.compile(
    r"\b(" + "|".join(sorted(CURRENCY_WORDS.values(), key=len, reverse=True)) + r")"
    r"\s+(?:against|versus|agst)\s+"
    r"(" + "|".join(sorted(CURRENCY_WORDS.values(), key=len, reverse=True)) + r")\b"
)

_READ_COUNTERPARTY = re.compile(r"\b(BANK_[ABC])\b")

_READ_NOTIONAL_APOSTROPHE = re.compile(r"\b(\d{1,3}(?:'\d{3})+)\b")
_READ_NOTIONAL_GROUPED = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")
_READ_NOTIONAL_WORD = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS.values()) + r")\s+(?:million|mio)\b"
)
_READ_NOTIONAL_BILLION_WORD = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS.values()) + r")\s+billion\b"
)
_READ_NOTIONAL_SUFFIX = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:mm|m)\b")
_READ_NOTIONAL_BILLION_SUFFIX = re.compile(
    r"\b(\d[\d,]*)\s*(?:bn|bio|yards?)\b", re.I
)

#: ``K`` stands in for ``strike of`` on a shaded-out option line.
_READ_OPTION = re.compile(
    r"\b(?:opt\s+)?(call|put)\s+(?:strike of\s+|K\s+)?(\S+)\s+"
    r"expiring\s+(\d{4}-\d{2}-\d{2})",
    re.I,
)
_READ_PREMIUM_STATED = re.compile(r"premium of\s+(\d[\d,]*(?:\.\d+)?)\s+([A-Z]{3})")
_READ_PREMIUM_REORDERED = re.compile(r"premium\s+([A-Z]{3})\s+(\d[\d,]*(?:\.\d+)?)")

_READ_SETTLEMENT_ISO = re.compile(
    r"\b(?:forward|frd|fwd)\s+settling\s+(\d{4}-\d{2}-\d{2})", re.I
)
_READ_SETTLEMENT_WRITTEN = re.compile(
    r"\b(?:forward|frd|fwd)\s+settling\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", re.I
)
_READ_SETTLEMENT_VALUE = re.compile(r"\bvalue\s+(\d{4}-\d{2}-\d{2})", re.I)
_READ_TENOR_PHRASE = re.compile(
    r"\b(?:forward|frd|fwd)\s+in\s+(\d+)\s+(week|weeks|month|months)", re.I
)
_READ_TENOR_ADJECTIVE = re.compile(r"(\d+)-(week|month)\s+forward", re.I)
#: A tenor count glued to an ``s`` means months. Read last, so it only applies when
#: nothing else in the sentence states a settlement.
_READ_TENOR_ATTACHED = re.compile(r"\b(\d+)s\b")

_WORD_TO_CODE = {word: code for code, word in CURRENCY_WORDS.items()}
_NICKNAME_TO_CODE = {nickname: code for code, nickname in _NICKNAMES.items()}
_WORD_TO_NUMBER = {word: value for value, word in _NUMBER_WORDS.items()}
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
    match = _READ_PAIR_NICKNAME.search(text)
    if match:
        return _NICKNAME_TO_CODE[match.group(1).lower()]
    match = _READ_PAIR_CODE.search(text)
    if match:
        return match.group(1)
    match = _READ_PAIR_WORDS.search(text)
    if match:
        return _WORD_TO_CODE[match.group(1)] + _WORD_TO_CODE[match.group(2)]
    raise CorpusError(f"cannot read a pair from {text!r}")


def _read_notional(text: str) -> float:
    # A grouped number is unambiguous, so the separators settle it first.
    for pattern in (_READ_NOTIONAL_APOSTROPHE, _READ_NOTIONAL_GROUPED):
        match = pattern.search(text)
        if match:
            return float(match.group(1).replace("'", "").replace(",", ""))
    for pattern, multiplier in (
        (_READ_NOTIONAL_WORD, 1_000_000),
        (_READ_NOTIONAL_BILLION_WORD, 1_000_000_000),
    ):
        match = pattern.search(text)
        if match:
            return float(_WORD_TO_NUMBER[match.group(1)]) * multiplier
    match = _READ_NOTIONAL_SUFFIX.search(text)
    if match:
        return float(match.group(1).replace(",", "")) * 1_000_000
    match = _READ_NOTIONAL_BILLION_SUFFIX.search(text)
    if match:
        return float(match.group(1).replace(",", "")) * 1_000_000_000
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
    match = _READ_SETTLEMENT_VALUE.search(text)
    if match:
        return date.fromisoformat(match.group(1))
    match = _READ_TENOR_PHRASE.search(text)
    if match:
        return _tenor_date((int(match.group(1)), match.group(2).lower()))
    match = _READ_TENOR_ADJECTIVE.search(text)
    if match:
        unit = "weeks" if match.group(2).lower().startswith("week") else "months"
        return _tenor_date((int(match.group(1)), unit))
    match = _READ_TENOR_ATTACHED.search(text)
    if match:
        return _tenor_date((int(match.group(1)), "months"))
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

    The inverse of :func:`_sentence`. It shares no state with the generator, so
    agreeing with the golden is evidence rather than tautology.
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
    if set(_SHIFTED_SPELLINGS) != set(CAPABILITIES):
        raise CorpusError(
            "every capability needs its shifted spellings declared in "
            "_SHIFTED_SPELLINGS; a tag with no wording cannot be attributed"
        )
    unknown = set(_NICKNAMES) - set(PAIRS)
    if unknown:
        raise CorpusError(
            f"the nickname table names {sorted(unknown)}, which CurrencyPair does "
            "not define"
        )
    collisions = set(_NICKNAMES.values()) & set(CURRENCY_WORDS.values())
    if collisions:
        raise CorpusError(
            f"{sorted(collisions)} name both a pair nickname and a spoken currency; "
            "the pair reader could not tell them apart"
        )


def _payload(rates: dict[str, tuple[float, date]]) -> dict:
    """Everything the file stores except its own digest."""
    spot_rates = {code: value for code, (value, _) in rates.items()}
    items: list[dict] = []
    for split, count in SPLIT_SIZES.items():
        if split == "D":
            continue
        for index in range(count):
            # Cell-major, not modulo the table length: that is what keeps existing
            # items in place when the table grows.
            cell_index, k = divmod(index, REPLICATES[split])
            ticket = _ticket(cell_index, k, split, spot_rates)
            items.append(
                {
                    "item_id": f"{split}-{index:03d}",
                    "split": split,
                    "capability": ticket.capability,
                    "instrument_type": ticket.instrument_type,
                    "variant": _item_variant(ticket, split),
                    # B[i] and C[i] are the same ticket, so they share this id.
                    "pair_id": f"P-{index:03d}" if split in ("B", "C") else None,
                    "text": _sentence(ticket, shifted=split == "C"),
                    "golden": _golden(ticket),
                    "reason": None,
                }
            )
    items.extend(_invalid_items())
    return {
        "trade_date": TRADE_DATE.isoformat(),
        "counts": dict(SPLIT_SIZES),
        "capabilities": list(CAPABILITIES),
        "cells": [list(cell) for cell in CELLS],
        "items": items,
    }


def digest(payload: dict) -> str:
    """The digest a payload must carry in its ``corpus_sha256`` field.

    It covers every field but that one, and is computed over a canonical rendering,
    so reindenting the file cannot change it.
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


def dumps(payload: dict) -> str:
    """The corpus file's text, with the cell table written one cell per line.

    ``indent=2`` would spread each two-element cell over four lines and bury the
    table the design is organised around; every other value reads better indented.
    Layout only - the digest ignores it.
    """
    lines: list[str] = []
    for key, value in payload.items():
        if key == "cells":
            rows = [json.dumps(list(cell), ensure_ascii=False) for cell in value]
            body = "[\n" + ",\n".join(f"    {row}" for row in rows) + "\n  ]"
        else:
            body = json.dumps(value, indent=2, ensure_ascii=False)
            body = body.replace("\n", "\n  ")
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {body}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def write(path: Path | str | None = None, snapshot: FrozenRateProvider | None = None) -> Path:
    """Build the corpus and write it out. Returns the path written."""
    target = Path(path or DEFAULT_CORPUS_PATH)
    target.write_text(dumps(build(snapshot)), encoding="utf-8")
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
