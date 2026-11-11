# Local SQLite backup and restore

Use explicit local paths for both commands:

```sh
python -m gigamind.cli.backup backup --db /path/to/source.db --output /secure/new-backup.db
python -m gigamind.cli.backup restore --db /secure/new-backup.db --output /secure/new-restored.db
```

The source is opened read-only. SQLite's online backup API produces a transactionally consistent snapshot, including database records and metadata present in that snapshot. It includes committed WAL changes. The destination must not already exist; it is created with mode 0600 (subject to a more restrictive umask). Existing files and symlinks are never overwritten. Restore checks SQLite integrity and schema version, runs the bundled migrations on the new copy, and checks schema readiness. It does not activate or replace a database; activation is a separate operator action after stopping the application and following its operational procedures.

Each successful command prints the SHA-256 of its output. Record this digest separately in a trusted location and compare it with the file before restoring; it is not embedded or automatically verified. Protect the backup, restored file, digest and their directories against unauthorized access: database records may contain confidential information and credentials. Use a private directory controlled by the operator; these commands do not defend against another process modifying files in that directory concurrently.

SQLite snapshots do not contain R2 object bytes or environment and issuer secrets. PostgreSQL and cloud object recovery are not implemented. This is not a coordinated distributed backup; separately protect and restore those dependencies. Restoring queued jobs does not execute them, but application workers may process them after activation.
