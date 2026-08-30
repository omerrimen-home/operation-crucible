# Ansible Inventories

This directory is reserved for persistent or reusable Ansible inventory definitions.

Crucible currently generates its active runtime inventory automatically at:

```text
.crucible/ansible/inventory.yml
```

Runtime inventories may contain machine-specific connection information or credentials and should not be committed to the repository.
