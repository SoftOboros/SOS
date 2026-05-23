"""Lint rule modules for the SOS-01 SCXML linter.

Each module implements one or more ``SCXML-LINT-NNN`` rules from
``docs/concepts/SOS-01-CONCEPTS.md`` §6. Rules expose a single
``check(ctx) -> list[Finding]`` entry point and are registered with
``main.py``'s rule registry.
"""
