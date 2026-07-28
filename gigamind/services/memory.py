import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from gigamind.db.database import engine, ProfileItem, MemoryItem, ConversationItem, TaskSessionItem
from gigamind.services.embedding import generate_embedding, cosine_similarity

def search_memory(query: str, category: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    query_vector = generate_embedding(query)
    query_lower = query.lower()
    query_keywords = [k for k in query_lower.split() if len(k) > 2]

    results = []

    with Session(engine) as session:
        # 1. Search Semantic Memories
        stmt = select(MemoryItem).order_by(MemoryItem.created_at.desc()).limit(100)
        if category:
            stmt = select(MemoryItem).where(MemoryItem.category == category).order_by(MemoryItem.created_at.desc()).limit(100)

        memories = session.exec(stmt).all()
        now_str = datetime.now(timezone.utc).isoformat()

        for mem in memories:
            score = 0.0
            try:
                vec = json.loads(mem.embedding_json)
                score += cosine_similarity(query_vector, vec) * 0.7
            except Exception:
                pass

            content_lower = mem.content.lower()
            kw_hits = sum(1 for kw in query_keywords if kw in content_lower)
            if query_keywords:
                score += (kw_hits / len(query_keywords)) * 0.3

            if score > 0.1:
                results.append({
                    "id": mem.id,
                    "source": "memory",
                    "content": mem.content,
                    "category": mem.category,
                    "score": round(score, 4),
                    "tags": json.loads(mem.tags_json or "[]")
                })
                mem.last_accessed = now_str

        session.commit()

        # 2. Search Profile Rules
        profile_stmt = select(ProfileItem)
        profiles = session.exec(profile_stmt).all()

        for prof in profiles:
            text = f"{prof.key}: {prof.value}".lower()
            score = 0.0
            for kw in query_keywords:
                if kw in text:
                    score += 0.4

            if score > 0.1:
                results.append({
                    "id": prof.id,
                    "source": "profile",
                    "content": f"[PROFILE RULE] {prof.key} = {prof.value}",
                    "category": prof.category,
                    "score": round(score, 4)
                })

        # Sort descending by relevance score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

def add_memory(content: str, category: str = "general", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    if tags is None:
        tags = []

    mem_id = f"mem_{uuid.uuid4().hex[:12]}"
    embedding = generate_embedding(content)
    now_str = datetime.now(timezone.utc).isoformat()

    item = MemoryItem(
        id=mem_id,
        content=content,
        category=category,
        tags_json=json.dumps(tags),
        embedding_json=json.dumps(embedding),
        created_at=now_str,
        last_accessed=now_str
    )

    with Session(engine) as session:
        session.add(item)
        session.commit()

    return {
        "id": mem_id,
        "content": content,
        "category": category,
        "tags": tags,
        "created_at": now_str
    }

def set_profile_rule(key: str, value: str, category: str = "general") -> Dict[str, Any]:
    prof_id = f"prof_{key.replace(' ', '_')}"
    now_str = datetime.now(timezone.utc).isoformat()

    with Session(engine) as session:
        existing = session.exec(select(ProfileItem).where(ProfileItem.key == key)).first()
        if existing:
            existing.value = value
            existing.category = category
            existing.updated_at = now_str
        else:
            item = ProfileItem(
                id=prof_id,
                key=key,
                value=value,
                category=category,
                updated_at=now_str
            )
            session.add(item)
        session.commit()

    return {
        "id": prof_id,
        "key": key,
        "value": value,
        "category": category,
        "updated_at": now_str
    }

def get_profile_rules(category: Optional[str] = None) -> List[Dict[str, Any]]:
    with Session(engine) as session:
        stmt = select(ProfileItem)
        if category:
            stmt = select(ProfileItem).where(ProfileItem.category == category)
        items = session.exec(stmt).all()
        return [{"id": i.id, "key": i.key, "value": i.value, "category": i.category, "updated_at": i.updated_at} for i in items]

def add_conversation_log(platform: str, title: str, summary: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    conv_id = f"conv_{platform}_{uuid.uuid4().hex[:8]}"
    text_for_vector = f"{title} {summary}"
    embedding = generate_embedding(text_for_vector)
    now_str = datetime.now(timezone.utc).isoformat()

    item = ConversationItem(
        id=conv_id,
        platform=platform,
        title=title,
        summary=summary,
        messages_json=json.dumps(messages),
        embedding_json=json.dumps(embedding),
        created_at=now_str
    )

    with Session(engine) as session:
        session.add(item)
        session.commit()

    return {"id": conv_id, "platform": platform, "title": title, "summary": summary, "created_at": now_str}
