#!/bin/bash
cd "$(dirname "$0")"
source venv_pe4/Scripts/activate
PYTHONPATH=$(pwd) python dashboard/app.py
