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
- Swallows `KeyboardInterrupt` (that is how Connect-initiated shutdown reaches the script).
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

- `client.stream(stream_id, timestamp, value, *, name=None, unit=None, start_time=None)` — single value.
- `client.stream(stream_id, timestamp, *, values=[...], names=[...], units={...}, start_time=None)` — multi-channel.
- `client.stream_from_dict(stream_id, timestamp, {"ch1": v1, "ch2": v2}, start_time=None, units={...})` — dict-shaped.
- `client.stream_batch(stream_id, timestamps, values, name=..., names=..., unit=..., units=..., start_time=...)` — many rows in one message (use when you have pre-buffered data). For multiple channels pass a list-of-lists (one sub-list per channel) plus `names`.
- `client.clear_stream(stream_id)` / `client.clear_all_streams()`.

Timestamps accept integer nanoseconds, float seconds (`time.time()`), ISO 8601 strings, or `datetime`. `start_time` is added to every timestamp, so timestamps can be relative; it cannot be combined with string or `datetime` timestamps.

Unit strings are UCUM. `connect_python.Units` holds the recognized constants, e.g. `client.stream("temp", ts, v, unit=connect_python.Units.CELSIUS)`.

Stream IDs are arbitrary strings and do not need to be pre-declared. A plot element in `app.connect` with the matching `stream_id` will render whatever data arrives.

`client.set_channel_scaling(config, stream_id, channels)` applies a transform to one or more channels of a stream, where `config` comes from `connect_python.scaling_config` (`Linear`, `Polynomial`, `ReverseLinear`, `Exponential`, `CustomLookupTable`, `Thermocouple`, `Pipeline`):

```python
from connect_python.scaling_config import Linear

client.set_channel_scaling(Linear(gain=2.0, offset=-10.0, unit="Cel"), "thermocouple", ["ch0", "ch1"])
```

### Reading from streams (cached channel values)

- `client.get_channel_values(stream_id, channels=None)` — latest cached value for one channel (a string), several (a list), or all channels (`None`). Returns `{channel: {"timestamp": <nanos>, "value": ...}}`; channels with no data are omitted, and an unknown stream yields `{}`.
- `client.get_stream_channels(stream_id)` — alphabetically sorted channel names in a stream, or `None` if the stream has never received data. Useful when the channel set is produced dynamically by a device or another script.

This works for streams written by devices (e.g. a CAN interface set up via the Devices panel) or by other scripts. Connect maintains a small in-memory cache per channel.

### Message bus

Pub/sub between scripts and between UI and scripts.

**Quick publish (no explicit bus lifecycle):**

```python
client.send_message("psu/command", {"set_voltage": 5.0, "enable": True})
```

Uses a lazily-created shared `MessageBus`. Good for one-off sends. Not for multi-threaded or device driver code.

`client.send_command(topic, cmd)` is the same thing for a command instance: it serializes `cmd` to the `{command_id: params}` shape that `@handle_command` handlers expect.

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
- `bus.publish_message(topic, contents)` — send on this bus instance. `bytes`/`bytearray` values in the payload are serialized as lists of ints.
- `bus.unsubscribe_from_topic(topic)`.
- `bus.open()` / `bus.close()` if you need to manage the lifecycle without a `with` block. `open()` blocks until the bus can round-trip a probe message (up to 2s) so that an immediate publish is not dropped.
- Subscriptions are per-object: they do not affect other `MessageBus` instances.
- `MessageBus` is NOT thread-safe; create one bus per thread.
- A `MessageBus` must not outlive the `Client` it was created from.

Topic convention: `<scope>/<action>`, e.g. `psu/command`, `pid/update`, `devices/vector:VEC_CH0/command`. UI buttons use `_kind: message` with matching topics.

### Devices panel helpers

Connect's Devices panel owns hardware drivers (LabJack, CAN, NI DAQ, etc.) and exposes per-device command topics of the form `devices/<device_id>/command`.

- `client.set_device_streaming(device_id, streaming: bool)` — start/stop a device.
- `client.send_device_command(device_id, channel_alias, output)` — set an output channel. `output` is an `OutputParams` instance from `connect_python.output_commands`, most easily built with the factories on `AnalogOutputCommand` (`constant_output`, `sine_output`, `square_output`, `sine_sweep_output`, `square_sweep_output`, `pid_output`, `hysteresis_output`) and `DigitalOutputCommand` (`binary_output`, `hysteresis_output`).

