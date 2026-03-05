"""Pydantic models for request/response validation."""

from typing import Any, Optional
from pydantic import BaseModel


class MetricSnapshot(BaseModel):
    machine_name: str
    machine_type: str
    timestamp: float
    system: dict[str, Any]
    security: dict[str, Any]


class Alert(BaseModel):
    id: Optional[int] = None
    machine_name: str
    severity: str          # info | warning | critical
    category: str          # security | health | connectivity
    message: str
    timestamp: float
    acknowledged: bool = False
