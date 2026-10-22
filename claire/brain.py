"""Brain: talks to a local Ollama server (standard library only, no installs)."""
import json
import urllib.error
import urllib.request


class BrainOffline(Exception):
    pass


class ToolsUnsupported(Exception):
    """This model can't use tools; she carries on as a plain chat."""


class Brain:
    def __init__(self, url, model, temperature=0.6, context_tokens=8192, timeout=300):
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.ctx = context_tokens
        self.timeout = timeout

    def _post(self, path, payload):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            if e.code == 404 and "not found" in body:
                raise BrainOffline(f"The model '{self.model}' isn't downloaded yet. Run:  ollama pull {self.model}")
            raise BrainOffline(f"Ollama error {e.code}: {body[:200]}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise BrainOffline("I can't reach my brain (Ollama). Start the Ollama app, then try again. "
                               f"[{getattr(e, 'reason', e)}]")

    def models(self):
        with urllib.request.urlopen(self.url + "/api/tags", timeout=5) as r:
            return [m["name"] for m in json.load(r).get("models", [])]

    def online(self):
        try:
            self.models()
            return True
        except Exception:
            return False

    def chat(self, messages, stream=True, on_token=None, temperature=None, json_mode=False):
        """Returns the full reply text. Calls on_token(piece) while streaming."""
        payload = {"model": self.model, "messages": messages, "stream": stream, "keep_alive": "30m",
                   "options": {"temperature": self.temperature if temperature is None else temperature,
                               "num_ctx": self.ctx}}
        if json_mode:
            payload["format"] = "json"
        resp = self._post("/api/chat", payload)
        out = []
        with resp:
            if not stream:
                return json.load(resp)["message"]["content"]
            for line in resp:
                if not line.strip():
                    continue
                part = json.loads(line)
                piece = part.get("message", {}).get("content", "")
                if piece:
                    out.append(piece)
                    if on_token:
                        on_token(piece)
                if part.get("done"):
                    break
        return "".join(out)

    def chat_tools(self, messages, tools, on_token=None, temperature=None):
        """One streamed round with tools offered. Returns (text, calls) where calls is a list of
        {"name": ..., "arguments": {...}}. Raises ToolsUnsupported if the model has no tool support."""
        payload = {"model": self.model, "messages": messages, "stream": True, "tools": tools, "keep_alive": "30m",
                   "options": {"temperature": self.temperature if temperature is None else temperature,
                               "num_ctx": self.ctx}}
        try:
            resp = self._post("/api/chat", payload)
        except BrainOffline as e:
            if "does not support tools" in str(e):
                raise ToolsUnsupported(str(e))
            raise
        out, calls = [], []
        with resp:
            for line in resp:
                if not line.strip():
                    continue
                part = json.loads(line)
                msg = part.get("message", {})
                piece = msg.get("content", "")
                if piece:
                    out.append(piece)
                    if on_token:
                        on_token(piece)
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    if fn.get("name"):
                        calls.append({"name": fn["name"], "arguments": args if isinstance(args, dict) else {}})
                if part.get("done"):
                    break
        return "".join(out), calls
