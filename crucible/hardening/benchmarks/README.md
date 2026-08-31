# Crucible Hardening Benchmarks

This directory contains machine-readable control inventories for
security benchmarks implemented by Operation Crucible.

Benchmark metadata is registered in:

`config/hardening.yml`

Each implemented benchmark may reference a control inventory in this
directory.

Control inventories describe:

- control identifiers;
- benchmark profile membership;
- source assessment type;
- Crucible implementation status;
- implementation tags.

Actual remediation and validation logic belongs in Ansible roles and
playbooks.

Operation Crucible must not report benchmark compliance merely because
a hardening playbook completed successfully. Compliance reporting must
be based on explicit post-configuration validation of applicable
controls.