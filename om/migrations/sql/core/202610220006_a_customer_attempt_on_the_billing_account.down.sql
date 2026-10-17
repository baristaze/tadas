-- Takes the attempt at the customer back out of the billing accounts.

ALTER TABLE core.billing_accounts DROP COLUMN customer_attempt;
