"""Build manifest skeleton and deterministic serialization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuildManifest:
    """Manifest contract published with every completed build."""

    project_id: str
    project_version: str
    tool_version: str
    source: Mapping[str, object]
    font: Mapping[str, object]
    scopes: Sequence[Mapping[str, object]]
    artifacts: Sequence[Mapping[str, object]]
    verification: Mapping[str, object]
    security: Mapping[str, object]
    profile: Mapping[str, object] | None = None
    build_id: str = ""

    def to_dict(self, *, include_build_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": "shieldfont-build/v1",
            "projectId": self.project_id,
            "projectVersion": self.project_version,
            "toolVersion": self.tool_version,
            "source": dict(self.source),
            "font": dict(self.font),
            "scopes": [dict(scope) for scope in self.scopes],
            "artifacts": [dict(artifact) for artifact in self.artifacts],
            "verification": dict(self.verification),
            "security": dict(self.security),
        }
        if self.profile is not None:
            payload["profile"] = dict(self.profile)
        if include_build_id:
            payload["buildId"] = self.build_id
        return payload

    def to_json(self) -> str:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        project_version: str,
        tool_version: str,
        source: Mapping[str, object],
        font: Mapping[str, object],
        scopes: Sequence[Mapping[str, object]],
        artifacts: Sequence[Mapping[str, object]] = (),
        verification: Mapping[str, object] | None = None,
        security: Mapping[str, object] | None = None,
        profile: Mapping[str, object] | None = None,
    ) -> BuildManifest:
        draft = cls(
            project_id=project_id,
            project_version=project_version,
            tool_version=tool_version,
            source=source,
            font=font,
            scopes=tuple(scopes),
            artifacts=tuple(artifacts),
            verification=verification or {"status": "pending"},
            security=security
            or {
                "browserDecoderIncluded": False,
                "mappingEmbedded": False,
            },
            profile=profile,
        )
        serialized = json.dumps(
            draft.to_dict(include_build_id=False),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(
            project_id=draft.project_id,
            project_version=draft.project_version,
            tool_version=draft.tool_version,
            source=draft.source,
            font=draft.font,
            scopes=draft.scopes,
            artifacts=draft.artifacts,
            verification=draft.verification,
            security=draft.security,
            profile=draft.profile,
            build_id=f"sha256:{hashlib.sha256(serialized).hexdigest()}",
        )
