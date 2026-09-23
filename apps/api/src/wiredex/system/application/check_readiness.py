from wiredex.system.application.ports import DatabaseProbe
from wiredex.system.domain.readiness import Readiness


class CheckReadiness:
    def __init__(self, database: DatabaseProbe) -> None:
        self._database = database

    async def __call__(self) -> Readiness:
        return Readiness(database_reachable=await self._database.is_reachable())
