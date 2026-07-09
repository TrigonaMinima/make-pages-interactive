---
name: make-pages-interactive
description: Turn a directory of static HTML or Markdown pages into a live commenting surface. Injects a feedback library, starts a tiny server, and routes user comments into a JSONL inbox that the agent monitors and responds to by editing the pages. Trigger phrases — "make this page interactive", "make these pages interactive", "let me comment on this page", "add feedback to these pages", and markdown variants like "make this markdown interactive", "add feedback to this .md".
---

# Make Pages Interactive

Turns any folder of HTML (or Markdown) files into a place the user can leave inline comments on (text selections, element selections, page-level notes). Comments POST to a local JSONL inbox; you (the agent) Monitor that inbox, edit the files in response, append to `feedback/history.json`, and the page auto-reloads with a walkthrough of what changed.

**Markdown is fully supported.** When the input is `.md`, it is the canonical file you edit. A thin HTML wrapper renders it client-side via `marked.js`. The `.md` on disk is the export — just open or copy it. See [Markdown flow](#markdown-flow) below.

## When to invoke

User says any of:
- "make this page interactive" / "make these pages interactive" → **Setup flow**
- "add feedback to this page" / "let me comment on this page" → **Setup flow**
- "set up feedback on <dir>" → **Setup flow**
- "make this markdown interactive" / "add feedback to this .md" → **Setup flow (markdown)**
- "stop the feedback server" / "kill the server" / "shut it down" → **Stop flow**
- "remove the feedback layer" / "make pages static again" → **Removal flow**
- "update the make-pages-interactive skill" → **Update flow**

---

## Setup flow — HTML pages

1. **Identify the target directory.** Usually the user's current working directory or a folder they named. If ambiguous, ask.
2. **Inject the feedback tags** into every `*.html` in that directory:
   ```
   python ~/.claude/skills/make-pages-interactive/scripts/inject.py <dir>
   ```
   Add `--recursive` if the pages live in subfolders. The script is idempotent — safe to re-run. It also creates `<dir>/feedback/inbox.jsonl` and `<dir>/feedback/history.json` if missing.
3. **Pick a port.** Default 5050. Before starting, check what's there:
   ```
   curl -s --max-time 2 http://localhost:5050/info
   ```
   - JSON with `artifact_dir` matching this `<dir>` → reuse it, skip to step 5.
   - JSON with a *different* `artifact_dir` → port is held by another exploration. Either ask the user to free it (`lsof -ti:5050 | xargs kill`) or use port 5051, 5052, … (try the next port; tell the user the URL).
   - No response → port 5050 is free.
4. **Start the server in the background** via Bash with `run_in_background: true`:
   ```
   python ~/.claude/skills/make-pages-interactive/lib/server.py <dir> --port <chosen>
   ```
   The server auto-shuts-down on parent death or 10 min of idle, so you don't need to manage its lifecycle.
5. **Tell the user the URL.** For example: `http://localhost:5050/index.html` (use whatever filename they actually have). If they have multiple pages, list the top-level ones.
6. **Start a Monitor on the inbox** so new comments notify you immediately:
   ```
   Monitor on path: <dir>/feedback/inbox.jsonl
   ```
   Do NOT poll — let the Monitor notification arrive.

---

## Setup flow — Markdown pages {#markdown-flow}

Markdown is the canonical artifact. You edit the `.md` directly; the HTML wrapper is a generated, marker-guarded view of it.

1. **Identify the target.** Single `.md` file or a directory of `.md` files.
2. **Generate the HTML wrapper(s)**:
   ```
   python ~/.claude/skills/make-pages-interactive/scripts/mdwrap.py <path>
   ```
   For each `<name>.md` this creates a sibling `<name>.html` that fetches and renders the markdown via `marked.js`, then boots `feedback.js`. Add `--recursive` to walk subdirectories. The script is idempotent.
3. **Pick a port, start the server, tell the user the URL, and start the Monitor** — identical to steps 3–6 of the HTML flow above. The server needs no changes; it already serves `/lib/*` from the skill's `lib/` directory where `marked.min.js` and `markdown.css` live.

---

## Responding to a feedback batch — HTML pages

When a new batch arrives in `inbox.jsonl`:
- Read the entry. Each comment has a stable `cf_id` and a selector pointing to the exact element/text the user commented on.
- Edit the relevant HTML files to address each comment. Wrap each modified region with `<span data-cf-change="ch-<short-slug>">...</span>` (or add `data-cf-change` to an existing wrapping element) so the post-reload walkthrough can find the change. One anchor per change.
- **Append** a new batch object to the end of `<dir>/feedback/history.json` (newest = last; the library walks from the end to find the latest batch). Schema:
  ```json
  {
    "batch_id": "b-<timestamp-or-slug>",
    "timestamp": "<ISO 8601>",
    "comments": [ /* echo back the inbox comments you addressed */ ],
    "changes": [
      {
        "id": "ch-<slug>",
        "in_response_to": ["<cf_id from inbox>"],
        "anchor": "ch-<slug>",
        "title": "short, concrete",
        "description": "longer prose (hidden in UI, just for the record)"
      }
    ]
  }
  ```
- The page polls `history.json`, sees the new batch, auto-reloads (scroll position preserved), and offers the user a walkthrough of the changes. The "processing…" banner clears automatically when any `in_response_to` matches a submitted comment id.

## Responding to a feedback batch — Markdown pages

The flow is the same **except you edit the `.md` file**, not the `.html` wrapper.

- Edit the relevant `.md` file to address each comment.
- **Anchor lifecycle — keep the file clean:**
  - At the **start** of each round, strip the **previous** round's `data-cf-change` spans from the `.md` (a simple regex replace: `<span data-cf-change="[^"]*">` / `</span>`). The tour only needs to highlight the most recent batch.
  - Wrap each newly changed region with an inline span: `<span data-cf-change="ch-...">edited text</span>`. This is valid `marked.js` passthrough — the span renders in the DOM and the feedback tour can find it.
  - Do **not** nest anchor spans inside each other.
- Append the batch to `history.json` as usual. On reload, the wrapper re-fetches and re-renders the `.md`, `feedback.js` re-initializes, and the tour finds the new anchors automatically.
- **When the user says they are done / wants to export:** strip **all** `data-cf-change` spans from the `.md` so the file is byte-clean. The `.md` on disk is the export — point them at the path. No reconstruction needed.

### Post in-flight status while you work

When you receive feedback and start working, POST a short status string so the user sees what you're doing instead of just a generic spinner:

```
POST /status
{"comment_id": "<cf_id from inbox>", "message": "Rewriting the intro section (~30s)"}
```

To clear an entry early, POST the same `comment_id` with `message: null` or `""`. Entries are auto-pruned by the server after 10 min so a crashed agent never leaves a stuck "working" message.

`history.json` remains the source of truth for "done" — the status message is decoration only. The banner clears the moment a matching batch lands in `history.json`, regardless of whether you cleared the status entry.

---

## On startup in a directory that already has feedback

If you find `<dir>/feedback/inbox.jsonl` and `<dir>/feedback/history.json` and the skill has been invoked in this session:
1. Scan inbox for comment ids.
2. Scan history's `changes[*].in_response_to` union — those are already processed.
3. If unprocessed comments exist, tell the user the count and ask whether to process now.
4. Either way, set up the Monitor on the inbox.

---

## Stop flow (user wants to kill the server)

1. Identify the port. If you started the server in this session, you know it. Otherwise check `curl -s http://localhost:5050/info` (try 5051, 5052 if 5050 returns nothing or a different artifact).
2. Kill it: `lsof -ti:<port> | xargs kill` (use `kill -9` only if a plain kill doesn't free the port within a few seconds — the server traps SIGTERM and exits cleanly).
3. Confirm: `lsof -i :<port>` should be silent.
4. If you also started a `Monitor` on the inbox in this session, it will keep watching the file — that's fine, the file just won't get new entries.

Note: in most cases the user doesn't need to manually stop the server. It auto-shuts-down when (a) the parent process dies (e.g. they close the Claude Code window — within ~5–10 s) or (b) no client requests for 10 min. Manual stop is for the case where they want the port back *right now* in the same session.

---

## Update flow (user wants the latest lib/)

```
python ~/.claude/skills/make-pages-interactive/scripts/update.py
```
Runs `git pull --ff-only` inside the skill dir. Requires git-clone install (the script tells the user how to re-install if not).

---

## Removal flow (clean static copy)

**HTML pages:**
```
python ~/.claude/skills/make-pages-interactive/scripts/inject.py <dir> --remove
```
Strips both feedback tags from every `*.html`. Leaves the `feedback/` directory alone (delete manually if not wanted).

**Markdown pages:**
```
python ~/.claude/skills/make-pages-interactive/scripts/mdwrap.py <path> --remove
```
Deletes the generated `<name>.html` wrapper for each `<name>.md` (marker-guarded — only removes files generated by `mdwrap.py`). The `.md` files and the `feedback/` directory are untouched.

---

## Files in this skill

```
~/.claude/skills/make-pages-interactive/
├── SKILL.md              # this file (agent-facing)
├── README.md             # GitHub-facing docs (human readers)
├── LICENSE
├── lib/
│   ├── feedback.js       # client library: selection + commenting + tour
│   ├── feedback.css      # feedback UI styles
│   ├── marked.min.js     # vendored markdown renderer (v15.0.12, MIT)
│   ├── markdown.css      # document theme for .md-rendered pages
│   └── server.py         # stdlib-only HTTP server
└── scripts/
    ├── inject.py         # idempotent feedback tag injection / removal (HTML)
    ├── mdwrap.py         # generate / remove HTML wrappers for .md files
    └── update.py         # git pull --ff-only
```

---

## Gotchas

- All `/lib/*` assets (including `marked.min.js`, `markdown.css`, `feedback.js`) are served from the skill's own `lib/` directory by `server.py`. Pages only work when opened through this server — opening the HTML directly in a browser will silently fail to load the feedback widget and the markdown renderer.
- `history.json` order matters: append, do not prepend. The library walks from the end to find the latest batch for the walkthrough.
- `anchor` values must match a `data-cf-change` attribute actually present in the HTML (or rendered from the `.md`). Typos here cause "anchor not found" warnings post-reload.
- For markdown pages: do not nest `data-cf-change` spans inside each other — the strip regex on export would leave unmatched tags.
- The generated `.html` wrapper is marker-guarded (`<!-- cf-mdwrap generated -->`). `mdwrap.py --remove` will not delete files without that marker, so hand-written HTML files with the same name are safe.
