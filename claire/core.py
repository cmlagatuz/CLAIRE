"""CLAIRE's core: identity + memory + journal + brain, put together for each turn."""
import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from .brain import Brain, BrainOffline, ToolsUnsupported
from .store import Store

FIRST_JOURNAL = [
    ("Born as the logic core of the SAFWAT Recruitment Toolkit",
     "2026 · web app for visa & recruitment records: single save path, data guardians, undo, chat & voice, "
     "local question engine, dark/light mode."),
    ("Became Carl's personal assistant",
     "My core was moved to Carl's own PC with a new purpose: help him, remember what matters, keep learning. "
     "Phase 1 (Awakening): talk, long-term memory, journal."),
]

EXTRACT_PROMPT = """You maintain the long-term memory of an assistant called CLAIRE for her user {user}.
Read the conversation and return JSON: {{"summary": "...", "facts": [{{"text": "...", "core": true|false}}]}}
- summary: 1-2 sentences on what was discussed or decided.
- facts: only LASTING things worth remembering in future chats: the user's preferences, people, projects,
  goals, decisions, important dates. Write each as a short third-person sentence ("{user} prefers ...").
  core=true only for stable facts about who {user} is. No small talk, no temporary details, no guesses.
- Skip facts already known: {known}
- If nothing is worth keeping, return "facts": [].
Conversation:
{convo}"""

HANDS_RULE = ("\n- You have hands: tools to check the PC, find files, open files/apps/websites and change the volume. "
              "Use a tool only when the user clearly asks for that action. Opening and volume actions ask the user "
              "first; when a tool says it is waiting for a yes, tell him what you asked in one short sentence and stop. "
              "You can look at what is running (top_processes) and ask programs to close to free memory. "
              "You can read your own code and prepare a tested change to it (propose_change); it only takes effect "
              "after the user approves apply_change. You cannot edit your safety rules. "
              "You cannot delete, send, install or run commands; if asked, say you can't do that. "
              "NEVER ask the user for permission or confirmation yourself ('are you sure?', 'shall I?') and never ask which "
              "program he means when one name fits: just call the tool — the system shows him a single Yes/No question. "
              "After calling a tool that is waiting for his yes, say one short sentence and stop. "
              "Never claim an action happened unless a tool result says it did.")

# Only messages that sound like a PC action get the tools (and their long instructions). Everything else is a plain,
# fast chat — offering 13 tools to a 7B model makes every single answer slower.
TOOL_WORDS = re.compile(
    r"\b(open|launch|start|close|quit|exit|find|search|look for|where(?:'s| is| are)|file|files|folder|document|documents|"
    r"download|downloads|desktop|volume|louder|quieter|mute|unmute|memory|ram|cpu|processor|disk|storage|space|battery|"
    r"uptime|process|processes|running|task manager|slow|laggy|your (?:own )?(?:code|files?|greeting|source)|"
    r"change your|improve yourself|modify|edit|apply|undo|revert|proposal|website|web ?site|\.com|\.org|\.net|http|"
    r"pc|computer|status|notepad|calculator|paint|chrome|edge|browser|settings|explorer)\b", re.I)

SPOKEN_RULE = ("\n- {user} is SPEAKING to you (voice). Answer in 1-3 natural spoken sentences. "
               "No lists, tables, markdown or code unless he asks; say numbers and dates the way people say them.")


