# Hypervisors

This package defines Crucible's virtualization-provider layer.

`base.py` contains common provider abstractions, while `virtualbox.py` implements the current Oracle VirtualBox backend.

VirtualBox is currently the only supported hypervisor, but this separation is intended to allow additional providers in future releases.
