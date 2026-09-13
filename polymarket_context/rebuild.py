"""Rebuild legacy D-C/candidate sources, then publish the fine dashboard."""
from pathlib import Path
import argparse


def main() -> None:
    from .seed import run
    from .fine import build
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=Path('config.two_markets.json'))
    p.add_argument('--documents', type=Path, default=Path('context/seed_documents.jsonl'))
    p.add_argument('--failed-search-status', type=Path)
    a = p.parse_args()
    run(a.config, a.documents, a.failed_search_status)
    build(a.config)


if __name__ == '__main__':
    main()
