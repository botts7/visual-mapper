# Forward Development Plan

This plan keeps Visual Mapper stable while allowing safe, predictable evolution.

## Goals
- Keep `main` stable and deployable.
- Maintain a tested runtime baseline (Python 3.11 today).
- Add newer runtimes only when dependencies are ready.
- Make upgrades reproducible and easy to validate.

## Supported Runtime Baseline
- **Primary runtime:** Python 3.11 (CI and releases).
- **Next runtime target:** Python 3.12 (enable after dependencies are validated).

## Dependency Strategy
- Keep `backend/requirements.txt` as the canonical list.
- Pin the baseline using constraints:
  - `backend/constraints-3.11.txt` (current baseline).
- Optional features stay in separate files:
  - `backend/requirements-ml.txt` for ML features.
- Upgrade process:
  1) Update `requirements.txt`.
  2) Refresh constraints for the baseline runtime.
  3) Run CI and smoke tests.
  4) Document any breaking changes.

## CI and Release Gates
- CI runs on the baseline runtime only.
- Add a second runtime (3.12) once constraints and tests are green.
- Required checks for merging into `beta`:
  - Backend unit tests.
  - Basic API smoke tests.
- `main` only receives changes that have passed in `beta`.

## Branching Model
- Feature branches for changes.
- `beta` for integration and stabilization.
- `main` for release-ready code.

## Security Defaults
- Auth and CORS should be restrictive by default.
- Looser settings must be explicit via environment variables.

## Deprecation Policy
- Announce breaking changes in advance.
- Provide migration notes for data or API changes.
- Keep compatibility helpers for one minor release cycle when possible.
