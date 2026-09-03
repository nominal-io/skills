# Common Connect app patterns

Five idioms that cover ~90% of real apps. Each includes the `app.connect` wiring and the matching Python.

Project convention: put shared constants (stream IDs, topics, device names) in a `constants.py` so `app.connect` strings and Python strings can't drift.

```python
# constants.py
PSU_STREAM_ID = "psu"
PSU_COMMAND_TOPIC = "psu/command"
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
```

---

## 2. Long-running driver + UI control via message bus

A script opens a piece of hardware, streams readings, and accepts commands from UI buttons. One script per instrument — a `psu_control.py` and a `dmm_control.py`, each owning exactly one handle.

```yaml
# app.connect (excerpt)
# --- Live readings ---
- display: stream_value
  stream_id: psu
  channel: myPSU.ch1_v
  units: V

# --- Commands ---
- input: slider
  id: psu_voltage
  label: Voltage
  min: 0.0
  max: 30.0
  default: 0.0
- input: checkbox
  id: psu_enable
  label: Enable
- text: Commit
  on_click_action:
    _kind: message
    topic: psu/command
    set_voltage: $psu_voltage
    output_enable: $psu_enable

# --- Start the driver ---
- text: Start PSU
  on_click_action:
    _kind: script
    path: psu_control.py
```

```python
# psu_control.py
import connect_python
from constants import PSU_STREAM_ID, PSU_COMMAND_TOPIC

logger = connect_python.get_logger(__name__)

@connect_python.main
def main(client: connect_python.Client):
    psu = open_psu(client.get_value("psu_visa_resource"))

    def cleanup():
        try: psu.close()
        except Exception as e: logger.warning(f"close failed: {e}")
    client.add_shutdown_callback(cleanup)

    # Stream measurements at 5 Hz in a background thread of the driver
    psu.start_streaming(lambda v, i: client.stream(
        PSU_STREAM_ID, time.time(), values=[v, i], names=["myPSU.ch1_v", "myPSU.ch1_i"],
    ))

    # Main loop: handle UI commands
    with connect_python.MessageBus(client) as bus:
        bus.subscribe_to_topic(PSU_COMMAND_TOPIC)
        while True:
            msg = bus.wait_for_message()
            try:
                if "set_voltage"   in msg.contents: psu.set_voltage(float(msg.contents["set_voltage"]))
                if "output_enable" in msg.contents: psu.enable(bool(msg.contents["output_enable"]))
            except Exception as e:
                logger.error(f"failed to apply {msg.contents}: {e}")

if __name__ == "__main__":
    main()
```

Key points:
- The script owns the hardware handle. Never open the same device from two scripts.
- Always `add_shutdown_callback` to close handles cleanly — Connect's shutdown is SIGINT-based.
- Use a single `MessageBus` on the main thread. For multi-threaded drivers, use `client.send_message(...)` from threads instead.

---

## 3. Closed-loop controller (UI live-tunes params, script runs the loop)

The script runs a control loop and exposes tunable parameters via a second message topic. UI sliders + an "Update" button publish a dict; the loop applies it and keeps running.

```yaml
# app.connect (excerpt)
- input: number
  id: kp
  label: Kp
  default: 0.1
- input: number
  id: setpoint_rpm
  label: Setpoint (RPM)
  default: 300
- text: Update
  on_click_action:
    _kind: message
    topic: pid/update
    kp: $kp
    setpoint_rpm: $setpoint_rpm
- plot: line
  stream_id: PID
  channels: [Reference (RPM), Actual Speed (RPM)]
  time_window: 30s
```

```python
# pid.py
import time
import connect_python
from constants import PID_STREAM_ID, PID_UPDATE_TOPIC

@connect_python.main
def main(client: connect_python.Client):
    kp = float(client.get_value("kp", 0.1))
    setpoint = float(client.get_value("setpoint_rpm", 300.0))

    with connect_python.MessageBus(client) as bus:
        bus.subscribe_to_topic(PID_UPDATE_TOPIC)
        while True:
            # Apply any UI updates without blocking the loop
            msg = bus.try_receive_message()
            if msg is not None:
                kp       = float(msg.contents.get("kp", kp))
                setpoint = float(msg.contents.get("setpoint_rpm", setpoint))

            actual = read_actual_rpm()
            # ... compute + command ...

            now = time.time()
            client.stream(PID_STREAM_ID, now, setpoint, name="Reference (RPM)")
            client.stream(PID_STREAM_ID, now, actual,   name="Actual Speed (RPM)")
            time.sleep(0.01)
```

