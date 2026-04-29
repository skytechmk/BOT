from pydantic import BaseModel, Field, StrictStr, StrictInt, StrictFloat, StrictBool
from typing import List, Optional, Union, Literal

class ForgotPasswordRequest(BaseModel):
    email: StrictStr

class ResetPasswordRequest(BaseModel):
    token: StrictStr
    password: StrictStr

class AdminSetTierRequest(BaseModel):
    tier: Literal["free", "plus", "pro", "ultra"]
    days: int = Field(default=30, ge=1)

class AdminSetMaintenanceRequest(BaseModel):
    enabled: bool = False
    message: Optional[str] = ""
    kind: Optional[str] = "maintenance"
    eta_minutes: int = Field(default=0, ge=0)

class AdminSetDeviceLimitRequest(BaseModel):
    limit: Optional[int] = None

class AdminGrantSlotsRequest(BaseModel):
    slots: int = Field(default=1, ge=1, le=50)
    months: int = Field(default=0, ge=0)
    note: Optional[str] = ""

class QuickEntryRequest(BaseModel):
    pair: StrictStr
    direction: Literal["LONG", "SHORT", "long", "short"]
    sl_price: float = Field(gt=0)
    tp_prices: List[float]
    leverage: int = Field(default=0, ge=0)

class BacktestRequest(BaseModel):
    start: float
    end: float
    pairs: Optional[List[str]] = None
    initial_capital: float = Field(default=10_000.0, gt=0)
    position_mode: Literal["risk_pct", "fixed"] = "risk_pct"
    risk_pct: float = Field(default=2.0, gt=0, le=50)
    fixed_amount: float = Field(default=200.0, gt=0)
    leverage: int = Field(default=0, ge=0, le=125)
    fee_pct: float = Field(default=0.05, ge=0, le=0.5)
    sim_mode: Literal["actual", "simulate"] = "actual"
    sl_mode: Literal["strict", "none"] = "strict"
    tp_mode: Literal["first", "last", "weighted"] = "weighted"
    max_hold_hours: int = Field(default=48, ge=1, le=168)
    atr_multipliers: Optional[List[float]] = None

class PushSubscribeRequest(BaseModel):
    subscription: dict
    user_agent: Optional[str] = ""

class PushUnsubscribeRequest(BaseModel):
    endpoint: StrictStr

class CopyTradeKeysRequest(BaseModel):
    exchange: Literal["binance", "mexc"]
    api_key: Optional[str] = ""
    api_secret: Optional[str] = ""
    passphrase: Optional[str] = ""

class CopyTradeToggleRequest(BaseModel):
    active: bool

class CopyTradeSettingsRequest(BaseModel):
    size_pct: Optional[float] = None
    max_size_pct: Optional[float] = None
    max_leverage: Optional[int] = None
    scale_with_sqi: Optional[bool] = None
    leverage_mode: Optional[str] = None
    size_mode: Optional[str] = None
    sl_mode: Optional[str] = None
    tp_mode: Optional[str] = None
    sl_pct: Optional[float] = None
    fixed_size_usd: Optional[float] = None

class CopyTradeFiltersRequest(BaseModel):
    allowed_tiers: str = "blue_chip,large_cap,mid_cap,small_cap,high_risk"
    allowed_sectors: str = "all"
    hot_only: bool = False

class TVWebhookPayload(BaseModel):
    secret: StrictStr
    action: Literal["LONG", "SHORT", "CLOSE", "long", "short", "close", "BUY", "SELL", "BUY_LONG", "SELL_SHORT"]
    symbol: StrictStr
    price: float = Field(gt=0)
    strategy: Optional[str] = None
    leverage: Optional[int] = None
    confidence: Optional[float] = None
