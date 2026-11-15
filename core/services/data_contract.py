"""Data Contract — standard envelope for all external data.

Every provider response that enters the system should be wrappable in a
DataContract so that source, units, time, geometry and quality are
explicit and traceable. Image/tile data (GIBS) uses the same envelope
with ``kind='imagery'`` and no numeric ``value``.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

QUALITY_VALID = 'valid'
QUALITY_PARTIAL = 'partial'
QUALITY_STALE = 'stale'
QUALITY_INVALID = 'invalid'


@dataclass
class DataContract:
    """Standard provenance envelope for one data payload."""
    source: str                       # 'NASA POWER', 'FAOSTAT', 'NASA GIBS', 'NASA CMR'
    dataset_id: str                   # e.g. 'power_daily_point', 'fao_qcl'
    kind: str = 'numeric'             # 'numeric' | 'imagery' | 'metadata' | 'statistics'
    parameter: str = ''               # e.g. 'T2M', 'yield'
    value: Optional[float] = None     # numeric value (None for imagery/series)
    original_unit: str = ''
    normalized_unit: str = ''
    lat: Optional[float] = None
    lon: Optional[float] = None
    temporal_resolution: str = ''     # 'daily', 'hourly', 'annual', '8day', ...
    spatial_resolution: str = ''      # 'point', '0.5deg', 'country', ...
    observed_at: str = ''             # data's own timestamp (ISO)
    retrieved_at: str = ''            # when we fetched it (ISO)
    quality_status: str = QUALITY_VALID
    limitations: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def now(cls, **kw):
        kw.setdefault('retrieved_at', datetime.now(timezone.utc).isoformat())
        return cls(**kw)


def validate_contract(c: DataContract, *, max_age_days: int = 30,
                      expected_unit: str = None) -> list:
    """Return list of quality issues found in a contract.

    Empty list = fully valid. Issues are strings; caller maps them to
    quality_status. Never raises — validation must not break pipelines.
    """
    issues = []
    # required fields
    if not c.source:
        issues.append('missing_source')
    if not c.dataset_id:
        issues.append('missing_dataset_id')
    if not c.retrieved_at:
        issues.append('missing_retrieved_at')
    # coordinate sanity
    if c.lat is not None and not (-90 <= c.lat <= 90):
        issues.append('lat_out_of_range')
    if c.lon is not None and not (-180 <= c.lon <= 180):
        issues.append('lon_out_of_range')
    # unit check
    if expected_unit and c.original_unit and c.original_unit != expected_unit:
        issues.append('unit_mismatch')
    # staleness
    if c.retrieved_at:
        try:
            rt = datetime.fromisoformat(c.retrieved_at.replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - rt).days
            if age > max_age_days:
                issues.append('stale_data')
        except ValueError:
            issues.append('invalid_retrieved_at')
    # numeric sanity
    if c.kind == 'numeric' and c.value is not None:
        if c.parameter in ('T2M', 'T2M_MAX', 'T2M_MIN') and not (-90 <= c.value <= 60):
            issues.append('value_out_of_range')
        if c.parameter == 'PRECTOTCORR' and c.value < 0:
            issues.append('value_out_of_range')
    return issues


def quality_from_issues(issues: list) -> str:
    """Map validation issues to a single quality_status."""
    if not issues:
        return QUALITY_VALID
    if 'stale_data' in issues:
        return QUALITY_STALE
    hard = {'missing_source', 'missing_dataset_id', 'lat_out_of_range',
            'lon_out_of_range', 'unit_mismatch', 'value_out_of_range',
            'invalid_retrieved_at'}
    if any(i in hard for i in issues):
        return QUALITY_INVALID
    return QUALITY_PARTIAL
