"""Third-party providers. Each is an interface with a real client and a
deterministic twin; the object model sees the interface, a process picks
the impl from its settings at boot, and the twin never runs outside a local
environment. Integrations imports infra and nothing from the object
model."""
