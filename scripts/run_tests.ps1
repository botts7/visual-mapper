$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

py -3.11 -m pip install -r backend\requirements.txt -c backend\constraints-3.11.txt
py -3.11 -m pytest tests/test_api.py tests/test_beta3_fixes.py tests/test_auth.py
