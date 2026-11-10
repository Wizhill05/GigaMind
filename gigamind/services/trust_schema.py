from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


class StrippedModel(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value


class Evidence(StrippedModel):
    source_type: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=512)
    quote: str = Field(min_length=1, max_length=10000)
    source_role: Optional[str] = Field(default=None, max_length=100)


class Proposal(StrippedModel):
    content: str = Field(min_length=1, max_length=50000)
    category: str = Field(default="general", min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    project_id: Optional[str] = Field(default=None, max_length=200)
    evidence: list[Evidence] = Field(max_length=100)

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value):
        if any(not tag or len(tag) > 100 for tag in value):
            raise ValueError("Invalid tag")
        return value

    @field_validator("project_id", "subject")
    @classmethod
    def nonblank_optional(cls, value):
        if value == "":
            raise ValueError("Must not be blank")
        return value

    kind: Literal["fact", "preference", "decision"] = "fact"
    subject: Optional[str] = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class Resolution(StrippedModel):
    action: Literal["approve", "reject"]
    expected_revision: int = Field(ge=1)
    content: Optional[str] = Field(default=None, min_length=1, max_length=50000)
    supersedes: list[str] = Field(default_factory=list, max_length=100)


class Restore(StrippedModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