Use `try_receive_message()` (non-blocking) inside the control loop; use `wait_for_message()` only when the script's only job is to react to commands.

---

## 4. TestWorkflow that orchestrates other driver scripts

One script subclasses `TestWorkflow` and coordinates other running driver scripts via the message bus. The drivers own the hardware; the test sends `psu/command` etc. and reads back cached channel values.

```yaml
# app.connect (excerpt)
- controls: test_workflow
  label: Line Regulation Test
  script:
    id: line_regulation_test
    path: line_regulation_test.py
  output_table:
    location: bottom
    columns: []
```

```python
# line_regulation_test.py
import time
import connect_python
from connect_python import TestWorkflow

PSU_TOPIC = "psu/command"
DMM_STREAM = "dmm"

class LineRegulation(TestWorkflow):
    fail_fast = True

    def start_workflow(self, client):
        self.asset_rid = client.get_value("asset_rid", None)
        self.settle_s = float(client.get_value("t_settle_s", 0.5))

    def test_a_preconditions(self):
        self.client.send_message(PSU_TOPIC, {"output_enable": False})

    def test_b_setup_psu(self):
        self.client.send_message(PSU_TOPIC, {"set_voltage": 4.5, "set_current": 1.0, "output_enable": True})
        time.sleep(self.settle_s)

    def test_c_measure(self):
        result = self.client.get_channel_values(DMM_STREAM, "myDMM.dc_voltage")
        self.assertIsNotNone(result, "no DMM reading")
        v = float(result["myDMM.dc_voltage"]["value"])
        self.assertGreater(v, 14.5)
        self.assertLess(v, 15.5)
        self.addComment(f"V_OUT = {v:.3f}V")

    def test_z_shutdown(self):
        self.client.send_message(PSU_TOPIC, {"output_enable": False, "set_voltage": 0.0})

if __name__ == "__main__":
    LineRegulation.main()
```

Key points:
- Tests run in the order they are defined in the source file (not alphabetically). Prefixes like `test_a_`, `test_b_`, `test_z_` are just a readability convention so the intended order is visually obvious — they do not affect execution order.
- Set `asset_rid` in `start_workflow` to auto-upload a Run + Events to Nominal Core.
- Always include a `test_z_shutdown` that returns hardware to a safe state. If a prior test fails, the shutdown step still runs unless `fail_fast` skips it — ALSO run safe-shutdown in `set_workflow_outputs` as a belt-and-suspenders.

---

## 5. Command Registry (no-code command builder)

Register a Pydantic command schema so the user can build commands via the Command Builder UI and send them from anywhere. The script receives the validated command via the message bus.

```python
# valve.py
import connect_python
from connect_python.commands import BaseCommand

@connect_python.Command(name="Actuate Valve", description="Open or close a valve")
class ActuateValve(BaseCommand):
    valve_id: str
    position: float = 0.0      # defaults become UI defaults

@connect_python.handle_command(topic="valve/command", cmd=ActuateValve)
def on_actuate(client, cmd: ActuateValve):
    driver.set_valve(cmd.valve_id, cmd.position)

@connect_python.main
def main(client: connect_python.Client):
    # ... open hardware ...
    client.register_and_wait_for_commands()   # keeps the process alive so handlers run

if __name__ == "__main__":
    main()
```

- `@Command` makes it selectable in the Command Builder UI.
- `@handle_command(topic=..., cmd=...)` routes incoming bus messages to validated handlers.
- Must call `client.register_and_wait_for_commands()` at the end of `main` — otherwise the process exits and handlers die.

---

## Cross-cutting advice

- **Stream IDs and topics are strings.** There is no type-safety between `app.connect` and Python. Put them in `constants.py`.
- **Pane IDs are UUIDv4s.** Generate new ones with `uuidgen` or Python `uuid.uuid4()`. Duplicates break the UI.
- **`requirements.txt` is usually not needed.** Put app deps under `python.packages` in `app.connect`; Connect manages a per-app venv.
- **README.md is optional but conventional.** A `display: markdown` tile pointing at `README.md` in a "README" tab is standard. Document: what the app does, equipment required, prerequisites, walkthrough of tabs.
