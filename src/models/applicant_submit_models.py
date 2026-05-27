"""Pydantic models for user loan application submit."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.services.applicant_service import CHANNELS, PURPOSES


class ApplicantSubmitRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    annual_income: float = Field(..., gt=0)
    dti: float = Field(..., ge=0, le=99)
    fico_score: int = Field(..., ge=300, le=850)
    emp_title: str = Field(..., min_length=1, max_length=100)
    emp_length: str = Field(..., min_length=1, max_length=20)
    home_ownership: str = Field(..., min_length=1, max_length=20)
    province: str = Field(..., min_length=1, max_length=50)
    city: str = Field("", max_length=50)
    delinq_2yrs: int = Field(0, ge=0, le=20)
    inq_last_6mths: int = Field(0, ge=0, le=50)
    revol_util: float = Field(0, ge=0, le=100)
    open_acc: int = Field(0, ge=0, le=100)
    total_acc: int = Field(0, ge=0, le=200)
    pub_rec: int = Field(0, ge=0, le=20)
    requested_amount: float = Field(..., gt=0)
    requested_term: int = Field(...)
    product_type: str = Field(..., min_length=1, max_length=20)
    channel: str = Field(..., min_length=1, max_length=50)
    purpose: str = Field(..., min_length=1, max_length=50)
    auto_start: bool = True

    @field_validator("requested_term")
    @classmethod
    def _validate_term(cls, v: int) -> int:
        if v not in (12, 24, 36):
            raise ValueError("requested_term 必须为 12、24 或 36")
        return v

    @field_validator("requested_amount")
    @classmethod
    def _validate_amount(cls, v: float) -> float:
        if v < 2000 or v > 200_000:
            raise ValueError("申请金额须在 2000～200000 元之间")
        return v

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, v: str) -> str:
        if v not in CHANNELS:
            raise ValueError(f"channel 无效，可选: {CHANNELS}")
        return v

    @field_validator("purpose")
    @classmethod
    def _validate_purpose(cls, v: str) -> str:
        if v not in PURPOSES:
            raise ValueError(f"purpose 无效，可选: {PURPOSES}")
        return v


class ApplicantSubmitResponse(BaseModel):
    applicant_id: str
    task_id: str | None = None
    status: str
    message: str


class FormOptionsResponse(BaseModel):
    product_types: list[str]
    channels: list[str]
    purposes: list[str]
    emp_titles: list[str]
    emp_lengths: list[str]
    home_ownerships: list[str]
    terms: list[int]
    locations: dict[str, list[str]]
