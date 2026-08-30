# Tests

This directory contains automated tests for Crucible components that can be validated without building a complete VM.

Current tests cover network slot layout, topology addressing, IPv4 validation, and deterministic MAC generation.

Run the test suite with:

```bash
python3 -m unittest discover -s tests -v
```

Full operating-system Forge testing remains an integration test requiring VirtualBox and installation media.