```python
from connect_python.output_commands import AnalogOutputCommand

client.send_device_command("labjack-t7-123456", "AO0", AnalogOutputCommand.constant_output(3.3))
```

For CAN devices, use raw `send_message` with payloads like `{"send_message": {"interface_name": "VEC_CH0", "message_name": "...", "signals": {...}}}` — the bus topic is `devices/<driver>:<interface>/command`.

### Notifications + timeline

- `client.send_notification(message, level="info", duration_seconds=None)` — toast. Levels: `info`, `warn`, `error`. With no duration the toast stays until dismissed.
- `client.add_timeline_milestone(time, tooltip=None, color=None)` — add a marker on the timeline widget. `color` is a named color, `rgb()`, or hex string.

### Panels

- `client.hide_panel(uuid)` / `client.focus_panel(uuid)` / `client.restore_panel(uuid)` — where `uuid` is the pane's `id` in `app.connect`.
- `client.show_prompt_window(window_id)` — open a modal defined in `prompt_windows` and block until the user submits; returns a dict of the values they entered. If the window sets `allow_cancel: true` and the user cancels, Connect replies with `null`, which surfaces in the script as a `TypeError`.

### Script output

- `client.set_output(value)` — set the output value for this script invocation (appears in `controls: script_table` output column, or in a `display: table` element if the value is a `TableData` dict: `{"columns": [...], "data": [[...]], "error": None}`).
- `with client.write_output(pa.schema(...)) as w: w.write_batch(...)` — Arrow-shaped output, useful for tabular results.
- `client.set_log_file_path(path)` — tell Connect to write this script's logs to a file.

### Shutdown hooks

```python
def cleanup():
    device.close()

client.add_shutdown_callback(cleanup)
```

Callbacks run in reverse order on exit (normal exit OR Connect-initiated shutdown), at most once. Exceptions are caught and logged. Always register shutdown for anything that holds a hardware/OS handle.

### Nominal Core client

```python
nm_client = client.create_core_client()
# nm_client is a nominal.core.NominalClient, authenticated with the user's
# current Connect login + workspace.
```

Use this for uploading runs, events, datasets, etc. — whenever the script needs to reach the Nominal backend. The raw credentials are also available as `client.api_key` and `client.workspace_rid`.

### 3D scene (spatial apps only)

- `client.stream_points(name, timestamp, points)` — stream a point cloud frame; each point is a `{x, y, z, r, g, b, label}` dict.
- `client.create_lidar_scan(name, timestamp, x, y, z, dir_x, dir_y, dir_z)` — record a lidar scan entry.
- `client.create_models(configs)` — spawn 3D objects at runtime.
- `client.clear_all_created_models()` — removes only runtime-created models, not those declared in `app.connect`.
- `client.stream_rgb(buffer_name, timestamp, width, data)` — stream video frames to a `display: video` element. `data` is row-major RGB as a list of ints or `bytes`, with a length that is a multiple of both 3 and `width`.
- `client.clear_frame_buffer(buffer_name)` — drop everything previously streamed with `stream_rgb`.

## Decorators

### `@connect_python.main`

Applied to the script's `main(client)` function. See above.

### `@connect_python.value_hook`

For scripts wired to a widget's `on_change_action`. Connect passes `--value-id` on the command line; the decorator reads the widget's current value and binds the handler's arguments by name and annotation: a parameter annotated `Client` gets the client, a parameter named `value_id` gets the widget id, and the one remaining parameter gets the value (coerced to `str`, `float`, or `int` if annotated as such).

```python
@connect_python.value_hook
def on_slider_changed(value_id: str, value: float, client: connect_python.Client):
    client.stream("slider_echo", time.time(), value)
```

### `@connect_python.Command`

Registers a command class with Connect's Command Registry (for the no-code Command Builder UI). The decorated class does not need to inherit anything — the decorator subclasses `BaseCommand` for you, so the annotated attributes become Pydantic model fields.

```python
from enum import Enum

@connect_python.Command
class ActuateValve:
    """Open or close a valve"""
    valve_id: str
    position: float = 0.0

@connect_python.Command("Control Pump")          # explicit name, positional
class PumpCommand:
    id: str
    rate: int = 0

@connect_python.Command(name="Test Command")     # explicit name, keyword
class TestCMD:
    id: str
```

