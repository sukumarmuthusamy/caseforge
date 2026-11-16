"""Puts one run into the browser tests' database that this build may read but not continue.

It is played for real while the reasoner weighs a suspect's own word differently, stamped as
the older behaviour, and stored. The tests then see what a person sees after a rules change.
"""
import sys

from caseforge import compat, reasoning
from caseforge.service import RunService
from caseforge.store import Store

reasoning.SELF_SERVING_TESTIMONY_WEIGHT = 2
compat.RULES_VERSION = "2026.11-older"
compat._FINGERPRINT = "older-behaviour0"
service = RunService(Store(sys.argv[1]))
run = service.create_run("quiet_substitution", 7, {"ibarra": "deceptive"}, label="e2e read-only older rules")
service.step(run["id"], 14)
