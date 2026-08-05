"""Framework-independent ShieldFont domain contracts."""

from shieldfont.domain.manifest import BuildManifest
from shieldfont.domain.ruleset import (
    CanonicalRule,
    NormalizedRuleset,
    ScopeRecord,
    build_ruleset,
)

__all__ = [
    "BuildManifest",
    "CanonicalRule",
    "NormalizedRuleset",
    "ScopeRecord",
    "build_ruleset",
]
