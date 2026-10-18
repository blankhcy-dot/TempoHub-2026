# Third-party notices

This repository does not contain EDIFIER TempoHub, its `_internal` resources,
or any EDIFIER binary. The installer reads the user's own installed copy and
creates a private patched copy under `%LOCALAPPDATA%`.

- Python 3.9 embeddable runtime: Python Software Foundation License.
- PyInstaller: GPL with a special exception for bootloader use.
- Qt / PyQt6: used from the user's existing EDIFIER TempoHub installation.
  PyQt6 is GPL/commercial software; this project does not redistribute PyQt6.
- NetEase Cloud Music: lyrics are queried through its public web endpoint.
  This project is not affiliated with NetEase.

The patched application still uses the user's licensed EDIFIER TempoHub
installation. If you build and redistribute a combined binary, review the
licenses of every included component, especially PyQt6.
