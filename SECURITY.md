# Security Policy

## Supported versions

Avow is pre-1.0 and moves quickly. Security fixes are applied to the `main`
branch; there are no long-term support branches yet.

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability.

Report it privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (Security tab -> Report a vulnerability), or contact the
maintainer through the address on the project's GitHub profile.

Please include enough detail to reproduce the issue. We aim to acknowledge a
report within a few days and will keep you informed as we work on a fix.

## Scope note

Avow runs code: it drives the `claude` CLI to generate code, executes generated
tests and solutions, and (when enabled) runs LLM-authored check commands. Treat a
Avow run with the same trust boundary as running any other untrusted code, and
run it in an isolated environment when the goal or inputs are not fully trusted.
This is a design property, not a vulnerability, but reports about ways the sandbox
boundary can be escaped unexpectedly are welcome.
