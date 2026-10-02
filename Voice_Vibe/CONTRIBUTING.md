# Developing Voice Vibe

Fork the repository and clone the branch you intend to develop. Work from the
repository root; do not depend on the original developer's sibling folders.
Windows 10/11 and Python 3.11 are the recommended development environment.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Profile hub
```

Installation is editable: source changes take effect without reinstalling.
Add `-Profile assistant`, `-Cuda`, `-Bot` or `-Overlay` when working on those
components. Stop and restart the affected app or hub after a change.

## Verification

Run the existing suite from `tests` so its sibling test helpers are importable:

```powershell
Push-Location tests
..\.venv\Scripts\python.exe -m unittest discover -s .
Pop-Location
git diff --check
```

Tests must fake windows, keyboard input, network and accounts. They must not
post messages, click real UI or mutate real accounts. Overlay tests may skip
without PySide6; install the overlay extra to exercise them. Integration setup
still requires manual verification on your hardware and accounts.

Keep dependencies in `pyproject.toml`; requirements files select extras.
Retain upstream license notices and record copied code provenance in
`THIRD_PARTY.lock`. The Telegram subtree has its own GPL-2.0-only license;
the repository currently has no overall license chosen by its owner.

## Sending changes

```powershell
git switch -c my-change
# Edit, run tests, then stage the specific changed files.
git add <files>
git commit -m "Describe the change"
git push -u origin my-change
```

Open a pull request to the intended upstream branch. Exclude environments,
model weights, recordings, credentials, account state and generated builds.
Documentation in `docs/history` describes the original workspace; its old
remote instructions and workstream assignments do not apply to your fork.
