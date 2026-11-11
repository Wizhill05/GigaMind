from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

Short = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
Item = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class HandoffInput(StrictModel):
    task_name: Short
    summary: Text
    status: Short
    project_id: Short | None = None
    verified_outcomes: list[Item] = Field(max_length=50)
    unresolved: list[Item] = Field(max_length=50)
    next_actions: list[Item] = Field(max_length=50)
    idempotency_key: Short

class IssueInput(StrictModel):
    memory_id: Short
    reason: Text
    project_id: Short | None = None
    idempotency_key: Short

class IssueResolution(StrictModel):
    status: Literal['resolved', 'dismissed']
    expected_revision: StrictInt = Field(ge=1)
