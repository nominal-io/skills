# `app.connect` YAML reference

The `app.connect` file declares the UI. Connect loads it when the user opens the app directory. Relative paths in `on_click_action`, `display: markdown`, `canvas:`, etc. are resolved against the app directory; absolute paths are used as-is.

## Top-level keys

```yaml
title: My App                    # App title shown in the title bar
window_title: null               # Optional override for OS window title
logo_path: null                  # Optional logo image path (or {light_mode:, dark_mode:})
timeline:                        # Timeline widget config (usually hidden)
  show: false
  display: relative              # relative | utc
  pixels_per_tick: 100.0
  milestones: []                 # [{ time: <f64>, tooltip: ..., color: ... }]
streaming:                       # Streaming + persistence config
  buffer_size: 5000              # In-memory buffer depth per stream
  playback_speed: null
  window: null
  persistence:                   # List of persistence targets
  - enabled: 'true'
    data_source_rid: ri.catalog.xxx
    file_path: null
    streams:
    - id: my_stream
      tags: {}
  channels: []                   # Per-channel display units / scaling
python:
  packages:                      # Extra pip packages, or a path to a requirements .txt
  - nominal-instro
  index_url: https://pypi.org/simple/   # `~` to disable downloads (offline / wheelhouse)
  wheelhouse: null               # Optional local wheelhouse path
on_load: null                    # Optional script to run when the app opens
on_unload: null                  # Optional script to run when the app closes
tiles: [...]                     # Main UI layout (see below)
scene: {}                        # 3D scene config (for spatial/pointcloud apps)
poster: null                     # Optional "poster" image
prompt_windows: []               # Modal prompt dialogs triggered by scripts
mcap_path: null                  # Optional path to an MCAP file for replay
conditionals: []                 # Channel conditions that fire actions
default_device_configs: {}       # { <driver>: { <device id>: <config file> } }
```

In practice every app sets `title` and `tiles`; everything else is optional. **Unknown top-level keys are a hard load error** — the top-level struct rejects fields it doesn't recognise, so a typo fails the whole app rather than being ignored.

`left_panel`, `right_panel`, and `bottom_panel` are deprecated — do not use them in new apps. Setting any of them *together with* `tiles` is a load error.

`lockdown:` is added by the publishing flow to make a shipped app read-only. Never write it by hand; it disables the UI builder outright.

### Streams and channels

A channel is addressed as `<stream_id>.<channel_name>`; the string is split on the first `.`, and a stream id may not itself contain a `.`. Elements that take a single stream accept `stream_id:` plus an unqualified `channel:`; elements that take several accept `stream_ids:` plus fully-qualified `channels:`. **Do not set `stream_id:` and also prefix the channel** — when `stream_id` is present the channel string is used verbatim as the channel name under that stream.

`streaming.channels` attaches display units and scaling to channels at load time:

```yaml
streaming:
  channels:
  - channel: motor.raw_rpm
    unit: V
    scale: { type: linear, gain: 0.25, offset: 0, unit: rpm }
  - channel: motor.unscaled_reference
```

## UI Builder compatibility (required)

Every app **must** stay editable in Connect's no-code UI builder. Users expect to open any
app and rearrange it by hand; an app that only Connect can render but nobody can edit is a
defect, not a stylistic choice. These constraints are not optional:

- The top-level `tiles` **must** be a list of exactly one tile, and that tile **must** be `layout: tabs`.
- No other `layout: tabs` may appear anywhere beneath it. A nested tabs container turns editing off for the whole app.
- Every pane **must** contain exactly one element. A pane with zero elements renders nothing at all; a pane with two or more is locked ("This panel created manually in the YAML config cannot be edited in the app").
- Every pane **must** set `should_fill: true`. This is what the builder writes on every pane it creates, and it is what makes the single element fill the pane.
- `lockdown:` **must** be absent.

The first two and `lockdown:` turn editing off for the entire app; a pane with the wrong
element count locks just that pane. Neither failure is announced at load time. If a layout you want
seems to require breaking one of them, restructure the layout — nest another `layout: grid`
inside a tab rather than hoisting a grid to the top level, put several widgets side by side as
a grid of one-element panes, collect related inputs and buttons into a single form element
(one `inputs:` element counts as one element), and give an otherwise-empty pane a
`display: banner` or `display: markdown` element instead of leaving it bare.

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
    allow_popout: true          # default true
    tile: { layout: pane, id: <uuid>, elements: [...] }
```

### Grid

Rows and columns are sized by `height` / `width`, which are **relative weights among siblings**, not fractions — `[1, 2]` makes the second twice as large as the first. Omit or `null` to use the default weight of `1.0`.

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
  id: <uuid>                # UUIDv4; generated if omitted
  title: My Panel
  direction: vertical       # vertical | horizontal
  should_fill: true
  elements: [ <exactly one element> ]
```

**`id` must be a UUID** (e.g. `7a13aace-e94a-4552-a461-39c728a54f02`). Use any valid v4. Always write one out: a pane with no `id` gets a fresh UUID on every load, so scripts can't address it and its identity isn't stable. Duplicates are not rejected at load time, but pane visibility, navigation, and selection all key on the UUID, so a duplicate silently acts on the wrong pane.

