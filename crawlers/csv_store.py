from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


CSV_ENCODING = "utf-8-sig"


def ensure_parent_dir(path: str | Path) -> Path:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    return csv_path


def prepare_dataframe(rows: pd.DataFrame | Iterable[dict] | None, columns: list[str]) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        df = rows.copy()
    else:
        materialized = list(rows or [])
        df = pd.DataFrame(materialized)

    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA

    return df[columns]


def load_csv(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        if columns is None:
            return pd.DataFrame()
        return pd.DataFrame(columns=columns)

    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()

    if columns is None:
        return df

    return prepare_dataframe(df, columns)


def save_csv(path: str | Path, rows: pd.DataFrame | Iterable[dict], columns: list[str]) -> pd.DataFrame:
    csv_path = ensure_parent_dir(path)
    df = prepare_dataframe(rows, columns)
    df.to_csv(csv_path, index=False, encoding=CSV_ENCODING)
    return df


def append_rows(path: str | Path, rows: Iterable[dict], columns: list[str]) -> int:
    materialized = list(rows)
    if not materialized:
        return 0

    csv_path = ensure_parent_dir(path)
    frame = prepare_dataframe(materialized, columns)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    frame.to_csv(
        csv_path,
        index=False,
        mode="a",
        header=write_header,
        encoding=CSV_ENCODING,
    )
    return len(frame)


def upsert_dataframe(
    existing: pd.DataFrame,
    incoming: pd.DataFrame | Iterable[dict],
    columns: list[str],
    key_columns: list[str],
    keep: str = "last",
) -> pd.DataFrame:
    incoming_df = prepare_dataframe(incoming, columns)
    if incoming_df.empty:
        return prepare_dataframe(existing, columns)

    merged = pd.concat(
        [prepare_dataframe(existing, columns), incoming_df],
        ignore_index=True,
    )
    return merged.drop_duplicates(subset=key_columns, keep=keep).reset_index(drop=True)


def upsert_csv(
    path: str | Path,
    incoming: pd.DataFrame | Iterable[dict],
    columns: list[str],
    key_columns: list[str],
    keep: str = "last",
) -> pd.DataFrame:
    existing = load_csv(path, columns)
    merged = upsert_dataframe(existing, incoming, columns, key_columns, keep=keep)
    return save_csv(path, merged, columns)
