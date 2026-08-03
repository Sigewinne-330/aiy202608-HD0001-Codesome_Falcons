from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _normalize_email(value: EmailStr) -> str:
    return str(value).strip().lower()


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    email: EmailStr
    verification_token: str = Field(min_length=32, max_length=256)
    nickname: Optional[str] = None
    grade: Optional[str] = None
    phone_number: Optional[str] = None
    wechat_id: Optional[str] = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(value)


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)


class VerificationCodeRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(value)


class VerificationCodeSubmit(VerificationCodeRequest):
    code: str = Field(pattern=r"^\d{6}$")


class VerificationCodeAccepted(BaseModel):
    message: str
    retry_after_seconds: int


class VerificationProofResponse(BaseModel):
    verification_token: str
    expires_in_seconds: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: Optional[str] = None
    grade: Optional[str] = None
    email: Optional[str] = None
    register_time: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