- The command name is derived from the class name (`ActuateValve` → `Actuate Valve`) unless one is passed positionally or as `name=`.
- The description is taken from the class docstring.
- Supported field types: `str`, `int`, `float`, `bool`, and `Enum` (all members of an enum must share one value type of `str`, `int`, or `float`). Any other field type raises when the schema is generated. Default values become defaults in the Command Builder UI.
- Registration is sent to Connect when the script calls `client.register_and_wait_for_commands()`. You can also register directly at runtime with `client.register_command("Actuate a Valve", ActuateValve, description=...)`.

`connect_python.commands.BaseCommand` is available for direct subclassing when you want the Pydantic base explicitly; `cmd.to_payload()` gives the `{command_id: params}` dict used on the wire.

### `@connect_python.handle_command(topic, cmd=CommandClass)`

Subscribes to a topic and invokes the handler whenever a matching command arrives. `cmd` must be a `@Command`-decorated class (or a `BaseCommand` subclass).

```python
@connect_python.handle_command(topic="valve/command", cmd=ActuateValve)
def handle_valve(client: connect_python.Client, cmd: ActuateValve):
    driver.set_valve(cmd.valve_id, cmd.position)

@connect_python.main
def main(client):
    # ... setup ...
    client.register_and_wait_for_commands()    # blocks until shutdown
```

Each registered topic gets its own daemon thread with its own `MessageBus`. Call `client.register_and_wait_for_commands()` at the end of `main` to register commands and keep the process alive; without it the script exits as soon as `main` returns. Handlers may be defined inside `main` — registration happens when `register_and_wait_for_commands()` runs.

Handlers receive a validated `cmd` instance (Pydantic validation); validation failures and exceptions raised by the handler are logged and skipped.

### `@connect_python.function_command(topic)`

Derives a command from a plain function: the name from the function name, the description from its docstring, and the parameters from its annotated arguments. It both registers the command and routes `topic` to the function, which is called with the validated parameters as keyword arguments — it does not receive a `Client`.

```python
@connect_python.function_command(topic="valve/command")
def actuate_valve(valve_id: str, position: float, enable: bool = True):
    """Open or close a valve"""
    driver.set_valve(valve_id, position)
```

Every parameter must be annotated with a supported type; `*args`/`**kwargs` are rejected.

## `TestWorkflow`

A structured test runner. Pair with a `controls: test_workflow` element in `app.connect`.

```python
import connect_python
from connect_python import TestWorkflow

class MyTests(TestWorkflow):
    fail_fast = True                     # stop on first failure
    allow_rerun_full_workflow = True     # allow re-running the whole suite
    allow_individual_rerun = True        # allow re-running a single test

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
        # runs after each test_*
        pass

    def set_workflow_outputs(self, test_records, client):
        passed = sum(1 for r in test_records if r.is_successful())
        client.set_output(f"{passed}/{len(test_records)} passed")

if __name__ == "__main__":
    MyTests.main()
```

