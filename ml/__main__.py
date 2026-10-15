from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ml", description="CS2 ML jobs (Postgres writer)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate-sample", help="Write data/sample_matches.csv")
    p_gen.add_argument("--n", type=int, default=480)

    p_load = sub.add_parser("load-history", help="Load finished matches from CSV into Postgres")
    p_load.add_argument("--path")

    p_past = sub.add_parser("ingest-past", help="Load ~10k newest real finished CS2 matches from PandaScore")
    p_past.add_argument("--max-pages", type=int, default=100)
    p_past.add_argument("--days", type=int, help="only the last N days (incremental)")

    sub.add_parser("train", help="Train Elo + logistic regression baseline")
    sub.add_parser("sync", help="Pull upcoming matches from PandaScore or fixtures")
    sub.add_parser("predict", help="Write predictions for upcoming matches")
    sub.add_parser("worker", help="Loop: train if needed, refresh XGBoost predictions")

    args = parser.parse_args(argv)

    if args.cmd == "generate-sample":
        from ml.generate_sample import write

        path = write(n_matches=args.n)
        print(path)
        return 0

    if args.cmd == "load-history":
        from pathlib import Path

        from ml.load_history import load_csv

        n = load_csv(Path(args.path) if args.path else None)
        print(f"loaded {n} finished matches")
        return 0

    if args.cmd == "ingest-past":
        from ml.history_pandascore import ingest, ingest_recent

        print(json.dumps(ingest_recent(args.days) if args.days else ingest(args.max_pages), indent=2))
        return 0

    if args.cmd == "train":
        from ml.train import train

        print(json.dumps(train(), indent=2))
        return 0

    if args.cmd == "sync":
        from ml.sync import sync

        print(json.dumps(sync(), indent=2))
        return 0

    if args.cmd == "predict":
        from ml.predict import predict_upcoming

        print(json.dumps({"written": predict_upcoming()}, indent=2))
        return 0

    if args.cmd == "worker":
        from ml.worker import run

        run()
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
