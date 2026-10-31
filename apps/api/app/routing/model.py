"""Pydantic модел на дефиницията на routing правило (docs/09-routing-rules-plan.md §3).

Wire форматът е snake_case — консистентен с останалите MeshGate API-та."""

from typing import Any

from pydantic import BaseModel, Field

EXECUTION_MODES = ("first_match", "all_match")
PAYLOAD_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists")
DEST_TYPES = ("mqtt", "http")


class SourceSpec(BaseModel):
    type: str = Field(default="mqtt", pattern=r"^mqtt$")
    broker: str = Field(default="local", pattern=r"^local$")  # mesh адаптери: Фаза M
    topic_filter: str = Field(default="#", min_length=1, max_length=256)


class TopicConditions(BaseModel):
    include: list[str] = Field(default_factory=list, max_length=32)
    exclude: list[str] = Field(default_factory=list, max_length=32)


class PayloadTerm(BaseModel):
    path: str = Field(min_length=1, max_length=256)
    op: str = Field(pattern=r"^(eq|ne|gt|gte|lt|lte|contains|exists)$")
    value: Any = None


class PayloadGroup(BaseModel):
    """Т20: вложена AND/OR група — terms може да съдържа термини И други
    групи (рекурсия; UI-то ограничава дълбочината на 3)."""
    mode: str = Field(default="all", pattern=r"^(all|any)$")
    terms: list["PayloadTerm | PayloadGroup"] = Field(default_factory=list, max_length=16)


class PayloadConditions(BaseModel):
    mode: str = Field(default="all", pattern=r"^(all|any)$")
    terms: list[PayloadTerm | PayloadGroup] = Field(default_factory=list, max_length=16)
    # Т20: поведение при непарсебъл payload (не е JSON обект/масив):
    # no_match (default — условието не пасва) | match („по тема" — пасва)
    on_unparseable: str = Field(default="no_match", pattern=r"^(no_match|match)$")


PayloadGroup.model_rebuild()


class Conditions(BaseModel):
    topic: TopicConditions = Field(default_factory=TopicConditions)
    payload: PayloadConditions = Field(default_factory=PayloadConditions)


class TransformSpec(BaseModel):
    topic_template: str | None = Field(default=None, max_length=256)
    set_fields: dict[str, Any] = Field(default_factory=dict)
    remove_fields: list[str] = Field(default_factory=list, max_length=32)
    add_envelope: bool = False


class RetrySpec(BaseModel):
    max: int = Field(default=2, ge=0, le=10)
    backoff_ms: int = Field(default=1000, ge=100, le=60000)


class ErrorPolicy(BaseModel):
    on_destination_failure: str = Field(
        default="continue", pattern=r"^(continue|halt)$"
    )
    retry: RetrySpec = Field(default_factory=RetrySpec)
    dead_letter: bool = True


class DestinationSpec(BaseModel):
    id: str | None = None
    # mqtt: локалният брокер или bridge:<uuid>; http: POST към url (R2 —
    # врата към n8n/Node-RED/ntfy/собствени API-та)
    type: str = Field(default="mqtt", pattern=r"^(mqtt|http)$")
    target: str = Field(default="local")  # 'local' или 'bridge:<uuid>'
    topic_template: str = Field(min_length=1, max_length=256)
    qos: int = Field(ge=0, le=2, default=0)
    retain: bool = False
    # само за type=http: абсолютен адрес; SSRF валидира се при запис
    url: str | None = Field(default=None, max_length=512)
    # Т22: независима error политика на КЛОН (разклонение) — при None важи
    # правилото (rule.error_policy); така 3-те дестинации могат да имат
    # различни retry/dead-letter/halt поведения едновременно
    error_policy: ErrorPolicy | None = None


class RuleDefinition(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str | None = None
    enabled: bool = False
    priority: int = Field(default=100, ge=1, le=10000)
    execution_mode: str = Field(default="first_match", pattern=r"^(first_match|all_match)$")
    source: SourceSpec = Field(default_factory=SourceSpec)
    conditions: Conditions = Field(default_factory=Conditions)
    transform: TransformSpec = Field(default_factory=TransformSpec)
    destinations: list[DestinationSpec] = Field(min_length=1, max_length=8)
    error_policy: ErrorPolicy = Field(default_factory=ErrorPolicy)


class TemplateOut(BaseModel):
    id: str
    title: str
    description: str
    definition: RuleDefinition
