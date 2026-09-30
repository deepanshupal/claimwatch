# Architecture and process

Claimwatch is deliberately small: one run loads targets, calls one adapter per target, compares normalized observations with a local JSON snapshot, emits typed events, then sends those events through configured transports.

## Boundaries

- **Checkers** own network calls and normalize platform-specific evidence into `not_registered`, `taken`, `unknown`, or `error`.
- **Core** owns state, field-level diffs, and atomic writes. It does not know platform APIs or alert protocols.
- **Transports** consume the same event objects. Adding Slack, NATS, or another destination should not change a checker.
- **CLI** owns config parsing and environment-variable expansion.

The state file is intentionally plain JSON. It can live on a persistent volume, in an object-store sync step, or as a CI artifact. Claimwatch does not need a database or daemon.

## Adding a checker

1. Implement `Checker.check(Target) -> Observation` in `checkers.py`.
2. Return `unknown`, rather than `available`, when the platform's response is ambiguous.
3. Put the exact evidence URL and a short explanation in the observation.
4. Register the platform in `checker_for` and add fixture-based tests.
5. Document the source, expected cadence, and failure modes in the README.

## Operating principle

A missing profile page is a signal, not a guarantee that registration will succeed. Platform blocks, reserved names, registry gaps, and eventual consistency exist. Claimwatch alerts you to investigate; the registrar or platform's own claim flow is authoritative.
