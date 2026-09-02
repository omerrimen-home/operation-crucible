# Tests

This directory contains automated regression tests for Operation Crucible components that can be validated without building a complete virtual machine.

Current coverage includes:

- VirtualBox network slot layout;
- topology addressing and IPv4 validation;
- deterministic MAC generation;
- configuration catalog validation;
- configuration execution/runtime behavior;
- capability-aware configuration relationships;
- hardening catalog and planning behavior;
- hardening exceptions and derived exceptions;
- Ubuntu 26.04 CIS milestone BA invariants;
- Ansible filesystem-path regression checks.

Run the complete unit test suite with:

```bash
python3 -m unittest discover -s tests -v
```
