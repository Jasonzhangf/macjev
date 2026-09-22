"""Measure the computer-use boundary against a live macOS window.

Run: PYTHONPATH=src python3 tests/benchmark_computer.py [--app Obsidian] [--runs 5]
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any, Callable

from macjev.computer import MacOSComputerDriver, ComputerService


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(quantile * (len(ordered) - 1))))
    return ordered[index]


def _report(name: str, samples: list[float]) -> None:
    print(
        f"{name:<22} n={len(samples):<3} "
        f"p50={_percentile(samples, 0.5):8.1f}ms "
        f"p95={_percentile(samples, 0.95):8.1f}ms "
        f"mean={statistics.fmean(samples):8.1f}ms"
    )


def _measure(
    name: str,
    runs: int,
    action: Callable[[], Any],
) -> list[Any]:
    results: list[Any] = []
    samples: list[float] = []
    for _ in range(runs):
        started = time.monotonic()
        results.append(action())
        samples.append((time.monotonic() - started) * 1000)
    _report(name, samples)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="Obsidian")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    driver = MacOSComputerDriver()
    service = ComputerService(driver)

    windows = _measure("list_windows", args.runs, driver.list_windows)[-1]
    target = next(
        (window for window in windows if window["application_name"] == args.app),
        None,
    )
    if target is None:
        raise SystemExit(f"no window found for {args.app!r}")
    window_id = str(target["window_id"])
    print(f"target window {window_id} {target['application_name']} {target['bounds']}")

    cold_start = time.monotonic()
    driver._ensure_binary()
    print(f"driver_build_or_verify  {(time.monotonic() - cold_start) * 1000:.1f}ms")

    observations = _measure(
        "observe",
        args.runs,
        lambda: service.observe({"window": window_id}),
    )
    observation = observations[-1]
    print(
        f"elements={len(observation['elements'])} "
        f"truncated={observation['truncated']} "
        f"screenshot={observation['screenshot']['width']}x"
        f"{observation['screenshot']['height']}"
    )
    print(f"revision_repeatable={observations[0]['revision'] == observation['revision']}")

    pressable = [
        element
        for element in observation["elements"]
        if "AXPress" in element.get("actions", [])
        and element.get("position")
        and element.get("size")
    ]
    if pressable:
        element = pressable[0]
        point = {
            "x": element["position"]["x"] + element["size"]["width"] / 2,
            "y": element["position"]["y"] + element["size"]["height"] / 2,
        }
        revision = observation["revision"]
        _measure(
            "guard_element",
            args.runs,
            lambda: service.guard(
                {
                    "revision": revision,
                    "operation": {
                        "kind": "click",
                        "element_id": element["element_id"],
                    },
                }
            ),
        )
        _measure(
            "guard_point_hit_test",
            args.runs,
            lambda: service.guard(
                {
                    "revision": revision,
                    "operation": {
                        "kind": "click",
                        "point": point,
                        "expected_element_id": element["element_id"],
                    },
                }
            ),
        )
        _measure(
            "hit_test",
            args.runs,
            lambda: driver.hit_test({"window_id": window_id, "point": point}),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
