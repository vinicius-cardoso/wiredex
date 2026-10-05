"""A numbered page over HTTP: `page` and `page_size` in, the page served and the total out.

The query bounds are the domain's, so a page out of bounds is FastAPI's 422 and never reaches a
use case; a page past the end is served as the last one, and `page` says which.
"""

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from wiredex.shared_kernel.domain.paging import MAX_PAGE, MAX_PAGE_SIZE

type PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE)]
type PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


class PagedResponse(BaseModel):
    """What every page answers besides its items: how many the whole list holds, the page served
    (the last one when the request lay past the end) and how many a page holds."""

    total: int
    page: int
    page_size: int
