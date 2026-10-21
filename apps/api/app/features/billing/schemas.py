from datetime import date as _date

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    amount: int = Field(gt=0)
    date: _date
    category: str = "기타"


class ExpenseOut(BaseModel):
    id: str
    title: str
    amount: int
    date: str
    category: str
    paid_by: str


class Balance(BaseModel):
    user_id: str
    name: str
    paid: int
    share: int
    balance: int  # 양수: 받을 돈, 음수: 낼 돈


class Summary(BaseModel):
    month: str
    total: int
    count: int
    balances: list[Balance]
