"""Structured JSON logging formatter — no secrets, request-scoped fields."""
import json
import logging
from datetime import datetime, timezone

_SAFE_FIELDS = (
    'request_id', 'method', 'path', 'status', 'duration_ms', 'client_ip',
    'user_agent', 'farmer_id', 'tool', 'owner', 'error', 'source',
    'http_status', 'dataset', 'intent', 'ms',
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        for key in _SAFE_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload['exc_info'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)
