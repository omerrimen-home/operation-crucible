# Crucible Validation

This package validates resolved Forge configuration before VM creation begins.

Current validation includes hardware limits, operating-system requirements, NIC layout, topology interfaces, attachment types, MAC addresses, and IPv4 configuration.

Invalid configuration should be rejected here rather than failing later during installation or provisioning.
