"""Schemas for city search and responses."""

from typing import Optional, List
from pydantic import BaseModel


class City(BaseModel):
    """City document returned to clients."""
    name: str
    state: str
    lat: Optional[float] = None
    lng: Optional[float] = None


class CitySearchResponse(BaseModel):
    """List response for city search/typeahead."""
    cities: List[City]
