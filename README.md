# C.L.A.I.R.E. — v2.6.0 · Phase 4 (Hands)
Personal AI assistant core by Lagatuz Labs. Runs on your PC. No fees.

![C.L.A.I.R.E.'s window: a living network of light, with a question card asking permission](docs/images/hands_ask.png)

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

## Her window
Run **window.bat** (or `python -m claire --window`). A window opens with a living network of light — the way she looks while she
works. It needs nothing new to install and never leaves this PC (it listens on `127.0.0.1` only).

| She is… | The network… |
|---|---|
| **Ready** | drifts slowly, a few quiet signals travel between clusters |
| **Listening** | draws inward and brightens with *your* voice; rings converge on the centre (cyan) |
| **Thinking** | signals race hub to hub, the whole network flickers (violet) |
| **Speaking** | ripples spread outward in time with *her* voice's loudness (warm) |

| Ready | Listening | Thinking | Speaking |
|---|---|---|---|
| ![Ready](docs/images/orb_idle.png) | ![Listening](docs/images/orb_listening.png) | ![Thinking](docs/images/orb_thinking.png) | ![Speaking](docs/images/orb_speaking.png) |

In the window: type and press Enter · **Talk** (or Ctrl+Space) for push-to-talk · **Hands-free** for “Hey Claire” ·
**Voice: auto/on/off** · **Stop** (or Esc). With the online Edge voice she can't be measured, so the network animates by itself while she speaks.
**Choosing her voice.** Say or type **“change your voice”**: she names her voices (American: Heart, Bella, Nicole…; British: Emma,
Isabella…) and listens for your answer — a name (“Bella”), “the second one”, “faster” / “slower”, then “keep it” or “never mind”.
In hands-free mode she listens for your answer without “Hey Claire” again. The **Voice** button opens the same choices as a list
with **Try** (hear it, then she goes back to her own voice), **Use** (keep it) and a speed slider. She also obeys “speak slower” any time.
(Needs the natural voices from setup_voice.bat; with the basic Windows voice she'll tell you.)

![Her window in light theme](docs/images/orb_light.png)

**Memory** button (top right): see everything she remembers (★ = core facts about you), add a memory, make it core, or
**Forget** one; the **Journal** tab shows her story and lets you add a note. **Theme**: auto (follows Windows) / dark / light.

| Memories | Journal | Voice |
|---|---|---|
| ![Memories](docs/images/panel_memories.png) | ![Journal](docs/images/panel_journal.png) | ![Voice](docs/images/panel_voice.png) |

**Anywhere on your PC:** press **Ctrl+Alt+C** and she starts listening (her window reopens if you closed it). For a tray icon
(Open · Talk · Quit) run `pip install pystray pillow` once; it is optional.
Settings in settings.json: `"ui": {"port": 8765, "open": true, "hotkey": "ctrl+alt+c", "tray": true}` — set `"hotkey": ""` to turn the hotkey off.

## Her hands (new in v2.5) — she acts, but only with your “yes”
Ask in plain words, by voice or typing:

| You say | What she does | Asks first? |
|---|---|---|
| “How's my PC doing?” / “how much disk space is left?” | Reads processor, memory, disks, battery, uptime | No — only reads |
| “Find my visa report” | Searches file **names** in Documents, Downloads, Desktop and lists the matches | No — only reads |
| “Open notepad” (calculator, paint, file explorer, settings, edge, chrome, task manager) | Starts that app | **Yes** |
| “Open that file” / “open example.com” | Opens the file or folder / the website in your normal program | **Yes** |
| “Turn the volume up / down”, “mute” | Presses the volume key | **Yes** |

![She asks "Open Notepad?" with Yes / No / Always, and waits](docs/images/hands_ask.png)

When something needs your OK, a card appears above the text box (and she says it aloud). Answer by **saying or typing**
*yes* / *no* / *always* (hands-free mode listens for your answer without “Hey Claire”), or tap **Yes · No · Always**.
**Always** means “don't ask me about this kind of action again” and is saved in `settings.json` (`tools.always`).
An unanswered question is dropped after 5 minutes. She only says an action happened when it really did.

![After you say yes: "Opened notepad."](docs/images/hands_done.png)

**The Actions tab** (Memory button → *Actions*) shows everything she asked, did, was refused or you declined — the same record
is kept in `data\actions.jsonl`.

| Dark | Light |
|---|---|
| ![Actions tab, dark](docs/images/panel_actions.png) | ![Actions tab, light](docs/images/panel_actions_light.png) |

### New in v2.6 — she watches Task Manager, protects your RAM, and can improve her own code
You asked for her to take much more control. She now has it, with one rule that stays: **she proposes, you decide**.

| You say / she notices | What she does | Asks first? |
|---|---|---|
| “What's using my memory?” | Looks at what is running (like Task Manager), grouped by program: *Chrome 3.1 GB (8 processes)* | No — only reads |
| **Memory goes above 85 %** (even when you haven't asked her anything) | Speaks up once, names the heavy programs and offers to close the biggest one she is allowed to touch | **Yes**, every time |
| “Close Chrome” | Asks the program to close politely (like clicking its X — never forced) | **Yes**, every time |
| “Read your greeting code” / “make your greeting warmer” | Reads her own code, writes a change and **tests it on a copy** with all her tests | No — nothing changes yet |
| “Apply it” | Shows you the exact change (a diff) and asks; if you say yes it is applied, with a backup | **Yes**, every time |
| “Undo that” | Puts the backup back (unless you edited the file since) | **Yes**, every time |

![Memory is high: she names the programs and asks before closing Chrome](docs/images/hands_ram.png)

![She wants to change her own code: you see the diff and tests-passed before saying yes](docs/images/hands_selfedit.png)

- **Always never applies** to closing programs or changing her own code; the *Always* button is hidden for them.
- **Never closed:** Windows' own parts (`svchost`, `explorer`, `lsass`, …), security software, terminals, Python, and **Ollama** (her brain).
- **Her code:** she may change `claire/` (except the files below), `tests/`, `docs/`, README, ROADMAP and `identity.md` — only `.py`, `.html`, `.md`.
  **Off limits to her** (only you can edit these, by hand): her safety rules `claire/hands/`, the window server `claire/web.py`,
  `claire/cli.py`, `claire/config.py`, the safety tests, `settings.json`, your `data` folder, and every `.bat` launcher.
  A change that makes any test fail is rejected automatically. Changes take effect after you restart her.
  Backups are in `data\backups`, proposals in `data\proposals`, and everything is in the Actions log.
- Turn the memory watcher off or change its level: `"tools": {"ram_watch": true, "ram_warn_percent": 85}`.

**Not built (on purpose):** taking over or disconnecting *other* devices on your network, and acting with no approval at all.
A 7B local model gets things wrong sometimes; asking first is what keeps one wrong guess from costing you your work.
**Next for your devices:** the Samsung phone and watch link (Wi-Fi ADB / Samsung tools) and a read-only network map — planned as Phase 4.7.

**What she will never do:** delete, send, install, or run commands — those tools simply don't exist (her only way to change files is the tested, approved change to her own code above). Other rules, all covered by tests:
- Files only inside the folders in `tools.folders` (default Documents, Downloads, Desktop); `..` tricks, shortcut/link
  escapes and network paths (`\\server\share`) are refused.
- Programs and files that can run code (`.exe .bat .ps1 .lnk .js .vbs .docm …`) are never opened — she tells you where they are.
- Websites: only `http`/`https`, and never an address with a hidden login (`google.com@evil.com`).
- Apps: only the ones on her list (`tools.apps`). Not on the list → “I only open apps on my list”. No terminals by default.
- If her model can't use tools she simply chats as before (the quick answers above still work with `qwen2.5:7b`).

Settings in settings.json:
```json
"tools": {"enabled": true,
          "folders": ["~/Documents", "~/Downloads", "~/Desktop", "D:/Work"],
          "apps": {"notepad": "notepad", "calculator": "calc"},
          "always": [], "volume_step": 10}
```
Set `"enabled": false` to switch her hands off. doctor.bat shows which folders she can search.

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

Hands: “how's my PC”, “find …”, “open …”, “volume up” — she asks before opening or changing anything (see *Her hands*).

Memory commands from Phase 1: `/remember`, `/remember!`, `/forget`, `/memories`, `/journal`, `/new`, `/model`, `/status`, `/quit`.

## Troubleshooting
- **Still the robotic voice?** `/status` shows why the natural voice was skipped (e.g. not installed, files missing).
- **Install errors:** use Python 3.12. Newer versions may not have the voice packages yet.
- **Download blocked:** the Studio prints two links; download them in your browser into the `voices` folder.

## Pictures
The screenshots in this file are made by `python docs/make_screenshots.py` (needs `pip install playwright`); they use a
pretend brain, voice and PC, so nothing is opened or changed while they are taken.

## Privacy
Speech recognition and the Kokoro voice run on this PC. Audio isn't saved; only message text is kept in `data\claire.db`. Actions are logged in `data\actions.jsonl`. File search reads names only, never contents.
