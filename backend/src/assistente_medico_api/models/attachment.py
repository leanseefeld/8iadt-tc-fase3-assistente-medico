"""Exam attachment (file upload) SQLModel table."""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class ExamAttachment(SQLModel, table=True):
    __tablename__ = "exam_attachments"

    id: str = Field(primary_key=True)
    exam_id: str = Field(foreign_key="exams.id", index=True)
    name: str
    mime: str
    size: int
    path: str
