"""CSV ledger reconciliation."""

import csv
from decimal import Decimal
from io import StringIO


def reconcile_accounts(csv_text):
    totals = {}
    for row in csv.DictReader(StringIO(csv_text)):
        account = row["account"]
        amount = Decimal(row["amount"])
        totals[account] = totals.get(account, Decimal("0.00")) + amount
    return {account: f"{amount:.2f}" for account, amount in sorted(totals.items())}
