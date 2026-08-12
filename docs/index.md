---
title: strictcli
description: "strictcli is a strict CLI framework for Python, Go, and TypeScript: declare everything, infer nothing, and keep all three implementations byte-identical."
order: 0
---

# strictcli

A strict CLI framework with three first-class implementations -- Python, Go, and TypeScript -- kept in behavioral lockstep by a shared conformance suite.

Declare everything, infer nothing. Help text is mandatory on every app, group, command, flag, and argument. Types are limited to `str`, `bool`, `int`, and `float`, parsed strictly. Every command declares its effect on the world, and the framework derives consent and previewing from that declaration.

## Start here

- [Python quickstart](python-quickstart.md)
- [Go quickstart](go-quickstart.md)
- [TypeScript quickstart](typescript-quickstart.md)

## Guides

- [Architecture and internals](architecture.md) -- the parse pipeline, registration-time validation, and the schema format
- [Flag system](flag-system.md) -- flags, arguments, dependencies, mutex groups, and the reserved quartet
- [Conformance](conformance.md) -- how the three implementations are proven identical

## Reference

- [API reference](gen-index.md) -- every module in all three implementations
