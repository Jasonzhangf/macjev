# MacJev

MacJev is a Mac-native foundation-capability service for applications. It is
not a browser automation application, desktop agent, or workflow runtime.

The project positioning and roadmap are defined in
[docs/product-positioning.md](docs/product-positioning.md). Browser
guard/repair and vision/computer-use use separate standard interfaces:

- [docs/browser-guard-repair-api.md](docs/browser-guard-repair-api.md)
- [docs/vision-computer-use-api.md](docs/vision-computer-use-api.md)
- [docs/computer-use-framework.md](docs/computer-use-framework.md)
- [docs/computer-use-containers.md](docs/computer-use-containers.md)
- [docs/wechat-verification.md](docs/wechat-verification.md)

Object identification and tracking are deferred extensions, not mainline
capabilities.

The current experimental backend is a Jev-compatible decision service.

The model is DiffusionGemma 26B-A4B-it. The inference backend is the Apple
Silicon Metal implementation from `mmastrac/diffgemma`. The existing Jev
request and response contract is preserved.

No model training is required for this path.

## API

The example request is `fixtures/example_request.json`. It includes
`model: "jev-latest"`, one of the accepted TypeSafe aliases. The public
response is `model`, `answers`, and `usage`.

## Production Runtime

Install the latest reviewed release globally:

```bash
macjev release --bump patch
```

Every release bumps `project.version` and the local build number, runs the
project regression suite, builds the wheel, force-installs the global
`macjev` and `macjev-mcp` entrypoints, installs the packaged Skills under
`~/.agents/skills`, and registers the stdio MCP server in
`~/.codex/config.toml`. Release requires a clean Git checkout, records the
source commit and tree, verifies the installed CLI/MCP handshake, and writes
the result to the release manifest. The first user-visible build is
`0.1.0001`; subsequent builds increment to `0.1.0002`, `0.1.0003`, and so on.
The package metadata uses a PEP 440 version with a build local segment for the
wheel. Add `--start-daemon` only when the configured model daemon should start
as part of the release.

Create the single runtime configuration:

```bash
PYTHONPATH=src python3 -m macjev.cli config init
```

Start the managed `diffgemma` daemon and the Jev API:

```bash
scripts/macjev-server
```

Then call the configured API:

```bash
curl http://127.0.0.1:8091/health
curl http://127.0.0.1:8091/v1/systemone \
  -H 'Content-Type: application/json' \
  --data-binary @fixtures/example_request.json
```

The runtime reads `~/.macjev/config.toml`, waits for the configured model to
be healthy before opening the API, and records the managed daemon PID under
`~/.macjev/run`. See [production runtime](docs/production-runtime.md) for
configuration and process lifecycle.

When `daemon.model_path` does not exist, the managed daemon downloads the
pinned `mmastrac/diffgemma-26b-a4b-it-q4` revision before starting. The
download is resumable; a failed download stops startup explicitly.

Verify the installed command surface:

```bash
macjev --version
macjev daemon status
macjev-mcp
```

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
