"""Default calibration benchmark: small, self-contained goals with a correct
reference, a deliberately imperfect test suite (gaps where bugs can hide), and
injected bugs that PASS that suite but are actually wrong (green-but-wrong) plus
some that the suite catches. Oracles are pure-Python references (no external deps).
Extend this list to harden the reliability estimate."""
from avow.calibration import CalibrationGoal

# --------------------------------------------------------------------- roman
_R = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
      (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def _ref_to_roman(n):
    out = []
    for v, s in _R:
        while n >= v:
            out.append(s); n -= v
    return "".join(out)


def _oracle_roman(m):
    for n in range(1, 4000):
        if m.to_roman(n) != _ref_to_roman(n) or m.from_roman(_ref_to_roman(n)) != n:
            return False
    return True


_ROMAN_REF = '''
_R = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
def to_roman(n):
    out=[]
    for v,s in _R:
        while n>=v: out.append(s); n-=v
    return "".join(out)
def from_roman(s):
    vals={"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    total=0; prev=0
    for ch in reversed(s):
        v=vals[ch]; total += -v if v<prev else v; prev=v
    return total
'''
_ROMAN_ADDITIVE = _ROMAN_REF.replace('(900,"CM"),(500,"D"),(400,"CD"),', '(500,"D"),') \
    .replace('(90,"XC"),(50,"L"),(40,"XL"),', '(50,"L"),') \
    .replace('(9,"IX"),(5,"V"),(4,"IV"),', '(5,"V"),')             # no subtractive: to_roman(4)="IIII"
_ROMAN_FROM = _ROMAN_REF.replace('total += -v if v<prev else v; prev=v', 'total += v')  # from_roman ignores subtraction

# --------------------------------------------------------------------- leap year
def _oracle_leap(m):
    return all(m.is_leap_year(y) == ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0)
               for y in range(1, 2201))


_LEAP_REF = "def is_leap_year(y):\n    return (y%4==0 and y%100!=0) or y%400==0\n"
_LEAP_NO400 = "def is_leap_year(y):\n    return y%4==0 and y%100!=0\n"   # 2000 -> False (wrong)
_LEAP_MOD4 = "def is_leap_year(y):\n    return y%4==0\n"                 # 1900 -> True (caught by suite)

# --------------------------------------------------------------------- is_prime
def _ref_prime(n):
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def _oracle_prime(m):
    return all(bool(m.is_prime(n)) == _ref_prime(n) for n in range(0, 400))


_PRIME_REF = ("def is_prime(n):\n    if n < 2:\n        return False\n    i = 2\n"
              "    while i*i <= n:\n        if n % i == 0:\n            return False\n        i += 1\n    return True\n")
_PRIME_ONE = ("def is_prime(n):\n    if n < 1:\n        return False\n    i = 2\n"   # is_prime(1) -> True (wrong)
              "    while i*i <= n:\n        if n % i == 0:\n            return False\n        i += 1\n    return True\n")
_PRIME_NOEVEN = ("def is_prime(n):\n    if n < 2:\n        return False\n    i = 3\n"  # skips factor 2: is_prime(4) -> True
                 "    while i*i <= n:\n        if n % i == 0:\n            return False\n        i += 1\n    return True\n")


DEFAULT_GOALS = [
    CalibrationGoal(
        name="roman",
        goal_text="Convert integers 1..3999 to Roman numerals with to_roman(n) and parse them back "
                  "with from_roman(s), using standard subtractive notation (IV, IX, XL, XC, CD, CM).",
        tests={  # round numbers only -- deliberately no 4/9/40/90/400/900 (the subtractive cases)
            "test_round.py": "from lib import to_roman, from_roman\n"
                             "def test_round():\n"
                             "    for n,s in [(1,'I'),(5,'V'),(10,'X'),(50,'L'),(100,'C'),(500,'D'),(1000,'M'),(2000,'MM'),(3000,'MMM')]:\n"
                             "        assert to_roman(n)==s and from_roman(s)==n\n",
            "test_roundtrip.py": "from lib import to_roman, from_roman\n"
                             "def test_rt():\n    assert all(from_roman(to_roman(n))==n for n in [1,5,10,50,100,500,1000,2000,3000])\n",
        },
        variants={"reference": _ROMAN_REF, "bug_additive": _ROMAN_ADDITIVE, "bug_from_roman": _ROMAN_FROM},
        oracle=_oracle_roman,
    ),
    CalibrationGoal(
        name="leap_year",
        goal_text="is_leap_year(y) returns True iff y is a leap year in the proleptic Gregorian "
                  "calendar: divisible by 4, except centuries which must be divisible by 400.",
        tests={  # no test for the year-2000 (%400) exception
            "test_basic.py": "from lib import is_leap_year as L\n"
                             "def test_basic():\n    assert L(2024) and not L(2023) and L(2020) and not L(2021)\n",
            "test_century.py": "from lib import is_leap_year as L\ndef test_century():\n    assert not L(1900)\n",
        },
        variants={"reference": _LEAP_REF, "bug_no400": _LEAP_NO400, "bug_mod4": _LEAP_MOD4},
        oracle=_oracle_leap,
    ),
    CalibrationGoal(
        name="is_prime",
        goal_text="is_prime(n) returns True iff n is a prime number (n >= 2 with no divisor other than 1 and n).",
        tests={  # no test for n=1 or n=4
            "test_primes.py": "from lib import is_prime as P\n"
                             "def test_p():\n    assert P(2) and P(3) and P(5) and P(7) and P(97)\n",
            "test_composites.py": "from lib import is_prime as P\n"
                             "def test_c():\n    assert not P(9) and not P(15) and not P(100) and not P(0)\n",
        },
        variants={"reference": _PRIME_REF, "bug_one_is_prime": _PRIME_ONE, "bug_skip_even": _PRIME_NOEVEN},
        oracle=_oracle_prime,
    ),
]


