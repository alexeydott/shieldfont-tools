"""Framework-independent ShieldFont domain contracts."""

from shieldfont.domain.manifest import BuildManifest
from shieldfont.domain.protection import (
    MappingContractSelection,
    derive_bundle_id,
    inventory_digest,
    nonce_metadata,
    select_versioned_mapping,
)
from shieldfont.domain.ruleset import (
    CanonicalRule,
    NormalizedRuleset,
    ScopeRecord,
    build_ruleset,
)

__all__ = [
    "BuildManifest",
    "CanonicalRule",
    "MappingContractSelection",
    "NormalizedRuleset",
    "ScopeRecord",
    "build_ruleset",
    "derive_bundle_id",
    "inventory_digest",
    "nonce_metadata",
    "select_versioned_mapping",
]
