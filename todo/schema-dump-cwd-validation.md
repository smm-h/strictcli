# schema dump writes to CWD without validation

## Problem

`--dump-schema` writes `.strictcli/schema.json` relative to CWD without checking if an existing schema belongs to a different app. Running `safegit --dump-schema` from claudestream's directory overwrites claudestream's schema with safegit's, corrupting downstream tools (selfdoc gen generates docs for the wrong app).

## Affected code

- Go: `strictcli.go` `writeSchema` function -- uses `filepath.Join(".", ".strictcli")`
- Python: `strictcli/__init__.py` -- uses `os.path.join(os.getcwd(), ".strictcli")`

## Fix

Before writing, check if `.strictcli/schema.json` already exists and if its `name` field differs from the current app's name. If mismatch, hard error explaining that the CWD contains a schema for a different app.
