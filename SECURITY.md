# Security Policy

## Supported Versions

The HLP specification and this reference SDK are pre-1.0. Security fixes are
applied to the latest released version on `main`; older versions do not receive
backports.

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub
issues.

Report them privately through GitHub Security Advisories:

https://github.com/simplosophy/loops/security/advisories/new

Please include:

- a description of the vulnerability and its impact,
- steps to reproduce or a proof of concept,
- affected versions, if known.

You can expect an acknowledgement within 7 days. We will investigate, develop a
fix, and coordinate disclosure with you. Once a fix is released, we will
publish the advisory and credit the reporter unless you prefer to remain
anonymous.

## Scope Notes

The SDK's reference store implementations (`HumanLoopStore`,
`SQLiteHumanLoopStore`) and the HLP-industrial profile (CAS, idempotency,
outbox, audit chain) are a **reference profile** for embedding and evaluation,
not a multi-writer production backend. Deployments are responsible for their
own persistence hardening, authentication, and transport security.
