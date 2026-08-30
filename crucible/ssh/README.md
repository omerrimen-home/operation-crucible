# Crucible SSH

This package manages controller-side SSH identity for Linux guests.

Each forged Linux VM receives a unique instance serial, Ed25519 keypair, and dedicated `known_hosts` file beneath `.crucible/ssh/machines/`.

This keeps disposable Crucible machines isolated from the controller user's personal SSH identity and `~/.ssh/known_hosts`.