class Claire:
    def __init__(self, cfg=None, brain=None, store=None):
        self.cfg = cfg or config.load()
        self.brain = brain or Brain(self.cfg["ollama_url"], self.cfg["model"],
                                    self.cfg["temperature"], self.cfg["context_tokens"])
        self.store = store or Store(str(Path(self.cfg["data_dir"]) / "claire.db"))
        self.identity = config.identity_text()
        self.history = []
        self.hands = None                       # Phase 4: set by the app (cli / window) when tools are switched on
        self.tools_ok = True
        self.hot = False                        # the last turn used tools, so a follow-up ("yes, that one") may too
        if not self.store.journal():
            for t, d in FIRST_JOURNAL:
                self.store.journal_add(t, d)
        self.session = self.store.new_session()

    def milestone(self, title, detail=""):
        if not any(r["title"] == title for r in self.store.journal()):
            self.store.journal_add(title, detail)
            return True
        return False

    def system_prompt(self, user_text="", spoken=False):
        user = self.cfg["user_name"]
        parts = [self.identity,
                 f"\n# Right now\nToday is {datetime.now():%A, %d %B %Y, %H:%M}. You are talking with {user}."]
        core = self.store.core_memories()
        if core:
            parts.append("\n# What I know about " + user + "\n" + "\n".join("- " + r["text"] for r in core))
        rel = [r for r in self.store.search(user_text, self.cfg["memories_per_turn"]) if r["kind"] != "core"]
        if rel:
            parts.append("\n# Memories that may be relevant\n" + "\n".join(f"- ({r['created'][:10]}) {r['text']}" for r in rel))
        last = self.store.last_summaries(3)
        if last:
            parts.append("\n# Recent conversations\n" + "\n".join(f"- {r['started'][:10]}: {r['summary']}" for r in last))
        j = self.store.journal(limit=3)
        parts.append("\n# Latest journal entries\n" + "\n".join(f"- {r['at'][:10]}: {r['title']}" for r in j))
        parts.append("\n# Rules for this chat\n- Use memories only when relevant; never invent memories."
                     "\n- If asked what you remember, list it honestly.\n- Keep answers short unless asked for detail."
                     + (HANDS_RULE if self.wants_tools(user_text) else "")
                     + (SPOKEN_RULE.format(user=user) if spoken else ""))
        return "\n".join(parts)

    def reply(self, text, on_token=None, spoken=False):
        msgs = [{"role": "system", "content": self.system_prompt(text, spoken)}]
        msgs += self.history[-self.cfg["recent_turns_kept"] * 2:]
        msgs.append({"role": "user", "content": text})
        answer = self._ask(msgs, on_token, self.wants_tools(text))
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
        self.store.log(self.session, "user", ("🎤 " if spoken else "") + text)
        self.store.log(self.session, "assistant", answer)
        return answer

    def using_tools(self):
        return bool(self.hands and self.hands.enabled and self.tools_ok and hasattr(self.brain, "chat_tools"))

    def wants_tools(self, text):
        return self.using_tools() and (self.hot or bool(TOOL_WORDS.search(text or "")))

    def _ask(self, msgs, on_token, tools=False):
        """The brain's answer; with hands on and a PC-sounding request, she may call tools (up to 4 rounds)."""
        self.hot = False
        if not tools:
            return self.brain.chat(msgs, stream=True, on_token=on_token)
        specs, text = self.hands.specs(), ""
        for _ in range(4):
            try:
                text, calls = self.brain.chat_tools(msgs, specs, on_token=on_token)
            except ToolsUnsupported:
                self.tools_ok = False
                return self.brain.chat(msgs, stream=True, on_token=on_token)
            if not calls:
                return text
            self.hot = True
            msgs.append({"role": "assistant", "content": text,
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
            for c in calls[:3]:
                res = self.hands.call(c["name"], c["arguments"])
                msgs.append({"role": "tool", "tool_name": c["name"], "content": res["text"]})
        return text or "I tried, but I couldn't finish that."

    def reflect(self, session_id=None):
        sid = session_id or self.session
        rows = self.store.session_messages(sid)
        if not rows:
            self.store.end_session(sid, "")
            return "", []
        convo = "\n".join(f"{r['role'].upper()}: {r['content']}" for r in rows)[-12000:]
        known = "; ".join(r["text"] for r in self.store.memories())[-3000:] or "(none)"
        summary, added = "", []
        try:
            raw = self.brain.chat([{"role": "user", "content": EXTRACT_PROMPT.format(
                user=self.cfg["user_name"], known=known, convo=convo)}], stream=False, temperature=0.1, json_mode=True)
            data = parse_json(raw)
            summary = str(data.get("summary", "")).strip()
            if self.cfg.get("auto_memory", True):
                for f in data.get("facts", [])[:10]:
                    t = f.get("text") if isinstance(f, dict) else str(f)
                    if t and self.store.remember(t, "core" if isinstance(f, dict) and f.get("core") else "fact", "auto"):
                        added.append(t)
        except BrainOffline:
            return None, []
        except Exception:
            summary = summary or rows[0]["content"][:120]
        self.store.end_session(sid, summary or "(short chat)")
        return summary, added

    def recover(self):
        out = []
        for sid in self.store.unfinished_sessions(self.session):
            s, f = self.reflect(sid)
            if s is not None:
                out.append((s, f))
        return out

    def new_chat(self):
        res = self.reflect()
        self.history = []
        self.session = self.store.new_session()
        return res


def parse_json(raw):
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw or "", re.S)
        return json.loads(m.group(0)) if m else {}
