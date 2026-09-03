# `app.connect` YAML reference

The `app.connect` file declares the UI. Connect loads it when the user opens the app directory. All paths in `on_click_action`, `display: markdown`, `canvas:`, etc. are resolved relative to the app directory.

## Top-level keys

```yaml
title: My App                    # App title shown in the title bar
window_title: null               # Optional override for OS window title
logo_path: null                  # Optional logo image path
timeline:                        # Timeline widget config (usually null / hidden)
  show: false
  display: relative
  pixels_per_tick: 0.0
  milestones: []
streaming:                       # Streaming + persistence config
  buffer_size: 5000              # In-memory buffer depth per stream
  timeline: null
  playback_speed: null
  window: null
  persistence:                   # List of Nominal Core datasets to persist streams to
  - enabled: 'true'
    data_source_rid: ri.catalog.xxx
    file_path: null
    streams:
    - id: my_stream
      tags: {}
python:
  packages:                      # Extra pip packages to install in the auto-venv
  - nominal-instro
  wheelhouse: null               # Optional local wheelhouse path
on_load: null                    # Optional script to run when the app opens
on_unload: null                  # Optional script to run when the app closes
tiles: [...]                     # Main UI layout (see below)
scene: {}                        # 3D scene config (for spatial/pointcloud apps)
poster: null                     # Optional "poster" image shown on startup
prompt_windows: []               # Modal prompt dialogs triggered by scripts
mcap_path: null                  # Optional path to an MCAP file for replay
```

Only `title` and `tiles` are required. Omit fields you aren't using.

`left_panel`, `right_panel`, and `bottom_panel` are deprecated — do not use them in new apps.

## UI Builder compatibility

For an app to remain editable in Connect's no-code UI builder, follow these constraints:

- The top-level `tiles` must be a single `layout: tabs` tile.
- Each pane contains at least one element.
- Panes set `should_fill: true`.

## Layouts

Tiles nest. Each tile has a `layout:` discriminator:

- `layout: tabs` — horizontal tab bar. Has a `tabs:` list.
- `layout: grid` — row/column grid. Has a `rows:` list; each row has `columns:`.
- `layout: pane` — leaf; contains `elements:` (the actual widgets).

### Tabs

```yaml
- layout: tabs
  tabs:
  - title: README
    allow_popout: true
    tile: { layout: pane, id: <uuid>, elements: [...] }
```

### Grid

Rows and columns are sized by `height` / `width`. Use `null` to let Connect auto-size, or a float (fraction of parent) for explicit sizing. Explicit weights do not need to sum to 1 — they are normalized.

```yaml
- layout: grid
  rows:
  - height: null
    columns:
    - width: 0.5
      tile: { layout: pane, ... }
    - width: 0.5
      tile: { layout: pane, ... }
```

### Pane

A pane is a leaf tile containing elements:

```yaml
- layout: pane
  id: <uuid>                # Required; MUST be a unique UUIDv4 per pane
  title: My Panel
  direction: vertical       # vertical | horizontal
  should_fill: true
  elements: [...]
```

**`id` must be a UUIDv4** (e.g. `7a13aace-e94a-4552-a461-39c728a54f02`). Use any valid v4. Duplicates will cause egui ID collisions and weird UI behavior.

## Elements

Elements are the widgets inside a pane. Each element is discriminated by one of several keys: `display:`, `plot:`, `canvas:`, `controls:`, `inputs:` (forms), `text:` (buttons), or bare IDs like `startup_file:` (file editor).

### Displays

Text / status widgets, all start with `display:`.

```yaml
- display: markdown
  path: README.md             # Markdown file in the app directory

- display: header
  label: Section Title

- display: separator

- display: banner              # Large status text, bound to a widget ID
  value_id: my_banner

- display: stream_value        # Single numeric value from a stream
  title: Voltage
  stream_id: psu
  channel: myPSU.ch1_v
  units: V
  show_channel_picker: true

- display: gauge
  stream_id: PID
  channel: Actual Speed (RPM)
  title: Motor RPM
  min: 0.0
  max: 2000.0
  arc: semi                    # semi | full
  radius: 84.0
  zones:
  - { start: 0.0,    end: 1500.0, color: safe }
  - { start: 1500.0, end: 1800.0, color: warn }
  - { start: 1800.0, end: 2000.0, color: critical }
  hysteresis: 0.0167
  refresh: 0.0333
  decimal_places: 0

- display: logs                # Script log output
  script_id: my_script         # Matches a script id configured elsewhere

- display: table               # Table output from client.set_output
  script_id: my_script

- display: channel_table       # All channels of a stream, live values
  stream_id: vector_vec_ch0

- display: can_frame_viewer    # Raw CAN frames (Devices panel CAN interface required)

- display: can_frame_sender    # UI for composing + sending CAN frames

- display: video               # Frame buffer (pair with client.stream_rgb)
  frames: my_camera
```

### Plots

