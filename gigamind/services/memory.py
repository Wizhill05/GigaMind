import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from gigamind.db.database import engine, ProfileItem, MemoryItem, ConversationItem, TaskSessionItem
from gigamind.services.embedding import generate_embedding, cosine_similarity

def search_memory(query: str, category: Optional[str] = None, source_agent: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    query_vector = generate_embedding(query)
    query_lower = query.lower()
    query_keywords = [k for k in query_lower.split() if len(k) > 2]

    results = []

    with Session(engine) as session:
        # 1. Search Semantic Memories
        stmt = select(MemoryItem)
        if category:
            stmt = stmt.where(MemoryItem.category == category)
        if source_agent:
            stmt = stmt.where(MemoryItem.source_agent == source_agent)

        stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(100)
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
                    "source_agent": getattr(mem, "source_agent", "user") or "user",
                    "score": round(score, 4),
                    "tags": json.loads(mem.tags_json or "[]")
                })
                mem.last_accessed = now_str

        session.commit()

        # 2. Search Profile Rules
        profile_stmt = select(ProfileItem)
        if category:
            profile_stmt = profile_stmt.where(ProfileItem.category == category)
        if source_agent:
            profile_stmt = profile_stmt.where(ProfileItem.source_agent == source_agent)

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
                    "source_agent": getattr(prof, "source_agent", "user") or "user",
                    "score": round(score, 4)
                })

        # Sort descending by relevance score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