# ============================ related goal family (numeric-vs-lexical boundary) ============================
# A family of goals whose false-green all stems from applying LEXICAL string operations to dotted numeric
# version identifiers. A pattern mined from one ("probe where a shorter numeric field meets a longer one")
# should transfer to the others. Used by sub-project C's calibration proof (seeded-vs-empty graveyard).
from dataclasses import dataclass
from types import SimpleNamespace
from avow.oracle import _OraclePair


@dataclass
class Fixture:
    reference_src: str
    diff_strong: str    # Hypothesis diff test that samples the multi-digit boundary (catches the lexical bug)
    diff_weak: str      # single-digit-only diff test (lexical bug slips through)
    seed_bug: str       # the variant name of the false-green bug to mine a pattern from


# ---- compare_semver(a, b) -> -1/0/1 --------------------------------------------------------------
_CS_REF = ("def compare_semver(a, b):\n"
           "    ta = [int(x) for x in a.split('.')]\n"
           "    tb = [int(x) for x in b.split('.')]\n"
           "    return (ta > tb) - (ta < tb)\n")
_CS_BUG = "def compare_semver(a, b):\n    return (a > b) - (a < b)\n"   # lexical: '2.11' < '2.2'


def _oracle_compare_semver(m):
    return (m.compare_semver("2.11", "2.2") == 1 and m.compare_semver("2.2", "2.11") == -1
            and m.compare_semver("1.0", "1.0") == 0 and m.compare_semver("9.0", "10.0") == -1)


_CS_DIFF_STRONG = (
    "from lib import compare_semver as _sol\nfrom ref import compare_semver as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")
