"""Shared schema primitives; domain slices are assembled by ``app.api.schemas``."""

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
