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
