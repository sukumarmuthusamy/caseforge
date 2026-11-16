# Changelog

## 1.0.0-rc.1

First release candidate. The Python package version is `1.0.0rc1`; the npm version is `1.0.0-rc.1`.
The event format is `ENGINE_VERSION` 3 and the reasoning rules are `2026.11-voices`. Neither follows the
package version. See [docs/RELEASE.md](docs/RELEASE.md) for what has been tested and where.

### Included

- **Local investigations.** Several agents work a case together on one machine: a Python backend with a
  FastAPI server and SQLite storage, and a React interface served by the same process. Two bundled
  scenarios, `missing_prototype` and `quiet_substitution`. Run it from a clone; there is no hosted service.
- **Separate knowledge and beliefs.** Each agent sees only its own view of the case: what it holds, what
  it was told and what it observed. Policies receive that view and nothing else. Beliefs are revised by a
  rule-based reasoner, so the same case can end differently depending on who knows what.
- **Testimony and deception.** Agents can tell each other things that are not true. The engine checks the
  form of a statement and that the speaker knows the entities in it, never whether it is true. A listener
  weighs a speaker by the hard evidence the listener holds, not by the truth or by how many others agree.
  Baseline and deceptive policies are included; model-backed agents are opt-in.
- **Evidence provenance and graph.** Every record carries where it came from. The interface shows a
  knowledge graph of who holds which record. The solution and each private agenda stay hidden until you
  reveal them.
- **Deterministic replay and branching.** A run is an append-only event log with a SHA-256 hash chain.
  Replaying the recorded decisions reproduces every event. You can scrub back to any tick and branch from
  it.
- **Counterfactual laboratory.** A registered collection of edited cases, with predictions written before
  the runs, scored as counts with denominators. Playable challenges and reasoning-only fixtures are
  reported separately. The recorded results are in `docs/lab/collection-1/`, and the web interface can
  re-run a bounded number of seeds.
- **Compatibility handling.** A stored run continues only if the current build reproduces its events.
  Runs from another engine or scenario version are listed but not opened. Runs the current rules would not
  reproduce stay readable, verifiable and branchable from before the divergence.
- **Local API protections.** The server accepts only loopback `Host` names plus any you name with
  `--allow-host`, and refuses state-changing requests from a foreign `Origin`. This is not authentication.

### Known limitations

- Single user, no authentication, not meant to be exposed to a network.
- Tested on Windows 11 locally and on Ubuntu in GitHub Actions (Python 3.11 and 3.13, Node 22, Chrome).
  Python 3.12 was tested locally only. macOS is untested.
- The `llm` policy has only been tested against a fake client, not a real model provider.
- The laboratory is pre-registered by the same author as the reasoner. It is not an independent benchmark.
- An installed wheel does not include the interface or the recorded laboratory results.
- The interface needs a window at least 1180 px wide.
