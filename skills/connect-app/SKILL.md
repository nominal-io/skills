---
name: connect-app
description: Scaffold a Nominal Connect app (app.connect YAML + Python scripts) from a high-level description of its UI and behavior. Use when the user asks to create a new Connect app, or to turn a description of a monitoring, control, or test UI into a runnable app with wired-up Python scripts, message-bus commands, and streaming.
---

# Connect app

Scaffold Nominal Connect apps: a directory containing an `app.connect` YAML and supporting Python scripts that the user can open in the Connect desktop app.

## What a Connect app is

A Nominal Connect app is a directory containing:

- `app.connect` — YAML declaring the UI (tabs, panes, forms, plots, buttons, canvases).
- One or more Python scripts launched by the UI. Scripts read UI values, publish to the message bus, stream data back to plots, handle commands, and/or orchestrate test workflows.
- Optional: `requirements.txt`, canvas YAMLs, DBC files, device config JSONs, images, `README.md`.

A user launches the app by opening its directory in Connect. On first load, Connect creates a `.venv/` inside the directory and installs `connect-python` (plus anything in `python.packages` in `app.connect`). The user never runs `pip install` by hand.

## Workflow

### Step 1. Elicit the spec

Before writing anything, confirm:

1. **Where does the app live?** Ask for the target directory if it isn't obvious from the request.
2. **What is the UI?** Which tabs, what's in each tab (plots, forms, buttons, markdown), what widgets the user interacts with. Sketch a rough layout.
3. **What Python scripts?** One per long-running device/driver, plus any one-shot "run once" scripts and any test workflows. Each script owns exactly one concern.
4. **What streams and topics?** Name each data stream (plot `stream_id`) and each message-bus topic (`<scope>/<action>`). These are strings shared between YAML and Python.
5. **External deps?** Hardware libraries (`nominal-instro`, `pycan`, etc.), the Devices panel, streaming persistence to Nominal Core.

If the user gave a freeform description and some of this is ambiguous, ask — don't guess on stream IDs or script boundaries, since they're load-bearing.

### Step 2. Pick a starting point

- **Trivial / "hello world"-shaped app** (one tab, a few widgets, one script): copy [`assets/hello-world/`](assets/hello-world/) into the target directory and modify in place.
- **Non-trivial app**: start from a blank `app.connect` and build up, using [`references/patterns.md`](references/patterns.md) for the shape of each script.

When working inside the Nominal `connect` repository, the apps under `test_apps/examples/` are the canonical reference for real-world layouts. Read them rather than copying them — the example layouts are complex and copying one wholesale imports unrelated UI.

### Step 3. Write `app.connect`

The grammar is large. **Read [`references/app_connect_schema.md`](references/app_connect_schema.md)** to get the full element catalog (tiles, grids, panes, inputs, displays, plots, actions).

**Every app must remain editable in Connect's no-code UI builder.** This is a hard requirement, not a preference — users rearrange apps by hand, and an app that has dropped out of the UI builder cannot be fixed without hand-editing YAML. Three constraints enforce it:

- The top-level `tiles` **must** be a single `layout: tabs` tile. Nest grids inside a tab; never hoist one to the top level.
- Every pane **must** contain at least one element. Give a spacer pane a `display: header` or `display: markdown` rather than leaving it bare.
- Every pane **must** set `should_fill: true`.

Other invariants:

- Every `pane` needs a unique UUIDv4 `id`. Generate one per pane at authoring time — `uuidgen | tr '[:upper:]' '[:lower:]'` (macOS/Linux) or `python -c "import uuid; print(uuid.uuid4())"` — and paste the result directly into the YAML. Never hardcode placeholder strings like `00000000-...` or reuse IDs across panes; duplicates cause egui ID collisions.
- Widget `id`s (the `id:` on inputs and buttons) are the keys scripts use with `client.get_value(id)`. Use `snake_case`; must be unique across the app.
- Stream IDs referenced in plots (`stream_id: foo`) are plain strings — scripts create them implicitly the first time they call `client.stream("foo", ...)`.
- `on_click_action` has two kinds: `_kind: script` (launches a Python script) and `_kind: message` (publishes a dict to a message-bus topic, with `$widget_id` substituted from current UI values).
- For apps that persist data, populate `streaming.persistence[]` with the target dataset RID and the list of streams to upload.

