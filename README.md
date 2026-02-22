# Ableton Offline Renderer

Batch export Ableton Live projects to audio files without manual interaction. Point it at a folder of `.als` files, and it renders them one by one — parsing content length, setting loop boundaries, triggering export, and monitoring progress.

## How It Works

The tool has two parts:

1. **RenderMonitor** — A MIDI Remote Script that runs inside Ableton Live. It opens a TCP server on `localhost:9877` and exposes Ableton's internal state (dialog messages, file paths, transport settings) to external tools.

2. **CLI** — A Python script that parses `.als` files (gzipped XML) to determine content length, then automates the export workflow: open project, set loop boundaries, trigger Cmd+Shift+R, confirm dialogs, wait for render, verify output.

```
┌─────────────────────────┐     TCP 9877     ┌──────────────────────────┐
│                         │ ◄──────────────► │                          │
│   CLI (Python)          │   GET/SET/STATUS │   Ableton Live           │
│                         │                  │   + RenderMonitor        │
│   • Parse .als XML      │                  │     Remote Script        │
│   • Resolve samples     │ ◄──────────────► │                          │
│   • Send keystrokes     │   JXA/osascript  │   • Dialog state         │
│   • Monitor progress    │                  │   • Transport control    │
│                         │                  │   • File path reporting  │
└─────────────────────────┘                  └──────────────────────────┘
```
## Prerequisites

- **macOS** (uses JXA/osascript for keyboard automation)
- **Ableton Live 12 Suite**
- **Python 3.11+**
- **ripgrep** (optional, recommended) — used for fast sample resolution; falls back to BSD `find` if not installed

```bash
brew install ripgrep
```

## Setup

### 1. Install the Remote Script

Copy or symlink `remote_script/RenderMonitor/` to your Ableton Remote Scripts folder:

```bash
ln -s "$(pwd)/remote_script/RenderMonitor" \
  ~/Music/Ableton/User\ Library/Remote\ Scripts/RenderMonitor
```

Then in Ableton: **Preferences → Link, Tempo & MIDI → Control Surface → RenderMonitor**

### 2. Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure sample search paths (optional)

If your projects reference samples that have moved, create a `config.json`:

```bash
cp config.json.template config.json
# Edit config.json with your sample library paths
```

### 4. Configure Ableton export settings

Before running, set your preferred export format and output folder in Ableton's export dialog (Cmd+Shift+R). The tool uses whatever settings are already configured.

## Usage

Render a single project:

```bash
python main.py path/to/project.als
```

Batch render all projects in a directory:

```bash
python main.py path/to/projects/ --export-dir ~/Music/Exports
```

The `--export-dir` flag enables post-render verification (checks that the exported file exists).

## Remote Script Protocol

The RenderMonitor Remote Script speaks a simple newline-delimited TCP protocol:

| Command | Response | Description |
|---------|----------|-------------|
| `PING` | `PONG` | Health check |
| `STATUS` | `IDLE` / `RENDERING:<msg>` / `EXPORT_DIALOG` | Current state |
| `GET:<path>` | `OK:<value>` | Read property (e.g. `song.file_path`) |
| `SET:<path>=<value>` | `OK:<path>=<value>` | Set property (e.g. `song.loop_start=0.0`) |

## Limitations

- **macOS only** — keyboard automation uses JXA (JavaScript for Automation)
- **Requires foreground** — Ableton must be the active application for keystrokes to register
- **Ableton Live 12 Suite** — tested on this version only
- **Export settings** — format, quality, and output folder must be pre-configured in Ableton

## Running Tests

```bash
pytest -v
```
