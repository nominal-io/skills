# `connect_python` API reference

The `connect_python` package is the Python side of a Connect app. Scripts declared in `app.connect` (via `_kind: script` or `controls:`) are spawned by Connect as subprocesses that talk to the Connect app over ZeroMQ. `connect_python` abstracts that transport.

## Script entrypoint

```python
import connect_python

logger = connect_python.get_logger(__name__)

@connect_python.main
def main(client: connect_python.Client):
    ...

if __name__ == "__main__":
    main()
```

The `@connect_python.main` decorator:
- Opens a `Client` (ZMQ sockets connected to Connect).
- Reads the initial app state (UI values, API key, workspace rid) from stdin.
- Registers any classes decorated with `@connect_python.Command`.
- Runs shutdown callbacks on exit.
- If `NOMINAL_CONNECT_ENVIRONMENT` is unset (script run standalone), constructs a `StubClient` instead — handy for testing outside Connect.

Use `logger = connect_python.get_logger(__name__)` for script logs. Log output is visible in Connect's `display: logs` panel.

## `Client`

### UI values

- `client.get_value(id, default=None)` — read current value of a UI widget by `id`.
- `client.get_values()` — dict of all current widget values.
- `client.set_value(id, value)` — set a UI widget programmatically.
- `client.clear_values(ids)` / `client.clear_all_values()`.
- `client.set_dropdown_options(id, options)` — replace a dropdown's options at runtime.

UI values update live — calling `get_value` re-reads the latest state.

### Streaming

- `client.stream(stream_id, timestamp, value, *, name=None, unit=None)` — single value.
- `client.stream(stream_id, timestamp, *, values=[...], names=[...], units={...})` — multi-channel.
- `client.stream_from_dict(stream_id, timestamp, {"ch1": v1, "ch2": v2}, units={...})` — dict-shaped.
- `client.stream_batch(stream_id, timestamps, values, *, name=..., names=..., unit=..., units=...)` — many rows in one message (use when you have pre-buffered data).
- `client.clear_stream(stream_id)` / `client.clear_all_streams()`.

Timestamps accept integer nanoseconds, float seconds (`time.time()`), strings, or `datetime`.

Stream IDs are arbitrary strings and do not need to be pre-declared. A plot element in `app.connect` with the matching `stream_id` will render whatever data arrives.

### Reading from streams (cached channel values)

- `client.get_channel_values(stream_id, channels=None)` — latest cached value for one/many channels. Returns `{channel: {"timestamp": ..., "value": ...}}` or `{}` if the stream has no data.

This works for streams written by devices (e.g. a CAN interface set up via the Devices panel) or by other scripts. Connect maintains a small in-memory cache per channel.

### Message bus

Pub/sub between scripts and between UI and scripts.

**Quick publish (no explicit bus lifecycle):**

```python
client.send_message("psu/command", {"set_voltage": 5.0, "enable": True})
```

Uses a lazily-created shared `MessageBus`. Good for one-off sends. Not thread-safe for multi-threaded drivers.

**Long-lived subscriber:**

```python
with connect_python.MessageBus(client) as bus:
    bus.subscribe_to_topic("psu/command")
    while True:
        msg = bus.wait_for_message()         # blocks
        # or: msg = bus.try_receive_message()  # non-blocking, returns None if empty
        if msg is None: continue
        handle(msg.topic, msg.contents)
```

- `bus.subscribe_to_topic(topic)` — prefix match. Subscribing to `foo` matches `foo/bar/baz`.
- `bus.publish_message(topic, contents)` — send on this bus instance.
- `bus.unsubscribe_from_topic(topic)`.
- `MessageBus` is NOT thread-safe; create one bus per thread.
- A `MessageBus` must not outlive the `Client` it was created from.

Topic convention: `<scope>/<action>`, e.g. `psu/command`, `pid/update`, `devices/vector:VEC_CH0/command`. UI buttons use `_kind: message` with matching topics.

### Devices panel helpers

Connect's Devices panel owns hardware drivers (LabJack, CAN, NI DAQ, etc.) and exposes per-device command topics.

- `client.set_device_streaming(device_id, streaming: bool)` — start/stop a device.
- `client.send_device_command(device_id, channel_alias, output)` — set an output channel. `output` is one of `AnalogOutputCommand`, `DigitalOutputCommand`, `BinaryParams`, `ConstantParams`, `SineParams`, etc. from `connect_python.output_commands`.

For CAN devices, use raw `send_message` with payloads like `{"send_message": {"interface_name": "VEC_CH0", "message_name": "...", "signals": {...}}}` — the bus topic is `devices/<driver>:<interface>/command`.

### Notifications + timeline

- `client.send_notification(message, level="info", duration_seconds=None)` — toast. Levels: `info`, `warn`, `error`.
- `client.add_timeline_milestone(time, tooltip=None, color=None)` — add a marker on the timeline widget.

### Panels

- `client.hide_panel(uuid)` / `client.focus_panel(uuid)` / `client.restore_panel(uuid)` — where `uuid` is the pane's `id` in `app.connect`.
- `client.show_prompt_window(window_id)` — open a modal defined in `prompt_windows`; returns the user's selections or `None` on cancel.

### Script output

- `client.set_output(value)` — set the output value for this script invocation (appears in `controls: script_table` output column, or in a `display: table` element if the value is a `TableData` dict).
- `with client.write_output(pa.schema(...)) as w: w.write_batch(...)` — Arrow-shaped output, useful for tabular results.

### Shutdown hooks

```python
def cleanup():
    device.close()

client.add_shutdown_callback(cleanup)
```

