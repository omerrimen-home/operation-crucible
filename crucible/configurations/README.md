# Crucible Configurations

This package implements the Operation Crucible post-install
configuration catalog.

Beginning with Crucible v0.3, configurations are selected
independently from operating-system profiles.

The catalog is stored in:

```text
config/configurations.yml
```

Configuration definitions may declare:

operating-system compatibility;
persistent topology requirements;
static IPv4 requirements;
implementation metadata;
configuration-specific parameters.

The Forge filters the catalog against the selected OS profile
before exposing configuration choices.