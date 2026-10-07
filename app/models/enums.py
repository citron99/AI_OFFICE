from enum import StrEnum


class GrantScope(StrEnum):
    """Data scopes a step grant may cover: agents read data only through grants."""

    TASK_TEXT = "task_text"
    ATTACHMENTS = "attachments"
    KNOWLEDGE = "knowledge"
    ACCOUNTING = "accounting"


class AgentType(StrEnum):
    ORCHESTRATOR = "orchestrator"
    ACCOUNTANT = "accountant"
    LAWYER = "lawyer"
    SECURITY = "security"


class TaskCategory(StrEnum):
    ACCOUNTING = "accounting"
    LEGAL = "legal"
    SECURITY = "security"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"


class TaskState(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    CLASSIFYING = "classifying"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_SOURCE = "waiting_source"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    FAILED_SAFE = "failed_safe"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecision(StrEnum):
    """Deterministic Policy Gate outcomes (TZ V2.1 section 7.2)."""

    ALLOW_READ = "allow_read"
    ALLOW_DRAFT = "allow_draft"
    REQUIRE_OWNER_APPROVAL = "require_owner_approval"
    DENY = "deny"
    ESCALATE = "escalate"
    OWNER_ONLY_OUTSIDE_AGENT = "owner_only_outside_agent"


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
