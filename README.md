# C.L.A.I.R.E. — v2.4.1 · Phase 3 (Face)
Personal AI assistant core by Lagatuz Labs. Runs on your PC. No fees.

## Setup
1. **Python 3.12** (3.10–3.13 work) — https://www.python.org/downloads/ · tick **Add python.exe to PATH**.
2. **Ollama** — https://ollama.com/download (leave it running).
3. Unzip this folder, e.g. `C:\CLAIRE`. Moving from an older version? Copy your old `data` folder in.
4. **setup_claire.bat** — gives her her *own* Python (a `.venv` folder, built from Python 3.10–3.13 even if a newer Python is
   also installed), downloads her brain, runs the self-test.
5. **setup_voice.bat** — installs her ears and her natural voice into that Python, opens the **Voice Studio**, tests the mic.
   If a package fails to install it stops and shows the error — send that text to get it fixed.
6. **start_claire.bat** — talk to her in the terminal, or **window.bat** — open her window (below).
If `.bat` files are blocked, rename the `.bat.txt` copies.

**Something not working (no natural voice, no microphone…)?** Run **doctor.bat**. It checks Python, every package, the voice
files, microphone, speakers and Ollama, and says exactly what to do about each ✗. Her voice files can be present while the
Python package that uses them is not — doctor.bat shows that difference.

## Her window (new)
Run **window.bat** (or `python -m claire --window`). A window opens with a living network of light — the way she looks while she
works. It needs nothing new to install and never leaves this PC (it listens on `127.0.0.1` only).

| She is… | The network… |
|---|---|
| **Ready** | drifts slowly, a few quiet signals travel between clusters |
| **Listening** | draws inward and brightens with *your* voice; rings converge on the centre (cyan) |
| **Thinking** | signals race hub to hub, the whole network flickers (violet) |
| **Speaking** | ripples spread outward in time with *her* voice's loudness (warm) |

In the window: type and press Enter · **Talk** (or Ctrl+Space) for push-to-talk · **Hands-free** for “Hey Claire” ·
**Voice: auto/on/off** · **Stop** (or Esc). With the online Edge voice she can't be measured, so the network animates by itself while she speaks.
**Choosing her voice.** Say or type **“change your voice”**: she names her voices (American: Heart, Bella, Nicole…; British: Emma,
Isabella…) and listens for your answer — a name (“Bella”), “the second one”, “faster” / “slower”, then “keep it” or “never mind”.
In hands-free mode she listens for your answer without “Hey Claire” again. The **Voice** button opens the same choices as a list
with **Try** (hear it, then she goes back to her own voice), **Use** (keep it) and a speed slider. She also obeys “speak slower” any time.
(Needs the natural voices from setup_voice.bat; with the basic Windows voice she'll tell you.)

**Memory** button (top right): see everything she remembers (★ = core facts about you), add a memory, make it core, or
**Forget** one; the **Journal** tab shows her story and lets you add a note. **Theme**: auto (follows Windows) / dark / light.

**Anywhere on your PC:** press **Ctrl+Alt+C** and she starts listening (her window reopens if you closed it). For a tray icon
(Open · Talk · Quit) run `pip install pystray pillow` once; it is optional.
Settings in settings.json: `"ui": {"port": 8765, "open": true, "hotkey": "ctrl+alt+c", "tray": true}` — set `"hotkey": ""` to turn the hotkey off.

## Her voice
| Engine | Quality | Where it runs | Notes |
|---|---|---|---|
| **kokoro** (default) | Natural, human-like | This PC, offline | ~340 MB one-time download |
| **edge** | Natural, very expressive | Online (Microsoft) | Needs internet; the text she speaks goes to Microsoft |
| piper | Good | Offline | Older engine, optional |
| windows | Basic, robotic | Offline | Last resort |

**Voice Studio** (`studio.bat`, or `/voice studio` in chat): hear every voice say the same line, then
- `1`…`10` listen · `all` hear them all · `mix 1 7 0.6` blend two voices (60/40) into one that is only hers
- `speed 0.95` slightly slower sounds calmer · `say <text>` test your own words · `edge` online voices · `save`

Best starting points: **af_heart** (warm, most natural), **bf_emma** (elegant British),
or a blend like `af_heart:0.6+bf_emma:0.4`.

## Talking
| Do this | What happens |
|---|---|
| Type a message | She answers on screen (and aloud if voice is `on`) |
| Press **Enter** on an empty line | Push-to-talk: speak, she answers aloud |
| `/handsfree` | She listens for **“Hey Claire, …”**. Say “stop listening” or press Ctrl+C |
| “mute” / “talk to me” / “stop” | Voice off / always on / stop talking now |
| `/voice list` · `/voice try <name>` · `/voice use <name>` | Browse, audition, keep a voice |
| `/voice speed 0.95` · `/voice engine kokoro\|edge\|windows` | Pace · engine |

Memory commands from Phase 1: `/remember`, `/remember!`, `/forget`, `/memories`, `/journal`, `/new`, `/model`, `/status`, `/quit`.

## Troubleshooting
- **Still the robotic voice?** `/status` shows why the natural voice was skipped (e.g. not installed, files missing).
- **Install errors:** use Python 3.12. Newer versions may not have the voice packages yet.
- **Download blocked:** the Studio prints two links; download them in your browser into the `voices` folder.

## Privacy
Speech recognition and the Kokoro voice run on this PC. Audio isn't saved; only message text is kept in `data\claire.db`.
