"""Tool Registry — controlled tool access for AI agents (Phase 6).

Every tool has: name, schema, permission check, input validation,
output validation, error handling and logging. Mutating tools require
explicit user confirmation before execution.
"""
import json
import logging
import time
from functools import wraps

from django.core.cache import cache

from .monitoring import record_tool_call

logger = logging.getLogger('agent.tools')


class ToolError(Exception):
    pass


class PermissionDenied(ToolError):
    pass


class ConfirmationRequired(ToolError):
    """Raised when a mutating tool needs user confirmation."""
    def __init__(self, tool_name, preview):
        super().__init__(f'confirmation required for {tool_name}')
        self.tool_name = tool_name
        self.preview = preview


class Tool:
    def __init__(self, name, description, fn, schema=None, mutating=False,
                 permission='read', owner_scoped=False):
        self.name = name
        self.description = description
        self.fn = fn
        self.schema = schema or {}
        self.mutating = mutating
        self.permission = permission  # 'read' | 'write'
        self.owner_scoped = owner_scoped

    def validate_input(self, params):
        """Schema validation — required fields + types."""
        params = params or {}
        for field, spec in self.schema.items():
            if spec.get('required') and field not in params:
                raise ToolError(f'missing required param: {field}')
            if field in params and spec.get('type'):
                v = params[field]
                t = spec['type']
                ok = (t == 'number' and isinstance(v, (int, float))) or \
                     (t == 'string' and isinstance(v, str)) or \
                     (t == 'bool' and isinstance(v, bool)) or \
                     (t == 'list' and isinstance(v, list))
                if not ok:
                    raise ToolError(f'invalid type for {field}: expected {t}')
        return params

    def validate_output(self, result):
        """Output validation — agent-facing payloads must be JSON-safe."""
        try:
            json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            raise ToolError(f'tool {self.name} returned non-serializable output: {e}')
        return result

    def permission_check(self, context):
        if self.permission == 'write' and getattr(context, 'read_only', False):
            raise PermissionDenied(f'tool {self.name} requires write permission')

    def run(self, params, context=None, confirmed=False):
        params = self.validate_input(params)
        if self.mutating and not confirmed:
            preview = {k: params.get(k) for k in list(params)[:6]}
            raise ConfirmationRequired(self.name, preview)
        t0 = time.time()
        try:
            result = self.fn(params, context=context)
        except ToolError:
            raise
        except Exception as e:
            logger.exception('tool %s failed', self.name)
            record_tool_call(self.name, ok=False)
            raise ToolError(f'tool {self.name} failed: {e}')
        elapsed = round((time.time() - t0) * 1000)
        logger.info('tool=%s owner=%s ms=%d', self.name,
                    getattr(context, 'owner_key', '?'), elapsed)
        record_tool_call(self.name, ok=True, ms=elapsed)
        return {'tool': self.name, 'result': self.validate_output(result), 'ms': elapsed}


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        self._tools[tool.name] = tool
        return tool

    def get(self, name):
        return self._tools.get(name)

    def list_tools(self, permission=None):
        return [{'name': t.name, 'description': t.description,
                 'mutating': t.mutating, 'permission': t.permission,
                 'schema': t.schema}
                for t in self._tools.values()
                if permission is None or t.permission == permission]

    def run(self, name, params, context=None, confirmed=False):
        tool = self.get(name)
        if tool is None:
            raise ToolError(f'unknown tool: {name}')
        # permission check
        tool.permission_check(context)
        return tool.run(params, context=context, confirmed=confirmed)


# ---------- Conversation Context ----------

class AgentContext:
    """Per-owner conversation context — never shared across owners."""
    def __init__(self, owner_key, read_only=False):
        self.owner_key = owner_key
        self.read_only = read_only
        self.active_farm_id = None
        self.active_field_id = None
        self.active_crop = None
        self.growth_stage = None
        self.current_task = None
        self.recent_observations = []
        self.history = []  # last N turns

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}

    @classmethod
    def from_dict(cls, owner_key, d):
        ctx = cls(owner_key)
        for k, v in (d or {}).items():
            if hasattr(ctx, k):
                setattr(ctx, k, v)
        return ctx


def get_context(owner_key, read_only=False):
    """Load context from cache (24h TTL)."""
    key = f'agent_ctx:{owner_key}'
    data = cache.get(key) or {}
    return AgentContext.from_dict(owner_key, data)


def save_context(ctx):
    cache.set(f'agent_ctx:{ctx.owner_key}', ctx.to_dict(), timeout=86400)


def update_context(owner_key, **fields):
    ctx = get_context(owner_key)
    for k, v in fields.items():
        if hasattr(ctx, k):
            setattr(ctx, k, v)
    save_context(ctx)
    return ctx
