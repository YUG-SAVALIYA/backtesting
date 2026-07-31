from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from rsi_supertrend_backtester.core.models import TradeSignal


def save_signals(output_file: str | Path, signals: Iterable[TradeSignal]) -> None:
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [s.to_dict() for s in signals]
    output_path.write_text(json.dumps(payload, indent=4))


def load_json(path: str | Path):
    return json.loads(Path(path).read_text())
