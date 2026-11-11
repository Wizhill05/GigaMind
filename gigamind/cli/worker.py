"""Run the durable job worker as a separate process."""

import argparse
import math
import signal
import threading


def finite_range(low, high):
    def parse(value):
        try:
            number = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be a number") from exc
        if not math.isfinite(number) or not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number

    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=finite_range(0.1, 86400), default=1.0)
    parser.add_argument("--lease-seconds", type=finite_range(1, 86400), default=60.0)
    args = parser.parse_args()

    from gigamind.db import jobs, memory_index, trust_models  # register models
    from gigamind import security  # register credential and OAuth models
    from gigamind.db.database import init_db
    from gigamind.services.jobs import run_once

    init_db()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    print("Worker ready", flush=True)
    while not stop.is_set():
        job = run_once(lease_seconds=args.lease_seconds)
        if args.once:
            break
        if job is None:
            stop.wait(args.poll_seconds)


if __name__ == "__main__":
    main()
