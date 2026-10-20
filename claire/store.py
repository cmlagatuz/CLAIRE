"""Long-term store: memories (facts), journal, conversations. One SQLite file."""
import re
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY, text TEXT NOT NULL, kind TEXT DEFAULT 'fact',
  source TEXT DEFAULT 'chat', created TEXT, last_used TEXT, uses INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text) VALUES('delete', old.id, old.text); END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE OF text ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, at TEXT, title TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, started TEXT, ended TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session_id INTEGER, at TEXT, role TEXT, content TEXT);
"""
STOP = set("""a an the and or but if of to in on at by for with from is are was were be been am i me my you your
he she it we they them our us this that these those do does did have has had what which who whom how when where why
can could would should will shall may might must not no yes so than then there here about into over just also very
please tell know want need like get got make let lets ok okay hi hello hey claire""".split())


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def stem(w):
    for suf in ("ies", "ing", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def norm(t):
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def remember(self, text, kind="fact", source="chat"):
        text = text.strip().rstrip(".") + "."
        if len(text) < 4:
            return None
        n = norm(text)
        for r in self.db.execute("SELECT id, text FROM memories WHERE active=1"):
            if norm(r["text"]) == n:
                return None
        cur = self.db.execute("INSERT INTO memories(text, kind, source, created) VALUES (?,?,?,?)",
                              (text, kind, source, now()))
        self.db.commit()
        return cur.lastrowid

    def forget(self, ident_or_text):
        if str(ident_or_text).isdigit():
            rows = self.db.execute("SELECT id, text FROM memories WHERE id=? AND active=1", (int(ident_or_text),)).fetchall()
        else:
            rows = self.search(ident_or_text, limit=1)
        for r in rows:
            self.db.execute("UPDATE memories SET active=0 WHERE id=?", (r["id"],))
        self.db.commit()
        return [r["text"] for r in rows]

    def memories(self, kind=None):
        q = "SELECT * FROM memories WHERE active=1" + (" AND kind=?" if kind else "") + " ORDER BY id"
        return self.db.execute(q, (kind,) if kind else ()).fetchall()

    def search(self, query, limit=6):
        words = [w for w in norm(query).split() if w not in STOP and len(w) > 2]
        if not words:
            return []
        fts = " OR ".join('"' + stem(w) + '"*' for w in dict.fromkeys(words))
        rows = self.db.execute(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid "
            "WHERE memories_fts MATCH ? AND m.active=1 ORDER BY bm25(memories_fts) LIMIT ?", (fts, limit)).fetchall()
        for r in rows:
            self.db.execute("UPDATE memories SET uses=uses+1, last_used=? WHERE id=?", (now(), r["id"]))
        self.db.commit()
        return rows

    def core_memories(self):
        return self.db.execute("SELECT * FROM memories WHERE active=1 AND kind='core' ORDER BY id").fetchall()

    def journal_add(self, title, detail=""):
        self.db.execute("INSERT INTO journal(at, title, detail) VALUES (?,?,?)", (now(), title, detail))
        self.db.commit()

    def journal(self, limit=None):
        q = "SELECT * FROM journal ORDER BY id" + (f" DESC LIMIT {int(limit)}" if limit else "")
        rows = self.db.execute(q).fetchall()
        return list(reversed(rows)) if limit else rows

    def new_session(self):
        cur = self.db.execute("INSERT INTO sessions(started) VALUES (?)", (now(),))
        self.db.commit()
        return cur.lastrowid

    def log(self, session_id, role, content):
        self.db.execute("INSERT INTO messages(session_id, at, role, content) VALUES (?,?,?,?)",
                        (session_id, now(), role, content))
        self.db.commit()

    def session_messages(self, session_id):
        return self.db.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id",
                               (session_id,)).fetchall()

    def end_session(self, session_id, summary):
        self.db.execute("UPDATE sessions SET ended=?, summary=? WHERE id=?", (now(), summary, session_id))
        self.db.commit()

    def last_summaries(self, n=3):
        rows = self.db.execute("SELECT started, summary FROM sessions WHERE summary IS NOT NULL AND summary<>'' "
                               "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return list(reversed(rows))

    def unfinished_sessions(self, current):
        return [r["id"] for r in self.db.execute(
            "SELECT s.id FROM sessions s WHERE s.summary IS NULL AND s.id<>? AND "
            "EXISTS(SELECT 1 FROM messages m WHERE m.session_id=s.id)", (current,))]