- Methods prefixed with `test_` run in the order they are defined in the source file (not alphabetically). Prefixes like `test_0_`, `test_a_`, `test_b_` are a readability convention — they make the intended order visually obvious but do not affect execution order. To reorder steps, move the method definitions.
- Discovery only looks at the class's own body, so test methods inherited from an intermediate base class are not run. Define the steps on the workflow class itself.
- Inherits `unittest.TestCase` assertions: `assertEqual`, `assertGreater`, `assertLess`, `assertAlmostEqual`, `assertIsNotNone`, `fail`, etc., plus `setUp`/`tearDown` around each step. `self.addComment(str)` records step notes on the test record.
- `self.client` is the `Client` for the running workflow. It is only available while the workflow is running under `main()`.
- `start_workflow(client)` runs before the steps on every execution, including individual reruns. Set `self.asset_rid` here (or as a class attribute) to auto-create a Nominal Core Run + Events for the workflow; the workflow needs a Nominal login (or `core_client_profile`) for that.
- `set_workflow_outputs(test_records, client)` runs after all tests and after each individual rerun, so make it idempotent; use it for summary output (`client.set_output(...)`).
- `self.add_cleanup(fn)` registers teardown for the whole workflow. Callbacks run in reverse order once the steps finish (and via the client's shutdown callbacks if Connect closes first); exceptions are swallowed.
- Override `log_file_path(self)` to return a path for Connect to write the script's logs to.
- Records stream back to the UI as each step completes. A `TestRecord` has `test`, `status` (`"pass"`, `"fail"`, `"skip"`, `"error"`, or `None` before it runs), `output`, `start_time`, `end_time`, and `is_successful()`.

Class-level flags:
- `fail_fast` — set to `True` to stop the run at the first failure. Not set by default.
- `allow_individual_rerun = True` (default) — individual steps can be rerun after the workflow has run.
- `allow_rerun_full_workflow = True` (default) — the whole workflow can be rerun.
- `allow_individual_run_before_full_workflow = False` (default) — individual steps can only be run after the full workflow has been run once.
- `asset_rid = None` (default) — the Nominal asset RID for auto-created runs and events. Nothing is created while it is `None`.
- `create_events = True` (default) — when `asset_rid` is set, create a Nominal Core Event per test step (name, status, duration, output).
- `create_run = True` (default) — when `asset_rid` is set, create a Nominal Core Run spanning the workflow and set its end time when the steps finish.
- `core_client_profile = None` (default) — a Nominal profile name to build the `NominalClient` from instead of the Connect session.
- Override the `submit_results(test_records, client)` **static method** to enable a **Submit** button with custom upload logic. The workflow instance and its attributes are not available inside it. (The instance method `submit_workflow_results` is deprecated and must not be used in new scripts.)

Retrying a flaky step:

```python
from connect_python import retry, wait_fixed

class MyTests(TestWorkflow):
    @retry(max_tries=3, wait=wait_fixed(0.5))
    def test_settles(self):
        ...
```

Each attempt streams back to the UI; only the final attempt's status is reported.

Outside a Connect app the workflow entrypoint takes one of `--discover-tests`, `--run-test-workflow`, `--run-test <name>`, or `--submit-results`, so a standalone smoke run is `python my_workflow.py --run-test-workflow`.

For a test suite with no Connect UI attached, `connect_python.TestCase` plus `connect_python.run_test_case_class(MyTests, fail_fast=False)` runs the same definition-ordered `test_` methods and returns the `TestRecord` list directly.

## `AutoSequenceWorkflow`

Same lifecycle as `TestWorkflow`, with steps prefixed `step_` instead of `test_`. It sets `fail_fast = True` and `allow_individual_rerun = False`, so the sequence stops at the first failure and steps cannot be rerun individually.

```python
class CalibrationSequence(connect_python.AutoSequenceWorkflow):
    def start_workflow(self, client):
        self.target_temp = float(client.get_value("target_temp"))

    def step_preheat(self):
        self.addComment(f"Preheating to {self.target_temp}C")

    def step_stabilize(self):
        self.assertAlmostEqual(self.client.get_value("temperature"), self.target_temp, delta=1.0)
```

## `RemoteAutoSequenceWorkflow`

An `AutoSequenceWorkflow` that sends output commands to a Connect Realtime driver on another machine over ZMQ.

```python
from connect_python.output_commands import SequenceCommand, ConstantParams

class RemoteCalibration(connect_python.RemoteAutoSequenceWorkflow):
    command_host = "192.168.1.100"   # default "localhost"
    rcvtimeo_ms = 2500               # command socket receive timeout
    default_driver = "ni_daq"
    default_task = "ao_task"
    default_channel = "ao0"

    def step_set_voltage(self):
        self.send_command(SequenceCommand(output=ConstantParams(value=5.0)))
        self.wait_for(0.5)
```

- `self.send_command(command, *, driver=None, task=None, channel=None)` sends one `SequenceCommand`; driver/task/channel resolve from the command, then the keyword override, then the class defaults.
- `self.send_commands(commands, *, driver=None, task=None, channel=None)` batches several into one request. They must all resolve to the same driver.
- `self.wait_for(seconds)` sleeps between steps.

## StubClient

When a script runs outside Connect (e.g., `python my_script.py` in a terminal), `@connect_python.main` returns a `StubClient` instead of a real `Client`. Detection key: the `NOMINAL_CONNECT_ENVIRONMENT` env var is set only when Connect spawns the script. Streaming, messaging, and command calls are no-ops; `get_value`/`set_value`/`clear_values` work against an in-memory dict; request-response calls (`show_prompt_window`, `get_channel_values`, `get_stream_channels`) return `None`. Useful for unit tests or quick local iteration.