```yaml
- plot: line
  stream_id: psu               # OR stream_ids: [psu, dmm, myLabJack] for cross-stream
  channels:                    # When stream_ids is a list, prefix channels with <stream_id>.
  - myPSU.ch1_v
  - myPSU.ch1_i
  colors:
  - rgb(249, 53, 53)
  - rgb(113, 249, 53)
  show_legend: true
  legend_placement: bottom_left   # top_left | top_right | bottom_left | bottom_right
  x_format: timestamp          # timestamp | number
  x_time_display: Local        # Local | UTC | Elapsed
  x_scale: linear              # linear | log
  y_scale: linear
  x_label: null                # optional axis labels
  y_label: RPM
  time_window: 30s             # Rolling window; omit for full history
```

### Canvas

Embeds an interactive diagram defined in a separate YAML.

```yaml
- id: system_diagram
  canvas: system_diagram.yaml
```

### Controls

Scripts are launched by the user. Connect auto-manages lifecycle.

```yaml
- controls: test_workflow      # Single-script test workflow runner
  label: My Test
  script:
    id: my_test
    label: My Test
    path: my_test.py           # Script subclassing connect_python.TestWorkflow
    args: []
    max_log_lines: 10000
  output_table:
    location: bottom           # bottom | right
    columns: []

- controls: script_table       # Run multiple scripts from a single table
  scripts:
  - label: Receiver
    path: receiver.py
  - label: Sender
    path: sender.py
```

### File Editor

Shows an editable file next to the UI.

```yaml
- id: my_script_editor
  startup_file: my_script.py
  show_picker: false
  show_run_button: false
  height: null
```

### Forms (inputs + buttons)

A form is an element with `inputs:` at its top level. Each entry is an input widget or a button. The form itself has no `input:` / `display:` key — it is discriminated by the presence of `inputs:`.

```yaml
- id: null
  spacing: normal              # normal | tight | wide
  inputs:
  - display: header
    label: Device Settings

  - input: text
    id: visa_resource
    label: VISA Resource
    default: 'USB0::0xF4EC::0x1430::XXX::INSTR'

  - input: number
    id: channel_number
    label: Channel
    default: 1.0

  - input: slider
    id: voltage
    label: Voltage (V)
    min: 0.0
    max: 30.0
    default: 0.0

  - input: checkbox
    id: enable
    label: Enable

  - input: toggle_switch
    id: streaming_on
    on_toggle_action:
      _kind: message
      topic: my/command
      streaming: $streaming_on

  - input: dropdown
    id: mode
    label: Mode
    options:
    - AUTO
    - MANUAL
    default: AUTO

  - input: asset_selector      # Picker for a Nominal Core Asset
    id: asset_rid
    label: Asset
    default: ''
    mapping:
      properties: {}

  # Buttons
  - id: commit_btn             # id is optional on buttons
    text: Commit
    on_click_action:
      _kind: message
      topic: my/command
      set_voltage: $voltage
      enable: $enable
    show_sigil: true           # Show a small icon on the button
    size: normal               # normal | big
    rounding: tight            # tight | wide
    color: null                # optional hex/rgb color override

  - text: Run Script
    on_click_action:
      _kind: script
      path: my_script.py
      args: []
      max_log_lines: 10000
    show_sigil: true
    size: normal
    rounding: tight
```

## Actions

`on_click_action` / `on_toggle_action` / `on_change_action` discriminated by `_kind`:

### `_kind: script` — run a Python script

```yaml
on_click_action:
  _kind: script
  id: my_script                # Optional stable id (used by `display: logs`)
  label: null
  path: my_script.py
  args: []                     # argv passed to the script
  max_log_lines: 10000
```

### `_kind: message` — publish to the message bus

The action publishes a dict to the topic. `$widget_id` is substituted with the current UI value of that widget at click time.

```yaml
on_click_action:
  _kind: message
  topic: psu/command
  set_voltage: $psu_voltage      # UI value substitution
  set_current: $psu_current
  enable: $psu_enable
  literal_flag: true             # Plain literals are passed through
```

Use for UI → script commands. Scripts subscribe to the topic via `MessageBus.subscribe_to_topic`.

## Widget IDs

- Widget `id`s are the keys used by `client.get_value(id)` / `client.set_value(id, v)`.
- They must be unique within the app.
- Use `snake_case` for readability.
- Pane `id`s (UUIDs) are a separate namespace; they identify panes for `client.hide_panel` / `focus_panel`.

## Common patterns

### Read UI values at script startup

Put all inputs in a form; read them with `client.get_values()` or `client.get_value(id)`.

### Send UI state to a script

Wire a button with `on_click_action: { _kind: message, topic: foo/command, ... }`. The script's main loop uses `MessageBus.wait_for_message()` to react.

### Stream data back to a plot

Declare the stream in the element (`stream_id: my_stream`), then `client.stream("my_stream", timestamp, value)` from Python. Stream IDs are plain strings — no pre-registration needed.

### Persist streams to Nominal Core

Add the stream under `streaming.persistence[].streams[]` with a `data_source_rid` pointing at the target dataset.

### Multi-stream plot

Use `stream_ids:` (plural) and prefix channel names with the stream id: `myLabJack.input_voltage`.
