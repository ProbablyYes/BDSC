from __future__ import annotations

"""Offline helper script: quick category pattern query in Neo4j.

用于在已导入的 Neo4j 最小图谱上做简单类别模式浏览，
方便教师或管理员做离线分析。在线 KG/超图诊断并不依赖
本脚本，核心链路只使用 HyperNetX + JSON。
"""

from neo4j import GraphDatabase

from app.config import settings


def main() -> None:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )

    session_kwargs = {"database": settings.neo4j_database} if settings.neo4j_database else {}
    with driver.session(**session_kwargs) as session:
        result = session.run(
            """
            MATCH (c:Category)<-[:BELONGS_TO]-(p:Project)
            OPTIONAL MATCH (p)-[:HAS_PAIN]->(pain:PainPoint)
            OPTIONAL MATCH (p)-[:HAS_SOLUTION]->(sol:Solution)
            RETURN c.name AS category,
                   count(DISTINCT p) AS projects,
                   collect(DISTINCT pain.name)[0..5] AS top_pains,
                   collect(DISTINCT sol.name)[0..5] AS top_solutions
            ORDER BY projects DESC
            """
        )
        rows = list(result)

    driver.close()
    print("=== Category Patterns ===")
    for row in rows:
        print(f"\n[{row['category']}] projects={row['projects']}")
        print(f"- pains: {row['top_pains']}")
        print(f"- solutions: {row['top_solutions']}")


if __name__ == "__main__":
    main()
