# OptiQ Vision Fix Evidence

`evidence.json` records the candidate commit and two verification results:

- the exact regression command declared in `.appsdk/project.json`, with 79
  tests passing and the full log SHA-256
- a real `macjev optiq-serve` image request against the pinned `mlx-optiq`
  0.5.12 runtime and local DiffusionGemma OptiQ model

The full regression log and raw HTTP response remain in `/tmp` for this
workspace run. Their SHA-256 values are recorded so the summarized evidence is
bound to those exact outputs.
