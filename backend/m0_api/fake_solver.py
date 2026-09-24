"""Stand-in for a long solver run, until M3/M4 provide the real launchers.

It does no hydraulics. It prints `PROGRESS k/N` once per step, sleeping
between steps, then prints `DONE ok`. With `--fail-at K` it prints `DONE failed`
at step K and exits non-zero. The worker launches it detached, exactly as it
will launch Delft3D, so the launch, log-reading and restart paths are real.

    python -m backend.m0_api.fake_solver --run-id kosi_s001__delft3d --steps 5 --step-s 2
"""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="only used so the process can be identified")
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--step-s", type=float, required=True)
    parser.add_argument("--fail-at", type=int, default=None)
    args = parser.parse_args(argv)

    print(f"fake solver started run {args.run_id}", flush=True)
    print(f"PROGRESS 0/{args.steps}", flush=True)
    for k in range(1, args.steps + 1):
        time.sleep(args.step_s)
        if args.fail_at is not None and k >= args.fail_at:
            print(f"DONE failed at step {k}", flush=True)
            return 1
        print(f"PROGRESS {k}/{args.steps}", flush=True)
    print("DONE ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
