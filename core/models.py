"""Data Intelligence Infrastructure — provenance & quality tracking.

Additive models for Phase 1: every external data point can be traced
to its source, dataset, retrieval time and quality status.
"""
from django.db import models


class DataSource(models.Model):
    """External data provider (NASA POWER, FAOSTAT, GIBS, CMR...)."""
    key = models.CharField(max_length=40, unique=True)  # e.g. 'nasa_power'
    name = models.CharField(max_length=120)
    base_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return self.name


class Dataset(models.Model):
    """A dataset/collection within a source (e.g. POWER daily point)."""
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='datasets')
    key = models.CharField(max_length=80)  # e.g. 'power_daily_point'
    name = models.CharField(max_length=160, blank=True)
    temporal_resolution = models.CharField(max_length=40, blank=True)  # daily/hourly/annual
    spatial_resolution = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('source', 'key')
        ordering = ['source', 'key']

    def __str__(self):
        return f'{self.source.key}/{self.key}'


class SavedAnalysis(models.Model):
    """Saved scientific analysis — reproducible with params + dataset version."""
    owner_key = models.CharField(max_length=120, db_index=True,
                                 help_text='session/user key — no auth system yet')
    title = models.CharField(max_length=200, blank=True)
    analysis_type = models.CharField(max_length=40,
                                     choices=[('power', 'POWER'), ('catalog', 'CMR Catalog'),
                                              ('timeseries', 'Time Series'), ('compare', 'Satellite Compare'),
                                              ('custom', 'Custom')])
    geo = models.JSONField(default=dict, blank=True)          # lat/lon/bbox/region
    time_range = models.JSONField(default=dict, blank=True)   # start/end/baseline
    data_source = models.CharField(max_length=80, blank=True) # NASA POWER / CMR / FAOSTAT
    parameters = models.JSONField(default=dict, blank=True)   # request params
    viz_settings = models.JSONField(default=dict, blank=True) # layers/opacity/etc
    dataset_version = models.CharField(max_length=120, blank=True)
    result_metadata = models.JSONField(default=dict, blank=True)  # summary of last run
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.analysis_type}:{self.title or self.id}'


class DataSnapshot(models.Model):
    """Immutable record of one fetched data payload with provenance."""
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='snapshots')
    request_key = models.CharField(max_length=200, db_index=True)  # cache/request identifier
    observed_at = models.DateTimeField(null=True, blank=True)      # data's own timestamp
    retrieved_at = models.DateTimeField(auto_now_add=True)
    quality_status = models.CharField(max_length=20, default='valid',
                                      choices=[('valid', 'معتبر'), ('partial', 'ناقص'),
                                               ('stale', 'قدیمی'), ('invalid', 'نامعتبر')])
    limitations = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # lat/lon/params/units summary
    payload_ref = models.CharField(max_length=300, blank=True)  # cache key or URL, not the payload itself

    class Meta:
        indexes = [models.Index(fields=['dataset', 'retrieved_at'])]
        ordering = ['-retrieved_at']

    def __str__(self):
        return f'{self.dataset} @ {self.retrieved_at:%Y-%m-%d %H:%M}'


class DataIngestionLog(models.Model):
    """Audit log of every external fetch attempt (success or failure)."""
    source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='logs')
    dataset_key = models.CharField(max_length=80, blank=True)
    request_url = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20,
                              choices=[('success', 'موفق'), ('error', 'خطا'), ('cached', 'کش'),
                                       ('stale', 'کش منقضی')])
    http_status = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source.key} {self.status} @ {self.created_at:%Y-%m-%d %H:%M}'
