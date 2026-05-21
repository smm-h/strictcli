# Six versions missing from PyPI and npm, undocumented

## Problem

strictcli versions 0.6.0, 0.6.1, 0.7.0, 0.7.1, 0.8.0, and 0.8.1 were tagged in git and have GitHub Releases, but never made it to PyPI or npm. The root cause was that PyPI Trusted Publishing rejects OIDC tokens from reusable workflows (`workflow_call`), and the monorepo publish router used `workflow_call`. This was fixed in rlsbl 0.38.0 (inline publish router), and 0.8.2+ publishes successfully.

PyPI has: 0.1.0, 0.1.1, 0.2.0, 0.3.0, 0.4.1, 0.5.0, 0.8.2, 0.8.3
npm has: the same set

## Impact

- Users who `pip install strictcli` jump from 0.5.0 to 0.8.2 with no explanation
- Anyone pinning to `>=0.6.0,<0.8` or similar gets no valid version
- The 0.8.2 changelog entry says "No user-facing changes" but from a PyPI perspective, 0.8.2 is the first version containing everything from 0.6.0 through 0.8.2

## What's needed

This gap cannot be fixed (PyPI does not allow re-uploading old versions). It should be documented:

- A note in the README or CHANGELOG explaining the gap and that 0.8.2 is effectively the first release containing features from the 0.6.x-0.8.x cycle
- Possibly a pinned note on the GitHub Releases for the affected versions indicating they were never published to registries
- Consumers that pin to minimum versions in the gap range should be updated (currently no consumers pin into this range, but future users might try)
