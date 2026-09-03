# Hello World

Minimal Nominal Connect app.

## Run

1. Open this directory in Connect (File → Open App, or drag `app.connect` onto the app).
2. On first load, Connect creates a `.venv` and installs `connect-python`.
3. Type a name in the **Name** field and click **Say Hello**.
4. Watch the sine wave stream into the plot and the banner update with your greeting.

## Files

- `app.connect` — UI layout (a pane with inputs + a plot).
- `hello.py` — Reads the `user_name` value, writes a banner, streams data.
