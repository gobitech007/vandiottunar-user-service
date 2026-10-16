from fastapi import APIRouter

from app.schemas import CityOut
from app.services import cities

router = APIRouter(tags=["cities"])


@router.get("/cities", response_model=list[CityOut])
async def list_cities():
    """Cities people can register in, in display order (no login needed)."""
    return [CityOut(slug=c, name_en=cities.DISTRICTS[c][0], name_ta=cities.DISTRICTS[c][1]) for c in cities.enabled()]