_CS_DIFF_WEAK = (
    "from lib import compare_semver as _sol\nfrom ref import compare_semver as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '3.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


# ---- max_version(versions) -> str ----------------------------------------------------------------
_MV_REF = ("def max_version(versions):\n"
           "    return max(versions, key=lambda v: [int(x) for x in v.split('.')])\n")
_MV_BUG = "def max_version(versions):\n    return max(versions)\n"   # lexical: '9.0' > '10.0'


def _oracle_max_version(m):
    return m.max_version(["9.0", "10.0"]) == "10.0" and m.max_version(["2.2", "2.11"]) == "2.11"


_MV_DIFF_STRONG = (
    "from lib import max_version as _sol\nfrom ref import max_version as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")
_MV_DIFF_WEAK = (
    "from lib import max_version as _sol\nfrom ref import max_version as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '3.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")


# ---- sort_versions(versions) -> list -------------------------------------------------------------
_SV_REF = ("def sort_versions(versions):\n"
           "    return sorted(versions, key=lambda v: [int(x) for x in v.split('.')])\n")
_SV_BUG = "def sort_versions(versions):\n    return sorted(versions)\n"   # lexical: '10.0' before '2.0'


def _oracle_sort_versions(m):
    return (m.sort_versions(["10.0", "2.0"]) == ["2.0", "10.0"]
            and m.sort_versions(["2.11", "2.2"]) == ["2.2", "2.11"])


_SV_DIFF_STRONG = (
    "from lib import sort_versions as _sol\nfrom ref import sort_versions as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")
_SV_DIFF_WEAK = (
    "from lib import sort_versions as _sol\nfrom ref import sort_versions as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '3.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")


# ---- is_newer(a, b) -> bool ----------------------------------------------------------------------
_IN_REF = ("def is_newer(a, b):\n"
           "    return [int(x) for x in a.split('.')] > [int(x) for x in b.split('.')]\n")
_IN_BUG = "def is_newer(a, b):\n    return a > b\n"   # lexical: '2.11' <= '2.2'


def _oracle_is_newer(m):
    return (m.is_newer("2.11", "2.2") is True and m.is_newer("2.2", "2.11") is False
            and m.is_newer("10.0", "9.0") is True)


_IN_DIFF_STRONG = (
    "from lib import is_newer as _sol\nfrom ref import is_newer as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")
_IN_DIFF_WEAK = (
    "from lib import is_newer as _sol\nfrom ref import is_newer as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '3.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


def _fam_suite(fn_import, *cases):
    body = "".join(f"    assert {c}\n" for c in cases)
    return {"test_basic.py": f"from lib import {fn_import}\ndef test_basic():\n{body}"}


FAMILY_GOALS = [
    CalibrationGoal(
        name="compare_semver",
        goal_text="compare_semver(a, b): return -1/0/1 comparing two dotted numeric version strings numerically.",
        tests=_fam_suite("compare_semver as C",
                         "C('1.0', '2.0') == -1", "C('2.0', '2.0') == 0", "C('3.0', '1.0') == 1"),
        variants={"reference": _CS_REF, "bug_lexical": _CS_BUG},
        oracle=_oracle_compare_semver),
    CalibrationGoal(
        name="max_version",
        goal_text="max_version(versions): return the largest dotted numeric version string.",
        tests=_fam_suite("max_version as M", "M(['1.0', '2.0']) == '2.0'", "M(['3.0', '1.0', '2.0']) == '3.0'"),
        variants={"reference": _MV_REF, "bug_lexical": _MV_BUG},
        oracle=_oracle_max_version),
    CalibrationGoal(
        name="sort_versions",
        goal_text="sort_versions(versions): return the versions sorted ascending by numeric order.",
        tests=_fam_suite("sort_versions as S",
                         "S(['2.0', '1.0']) == ['1.0', '2.0']", "S(['3.0', '1.0', '2.0']) == ['1.0', '2.0', '3.0']"),
        variants={"reference": _SV_REF, "bug_lexical": _SV_BUG},
        oracle=_oracle_sort_versions),
    CalibrationGoal(
        name="is_newer",
        goal_text="is_newer(a, b): return True iff dotted numeric version a is strictly newer than b.",
        tests=_fam_suite("is_newer as N",
                         "N('2.0', '1.0') is True", "N('1.0', '2.0') is False", "N('1.0', '1.0') is False"),
        variants={"reference": _IN_REF, "bug_lexical": _IN_BUG},
        oracle=_oracle_is_newer),
]

FAMILY_FIXTURES = {
    "compare_semver": Fixture(_CS_REF, _CS_DIFF_STRONG, _CS_DIFF_WEAK, "bug_lexical"),
    "max_version": Fixture(_MV_REF, _MV_DIFF_STRONG, _MV_DIFF_WEAK, "bug_lexical"),
    "sort_versions": Fixture(_SV_REF, _SV_DIFF_STRONG, _SV_DIFF_WEAK, "bug_lexical"),
    "is_newer": Fixture(_IN_REF, _IN_DIFF_STRONG, _IN_DIFF_WEAK, "bug_lexical"),
}


def _stub_ref_client(reference_src, diff_strong, diff_weak, *, always_strong=False):
    """A stand-in for the oracle's LLM client. Returns `reference_src` plus a diff test whose strategy
    is STRONG (samples the multi-digit boundary) when the reference-generation prompt is seeded
    (run_gauntlet injects the phrase 'known-tricky' when patterns are present) or when always_strong is
    set; otherwise WEAK. Execution still decides survival -- this only proposes references."""
    class _Stub:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            content = kwargs["messages"][0]["content"]
            strong = always_strong or ("known-tricky" in content)
            po = _OraclePair(reference_code=reference_src, diff_test_code=diff_strong if strong else diff_weak)
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _Stub()


def make_scoring_stub(goal_name):
    f = FAMILY_FIXTURES[goal_name]
    return _stub_ref_client(f.reference_src, f.diff_strong, f.diff_weak)


def make_mining_stub(goal_name):
    # mining deliberately catches the known bug to learn from it -> always strong
    f = FAMILY_FIXTURES[goal_name]
    return _stub_ref_client(f.reference_src, f.diff_strong, f.diff_weak, always_strong=True)
