"""Provider JSON formats, one module per wire family, spelled once.

A format module is pure shape knowledge: functions and lenient parse models with no URLs, auth
or I/O. Both sides of the gateway import it; an adapter renders requests out of it, an ingress
interpretation parses requests into it, and neither imports the other."""
