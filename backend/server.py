"""
Compatibility shim for legacy imports.

Historically, tests and routes imported `server` as the FastAPI entrypoint.
The refactor moved the entrypoint to `main.py`, so this module forwards
attribute access/assignment to `main` to keep older imports working.
"""
from __future__ import annotations

import sys
import types

import main as _main


class _ServerModule(types.ModuleType):
    def __getattr__(self, name: str):
        return getattr(_main, name)

    def __setattr__(self, name: str, value):
        setattr(_main, name, value)
        return super().__setattr__(name, value)


_module = sys.modules[__name__]
_module.__class__ = _ServerModule
