"""Combine per-profile evidence for one object into one stable record.

Rendering each deployment profile yields one fact set per profile for the same
Kubernetes object. Reports need one record under the object's stable identity:
a protective fact holds only if it holds in every profile, any other boolean is
a risk that counts if any profile has it, and other values keep their type when
profiles agree and are listed when they differ. The record cites the manifest of
the first failing profile, so its excerpt and source path describe the same
thing.
"""

from collections.abc import Iterable, Mapping

from infra_fleet_advisor.core.evidence import Evidence

FactValue = bool | str | int


def combine_profiles(
    per_profile: Mapping[str, Iterable[Evidence]], protective: frozenset[str]
) -> tuple[Evidence, ...]:
    grouped: dict[str, list[tuple[str, Evidence]]] = {}
    for profile, items in per_profile.items():
        for item in items:
            grouped.setdefault(item.evidence_id, []).append((profile, item))

    combined = []
    for evidence_id in sorted(grouped):
        entries = sorted(grouped[evidence_id], key=lambda entry: entry[0])
        first = entries[0][1]
        fact: dict[str, FactValue] = {}
        for key, value in first.fact.items():
            values = [item.fact.get(key) for _profile, item in entries]
            if key in protective:
                fact[key] = all(v is True for v in values)
            elif isinstance(value, bool):
                fact[key] = any(v is True for v in values)
            elif all(v == value for v in values):
                fact[key] = value
            else:
                fact[key] = ", ".join(sorted({str(v) for v in values}))
        failing = [
            profile
            for profile, item in entries
            if any(item.fact.get(key) is not True for key in protective & set(item.fact))
        ]
        profiles = [profile for profile, _item in entries]
        fact["profiles"] = ", ".join(profiles)
        fact["failing_profiles"] = ", ".join(failing)
        shown = next((item for profile, item in entries if profile in failing), first)
        combined.append(
            Evidence(
                evidence_id=evidence_id,
                kind=first.kind,
                source_path=shown.source_path,
                locator=first.locator,
                excerpt=f"[{', '.join(failing or profiles)}] {shown.excerpt}"[:280],
                fact=fact,
                collector_id=first.collector_id,
                collector_version=first.collector_version,
            )
        )
    return tuple(combined)
