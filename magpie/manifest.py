"""Anti-drift checks for repo-canonical collections.

Drift is the real risk in a folder-of-files knowledge store: near-duplicate
store names for the same thing (``reach-strategy`` vs ``reach_strategy``), or the
same value landing under different keys. A folder can't stop this on its own — a
central registry can. ``collections/_manifest.json`` is that registry:

    {
      "stores": {
        "strategy": { "title": "Reach strategy", "keys": ["wedge", "mrr"] },
        "brand":    { "title": "Brand tokens" }
      }
    }

On ``magpie push`` we check scanned collections against it:

- A collection file whose slug is **not** declared is rejected (with a
  nearest-match suggestion) — creation must be deliberate.
- Two files whose slugs collapse to the same normalized form are rejected as
  near-duplicates, manifest or not.
- If a store declares ``keys``, document keys outside that list are **warned**
  about (soft — they don't block the push) so typo'd keys surface early.

Pure module: structures in, errors/warnings out, no filesystem or DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches


@dataclass
class DriftResult:
    errors: list[str] = field(default_factory=list)  # block the push
    warnings: list[str] = field(default_factory=list)  # surfaced, non-blocking

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_slug(slug: str) -> str:
    """Collapse a slug to its drift-comparison form: lowercase, separators
    stripped, so ``reach-strategy`` and ``reach_strategy`` compare equal."""
    return "".join(c for c in slug.lower() if c.isalnum())


def validate_manifest(manifest: object) -> list[str]:
    """Validate the manifest structure. Returns a list of error messages."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["_manifest.json must be a JSON object"]
    stores = manifest.get("stores")
    if not isinstance(stores, dict):
        return ["_manifest.json must have a 'stores' object"]
    for slug, spec in stores.items():
        if not isinstance(spec, dict):
            errors.append(f"Manifest store {slug!r} must be an object")
            continue
        keys = spec.get("keys")
        if keys is not None and not (
            isinstance(keys, list) and all(isinstance(k, str) for k in keys)
        ):
            errors.append(f"Manifest store {slug!r} 'keys' must be a list of strings")
    return errors


def check_drift(collections, manifest: dict | None) -> DriftResult:
    """Check scanned collections for drift against the manifest.

    ``collections`` is the list of scanned BundleCollection objects (anything
    with ``.slug`` and ``.documents``). ``manifest`` is the parsed manifest dict,
    or None when the bundle has no manifest.
    """
    result = DriftResult()

    # Near-duplicate slugs within the bundle — independent of the manifest.
    by_norm: dict[str, list[str]] = {}
    for col in collections:
        by_norm.setdefault(normalize_slug(col.slug), []).append(col.slug)
    for norm, slugs in by_norm.items():
        if len(slugs) > 1:
            result.errors.append(
                f"Near-duplicate collection slugs (same normalized form {norm!r}): "
                f"{', '.join(sorted(slugs))}. Pick one canonical name."
            )

    if manifest is None:
        return result

    structure_errors = validate_manifest(manifest)
    if structure_errors:
        result.errors.extend(structure_errors)
        return result

    stores: dict = manifest["stores"]
    declared = list(stores.keys())
    declared_norms = {normalize_slug(s) for s in declared}

    for col in collections:
        if col.slug in stores:
            spec = stores[col.slug]
            keys = spec.get("keys")
            if isinstance(keys, list):
                allowed = set(keys)
                for doc in col.documents:
                    if doc.key not in allowed:
                        result.warnings.append(
                            f"{col.slug}: key {doc.key!r} is not declared in the manifest"
                        )
            continue

        # Undeclared store — reject, suggesting the nearest declared slug.
        suggestion = ""
        close = get_close_matches(col.slug, declared, n=1, cutoff=0.6)
        if close:
            suggestion = f" Did you mean {close[0]!r}?"
        elif normalize_slug(col.slug) in declared_norms:
            match = next(s for s in declared if normalize_slug(s) == normalize_slug(col.slug))
            suggestion = f" Did you mean {match!r}? (separator/case differs)"
        result.errors.append(
            f"Collection {col.slug!r} is not declared in _manifest.json.{suggestion} "
            "Add it to the manifest to create it deliberately."
        )

    return result
