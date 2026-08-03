from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class UserCreate(BaseModel):
    """注册：username + password 必填，其余可选"""
    username: str
    password: str
    email: Optional[str] = None
    nickname: Optional[str] = None
    grade: Optional[str] = None
    phone_number: Optional[str] = None
    wechat_id: Optional[str] = None


class UserLogin(BaseModel):
    """登录：支持用户名或邮箱 + 密码"""
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    nickname: Optional[str] = None
    grade: Optional[str] = None
    email: Optional[str] = None
    register_time: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
