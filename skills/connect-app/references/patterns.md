# Common Connect app patterns

Five idioms that cover ~90% of real apps. Each includes the `app.connect` wiring and the matching Python.

Stream IDs, message-bus topics, and channel names are plain strings shared between YAML and Python, and nothing type-checks them. Keep the Python side in one module so scripts can't drift from each other: a driver script exports its own topic constant and command classes, and a `constants.py` holds anything several scripts share. The YAML side still has to match by hand.

```python
# constants.py
PSU_STREAM_ID = "psu"                 # must match `stream_id: psu` in app.connect
PSU_COMMAND_TOPIC = "psu/command"
PID_STREAM_ID = "PID"
PID_UPDATE_TOPIC = "pid/update"
```

---

## 1. UI → script one-shot (button runs a script that reads inputs)

User enters values, clicks a button, a script runs once, sets a banner, exits.

```yaml
# app.connect (excerpt)
- input: number
  id: target_voltage
  label: Target (V)
  default: 5.0
- text: Run
  on_click_action:
    _kind: script
    path: run_once.py
    args: []
    max_log_lines: 1000
- display: banner
  value_id: status_banner
```

```python
# run_once.py
import connect_python

@connect_python.main
def main(client: connect_python.Client):
    target = float(client.get_value("target_voltage", 0.0))
    client.set_value("status_banner", f"Ran with target={target}V")

if __name__ == "__main__":
    main()
```

The `@connect_python.main` decorator does not invoke the function, so the `__main__` block is required in every script.

---

## 2. Long-running driver + typed commands from the UI

A script opens a piece of hardware, streams readings, and serves commands from UI buttons. One script per instrument — a `psu_control.py` and a `dmm_control.py`, each owning exactly one handle.

Each command is a plain annotated class decorated with `@Command`. UI buttons target it with a `_kind: command` action.

```yaml
# app.connect (excerpt)
# --- Live readings ---
- display: stream_value
  title: Voltage
  stream_id: psu
  channel: myPSU.ch1_v
  units: V

# --- Commands ---
- input: number
  id: psu_voltage
  label: Voltage
  min: 0.0
  max: 30.0
  default: 0.0
- text: Set Voltage
  on_click_action:
    _kind: command
    topic: psu/command
    command_id: set_voltage
    params:
      voltage: $psu_voltage
- input: checkbox
  id: psu_enable
  label: Enable
  on_toggle_high_action:
    _kind: command
    topic: psu/command
    command_id: set_output_enable
    params:
      enable: true
  on_toggle_low_action:
    _kind: command
    topic: psu/command
    command_id: set_output_enable
    params:
      enable: false

# --- Start the driver ---
- text: Start PSU
  on_click_action:
    _kind: script
    path: psu_control.py
```

`command_id` is the snake_case of the command *class* name — `SetVoltage` → `set_voltage`, `SetOutputEnable` → `set_output_enable` — not the display name. `params` values may be literals or `$value_id` references, resolved from the current UI values at click time (substitution recurses into nested objects and lists).

```python
# psu_control.py
import time

import connect_python
from connect_python import Command

from constants import PSU_STREAM_ID, PSU_COMMAND_TOPIC

logger = connect_python.get_logger(__name__)


@Command(name="Set PSU Voltage")
class SetVoltage:
    """Set the PSU output voltage for the configured channel."""

    voltage: float


@Command(name="Set PSU Output Enable")
class SetOutputEnable:
    """Enable or disable the PSU output for the configured channel."""

    enable: bool


@connect_python.main
def main(client: connect_python.Client):
    channel = int(client.get_value("psu_channel_number", 1))
    psu = create_psu(client.get_value("psu_visa_resource"))

    def psu_shutdown():
        try:
            psu.close()
        except Exception as e:
            logger.warning(f"could not close PSU: {e}")

    client.add_shutdown_callback(psu_shutdown)
    psu.open()

    # Stream measurements at 5 Hz from the driver's own background thread.
    psu.start_streaming(lambda v, i: client.stream(
        PSU_STREAM_ID, time.time(), values=[v, i], names=["myPSU.ch1_v", "myPSU.ch1_i"],
    ))

    @connect_python.handle_command(topic=PSU_COMMAND_TOPIC, cmd=SetVoltage)
    def handle_set_voltage(client: connect_python.Client, cmd: SetVoltage):
        psu.set_voltage(voltage=cmd.voltage, channel=channel)
        logger.info(f"ch{channel} voltage -> {cmd.voltage}V")

    @connect_python.handle_command(topic=PSU_COMMAND_TOPIC, cmd=SetOutputEnable)
    def handle_set_output_enable(client: connect_python.Client, cmd: SetOutputEnable):
        psu.output_enable(enable=cmd.enable, channel=channel)
        logger.info(f"ch{channel} output_enable -> {cmd.enable}")

    client.register_and_wait_for_commands()


if __name__ == "__main__":
    main()
```