## Elements

Elements are the widgets inside a pane. Each element is discriminated by the presence of one key, checked in this order: `input:`, `dashboard:`, `edit_file:`/`startup_file:`, `plot_configs:`, `columns:`, `group_layout:`, `plot:`, `display:`, `controls:`, `on_click_action:` (buttons), `layout_picker:`, `inputs:` (forms), `canvas:`. A mapping with none of these parses as an unknown element and renders as an error in place.

### Displays

Text / status widgets, all start with `display:`.

```yaml
- display: markdown
  path: README.md             # Markdown file in the app directory
                              # or `const: "# inline markdown"`, or `value_id: my_value`

- display: banner              # Large status text (`display: header` is an alias)
  value_id: my_banner          # or `value: "static text"`
  font_size: null

- display: labeled_value       # Static label paired with a dynamic value
  label: 'Status:'
  value_id: my_status

- display: separator

- display: stream_value        # Single numeric value from a stream
  title: Voltage
  stream_id: myPSU
  channel: ch1_v
  units: V
  show_channel_picker: true
  format: { type: decimal, count: 2 }   # or { type: significant, count: 3 }

- display: gauge               # Radial gauge: set `radius`
  stream_id: PID
  channel: Actual Speed (RPM)
  title: Motor RPM
  units: RPM
  min: 0.0
  max: 2000.0
  arc: semi                    # only `semi` is supported
  radius: 84.0
  zone_width: 20.0
  zones:
  - { start: 0.0,    end: 1500.0, color: safe }
  - { start: 1500.0, end: 1800.0, color: warn }
  - { start: 1800.0, end: 2000.0, color: critical }
  hysteresis: 0.0167           # colour refresh, seconds
  refresh: 0.0333              # value refresh, seconds
  decimal_places: 0
  # For a bar gauge instead, set `orientation: vertical` plus `width:` and `height:`
  # and omit `radius`. Exactly one of `radius` / `orientation` must be present.

- display: meter               # Linear bar with zones
  stream_id: PID
  channel: Actual Speed (RPM)
  orientation: horizontal      # horizontal | vertical
  scale: { kind: linear, ticks: 5 }   # or { kind: logarithmic, base: 10 }
  min: 0.0
  max: 100.0
  zones: [...]

- display: indicator_light     # On/off lamp
  label: Armed
  value_id: armed
  lit_when: 1                  # 0 | 1
  colors: { lit: '#00ff00', unlit: '#ff0000' }

- display: callout             # Inline warning / error / info box
  message: Pressure out of range
  callout_type: warning        # warning | error | info
  show_background: true

- display: logs                # Script log output
  script_id: my_script         # Matches a script `id` configured elsewhere

- display: table               # Table output from client.set_output
  script_id: my_script         # or `value_id: my_table`

- display: channel_table       # Live values for a stream's channels
  stream_id: vector_vec_ch0
  channels: []                 # omit for all channels of the stream

- display: image
  path: diagram.png            # or {light_mode:, dark_mode:}
  fit: fit                     # fit | zoom | stretch

- display: scene               # 3D viewport for the top-level `scene:` config
  height: null                 # at most one of these per app

- display: can_frame_viewer    # Raw CAN frames (Devices panel CAN interface required)

- display: can_frame_sender    # UI for composing + sending CAN frames

- display: video               # Frame buffer (pair with client.stream_rgb)
  frames: my_camera            # or `stream: <camera stream_id>`, or `mcap: <channel name>`
```

`display: wind_indicator` and `display: pfd` (primary flight display) also exist for vehicle apps; both take a `channel_mapping:` of named channels.

### Plots

`plot:` selects the kind: `line`, `spectrogram`, `scatter`, or `smith_chart`.

```yaml
- plot: line
  title: null
  stream_id: myPSU             # single stream: `channels` are unqualified names
  channels:
  - ch1_v
  - ch1_i
  # OR, for cross-stream plots, use `stream_ids: [myPSU, dmm]` and fully-qualified
  # `channels: [myPSU.ch1_v, dmm.reading]`.
  colors:
  - rgb(249, 53, 53)
  - rgb(113, 249, 53)
  show_legend: true            # default true
  show_picker: true            # channel picker on hover; default true
  show_cursor_values: false
  legend_placement: bottom_left   # top_left | top_right | bottom_left | bottom_right
  x_format: timestamp          # raw | timestamp
  x_time_display: local        # local | utc
  x_scale: linear              # linear | log
  y_scale: linear
  x_label: null                # optional axis labels
  y_label: RPM
  y_bounds: { min: 0.0, max: 100.0 }   # fixes the axis; omit to autoscale
  time_window: 30s             # rolling window; defaults to 30s, null for full history
  height: null
  hide_grid: false
  hide_axes: false
  warning_threshold: null      # draws a line; values above are recoloured
  critical_threshold: null
  secondary_axis:              # optional right-hand y-axis
    channels: [myPSU.ch1_i]
    label: Current
    y_bounds: null
  regions: my_plot_regions     # value id written from Python with client.set_value
```

