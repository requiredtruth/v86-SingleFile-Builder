#!/usr/bin/env sh
set -eu
python3 -m compileall -q v86_singlefile tests
python3 -m unittest discover -s tests -v