Key points:
- The script owns the hardware handle. Never open the same device from two scripts — a second VISA or serial session against the same resource either fails outright or interleaves writes with the first.
- Nest the handlers inside `main` so they close over the open handle and the values read at startup.
- Register `add_shutdown_callback` before opening the handle. Callbacks run in reverse registration order; Connect signals the script over its control socket and the SDK raises a `KeyboardInterrupt` on the main thread to unblock it.
- `client.register_and_wait_for_commands()` registers every decorated command, starts one dispatch thread per topic, and blocks. Without it the process exits and the handlers die.

For a payload with no fixed schema, a button can instead publish an untyped dict with `_kind: message`: a `topic` plus arbitrary flat key/value pairs, again with `$value_id` substitution. A script reads those off a `MessageBus`:

```python
with connect_python.MessageBus(client) as bus:
    bus.subscribe_to_topic("ui/commit")
    while True:
        msg = bus.wait_for_message()
        logger.info(f"{msg.topic}: {msg.contents}")
```

Reach for that only when a schema genuinely doesn't fit. A registered command gets validation, a generated parameter form, and a stable payload shape for free.

---

## 3. Closed-loop controller (UI live-tunes params, script runs the loop)

The script takes its tunable parameters as one command and runs the control loop on a daemon thread. The main thread blocks dispatching commands; the handler mutates shared state under a lock.

```yaml
# app.connect (excerpt)
- input: number
  id: setpoint_rpm
  label: Reference Speed (RPM)
  default: 300.0
- input: number
  id: kp
  label: Proportional
  default: 0.1
- input: number
  id: ki
  label: Integral
  default: 0.0002
- text: Update Parameters
  on_click_action:
    _kind: command
    topic: pid/update
    command_id: update_pid_parameters
    params:
      setpoint_rpm: $setpoint_rpm
      kp: $kp
      ki: $ki
- plot: line
  stream_id: PID
  channels:
  - Reference (RPM)
  - Actual Speed (RPM)
  time_window: 30s
```

```python
# pid.py
import threading
import time

import connect_python
from connect_python import Command

from constants import PID_STREAM_ID, PID_UPDATE_TOPIC

logger = connect_python.get_logger(__name__)


@Command(name="Update PID Parameters")
class UpdatePidParameters:
    """Update the velocity setpoint and PID gains."""

    setpoint_rpm: float
    kp: float
    ki: float = 0.0


@connect_python.main
def main(client: connect_python.Client):
    # Shared state mutated by the command handler, read by the control loop.
    state_lock = threading.Lock()
    state = {
        "setpoint_rpm": float(client.get_value("setpoint_rpm", 300.0)),
        "kp": float(client.get_value("kp", 0.1)),
        "ki": float(client.get_value("ki", 0.0)),
    }

    @connect_python.handle_command(topic=PID_UPDATE_TOPIC, cmd=UpdatePidParameters)
    def handle_pid_update(client: connect_python.Client, cmd: UpdatePidParameters):
        with state_lock:
            state["setpoint_rpm"] = cmd.setpoint_rpm
            state["kp"] = cmd.kp
            state["ki"] = cmd.ki
        logger.info(f"updated: setpoint={cmd.setpoint_rpm} RPM, kp={cmd.kp}, ki={cmd.ki}")

    def control_loop():
        while True:
            with state_lock:
                setpoint, kp, ki = state["setpoint_rpm"], state["kp"], state["ki"]

            actual = read_actual_rpm()
            # ... compute + command ...

            now = time.time()
            client.stream(PID_STREAM_ID, now, setpoint, name="Reference (RPM)")
            client.stream(PID_STREAM_ID, now, actual, name="Actual Speed (RPM)")
            time.sleep(0.01)

    # The loop runs on a background thread so the main thread can block on
    # register_and_wait_for_commands() and dispatch incoming parameter updates.
    threading.Thread(target=control_loop, daemon=True).start()

    client.register_and_wait_for_commands()


if __name__ == "__main__":
    main()
```

