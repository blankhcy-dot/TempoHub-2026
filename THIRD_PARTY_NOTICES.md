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
- Intel PresentMon 2.6.0 is used optionally for frame-rate capture. It is
  distributed under the MIT license:

  Copyright (C) 2017-2024 Intel Corporation

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to
  deal in the Software without restriction, including without limitation the
  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
  sell copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
  IN THE SOFTWARE.
- SoundCard 0.4.6 is used for WASAPI system-output loopback capture under the
  BSD 3-Clause license:

  Copyright (c) 2016 Bastian Bechtold
  All rights reserved.

  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the conditions in the complete
  license distributed at `vendor/soundcard-0.4.6.dist-info/licenses/LICENSE`
  are met. The software is provided "AS IS", without warranty of any kind.

The patched application still uses the user's licensed EDIFIER TempoHub
installation. If you build and redistribute a combined binary, review the
licenses of every included component, especially PyQt6.
