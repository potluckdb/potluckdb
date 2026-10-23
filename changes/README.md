# Change notes

Every change that users can notice adds one file here, in the same pull
request. The release collects them into the release notes and `CHANGELOG.md`.

Name the file after the change (for example `uri-sync.md`). Its first line is
the type, then a blank line, then one or two plain sentences for users:

```
type: added

Python's sqlite3 module now syncs a database opened with a bucket address.
```

| Type | Use for |
| --- | --- |
| `summary` | The one-line summary of a release (optional; otherwise the first `added` note is used) |
| `added` | Something new |
| `changed` | Different behaviour |
| `fixed` | A bug fix |
| `compatibility` | Which versions sync together, format changes, update steps |
| `known-issue` | Something that doesn't work yet |

Internal changes (tests, refactoring, CI) need no note.