If a loop reads a raw topic itself rather than taking a command, use `try_receive_message()` — it returns `None` immediately when nothing is queued, so the loop keeps its period. `wait_for_message()` blocks until a message arrives and is only appropriate when reacting to messages is the thread's only job.

---

## 4. TestWorkflow that orchestrates other driver scripts

One script subclasses `TestWorkflow` and coordinates already-running driver scripts. The drivers own the hardware; the test imports their command classes, sends commands, and reads back cached channel values.

```yaml
# app.connect (excerpt)
- controls: test_workflow
  label: Line Regulation Test
  script:
    id: line_regulation_test
    label: Line Regulation Test
    path: line_regulation_test.py
    args: []
    max_log_lines: 10000
  output_table:
    location: bottom
    columns: []
```

```python
# line_regulation_test.py
import time

import connect_python
from connect_python import TestWorkflow, TestRecord

from constants import PSU_COMMAND_TOPIC
from psu_control import SetVoltage, SetOutputEnable

DMM_STREAM_ID = "dmm"
DMM_VOLTAGE_CHANNEL = "myDMM.dc_voltage"


class LineRegulationTest(TestWorkflow):
    fail_fast = True

    def start_workflow(self, client: connect_python.Client):
        # `self.client` is not available yet — use the client argument here.
        self.asset_rid = client.get_value("asset_rid", None)
        self.settle_s = float(client.get_value("t_settle_s", 0.5))
        self.results: dict[str, float] = {}
        self.add_cleanup(lambda: self._safe_shutdown(client))

    def _safe_shutdown(self, client: connect_python.Client):
        client.send_command(PSU_COMMAND_TOPIC, SetOutputEnable(enable=False))
        client.send_command(PSU_COMMAND_TOPIC, SetVoltage(voltage=0.0))

    def test_preconditions(self):
        self.client.send_command(PSU_COMMAND_TOPIC, SetOutputEnable(enable=False))

    def test_setup_psu(self):
        self.client.send_command(PSU_COMMAND_TOPIC, SetVoltage(voltage=4.5))
        self.client.send_command(PSU_COMMAND_TOPIC, SetOutputEnable(enable=True))
        time.sleep(self.settle_s)

    def test_measure_vout(self):
        result = self.client.get_channel_values(DMM_STREAM_ID, DMM_VOLTAGE_CHANNEL)
        if not result or DMM_VOLTAGE_CHANNEL not in result:
            self.fail(f"no reading on '{DMM_STREAM_ID}' — is dmm_control.py running?")
        v_out = float(result[DMM_VOLTAGE_CHANNEL]["value"])
        self.results["V_OUT"] = v_out
        self.assertGreater(v_out, 14.5)
        self.assertLess(v_out, 15.5)
        self.addComment(f"V_OUT = {v_out:.3f}V")

    def test_shutdown(self):
        self._safe_shutdown(self.client)
        self.addComment("Safe shutdown complete")

    def set_workflow_outputs(self, test_records: list[TestRecord], client: connect_python.Client):
        client.set_output({
            "columns": ["Measurement", "Value"],
            "data": [[k, f"{v:.3f}V"] for k, v in self.results.items()],
            "error": None,
        })


if __name__ == "__main__":
    LineRegulationTest.main()
```

Key points:
- Test methods run in the order they are defined in the source file, not alphabetically. Name them for what they do and write them in the order they must run. Only `test_*` methods declared directly in the class body are discovered — ones inherited from an intermediate base class are not.
- `get_channel_values(stream_id, channel)` returns `{channel: {"value": ..., "timestamp": ...}}`, or an empty dict if the stream has no data. Check before indexing.
- `self.client` is only valid once the workflow is running; `start_workflow` receives the client as an argument instead.
- Set `self.asset_rid` in `start_workflow` to upload a Run and Events to Nominal Core (`create_run` and `create_events` both default to `True`).
- Register the safe-shutdown with `self.add_cleanup(...)`. Cleanups run in reverse registration order after the steps finish — including when `fail_fast` cut the run short — and are also wired to the client's shutdown callbacks so they still fire if the app closes mid-run. Keep an explicit `test_shutdown` step as well when the shutdown should appear as a row in the results.
- `set_workflow_outputs` may run more than once (it runs again after an individual test is rerun), so keep it idempotent, and use it for outputs rather than for shutdown. A `TableData` dict passed to `client.set_output` renders in the element's output table; the `output_table.columns` list is only placeholder headers shown before that table exists.
- For an ordered procedure that isn't a pass/fail test, subclass `AutoSequenceWorkflow` instead: methods are prefixed `step_`, the sequence is fail-fast, and individual steps cannot be rerun.

