# Crucible CLI

This package contains command-line orchestration used by Operation Crucible.

`create_machine.py` resolves a machine manifest into a VirtualBox VM, installation media, networking, and the appropriate unattended-install backend.

The top-level `crucible.py` Forge currently provides the main interactive user interface.
