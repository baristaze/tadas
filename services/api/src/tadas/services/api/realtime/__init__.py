"""The realtime channel: one socket per client, typed envelopes, a bounded
outbox per socket, and a single-use ticket to open it."""
