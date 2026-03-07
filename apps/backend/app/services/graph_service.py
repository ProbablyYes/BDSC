from dataclasses import dataclass

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError


@dataclass
class GraphSignal:
    connected: bool
    detail: str


class GraphService:
    def __init__(self, uri: str, username: str, password: str) -> None:
        self.uri = uri
        self.username = username
        self.password = password

    def health(self) -> GraphSignal:
        try:
            driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            with driver.session() as session:
                result = session.run("RETURN 'ok' AS status")
                status = result.single()["status"]
            driver.close()
            return GraphSignal(connected=status == "ok", detail="neo4j connected")
        except Neo4jError as exc:
            return GraphSignal(connected=False, detail=f"neo4j error: {exc.code}")
        except Exception as exc:  # noqa: BLE001
            return GraphSignal(connected=False, detail=f"neo4j unavailable: {exc}")
