"""Checking that the coach's figures came from somewhere.

The coach's one rule is that every number it quotes comes from a tool call.
The system prompt asks for that; this checks it. After an answer, every figure
in the text is looked for in what the tools returned that turn, in the
athlete's own question, and in a couple of constants the app itself defines.
A figure found nowhere is reported as unverified.

The Android coach implements the same rules, and fixtures/grounding.json holds
the cases both must agree on. Change a rule here and that fixture — and so the
Kotlin build — has to change with it.

What counts as a match is deliberately forgiving of presentation and strict
about substance:

- rounding to the precision written: 116.67 may be quoted as 117 or 116.7;
- round thousands read as approximate: "about 10,000 steps" for 9,876;
- compact and percentage forms: 10.9K, 40% for a ratio of 0.4;
- the lossless rescalings the app itself uses — minutes and hours, kilograms
  and tonnes, metres and kilometres — but only when the unit written beside
  the number says so, and "7h 30m" as one quantity.

That last condition matters more than it looks. Rescaling every number by
every factor would let "8 sets" pass because some unrelated value was 8000,
and a check that says "verified" when it should not is worse than no check.

What is *not* forgiven is arithmetic. "300 kg more than last week" is a
difference the model computed, and the design is that the model never does
arithmetic — so it is reported, by intent.

Dates are not checked in this version: they are stripped before extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

# Numbers the app defines, which the coach may state without looking them up.
DEFINITIONAL = (7.0, 28.0)  # the acute and chronic load windows, in days

# The rescalings a unit allows, as (multiply, divide) applied to a source value.
# A figure with no recognised unit is matched only as written. Plurals are
# listed rather than stripped, so both languages read exactly the same words.
_FROM_METRES = (1, 1000)
_FROM_KG = (1, 1000)
_FROM_MINUTES_TO_HOURS = (1, 60)
_FROM_SECONDS = (1, 60)
_FROM_HOURS = (60, 1)
_FROM_KM = (1000, 1)
_FROM_TONNES = (1000, 1)
UNIT_RESCALINGS: dict[str, tuple[tuple[int, int], ...]] = {
    **dict.fromkeys(("km", "kms", "kilometre", "kilometres", "kilometer", "kilometers"),
                    (_FROM_METRES,)),
    **dict.fromkeys(("t", "tonne", "tonnes", "ton", "tons"), (_FROM_KG,)),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), (_FROM_MINUTES_TO_HOURS,)),
    **dict.fromkeys(("min", "mins", "minute", "minutes"), (_FROM_SECONDS, _FROM_HOURS)),
    **dict.fromkeys(("s", "sec", "secs", "second", "seconds"), ((60, 1),)),
    **dict.fromkeys(("metre", "metres", "meter", "meters"), (_FROM_KM,)),
    **dict.fromkeys(("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"), (_FROM_TONNES,)),
    # Bare "m" is minutes or metres; both are allowed rather than guessed.
    "m": (_FROM_SECONDS, _FROM_KM),
}
_AS_WRITTEN = (1, 1)

# Explicit ASCII classes rather than \d, \w, \s and \b. Android's regex engine
# is ICU, where those are Unicode-aware; the JVM's and Python's (in this
# form) are not. Spelling the classes out is what makes the three agree —
# and the Kotlin port copies these patterns character for character.
_WORD = "A-Za-z0-9_"
_ISO_DATE = re.compile(
    r"(?<![A-Za-z0-9_])[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9:.]+Z?)?(?![A-Za-z0-9_])"
)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_NAMED_DATE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[0-9]{1,2}(?:st|nd|rd|th)?[ \t]+" + _MONTH
    + r"(?:[ \t]+[0-9]{4})?"
    + r"|(?<![A-Za-z0-9_])" + _MONTH + r"[ \t]+[0-9]{1,2}(?:st|nd|rd|th)?(?:,?[ \t]+[0-9]{4})?"
)
_ONE_REP_MAX = re.compile(r"(?i)(?<![A-Za-z0-9_])e?1rm(?![A-Za-z0-9_])")
_LIST_MARKER = re.compile(r"(?m)^[ \t]*[0-9]+[.)][ \t]")
_HOURS_MINUTES = re.compile(r"(?<![A-Za-z0-9_])([0-9]+)h[ \t]*([0-9]+)m(?![A-Za-z0-9_])")
_NUMBER_BODY = (
    r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?((?:[Kk]|M)(?![A-Za-z])|%)?(?![0-9])"
)
# In an answer, "4x5" is two figures, so only a digit or a point may precede one.
_NUMBER = re.compile(r"(?<![0-9.])" + _NUMBER_BODY)
# In tool results a digit inside an identifier — acute_7d, best_e1rm_kg — is
# part of a key, not a value, so a letter or underscore may not precede one.
_SOURCE_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])" + _NUMBER_BODY)
_UNIT = re.compile(r"[ \t]*([A-Za-z]+)")


@dataclass(frozen=True)
class Claim:
    text: str
    mantissa: Decimal
    decimals: int
    suffix: str | None
    unit: str | None = None


@dataclass
class Grounding:
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unverified

    def as_dict(self) -> dict:
        return {"ok": self.ok, "verified": self.verified, "unverified": self.unverified}


def _strip_common(text: str) -> str:
    text = _ISO_DATE.sub(" ", text)
    return _ONE_REP_MAX.sub(" ", text)


def claims_in(answer: str) -> list[Claim]:
    """Every figure the answer states, in order, each once."""
    text = _strip_common(answer)
    text = _NAMED_DATE.sub(" ", text)
    text = _LIST_MARKER.sub(" ", text)

    found: list[Claim] = []

    def hours_minutes(match: re.Match) -> str:
        minutes = int(match.group(1)) * 60 + int(match.group(2))
        found.append(Claim(match.group(0), Decimal(minutes), 0, None, "min"))
        return " "

    text = _HOURS_MINUTES.sub(hours_minutes, text)

    for match in _NUMBER.finditer(text):
        whole, fraction, suffix = match.group(1), match.group(2), match.group(3)
        written = whole.replace(",", "") + (f".{fraction}" if fraction else "")
        unit_match = _UNIT.match(text, match.end())
        found.append(
            Claim(
                text=match.group(0),
                mantissa=Decimal(written),
                decimals=len(fraction) if fraction else 0,
                suffix=suffix,
                unit=unit_match.group(1).lower() if unit_match else None,
            )
        )

    unique: dict[str, Claim] = {}
    for claim in found:
        unique.setdefault(claim.text, claim)
    return list(unique.values())


def pool_from(sources: list[str]) -> list[float]:
    """Every number in the tool results and the question, plus the constants."""
    values: list[float] = list(DEFINITIONAL)
    for source in sources:
        text = _strip_common(source)
        for match in _SOURCE_NUMBER.finditer(text):
            whole, fraction = match.group(1), match.group(2)
            values.append(float(whole.replace(",", "") + (f".{fraction}" if fraction else "")))
    return values


def _multipliers(suffix: str | None) -> tuple[float, ...]:
    if suffix in ("K", "k"):
        return (1000.0,)
    if suffix == "M":
        return (1_000_000.0,)
    if suffix == "%":
        return (1.0, 0.01)
    return (1.0,)


def _precision(claim: Claim) -> int:
    # A big round number is an approximation: "10,000 steps" means about ten
    # thousand, not exactly. Only from a thousand up — "10 reps" means ten.
    if claim.decimals == 0 and claim.suffix is None and claim.mantissa >= 1000:
        digits = str(int(claim.mantissa))
        return -(len(digits) - len(digits.rstrip("0")))
    return claim.decimals


def _rounds_to(value: float, places: int, target: Decimal) -> bool:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_EVEN) == target


def _rescalings(claim: Claim) -> tuple[tuple[int, int], ...]:
    return (_AS_WRITTEN, *UNIT_RESCALINGS.get(claim.unit or "", ()))


def is_grounded(claim: Claim, pool: list[float]) -> bool:
    places = _precision(claim)
    for source in pool:
        for multiply, divide in _rescalings(claim):
            for multiplier in _multipliers(claim.suffix):
                value = source * multiply / divide / multiplier
                if _rounds_to(value, places, claim.mantissa):
                    return True
    return False


def check(answer: str, sources: list[str]) -> Grounding:
    pool = pool_from(sources)
    result = Grounding()
    for claim in claims_in(answer):
        (result.verified if is_grounded(claim, pool) else result.unverified).append(claim.text)
    return result


# --------------------------------------------------------------------------
# What the harness says back to the model
# --------------------------------------------------------------------------

# Marks a message the harness sent, so it is never counted as evidence: the
# correction quotes the unverified figures back, and counting it would let a
# retry verify a figure simply by repeating it. Exported with the body for the
# Android coach, which must send exactly the same words.
CORRECTION_PREFIX = "[Grounding check] "
CORRECTION_BODY = (
    "Your answer quoted {figures}, which no tool returned in this conversation "
    "and the athlete did not say. Call a tool that returns them, or rewrite the "
    "answer without them. Do not estimate, recall or compute figures."
)


def correction(grounding: Grounding) -> str:
    return CORRECTION_PREFIX + CORRECTION_BODY.format(figures=", ".join(grounding.unverified))


def describe(grounding: Grounding) -> str:
    total = len(grounding.verified) + len(grounding.unverified)
    if total == 0:
        return "no figures to check"
    if grounding.ok:
        return f"{total} of {total} traced"
    return f"{len(grounding.unverified)} of {total} not found: " + ", ".join(grounding.unverified)
