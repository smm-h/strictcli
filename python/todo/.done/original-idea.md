# Original Idea: The `cli` Package

Status: Proposed
Priority: High

## Vision

A general-purpose CLI framework for Python that replaces argparse. Claim the `cli` name on PyPI — the most obvious package name for the most common task in Python.

## Motivation

argparse is verbose, awkward, and produces bad help output. Every major CLI tool ends up building its own dispatch layer on top of it. rlsbl did this manually — hand-rolled argument parsing, no per-command help, a single monolithic help string. click and typer are better but heavy (click is 300+ files, typer depends on click).

The Python ecosystem needs a minimal, zero-dependency CLI library that:
- Makes subcommand dispatch trivial
- Generates per-command help automatically
- Handles value flags, boolean flags, and positional args cleanly
- Produces beautiful, aligned help output
- Is small enough to vendor into a single file

## Design Principles

- Zero dependencies
- Single module (or very small package)
- Decorator-based API (like click) but without the weight
- Automatic help generation from function signatures and docstrings
- First-class subcommand support with per-command help
- No magic — explicit is better than implicit

## First Consumer

rlsbl — replace its manual CLI dispatch (~300 lines in __init__.py) with this library. If it works for rlsbl's 16 commands with subcommands (monorepo has 9 subcommands), it works for anything.

## Name

`cli` on PyPI. Three letters. The most obvious name for the job. Available as of 2026-05-12.