`plot_configs:` (a `subplot`) tiles several line plots in a grid: `rows`, `columns`, `row_ratios`, `column_ratios`, `plot_configs` (a list of line-plot configs, row-major).

### Canvas

Embeds an interactive diagram defined in a separate YAML.

```yaml
- id: system_diagram
  label: null
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
    location: bottom           # top | bottom
    columns: []

- controls: script_table       # Run multiple scripts from a single table
  show_output_column: true
  scripts:
  - label: Receiver
    path: receiver.py
  - label: Sender
    path: sender.py
```

### File Editor

Shows an editable file next to the UI.

```yaml
- id: my_script_editor         # required
  startup_file: my_script.py
  label: null
  show_picker: false
  show_run_button: false
  height: null
```

### Forms (inputs + buttons)

A form is an element with `inputs:` at its top level. Each entry is an input widget, a display, or a button. The form itself has no `input:` / `display:` key — it is discriminated by the presence of `inputs:`. A form is a single element, so it is the way to put several controls in one pane.

```yaml
- spacing: normal              # tight | normal | loose
  inputs:
  - display: banner
    value: Device Settings

  - input: text
    id: visa_resource
    label: VISA Resource
    default: 'USB0::0xF4EC::0x1430::XXX::INSTR'
    width: null
    private: false             # mask characters
    auto_highlight: false

  - input: multiline
    id: notes_field
    label: Notes

  - input: number              # `input: slider` is an alias for the same widget
    id: voltage
    label: Voltage (V)
    default: 0.0
    min: 0.0                   # optional bounds; unset means unbounded
    max: 30.0
    units: V
    stepper: { amount: 1.0 }   # adds +/- buttons

  - input: checkbox
    id: enable
    label: Enable
    default: false
    on_toggle_action: ...      # also on_toggle_high_action / on_toggle_low_action

  - input: toggle_switch
    id: streaming_on
    on_label: Streaming
    off_label: Stopped
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
    on_change: { path: mode_changed.py }   # a script hook, not an action
    on_click_action: ...

  - input: file                # also: files, folder, folders
    id: input_csv
    label: Input CSV

  - input: asset_selector      # Picker for a Nominal Core Asset
    id: asset_rid
    label: Asset
    default: ''
    allow_create: false
    mapping:
      properties: {}

  # Buttons — discriminated by `on_click_action`, which must be present
  - id: commit_btn             # id is optional on buttons
    text: Commit
    on_click_action:
      _kind: message
      topic: my/command
      set_voltage: $voltage
      enable: $enable
    show_sigil: true           # Show a small icon on the button; default true
    size: normal               # small | normal | big | huge | enormous
    rounding: tight            # none | tight | wide
    color: null                # '#77DD77', or a conditional block (see below)

  - text: Run Script
    on_click_action:
      _kind: script
      path: my_script.py
      args: []
      max_log_lines: 10000
```

Other input kinds: `checkbox_group`, `radio`, `date_time`, `time`, `notes`, `stopwatch`, `event_marker`, `geo_map`, `nidaqmx`, `instrument`, and the Nominal Core pickers `dataset_selector`, `run_selector`, `template_selector`, `checklist_selector`, `connection_selector`.

A button's `color:` can also be driven by a channel:

```yaml
color:
  kind: conditional
  channel: psu.state
  colors: [...]
```

## Actions

`on_click_action` / `on_toggle_action` / `on_toggle_high_action` / `on_toggle_low_action` take either a single action mapping or a **list** of them (all are dispatched, order of arrival is not guaranteed). Each action is discriminated by `_kind`; omitting `_kind` is read as `message`.

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

### `_kind: command` — send a registered command

```yaml
on_click_action:
  _kind: command
  topic: devices/{device_id}/command
  command_id: set_output
  params: { channel: 1, value: $voltage }
```

Sends `{ <command_id>: <params> }` on the topic. `$widget_id` references inside `params` are expanded the same way.

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

Add the stream under `streaming.persistence[].streams[]` with a `data_source_rid` pointing at the target dataset. A `file_path` writes an Avro file instead of (or as well as) sending to Core. `enabled`, `data_source_rid`, `file_path`, and tag values all accept `{ value_id: <widget id> }` in place of a constant.

### Multi-stream plot

Use `stream_ids:` (plural) and prefix channel names with the stream id: `myLabJack.input_voltage`.

### Alarm on a channel

Add a top-level `conditionals:` entry:

```yaml
conditionals:
- name: OVERPRESSURE
  combiner_type: and                 # and | or
  conditions:
  - channel: tank.pressure
    operator: greater_than           # greater_than, less_than, greater_than_or_equal,
    threshold: 100.0                 # less_than_or_equal, or {equal: {tolerance: 0.1}}
  trigger_action:                    # / {not_equal: {tolerance: 0.1}}
    action:
    - _kind: message
      topic: alarms
      overpressure: true
    time_persistence: { unit: Milliseconds, value: 0 }
  untrigger_action: null
```

`threshold` also accepts a `$widget_id` reference in place of a literal.
