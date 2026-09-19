# MacJev

MacJev is an experimental Mac-native backend for a Jev-compatible decision
service.

The model is DiffusionGemma 26B-A4B-it. The inference backend is the Apple
Silicon Metal implementation from `mmastrac/diffgemma`. The existing Jev
request and response contract is preserved.

No model training is required for this path.

## Playground

Run the protocol experiment with the explicit mock backend:

```bash
PYTHONPATH=src python3 -m playground.run_mock
```

Then:

```bash
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8090/v1/systemone \
  -H 'Content-Type: application/json' \
  --data-binary @playground/example_request.json
```

The example request includes `model: "jev-latest"`, one of the accepted
TypeSafe aliases. The public response is `model`, `answers`, and `usage`.

Probe a local `diffgemma` server:

```bash
PYTHONPATH=src python3 -m playground.probe_diffgemma
```

Run the Mac backend behind the Jev API:

```bash
PYTHONPATH=src python3 -m playground.run_live
```

The live path fails if the local Metal server is unavailable. It never falls
back to mock output.

## Production Runtime

Create the single runtime configuration:

```bash
PYTHONPATH=src python3 -m macjev.cli config init
```

Start the managed `diffgemma` daemon and the Jev API:

```bash
scripts/macjev-server
```

The runtime reads `~/.macjev/config.toml`, waits for the configured model to
be healthy before opening the API, and records the managed daemon PID under
`~/.macjev/run`. See [production runtime](docs/production-runtime.md) for
configuration and process lifecycle.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Local Metal Backend

Install the Apple Silicon engine and download the pinned q4 pack:

```bash
cargo install --git https://github.com/mmastrac/diffgemma --locked diffgemma
diffgemma download \
  --repo mmastrac/diffgemma-26b-a4b-it-q4 \
  --revision be312db884e99c963518a5e5a97de6080263f2a8
diffgemma serve --ctx 100000
```

The downloader writes `model/diffgemma-26b-a4b-it-q4`, verifies the pack, and
resumes interrupted transfers. The q4 blob is about 19 GiB.

## Status

The repository now has a production runtime skeleton: the Jev API, managed
DiffusionGemma daemon lifecycle, TOML configuration, and a goal-driven browser
adapter boundary. The browser transport implementation remains a separate
follow-up.
