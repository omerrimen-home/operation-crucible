# Crucible Networking

This package implements Crucible's network model.

`layout.py` defines canonical NIC ordering, `management.py` manages the Crucible host-only management network and IPAM, and `topology.py` defines persistent lab interfaces, addressing, route metrics, and deterministic MAC addresses.

Persistent topology interfaces occupy the lowest NIC slots, while Crucible NAT and management interfaces are appended afterward.