Callbacks run in reverse order on exit (normal exit OR Connect-initiated shutdown). Exceptions are caught and logged. Always register shutdown for anything that holds a hardware/OS handle.

### Nominal Core client

```python
nm_client = client.create_core_client()
# nm_client is a nominal.core.NominalClient, authenticated with the user's
# current Connect login + workspace.
```

Use this for uploading runs, events, datasets, etc. — whenever the script needs to reach the Nominal backend.

### 3D scene (spatial apps only)

- `client.stream_points(name, timestamp, points)` — stream a point cloud frame.
- `client.create_lidar_scan(...)` — record a lidar scan entry.
- `client.create_models(configs)` — spawn 3D objects at runtime.
- `client.clear_all_created_models()`.
- `client.stream_rgb(buffer_name, timestamp, width, data)` — stream video frames to a `display: video` element.

## Decorators

### `@connect_python.main`

Applied to the script's `main(client)` function. See above.

### `@connect_python.value_hook`

For scripts wired to a widget's `on_change_action`. Receives the widget id + new value automatically.

```python
@connect_python.value_hook
def on_slider_changed(value_id: str, value: float, client: connect_python.Client):
    client.stream("slider_echo", time.time(), value)
```

### `@connect_python.Command(name, description=None)`

Auto-registers a `BaseCommand` subclass with Connect's Command Registry (for the no-code Command Builder UI). Runs at client startup.

```python
from connect_python.commands import BaseCommand

@connect_python.Command(name="Actuate Valve", description="Open or close a valve")
class ActuateValve(BaseCommand):
    valve_id: str
    position: float
    timestamp: int
```

`BaseCommand` is a Pydantic `BaseModel`. Supported field types: `str`, `int`, `float`, `bool`, `Enum`, nested classes. Default values become defaults in the Command Builder UI.

Alternatively call `client.register_command("Actuate Valve", ActuateValve, description=...)` directly at runtime.

### `@connect_python.handle_command(topic, cmd=BaseCommandSubclass)`

Subscribes to a topic and invokes the handler whenever a matching command arrives.

```python
@connect_python.handle_command(topic="valve/command", cmd=ActuateValve)
def handle_valve(client: connect_python.Client, cmd: ActuateValve):
    driver.set_valve(cmd.valve_id, cmd.position)

@connect_python.main
def main(client):
    # ... setup ...
    client.register_and_wait_for_commands()    # blocks until shutdown
```

Each registered topic gets its own background thread with its own `MessageBus`. Call `client.register_and_wait_for_commands()` at the end of `main` to keep the process alive; without it the script will exit immediately after `main` returns.

Handlers receive a validated `cmd` instance (Pydantic validation); validation failures are logged and skipped.

## `TestWorkflow`

A structured test runner. Pair with a `controls: test_workflow` element in `app.connect`.

```python
import connect_python
from connect_python import TestWorkflow

class MyTests(TestWorkflow):
    fail_fast = True           # stop on first failure
    allow_rerun = True         # allow re-running the whole suite
    allow_individual_rerun = True  # allow re-running a single test

    def start_workflow(self, client):
        self.asset_rid = client.get_value("asset_rid", None)
        self.target_v = float(client.get_value("target_voltage", 5.0))

    def test_0_setup(self):
        self.client.send_message("psu/command", {"set_voltage": self.target_v, "enable": True})

    def test_a_sanity(self):
        result = self.client.get_channel_values("psu", "myPSU.ch1_v")
        v = result["myPSU.ch1_v"]["value"]
        self.assertGreater(v, self.target_v - 0.1)
        self.assertLess(v, self.target_v + 0.1)
        self.addComment(f"Measured {v:.3f} V")

    def tearDown(self):
        # runs between each test_*
        pass

    def set_workflow_outputs(self, test_records, client):
        passed = sum(1 for r in test_records if r.is_successful())
        client.set_output(f"{passed}/{len(test_records)} passed")

if __name__ == "__main__":
    MyTests.main()
```

- Methods prefixed with `test_` run in the order they are defined in the source file (not alphabetically). Prefixes like `test_0_`, `test_a_`, `test_b_` are a readability convention — they make the intended order visually obvious but do not affect execution order. To reorder steps, move the method definitions.
- Inherits `unittest.TestCase` assertions: `assertEqual`, `assertGreater`, `assertLess`, `assertAlmostEqual`, `assertIsNotNone`, `fail`, etc. Plus `self.addComment(str)` for step notes.
- `self.client` is the `Client` for the running workflow.
- Set `self.asset_rid` in `start_workflow` to auto-create a Nominal Core Run + Events for the workflow (requires the user to be logged in + the dataset is streaming-persisted).
- `set_workflow_outputs(test_records, client)` runs after all tests; use for summary output (`client.set_output(...)`).

Class-level flags:
- `create_events = True` (default) — auto-create Nominal Core Events per test step.
- `create_run = True` (default) — auto-create a Nominal Core Run spanning the workflow.
- Override `submit_results(test_records, client)` to enable a **Submit** button with custom upload logic.

Related: `AutoSequenceWorkflow`, `RemoteAutoSequenceWorkflow` (same pattern, different execution model).

## StubClient

When a script runs outside Connect (e.g., `python my_script.py` in a terminal), `@connect_python.main` returns a `StubClient` instead of a real `Client`. It accepts all the same calls but just logs them — useful for unit tests or quick local iteration. Detection key: the `NOMINAL_CONNECT_ENVIRONMENT` env var is set only when Connect spawns the script.
