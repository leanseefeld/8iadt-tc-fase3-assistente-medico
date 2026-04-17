"""Schemas for exam resources."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExamAttachment(BaseModel):
    name: str
    mime: str
    size: int
    path: str


class Exam(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    requested_at: datetime = Field(alias="requestedAt")
    status: str
    result: str | None = None
    interpretation: str | None = None
    source: str
    protocol_ref: str | None = Field(default=None, alias="protocolRef")
    attachments: list[ExamAttachment] = Field(default_factory=list)


class ExamCreateRequest(BaseModel):
    name: str


class ExamPatchRequest(BaseModel):
    status: str | None = None
    result: str | None = None
    interpretation: str | None = None


class ExamResponse(BaseModel):
    exam: Exam
