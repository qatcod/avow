# Contributing to Avow

Thanks for considering a contribution. Avow is a verifier for AI-generated code,
so the bar for changes to the verification path is high: a change to how confidence
is computed has to be *measured*, not argued.

## Getting set up

Avow needs Python 3.11 or newer.

```bash
git clone https://github.com/qatcod/avow
cd avow
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q          # the full suite (a few minutes; mutation tests are slow)
```

The builder drives the [`claude`](https://claude.com/claude-code) CLI (it uses your
login); the LLM verification hooks use the `anthropic` SDK and read `ANTHROPIC_API_KEY`.
The test suite runs fully offline with stubs, so you do not need either to run the tests.

## How the code is organized

- `avow/` is the package. `loop.py` is the build-and-verify loop; the verification
  signals live in `mutation.py`, `backtranslation.py` (intent), `oracle.py`,
  `properties.py`, and `confidence.py`; `calibration.py` and `realcorpus.py` measure
  whether the confidence number is trustworthy.
- `tests/` mirrors the package. Every module has tests; the suite is the gate.
- `docs/specs/` and `docs/plans/` hold the per-feature design docs.

## Making a change

1. Open an issue first for anything non-trivial, so we can agree on the approach.
2. Write a test that fails, then make it pass. New behavior needs a test.
3. Keep the change focused. One logical change per pull request.
4. Run the full suite locally (`python -m pytest -q`) and make sure it is green.
5. If you touch the confidence path, run `avow calibrate` before and after and put
   the numbers in the PR. A confidence change that does not report its effect on the
   reliability curve will not be merged.

## Pull request conventions

- Start the PR title with a conventional-commit prefix: `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, or `chore:`.
- Keep the description short and concrete: what changed and why, plus test evidence.
- Sign off your commits (`git commit -s`) to certify you have the right to submit the
  work under the project license (the Developer Certificate of Origin,
  https://developercertificate.org).

## Licensing of contributions

Avow is licensed under Apache-2.0 (see `LICENSE`). By submitting a contribution you
agree that it is provided under the same license.
