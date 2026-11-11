"""Create a synthetic corpus in a new local SQLite database."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="new local SQLite file")
    args = parser.parse_args()
    if "://" in args.db or args.db == ":memory:":
        parser.error("--db must be a new local SQLite file path")
    if os.environ.get("ENVIRONMENT", "").strip().lower() in (
        "production",
        "prod",
    ) or os.environ.get("RENDER"):
        parser.error("demo seeding is disabled in production environments")
    path = Path(args.db).expanduser().absolute()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        parser.error(f"cannot create new database: {exc}")
    os.close(fd)
    os.environ["DATABASE_URL"] = ""
    os.environ["DB_PATH"] = str(path)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from sqlmodel import Session
    from gigamind.db.database import init_db, engine, MemoryItem, ConversationItem
    from gigamind.db.memory_index import MemoryIndexState
    from gigamind.security import Actor
    from gigamind.services import trust

    data = json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures/demo/corpus.json").read_text()
    )
    init_db()
    actor = Actor("synthetic-demo-admin", set(), None, True)
    stamp = "2025-01-01T00:00:00+00:00"
    with Session(engine) as session:
        for i in range(64):
            topic = data["topics"][i % len(data["topics"])]
            project = data["projects"][i % len(data["projects"])]
            mid = f"demo-memory-{i:03d}"
            content = "SYNTHETIC DEMO: " + data["notes"][topic].format(
                project=project, index=i
            )
            session.add(
                MemoryItem(
                    id=mid,
                    content=content,
                    category=topic,
                    source_agent="synthetic-demo",
                    tags_json=json.dumps(["synthetic-demo", project]),
                    created_at=stamp,
                    last_accessed=stamp,
                )
            )
            session.add(
                MemoryIndexState(memory_id=mid, created_at=stamp, updated_at=stamp)
            )
        for i in range(15):
            project = data["projects"][i % len(data["projects"])]
            messages = [
                {
                    "role": "user" if n % 2 == 0 else "assistant",
                    "content": f"SYNTHETIC DEMO: {project} conversation {i}, turn {n}: fictional planning details. "
                    + (
                        "A late turn mentions the cobalt milestone. " * 12
                        if n == 29
                        else ""
                    ),
                }
                for n in range(30)
            ]
            session.add(
                ConversationItem(
                    id=f"demo-conversation-{i:03d}",
                    platform="demo-chat" if i % 2 else "demo-notes",
                    title=f"SYNTHETIC DEMO: {project} discussion {i}",
                    summary=f"SYNTHETIC DEMO: fictional discussion for {project}",
                    source_agent="synthetic-demo",
                    messages_json=json.dumps(messages),
                    created_at=stamp,
                )
            )
        session.commit()

    def proposal(
        key,
        content,
        project=None,
        kind="fact",
        subject=None,
        approve=True,
        supersedes=None,
    ):
        text = "SYNTHETIC DEMO: " + content
        p = trust.create_proposal(
            actor,
            content=text,
            project_id=project,
            kind=kind,
            subject=subject,
            tags=["synthetic-demo"],
            evidence=[
                {
                    "source_type": "synthetic-demo-fixture",
                    "source_id": "demo-fixture-" + key,
                    "quote": text,
                }
            ],
            idempotency_key="demo-" + key,
        )["proposal"]
        if approve:
            return trust.resolve_proposal(
                actor,
                p["id"],
                action="approve",
                expected_revision=1,
                supersedes=supersedes or [],
            )["memory"]
        return p

    proposal(
        "rule",
        "For this fictional assistant, use concise response format.",
        kind="preference",
        subject="response format",
    )
    old = proposal(
        "old",
        "Orchard launch cadence is daily.",
        "demo-orchard",
        subject="launch cadence",
    )
    proposal(
        "new",
        "Orchard launch cadence is weekly.",
        "demo-orchard",
        subject="launch cadence",
        supersedes=[old["id"]],
    )
    proposal(
        "harbor",
        "Harbor launch cadence is monthly.",
        "demo-harbor",
        subject="launch cadence",
    )
    proposal(
        "observatory",
        "Observatory reviews telescope notes on Fridays.",
        "demo-observatory",
        subject="review schedule",
    )
    for i, project in enumerate(data["projects"]):
        proposal(
            f"pending-{i}",
            f"Pending fictional {project} budget review.",
            project,
            subject="budget",
            approve=False,
        )
    print(f"Synthetic demo database created: {path}")


if __name__ == "__main__":
    main()
