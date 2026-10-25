# HolidayGest - il gestionale locale per la tua casa vacanze
# Copyright (C) 2026 Fabrizio Frigau
# SPDX-License-Identifier: GPL-3.0-or-later
"""Punto di ingresso dell'eseguibile AvviaGestionale.exe."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
