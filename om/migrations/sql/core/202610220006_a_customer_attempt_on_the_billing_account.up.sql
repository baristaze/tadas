-- The attempt at the org's customer, which the customer create's idempotency
-- key carries. An account made before it is at the first attempt, under the
-- key every create used until now.

ALTER TABLE core.billing_accounts ADD COLUMN customer_attempt integer NOT NULL DEFAULT 0;