---

## 5. Command Registry (no-code command building)

Registering a command schema is what lets someone wire a button to a script without hand-writing YAML. Setting a button's action to Command in Connect's UI builder shows a Destination (topic) field, a dropdown of every registered command, and a parameter form generated from the command's schema — producing exactly the `_kind: command` action shown in pattern 2.

```python
# valve.py
import connect_python
from connect_python import Command


@Command
class ActuateValve:
    """Open or close a valve."""

    valve_id: str
    position: float = 0.0      # defaults become the form's defaults


@connect_python.handle_command(topic="valve/command", cmd=ActuateValve)
def on_actuate(client: connect_python.Client, cmd: ActuateValve):
    driver.set_valve(cmd.valve_id, cmd.position)


@connect_python.main
def main(client: connect_python.Client):
    # ... open hardware ...
    client.register_and_wait_for_commands()   # keeps the process alive so handlers run


if __name__ == "__main__":
    main()
```

- `@Command` on a bare annotated class is all that's needed — no base class to inherit. The docstring becomes the description shown in the UI, and the display name is derived from the class name (`ActuateValve` → "Actuate Valve"). Pass `@Command(name="Actuate Valve")` to set it explicitly.
- Parameter types are limited to `str`, `int`, `float`, `bool`, and `Enum`s whose values are all `str`, `int`, or `float`. Enum parameters travel as their `.value`.
- `@handle_command(topic=..., cmd=...)` routes validated commands to a handler taking `(client, cmd)`. Handlers may live at module scope or nested inside `main`; nest them when they need an open hardware handle.
- For a function that already has annotated arguments, `@connect_python.function_command(topic=...)` derives the command from its signature, registers it, and calls it with the validated parameters as keyword arguments — it receives no `client`.
  ```python
  @connect_python.function_command(topic="valve/command")
  def control_actuator(id: str, position: int, enable: bool):
      """Move an actuator if it is enabled."""
  ```
- Commands are registered when the script calls `client.register_and_wait_for_commands()`, so the script has to be running for its commands to appear in the dropdown. Handler exceptions are logged as warnings and do not kill the dispatch thread.
- Another script sends a registered command with `client.send_command(topic, ActuateValve(valve_id="v1", position=0.5))`, which puts the same `{command_id: params}` payload on the topic.

---

## Cross-cutting advice

- **Stream IDs, topics, and channel names are strings.** There is no type-safety between `app.connect` and Python. A stream ID may not contain `.`, since a channel is addressed as `stream_id.channel_name`.
- **Pane IDs are UUIDv4s.** A pane's `id` deserializes as a UUID, so a slug or a placeholder like `0000...` is a load error; omitting it mints a fresh v4. Generate one per pane at authoring time with `uuidgen` or Python `uuid.uuid4()`, and never reuse one — pane visibility, navigation, and selection all key on that UUID, so two panes sharing an ID means those operations hit the wrong one. Everything else that takes an `id` (inputs, scripts, canvases, prompt windows) is a free-form string; use readable `snake_case` slugs. Duplicate script IDs are a hard config-load failure, as are duplicate model, sensor, waypoint, and prompt-window IDs.
- **`requirements.txt` is usually unnecessary.** List app deps inline under the top-level `python.packages` key and Connect installs them into a per-app venv. Pins, extras, and VCS URLs all work in that list. A requirements file is never picked up implicitly — point at it explicitly with `packages: requirements.txt` when the list is long enough to be worth a separate file.
- **`min`/`max` on `input: number`** clamp the value in a bounded number box.
- **A README tab is conventional.** Put `display: markdown` with `path: README.md` in a pane in the first tab, titled "README" or "Overview". Document: what the app does, equipment required, prerequisites, walkthrough of the other tabs.
- **`MessageBus` objects are single-threaded.** One instance must not be shared across threads; create one per thread and re-subscribe to its topics. `client.send_message` and `client.send_command` publish through a lock-guarded shared bus, so they need no lifecycle management for one-off sends.
