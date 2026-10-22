# C.L.A.I.R.E. — Roadmap
**Centralized Logic And Intelligent Record Executive** · Lagatuz Labs
Rules for every phase: **local first** · **ask before acting** · **tests must pass** · **she keeps her story**.

## Phase 1 · Awakening  ✅ complete (v1.0.0)
1.1 Identity & origin story · 1.2 Brain (Ollama, streaming) · 1.3 Terminal chat · 1.4 Long-term memory ·
1.5 Learns facts automatically · 1.6 Journal · 1.7 Recalls past chats · 1.8 Settings, launchers, tests

## Phase 2 · Voice  ✅ complete (v2.1.0)
| # | Milestone | Status |
|---|---|---|
| 2.1 | Natural voice: Kokoro (offline) · Edge neural (online option) · Piper · Windows fallback | ✅ v2.1 |
| 2.1b | Voice Studio: audition, blend two voices, speed, save · `/voice try/use/speed/engine` | ✅ v2.1 |
| 2.1c | Gap-free speech: next sentence prepared while the current one plays | ✅ v2.1 |
| 2.2 | Speech-to-text (faster-whisper, offline) with end-of-speech detection | ✅ |
| 2.3 | "Hey Claire" hands-free mode; optional openWakeWord | ✅ |
| 2.4 | Push-to-talk, voice modes auto/on/off, mute & stop by voice | ✅ |
| 2.5 | Natural spoken answers; journal entries "Found my voice", "Chose my voice" | ✅ |

## Phase 3 · Face: desktop app  ✅ complete (v2.3.0)
| # | Milestone | Status |
|---|---|---|
| 3.1 | Chat window (local web UI, this PC only) | ✅ v2.2 |
| 3.5 | Living neural-network orb: idle · listening (your voice) · thinking · speaking (her voice) · Talk button | ✅ v2.2 |
| 3.2 | Global hotkey (Ctrl+Alt+C) + optional tray icon | ✅ v2.3 |
| 3.3 | Memory & journal viewer/editor | ✅ v2.3 |
| 3.4 | Light/dark theme (auto / dark / light) | ✅ v2.3 |
| 3.6 | Choose her voice by talking (“change your voice”) + Voice tab with Try / Use / speed | ✅ v2.4 |

## Phase 4 · Hands — tools on the PC (ask before acting)  ✅ complete (v2.5.0)
| # | Milestone | Status |
|---|---|---|
| 4.1 | Tool calling through Ollama (falls back to plain chat if the model has no tool support) | ✅ v2.5 |
| 4.2 | Safe, read-only tools: PC status (CPU · memory · disks · battery · uptime), file search in Documents / Downloads / Desktop | ✅ v2.5 |
| 4.3 | Ask-first tools: open a file/folder, open an app from her list, open a website, volume up/down/mute | ✅ v2.5 |
| 4.4 | Approval: spoken or typed yes / no / always, or buttons on a question card in her window | ✅ v2.5 |
| 4.5 | Audit log (`data\actions.jsonl`) + **Actions** tab in the window | ✅ v2.5 |
| 4.6 | Safety rules, tested: no delete/send/run-command tools, allowed folders only, no `..`/link/network-path escapes, programs and macro files never opened, http(s) links only (no hidden logins), apps only from her list | ✅ v2.5 |
### Phase 4.5 · Control — Task Manager, RAM, self-editing  ✅ v2.6.0
| # | Milestone | Status |
|---|---|---|
| 4.5.1 | Task Manager awareness (programs grouped, biggest first) | ✅ |
| 4.5.2 | RAM watcher: warns once, offers to close the biggest allowed program (always asks, never system/Ollama/Python) | ✅ |
| 4.5.3 | Self-editing: propose → tested on a copy → diff shown → your yes → applied with backup → undo; safety files protected | ✅ |
### Phase 4.7 · Devices  ✅ v2.7.0
| # | Milestone | Status |
|---|---|---|
| 4.7.1 | Read-only network map (devices on your Wi-Fi, flag new/unknown; private ranges only) | ✅ |
| 4.7.2 | Android/Samsung phone link (Wi-Fi ADB: status, connect, open listed apps) — ask-first | ✅ |
| 4.7.3 | Watch & smart-home via your own named shortcuts (Tasker / SmartThings / Home Assistant, LAN only) — ask-first | ✅ |

## Phase 5 · Knowledge — your documents, with sources  ✅ v2.7.0
| # | Milestone | Status |
|---|---|---|
| 5.1 | Local index (SQLite full-text) of allowed folders; incremental updates | ✅ |
| 5.2 | Readers: txt/md/csv/html/docx/pptx (+ pdf with pypdf), Arabic OK | ✅ |
| 5.3 | Answers cite file + place (lines / paragraphs / slide / page); "not found" instead of guessing | ✅ |
| 5.4 | Safety: allowed folders only, links out ignored, document text treated as data | ✅ |
| 5.5 | Meaning-based search with embeddings (Ollama `nomic-embed-text`) | ⬜ later |

## Phase 6 · Growth — memory review, evaluation set, optional fine-tune
## Phase 7 · Autonomy — briefings, schedules, proactive reminders