def add_memory(content: str, category: str = "general", source_agent: str = "user", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    if tags is None:
        tags = []

    mem_id = f"mem_{uuid.uuid4().hex[:12]}"
    embedding = generate_embedding(content)
    now_str = datetime.now(timezone.utc).isoformat()

    item = MemoryItem(
        id=mem_id,
        content=content,
        category=category,
        source_agent=source_agent or "user",
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
        "source_agent": source_agent or "user",
        "tags": tags,
        "created_at": now_str
    }

def set_profile_rule(key: str, value: str, category: str = "general", source_agent: str = "user") -> Dict[str, Any]:
    prof_id = f"prof_{key.replace(' ', '_')}"
    now_str = datetime.now(timezone.utc).isoformat()

    with Session(engine) as session:
        existing = session.exec(select(ProfileItem).where(ProfileItem.key == key)).first()
        if existing:
            existing.value = value
            existing.category = category
            existing.source_agent = source_agent or "user"
            existing.updated_at = now_str
        else:
            item = ProfileItem(
                id=prof_id,
                key=key,
                value=value,
                category=category,
                source_agent=source_agent or "user",
                updated_at=now_str
            )
            session.add(item)
        session.commit()

    return {
        "id": prof_id,
        "key": key,
        "value": value,
        "category": category,
        "source_agent": source_agent or "user",
        "updated_at": now_str
    }

def get_profile_rules(category: Optional[str] = None, source_agent: Optional[str] = None) -> List[Dict[str, Any]]:
    with Session(engine) as session:
        stmt = select(ProfileItem)
        if category:
            stmt = stmt.where(ProfileItem.category == category)
        if source_agent:
            stmt = stmt.where(ProfileItem.source_agent == source_agent)
        items = session.exec(stmt).all()
        return [{
            "id": i.id,
            "key": i.key,
            "value": i.value,
            "category": i.category,
            "source_agent": getattr(i, "source_agent", "user") or "user",
            "updated_at": i.updated_at
        } for i in items]

def add_conversation_log(platform: str, title: str, summary: str, messages: List[Dict[str, Any]], source_agent: str = "user") -> Dict[str, Any]:
    conv_id = f"conv_{platform}_{uuid.uuid4().hex[:8]}"
    text_for_vector = f"{title} {summary}"
    embedding = generate_embedding(text_for_vector)
    now_str = datetime.now(timezone.utc).isoformat()

    item = ConversationItem(
        id=conv_id,
        platform=platform,
        title=title,
        summary=summary,
        source_agent=source_agent or "user",
        messages_json=json.dumps(messages),
        embedding_json=json.dumps(embedding),
        created_at=now_str
    )

    with Session(engine) as session:
        session.add(item)
        session.commit()

    return {
        "id": conv_id,
        "platform": platform,
        "title": title,
        "summary": summary,
        "source_agent": source_agent or "user",
        "created_at": now_str
    }

def get_memories(page: int = 1, limit: int = 20, category: Optional[str] = None, source_agent: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as session:
        stmt = select(MemoryItem)
        if category:
            stmt = stmt.where(MemoryItem.category == category)
        if source_agent:
            stmt = stmt.where(MemoryItem.source_agent == source_agent)

        all_items = session.exec(stmt).all()
        total = len(all_items)

        offset = (page - 1) * limit
        items = session.exec(stmt.order_by(MemoryItem.created_at.desc()).offset(offset).limit(limit)).all()

        res_memories = []
        for mem in items:
            res_memories.append({
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "media_type": mem.media_type,
                "media_url": mem.media_url,
                "source_agent": getattr(mem, "source_agent", "user") or "user",
                "tags": json.loads(mem.tags_json or "[]"),
                "created_at": mem.created_at,
                "last_accessed": mem.last_accessed
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "memories": res_memories,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }

def delete_memory(memory_id: str) -> bool:
    with Session(engine) as session:
        item = session.exec(select(MemoryItem).where(MemoryItem.id == memory_id)).first()
        if not item:
            return False
        session.delete(item)
        session.commit()
        return True

def update_memory(memory_id: str, content: Optional[str] = None, category: Optional[str] = None, source_agent: Optional[str] = None, tags: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    with Session(engine) as session:
        item = session.exec(select(MemoryItem).where(MemoryItem.id == memory_id)).first()
        if not item:
            return None

        if content is not None:
            item.content = content
            item.embedding_json = json.dumps(generate_embedding(content))
        if category is not None:
            item.category = category
        if source_agent is not None:
            item.source_agent = source_agent
        if tags is not None:
            item.tags_json = json.dumps(tags)

        now_str = datetime.now(timezone.utc).isoformat()
        item.last_accessed = now_str
        session.commit()

        return {
            "id": item.id,
            "content": item.content,
            "category": item.category,
            "media_type": item.media_type,
            "media_url": item.media_url,
            "source_agent": getattr(item, "source_agent", "user") or "user",
            "tags": json.loads(item.tags_json or "[]"),
            "created_at": item.created_at,
            "last_accessed": item.last_accessed
        }

def get_conversations(page: int = 1, limit: int = 20, platform: Optional[str] = None, source_agent: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as session:
        stmt = select(ConversationItem)
        if platform:
            stmt = stmt.where(ConversationItem.platform == platform)
        if source_agent:
            stmt = stmt.where(ConversationItem.source_agent == source_agent)

        all_items = session.exec(stmt).all()
        total = len(all_items)

        offset = (page - 1) * limit
        items = session.exec(stmt.order_by(ConversationItem.created_at.desc()).offset(offset).limit(limit)).all()

        res_convs = []
        for conv in items:
            res_convs.append({
                "id": conv.id,
                "platform": conv.platform,
                "title": conv.title,
                "summary": conv.summary,
                "source_agent": getattr(conv, "source_agent", "user") or "user",
                "messages": json.loads(conv.messages_json or "[]"),
                "created_at": conv.created_at
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "conversations": res_convs,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }

def delete_profile_rule(rule_id: str) -> bool:
    with Session(engine) as session:
        item = session.exec(select(ProfileItem).where((ProfileItem.id == rule_id) | (ProfileItem.key == rule_id))).first()
        if not item:
            return False
        session.delete(item)
        session.commit()
        return True

def get_stats() -> Dict[str, Any]:
    with Session(engine) as session:
        memories = session.exec(select(MemoryItem)).all()
        profile_rules = session.exec(select(ProfileItem)).all()
        chat_logs = session.exec(select(ConversationItem)).all()
        task_sessions = session.exec(select(TaskSessionItem)).all()

        source_distribution = {}
        for mem in memories:
            agent = getattr(mem, "source_agent", "user") or "user"
            source_distribution[agent] = source_distribution.get(agent, 0) + 1

        return {
            "total_memories": len(memories),
            "total_profile_rules": len(profile_rules),
            "total_chat_logs": len(chat_logs),
            "total_task_sessions": len(task_sessions),
            "source_distribution": source_distribution
        }

