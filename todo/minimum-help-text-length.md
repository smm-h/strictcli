# Minimum CLI help text length validation

## Problem

Short CLI help texts (under ~50 chars) cause SEO warnings when selfdoc generates documentation from them. There is no validation at the strictcli level to enforce minimum length.

## Proposed solution

Add optional `min_help_length` configuration to strictcli's check system. When enabled, commands and flags with help text under the threshold produce a check failure. This catches short descriptions at definition time, not at doc-generation time.

## Effort

Small. Add a new check in the check system that iterates command/flag definitions and validates help text length.
