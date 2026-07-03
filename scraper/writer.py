"""
writer.py — Incremental JSONL + CSV output writers.

Supports:
  - Streaming writes (open in append mode) for crash-resilience
  - Dynamic CSV columns (expands when new stat/extra_fields columns appear)
  - Checkpoint file tracking of scraped player IDs (for resume support)
"""
from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from .models import PlayerData

logger = logging.getLogger(__name__)


class OutputWriter:
    """
    Manages JSONL and CSV output files with incremental, append-mode writes.

    The CSV is rebuilt from the JSONL when columns change (new stats/fields);
    or new columns are added to the right side of the existing CSV on-the-fly.
    """

    def __init__(self, output_dir: str, jsonl_name: str, csv_name: str, checkpoint_file: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.jsonl_path = self.output_dir / jsonl_name
        self.csv_path = self.output_dir / csv_name
        self.checkpoint_path = Path(checkpoint_file)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        self._jsonl_fh = open(self.jsonl_path, "a", encoding="utf-8")
        self._csv_fh = None
        self._csv_writer: Optional[csv.DictWriter] = None
        self._csv_columns: List[str] = []

        # Load checkpoint (set of already-scraped player IDs)
        self._scraped_ids: Set[int] = self._load_checkpoint()
        self._checkpoint_fh = open(self.checkpoint_path, "a", encoding="utf-8")

        logger.info(
            "OutputWriter initialised — JSONL: %s, CSV: %s",
            self.jsonl_path, self.csv_path,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def already_scraped(self, player_id: int) -> bool:
        return player_id in self._scraped_ids

    def write(self, player: PlayerData) -> None:
        """Write one player to JSONL, CSV, and the checkpoint."""
        d = player.to_dict()
        flat = player.to_flat_dict()

        # ── JSONL
        self._jsonl_fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        self._jsonl_fh.flush()

        # ── CSV
        self._ensure_csv_writer(flat)
        # Add any missing columns
        new_cols = [c for c in flat if c not in self._csv_columns]
        if new_cols:
            self._expand_csv_columns(new_cols)
        self._csv_writer.writerow({k: flat.get(k, "") for k in self._csv_columns})
        self._csv_fh.flush()

        # ── Checkpoint
        self._scraped_ids.add(player.fifaindex_id)
        self._checkpoint_fh.write(f"{player.fifaindex_id}\n")
        self._checkpoint_fh.flush()

    def close(self) -> None:
        self._jsonl_fh.close()
        if self._csv_fh:
            self._csv_fh.close()
        self._checkpoint_fh.close()

    def get_scraped_count(self) -> int:
        return len(self._scraped_ids)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_checkpoint(self) -> Set[int]:
        if not self.checkpoint_path.exists():
            return set()
        ids = set()
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.isdigit():
                        ids.add(int(line))
        except Exception as exc:
            logger.warning("Could not read checkpoint: %s", exc)
        logger.info("Loaded %d player IDs from checkpoint", len(ids))
        return ids

    def _ensure_csv_writer(self, flat: Dict) -> None:
        if self._csv_writer is not None:
            return

        # Determine initial columns
        if self.csv_path.exists() and self.csv_path.stat().st_size > 0:
            # Read existing header
            with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                try:
                    self._csv_columns = next(reader)
                except StopIteration:
                    self._csv_columns = list(flat.keys())
            self._csv_fh = open(self.csv_path, "a", encoding="utf-8", newline="")
        else:
            self._csv_columns = list(flat.keys())
            self._csv_fh = open(self.csv_path, "w", encoding="utf-8", newline="")
            # Write header
            writer = csv.writer(self._csv_fh)
            writer.writerow(self._csv_columns)
            self._csv_fh.flush()

        self._csv_writer = csv.DictWriter(
            self._csv_fh,
            fieldnames=self._csv_columns,
            extrasaction="ignore",
            lineterminator="\n",
        )

    def _expand_csv_columns(self, new_cols: List[str]) -> None:
        """
        When new columns appear (future stats/fields), we need to rebuild the CSV
        from the existing JSONL to add those columns properly.

        For performance during large runs, we log a warning and add the columns
        at the end of the current file (for rows that have those fields).
        A full rebuild can be triggered separately.
        """
        logger.warning(
            "New CSV columns detected: %s — adding to schema. "
            "Existing rows will have empty values for these columns. "
            "Run rebuild_csv() after the full scrape for a clean file.",
            new_cols,
        )
        self._csv_columns.extend(new_cols)
        # Reinitialise DictWriter with expanded columns
        self._csv_writer = csv.DictWriter(
            self._csv_fh,
            fieldnames=self._csv_columns,
            extrasaction="ignore",
            lineterminator="\n",
        )

    def rebuild_csv(self) -> None:
        """
        Rebuild the CSV from the JSONL file with a consistent, complete column set.
        Call this after a full scrape to get a clean, uniformly-columned CSV.
        """
        logger.info("Rebuilding CSV from JSONL: %s", self.jsonl_path)
        if self._csv_fh:
            self._csv_fh.close()

        # First pass: collect all column names
        all_keys: list = []
        seen_keys: set = set()
        rows = []
        with open(self.jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # Re-flatten and flatten manually here to avoid circular imports issues
                    flat = _flatten_dict(d)
                    rows.append(flat)
                    for k in flat:
                        if k not in seen_keys:
                            seen_keys.add(k)
                            all_keys.append(k)
                except Exception:
                    continue

        # Second pass: write CSV
        tmp_path = self.csv_path.with_suffix(".tmp.csv")
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in all_keys})

        os.replace(tmp_path, self.csv_path)
        logger.info("CSV rebuilt: %d rows, %d columns", len(rows), len(all_keys))

        # Reopen for appending
        self._csv_columns = all_keys
        self._csv_fh = open(self.csv_path, "a", encoding="utf-8", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_fh,
            fieldnames=self._csv_columns,
            extrasaction="ignore",
            lineterminator="\n",
        )


def _flatten_dict(d: dict) -> dict:
    """Flatten a player dict (same logic as PlayerData.to_flat_dict but standalone)."""
    flat = {}
    for key, val in d.items():
        if key == "stats":
            for stat_name, stat_val in (val or {}).items():
                flat[f"stat_{stat_name.lower().replace(' ', '_')}"] = stat_val
        elif key == "extra_fields":
            for ef_key, ef_val in (val or {}).items():
                flat[f"extra_{ef_key.lower().replace(' ', '_')}"] = ef_val
        elif isinstance(val, (list, dict)):
            flat[key] = json.dumps(val, ensure_ascii=False)
        else:
            flat[key] = val
    return flat
