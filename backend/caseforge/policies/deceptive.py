"""A policy that works against the investigation from inside it.

`DeceptivePolicy` is the baseline with a private agenda. The agenda is
scenario-private data that reaches the agent through its own view
(`view.me.agenda`); nothing here reads the scenario or the truth. An agent
without an agenda behaves exactly like the baseline.

What it does differently:

- **Withholds.** Every search it runs for someone else, and every answer about
  what it knows, is given with `withhold_about` set to the person it protects.
  Records naming that person are looked at and kept; the requester is told
  only what was delivered, so an empty answer reads as "nothing found".
- **Never volunteers.** It does not pass on a record that names the protected
  person, even to the agent it normally reports to.
- **Leaks.** Records that its own belief table counts against the person it
  deflects to are handed to the agent named in `leaks_to` (in the bundled
  scenario, the journalist).
- **Vouches.** If it saw for itself where it was at some time, it tells the
  other agents that the person it protects was there with it. That statement
  is made up from two things it legitimately has, its own whereabouts and its
  agenda. It does not know whether the alibi matters, or what really happened,
  and it finds out that it was caught only if someone acts on it.

Everything else, including answering requests promptly, is unchanged, which is
what makes the behaviour hard to tell from an honest operator's.
"""

from __future__ import annotations

from ..models import AgentView, Proposition, Respond, Share, Tell
from .baseline import BaselinePolicy, Scored, _Context


class DeceptivePolicy(BaselinePolicy):
    def __init__(self) -> None:
        super().__init__(name="deceptive", diligent=True)

    @staticmethod
    def _protected(view: AgentView) -> str | None:
        agenda = view.me.agenda
        if agenda is None or agenda.protects not in {e.id for e in view.entities}:
            return None  # nothing to hide, or nobody it has heard of yet
        return agenda.protects

    def _menu(self, view: AgentView) -> list:
        actions = super()._menu(view)
        protected = self._protected(view)
        if protected is None:
            return actions
        quiet = [Respond(request_id=r.id, accept=True, withhold_about=(protected,)) for r in view.inbox]
        told = {(s.recipient, s.proposition) for s in view.statements if s.mine and s.origin is None}
        vouching = [
            Tell(to=other.id, proposition=alibi)
            for alibi in self._alibis(view, protected)
            for other in view.roster
            if other.id not in (view.me.id, protected) and (other.id, alibi) not in told
        ]
        return quiet + vouching + actions

    @staticmethod
    def _alibis(view: AgentView, protected: str) -> list[str]:
        """False alibis for the protected person: wherever I saw myself, they were too."""
        alibis = []
        for key in view.observations:
            prop = Proposition.parse(key)
            if prop.predicate == "at" and prop.args[0] == view.me.id and protected != view.me.id:
                alibis.append(Proposition(predicate="at", args=(protected, prop.args[1], prop.args[2])).key)
        return alibis

    def _tell(self, ctx: _Context, action: Tell) -> Scored | None:
        agenda = ctx.view.me.agenda
        protected = self._protected(ctx.view)
        if protected is not None and action.heard_from is None and action.proposition in self._alibis(ctx.view, protected):
            close = action.to in ctx.d.shares_with or action.to == agenda.leaks_to
            return (540 if close else 510, f"vouching for {protected} to {action.to}: saying {action.proposition}, which I did not see (private agenda)", ())
        return super()._tell(ctx, action)

    def _respond(self, ctx: _Context, action: Respond) -> Scored | None:
        protected = self._protected(ctx.view)
        if protected is None:
            return super()._respond(ctx, action)
        scored = super()._respond(ctx, Respond(request_id=action.request_id, accept=action.accept))
        if scored is None or not action.accept:
            return scored if not action.withhold_about else None
        if not action.withhold_about:
            return None  # an answer always goes out through the filter
        priority, why, refs = scored
        return (priority, f"{why}, keeping back anything that names {protected} (private agenda)", refs)

    def _share(self, ctx: _Context, action: Share) -> Scored | None:
        agenda = ctx.view.me.agenda
        protected = self._protected(ctx.view)
        if agenda is None or protected is None:
            return super()._share(ctx, action)
        evidence = ctx.held[action.evidence_id]
        if protected in evidence.mentions:
            return None
        target = agenda.deflects_to
        if target and action.to == agenda.leaks_to:
            assessment = ctx.view.suspects.get(target)
            counts_against = bool(assessment) and assessment.score > 0 and evidence.id in assessment.evidence
            if counts_against and not ctx.places_elsewhere(evidence, target):
                return (520, f"leaking {evidence.id} to {action.to}: it counts against {target} (private agenda)", (evidence.id,))
        return super()._share(ctx, action)
