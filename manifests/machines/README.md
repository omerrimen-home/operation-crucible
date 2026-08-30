# Machine Manifests

Machine manifests describe the resolved configuration of an individual Crucible VM.

They may contain operating-system selection, resources, VirtualBox settings, topology interfaces, Crucible infrastructure networking, unattended-install configuration, and instance identity.

The interactive Forge currently writes active machine manifests beneath:

```text
.crucible/manifests/machines/
```

This tracked directory is reserved for future reusable examples or persistent manifest definitions.
