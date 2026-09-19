# Production Runtime

## Boundary

MacJev owns two local processes:

```text
scripts/macjev-server
        |
        +-- diffgemma serve   Apple Silicon model daemon
        |
        +-- macjev API        standard Jev HTTP contract
```

The model daemon and Jev API are separate processes. The API starts only after
the configured backend reports both `/health` and the configured model in
`/v1/models`. If that check fails, startup fails explicitly; there is no mock
or alternate-model fallback.

The runtime configuration has one source:

```text
~/.macjev/config.toml
```

Create it with:

```bash
PYTHONPATH=src python3 -m macjev.cli config init
```

Start both processes:

```bash
scripts/macjev-server
```

The script defaults to `~/.macjev/config.toml`. Override only the file path
with `MACJEV_CONFIG`; individual runtime values remain in TOML.

## Configuration

```toml
[server]
host = "127.0.0.1"
port = 8091
max_body_bytes = 1048576

[backend]
type = "diffgemma"
base_url = "http://127.0.0.1:8080"
model = "diffgemma-26b-a4b-it-q4"
timeout_seconds = 180.0

[backend.schema_options]

[daemon]
managed = true
executable = "diffgemma"
model_path = "/Users/fanzhang/code/macjev/model/diffgemma-26b-a4b-it-q4"
context_size = 131072
extra_args = []
startup_timeout_seconds = 180.0
poll_interval_seconds = 0.5

[paths]
run_dir = "~/.macjev/run"
log_dir = "~/.macjev/log"

[auth]
api_key = ""
origin_secret = ""
```

`daemon.managed = false` attaches to an already-running backend and never
starts or stops it. A managed daemon is recorded in
`run_dir/diffgemma.pid`; stop only that recorded, command-verified process.

Authentication is optional. When set, `api_key` requires
`Authorization: Bearer ...` and `origin_secret` requires
`X-Origin-Secret`.

## Operations

```bash
scripts/macjev-server
scripts/macjev-server --no-daemon
PYTHONPATH=src python3 -m macjev.cli daemon status
PYTHONPATH=src python3 -m macjev.cli daemon stop
```

`macjev serve` stops a daemon only when that invocation started it. An
already-running external or managed daemon is left running. `daemon stop`
uses the PID file and verifies that the process command contains both
`diffgemma` and the configured model path before sending `SIGTERM`.

Logs:

```text
~/.macjev/log/diffgemma.log
```

## Browser Boundary

Browser automation is not part of the model service. The adapter contract in
`src/macjev/browser.py` defines only:

```text
BrowserGoal
  target         description of what to find in the DOM
  action         operation to perform, for example locate/click/type/read
  arguments      operation parameters

BrowserAdapter.execute(goal)
  -> BrowserResult
       container       matched DOM container identity/context
       action_result   result of the requested operation
```

A future Chrome/CDP or Camo implementation owns its transport, profiles,
login state, timeouts, and action execution. Those control details must not be
written into Jev requests, responses, or metadata.
