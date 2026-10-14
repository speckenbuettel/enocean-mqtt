# Project Versioning

## Objective

This document defines the canonical project versioning model.

The versioning system is intended to support:

- project evolution tracking
- runtime identification
- documentation traceability
- future release handling
- future CI/CD support
- future compatibility management

---

# Version Format

Starting on 2026-10-14, development and public releases share Semantic Versioning
(SemVer), beginning with `0.9.0`. Earlier dated versions remain historical.

Format:

```text
MAJOR.MINOR.PATCH
```

Examples:

```text
0.9.0
0.9.1
1.0.0
```

---

# Rationale

Version `0.9.0` is intended for initial public user testing before `1.0.0`.
Pre-1.0 APIs, MQTT structures and persistence schemas may still change; document
compatibility changes and migrations rather than implying a stability guarantee.
Use patch increments for compatible fixes and minor increments for new pre-1.0
milestones or incompatible changes. From 1.0.0 onward, incompatible public-contract
changes require a major increment, compatible features a minor increment and
compatible fixes a patch increment.

Store three non-negative decimal components without leading zeroes in VERSION;
do not include a `v` prefix. Git tags may use `v0.9.0`. The current build/export
validation supports plain release versions, not SemVer prerelease/build suffixes.
The historical `YYYY-MM-NNN` scheme is accepted only for old-source rebuilds and
export tests; it is not maintained as a parallel current project version.

---

# Canonical Version Source

The canonical project version shall be stored in:

```text
/VERSION
```

This file is the single source of truth for:

- runtime version reporting
- MQTT diagnostics
- startup logging
- future Docker labels
- future CI/CD support
- future OBS integration metadata

---

# Relationship to Document Versions

Project versions and document versions are intentionally separated.

The global project version defines the overall project and runtime revision.

Document versions define revisions of individual documents and are therefore independent from the global project version.

Document revision metadata does not override the root `VERSION` file. Internal
planning-document revisions are not runtime or public release versions.

## Python package metadata

Python distribution metadata requires a PEP 440-compatible version. The build
configuration derives it from `VERSION`: `0.9.0` remains `0.9.0`, without conversion
or an independently maintained package version. For historical dated sources,
`2026-08-003` becomes `2026.8.3` for compatibility with PEP 440.

`setup.py` validates the value for the standard setuptools build backend.
An absent, empty or malformed `VERSION` fails the build rather than silently
falling back to an unrelated package version. Source archives retain `VERSION`
so that rebuilding does not require Git or access to the development repository.

The runtime/API/MQTT report the canonical spelling from `VERSION`, now `0.9.0`.
The supported installation is a source checkout with the repository as working
directory. A wheel alone does not supply the complete configuration/profile tree
or the root `VERSION`; it is not yet a standalone gateway distribution.
