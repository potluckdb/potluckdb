type: known-issue

A synced database takes changes from one device at a time for now; several writing devices come in 0.8.3. When two devices write at the same time, one device's changes are not merged: they are kept in a copy next to its database (`app.db.conflict-<time>.db`).
