"""Brain: talks to a local Ollama server (standard library only, no installs)."""
import json
import urllib.error
import urllib.request


class BrainOffline(Exception):
    pass


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
        payload = {"model": self.model, "messages": messages, "stream": stream,
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
