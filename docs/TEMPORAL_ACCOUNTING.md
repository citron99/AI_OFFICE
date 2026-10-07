# Temporal accounting rules

The financial report is a point-in-time read model. Its synthetic accounting
dataset is `synthetic-accounting-rub-v4` and uses RUB only.

## Receivables

`Receivable` is the claim; it no longer carries a mutable aggregate `received`
field. Each collection is an immutable `ReceivableReceipt` with an ID, a
receivable ID, amount, currency, and `received_on` date.

For report end date `D`, receivable outstanding is:

`max(0, gross - sum(receipt.amount where receipt.received_on <= D))`

The builder rejects duplicate receipt IDs, a receipt for an unknown receivable,
currency mismatches, and receipts dated before the claim was issued. This
prevents a collection made later from changing a historical report.

## Bank accounts

Every `AccountBalance` has a stable `account_id`. For each account, the report
uses the latest balance snapshot whose `as_of` date is not later than `D`.
Two records for the same account and snapshot date are invalid.

`balances_as_of` is returned only if all included account balances have the
same date. For a mixed-age collection the field is null, while
`account_balance_dates` exposes the selected date per account. The report never
labels a mixed-date sum as a single-date balance.

The accounting sync receipt and its SHA-256 include eight source collections,
including dated receivable receipts, plus the synthetic accrual journal.
