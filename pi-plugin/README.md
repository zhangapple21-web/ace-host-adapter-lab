# ACE Bridge

PI plugin registering ace_capabilities, ace_status, ace_tasks, and ace_capsule.

Reads use ace_host_adapter.py. Capsule commands use ace_capsule.py, which only calls ACE's existing worker_capsule_cli. No shell and no arbitrary pool path.

ACE validates claims, tokens, and pool face. A REFUSED result is final for that call.

The plugin is loaded from this directory as a development plugin. Saving these files hot-reloads it when PI is watching the folder.
