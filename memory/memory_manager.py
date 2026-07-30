import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Them duong dan dominus-core vao PYTHONPATH de import database connection
project_root = Path(__file__).resolve().parent.parent.parent
core_path = project_root / "dominus-core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

try:
    from src.database.connection import get_db_session
    from src.database.models.assistant import DominusAssistantMemory
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("[Memory DB] Warning: Cannot import database connection. Falling back to local memory.")

MEMORY_PATH = Path(__file__).resolve().parent / "long_term.json"
MAX_VALUE_LENGTH = 380

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
        "sessions":      []
    }

def load_memory() -> dict:
    if not DB_AVAILABLE:
        if not MEMORY_PATH.exists():
            return _empty_memory()
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else _empty_memory()
        except Exception:
            return _empty_memory()

    memory = _empty_memory()
    try:
        with get_db_session() as session:
            rows = session.query(DominusAssistantMemory).all()
            for r in rows:
                cat = r.category
                if cat in memory:
                    memory[cat][r.key] = {
                        "value": r.value,
                        "updated": r.updated_at.strftime("%Y-%m-%d") if r.updated_at else datetime.utcnow().strftime("%Y-%m-%d")
                    }
                elif cat == "sessions_store":
                    # Phuc hoi session summaries tu ban ghi dac biet
                    try:
                        memory["sessions"] = json.loads(r.value)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[Memory DB] Error loading memory: {e}")
    return memory

def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    if not DB_AVAILABLE:
        # Fallback ghi ra file JSON
        memory = load_memory()
        # Update logic ...
        return memory

    try:
        with get_db_session() as session:
            for cat, items in memory_update.items():
                if cat not in {"identity", "preferences", "projects", "relationships", "wishes", "notes"}:
                    continue
                if not isinstance(items, dict):
                    continue
                for key, val_obj in items.items():
                    val = val_obj["value"] if isinstance(val_obj, dict) else val_obj
                    if val is None or (isinstance(val, str) and not val.strip()):
                        continue
                    
                    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
                        val = val[:MAX_VALUE_LENGTH].rstrip() + "..."
                        
                    row = session.query(DominusAssistantMemory).filter_by(category=cat, key=key).first()
                    if row:
                        row.value = str(val)
                        row.updated_at = datetime.utcnow()
                    else:
                        row = DominusAssistantMemory(category=cat, key=key, value=str(val))
                        session.add(row)
            session.commit()
    except Exception as e:
        print(f"[Memory DB] Error updating memory: {e}")
    return load_memory()

def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []
    
    identity = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
                
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    for cat in ["preferences", "projects", "relationships", "wishes", "notes"]:
        items = memory.get(cat, {})
        if items:
            lines.append("")
            lines.append(f"{cat.title()}:")
            for key, entry in list(items.items())[:15]:
                val = entry.get("value") if isinstance(entry, dict) else entry
                if val:
                    lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON - use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "..."
    return result + "\n"

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"

def forget(key: str, category: str = "notes") -> str:
    if not DB_AVAILABLE:
        return "Database not available"
    try:
        with get_db_session() as session:
            row = session.query(DominusAssistantMemory).filter_by(category=category, key=key).first()
            if row:
                session.delete(row)
                session.commit()
                return f"Forgotten: {category}/{key}"
            return f"Not found: {category}/{key}"
    except Exception as e:
        return f"Error: {e}"

forget_memory = forget

def save_session_summary(summary: str, language: str = "") -> None:
    summary = (summary or "").strip()
    if not summary or not DB_AVAILABLE:
        return
        
    try:
        with get_db_session() as session:
            # Load hoac tao moi sessions list trong database
            row = session.query(DominusAssistantMemory).filter_by(category="sessions_store", key="active_sessions").first()
            sessions = []
            if row:
                try:
                    sessions = json.loads(row.value)
                except Exception:
                    pass
            else:
                row = DominusAssistantMemory(category="sessions_store", key="active_sessions", value="[]")
                session.add(row)
                
            entry = {
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "summary": summary[:280]
            }
            if language:
                entry["language"] = language
                
            sessions.append(entry)
            sessions = sessions[-3:]  # Cap 3 sessions
            
            row.value = json.dumps(sessions, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
            session.commit()
    except Exception as e:
        print(f"[Memory DB] Error saving session summary: {e}")

def pop_last_session() -> dict | None:
    if not DB_AVAILABLE:
        return None
    try:
        with get_db_session() as session:
            row = session.query(DominusAssistantMemory).filter_by(category="sessions_store", key="active_sessions").first()
            if not row:
                return None
            try:
                sessions = json.loads(row.value)
            except Exception:
                sessions = []
                
            if not sessions:
                return None
                
            entry = sessions.pop()
            row.value = json.dumps(sessions, ensure_ascii=False)
            session.commit()
            return entry
    except Exception as e:
        print(f"[Memory DB] Error popping last session: {e}")
        return None