### Step 4. Write the Python scripts

**Read [`references/connect_python_api.md`](references/connect_python_api.md)** for the full API surface and **[`references/patterns.md`](references/patterns.md)** for the five idioms (one-shot, long-running driver + UI, closed-loop controller, TestWorkflow orchestrator, Command Registry). Pick the pattern that matches each script's role and adapt it.

Conventions:

- Every script starts with `@connect_python.main` wrapping a `main(client)` function.
- `logger = connect_python.get_logger(__name__)` — this routes to Connect's logs panel.
- For any hardware handle, register `client.add_shutdown_callback(lambda: thing.close())` early.
- Put shared strings (stream IDs, message-bus topics, device names) in a `constants.py` so YAML and Python can't drift.
- Reading UI: `client.get_value("id", default)` or `client.get_values()` (all at once). Writing UI: `client.set_value("id", value)`.
- Streaming: `client.stream(stream_id, timestamp, value, name="channel_name")` for single-channel, `client.stream(stream_id, timestamp, values=[...], names=[...])` for multi-channel.
- Message bus: `client.send_message(topic, dict)` for one-offs; `with MessageBus(client) as bus: bus.subscribe_to_topic(...); bus.wait_for_message()` for subscribers. Use `try_receive_message()` (non-blocking) inside control loops.
- For `@connect_python.handle_command` handlers, call `client.register_and_wait_for_commands()` at the end of `main` or the process exits.
- For test workflows, subclass `connect_python.TestWorkflow`. Test methods (`test_*`) run in the order they are defined in the source file, not alphabetically — prefixes like `test_a_`, `test_b_` are just a readability convention that makes the intended order obvious. Set `self.asset_rid` in `start_workflow` to auto-upload to Nominal Core, and always define a final shutdown step that returns hardware to safe state.

### Step 5. Sanity-check

Before handing back:

1. **UI builder compatibility holds**: top-level `tiles` is a single `layout: tabs`, every pane has `should_fill: true`, and no pane is empty. Check this first — it is the easiest thing to break and the most disruptive to the user.
2. Every widget `id` referenced in `client.get_value`/`get_values` has a matching `input:` entry in `app.connect`.
3. Every `stream_id` used in `client.stream` appears in at least one plot, `display: stream_value`, or `streaming.persistence[].streams[]`.
4. Every message-bus topic published from `_kind: message` is subscribed to by a script (and vice versa).
5. All pane `id`s are UUIDv4s and unique.
6. Shutdown callbacks registered for anything that opens a hardware/network handle.

Do not attempt to run the app — it requires the Connect GUI on the user's machine and often physical hardware. Tell the user how to test manually (e.g. "open the directory in Connect, click Run on `my_script.py`, verify the plot populates").

## Quick decision guide

- User wants one button that runs a script and shows a result? → Pattern 1 in `references/patterns.md`. Start from `assets/hello-world/`.
- User wants live readings from a device + UI to command it? → Pattern 2. One long-running script per device.
- User wants live-tunable control loop? → Pattern 3. Keep UI params in a separate `*/update` topic, apply via `try_receive_message`.
- User wants an automated pass/fail test? → Pattern 4. `TestWorkflow` with `test_*` methods and a `controls: test_workflow` element.
- User wants the no-code Command Builder? → Pattern 5. `@Command` + `@handle_command` + `client.register_and_wait_for_commands()`.

## Resources

- [`references/app_connect_schema.md`](references/app_connect_schema.md) — YAML schema: tiles, grids, panes, elements, inputs, actions, streaming. **Read this before editing `app.connect`.**
- [`references/connect_python_api.md`](references/connect_python_api.md) — `connect_python` API: Client methods, MessageBus, decorators, TestWorkflow. **Read this before writing scripts.**
- [`references/patterns.md`](references/patterns.md) — Five idiomatic patterns with full YAML+Python examples.
- [`assets/hello-world/`](assets/hello-world/) — Copy-and-modify starter template (one tab, form, button, plot, one script).

## Reporting back

When you finish, report concisely:

- Where the app was written (absolute path).
- Which scripts were created and their roles.
- Stream IDs and message-bus topics used.
- How to test manually (open directory in Connect, click Run on `<script>`, expected behavior).

Do not narrate intermediate file reads or summarize the full YAML — the user can open the files themselves.
