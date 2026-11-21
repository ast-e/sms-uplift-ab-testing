"""Aggregate X5's line-level purchase history into one row per customer.

`purchases.csv.gz` has one row per PRODUCT line, and `purchase_sum` (the receipt total) is repeated on
every line of the same transaction. Summing it directly would multiply each receipt by its number of
products, so we first collapse to one row per (client_id, transaction_id) and only then aggregate.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["client_id", "transaction_id", "transaction_datetime", "purchase_sum"]


def build_purchase_features(purchases_path: str, out_path: str, chunksize: int = 2_000_000) -> None:
    """Write `out_path` with columns client_id, n_transactions, total_spend, log_spend, last_purchase_date, has_history."""
    path = Path(purchases_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Download `purchases.csv.gz` from the Hugging Face dataset "
            "`pytorch-lifestream/retailhero-uplift` into the `data_raw/` folder (see README)."
        )

    pieces = []
    for chunk in pd.read_csv(path, usecols=COLUMNS, chunksize=chunksize):
        # One row per receipt inside this chunk. Both values are identical on every line of a receipt,
        # so `max` just picks that value (and is safe if a receipt is split across two chunks).
        pieces.append(
            chunk.groupby(["client_id", "transaction_id"], as_index=False).agg(
                purchase_sum=("purchase_sum", "max"),
                transaction_datetime=("transaction_datetime", "max"),  # ISO strings sort chronologically
            )
        )

    # A receipt split across chunk boundaries appears twice: collapse again before aggregating per client.
    receipts = pd.concat(pieces, ignore_index=True).groupby(["client_id", "transaction_id"], as_index=False).agg(
        purchase_sum=("purchase_sum", "max"),
        transaction_datetime=("transaction_datetime", "max"),
    )

    features = receipts.groupby("client_id", as_index=False).agg(
        n_transactions=("transaction_id", "size"),
        total_spend=("purchase_sum", "sum"),
        last_purchase_date=("transaction_datetime", "max"),
    )
    features["last_purchase_date"] = pd.to_datetime(features["last_purchase_date"])
    # log1p tames the heavy right tail of spend; it needs total_spend > -1 (refunds are checked in the notebook).
    features["log_spend"] = np.log1p(features["total_spend"].clip(lower=0))
    features["has_history"] = True
    features[
        ["client_id", "n_transactions", "total_spend", "log_spend", "last_purchase_date", "has_history"]
    ].to_csv(out_path, index=False)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "data_raw/purchases.csv.gz"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data_raw/purchases_features.csv.gz"
    build_purchase_features(src, dst)
    print(f"written {dst}")
