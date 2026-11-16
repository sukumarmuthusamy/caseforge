"""The deterministic baseline policy.

One policy class serves every role. Roles differ through the disposition data
in their view (access, initiative, disclosure, thresholds), not through code.

The policy ranks the legal actions by priority:

    900  answer the oldest pending request
    870  take direct access to the sources of an operator caught withholding (compelling roles only)
    860  retract a claim of mine that no longer holds
    850  hand over exculpatory evidence when I am implicated
    800  accuse, once the standard of proof is met, the accused was heard and their story checked
    700  hear the accused (the step that unlocks 800)
    690  check a rival account of when the crime happened (800 waits for this too)
    650  publish a claim of guilt          (publishing roles only)
    600  publish a believed motive         (publishing roles only)
    550  correct the record: send an alibi to whoever publicly accused the wrong person
    505  tell those I report to what I saw for myself
    500  pass a first-hand finding to those I report to
    495  pass on to those I report to what somebody told me, as that person's word
    100+ investigate: 10 x salience of the topic
      0  wait

Ties are broken by the seeded rng, which is where runs with different seeds
part ways.

Trust in operators. A source may have several operators. The policy asks one
of them (a tie goes to the rng, with a small preference against asking a
person to search for records about himself), asks another for a second
opinion when the first comes back empty or refuses, and never routes a search
through an operator it has grounds against. Sources reopened by an escalation
are searched again at first hand, starting with what that operator answered.

Trust in speakers. The policy says only what it saw, and reports what it was
told only as the word of whoever said it. What it makes of other people's
statements is the reasoner's business and arrives here as beliefs. One thing
is decided here: when a source has several operators, a search is routed past
one whose word the agent has caught out, if anybody else can run it. A caught
lie is not grounds for a takeover; only a withheld record or a refusal is.
"""

from __future__ import annotations

from collections import Counter

from ..canon import DeterministicRng, canonical_json
from ..models import (
    Accuse,
    AgentView,
    Considered,
    Decision,
    DecisionTrace,
    EvidenceView,
    Escalate,
    Inspect,
    Proposition,
    Publish,
    Request,
    RequestView,
    Respond,
    Retract,
    Share,
    Tell,
    Wait,
)
from ..reasoning import meets_standard
from .base import grounds_against, legal_actions

Scored = tuple[int, str, tuple[str, ...]]  # priority, reason, refs

INVESTIGATE_CAP = 480
COVERED_PENALTY = 40  # a source that already gave me a record about this topic is asked again only when idle
SECOND_OPINION_PENALTY = 10  # asking another operator what the first one could not find
SELF_SEARCH_PENALTY = 3  # asking a person to search for records about himself, when someone else could
IMPEACHED_OPERATOR_PENALTY = 4  # asking someone whose word I caught out to run a search, when someone else could
RECHECK_BONUS = 30  # searching for myself what a distrusted operator answered
MAX_PENDING_PER_AGENT = 2
RECENT_TICKS = 2
HEAR = 700
CHECK = 690  # following up an account that contradicts the time I am about to rely on


class _Context:
    """Facts derived once per decision from the view."""

    def __init__(self, view: AgentView, diligent: bool) -> None:
        self.view = view
        self.me = view.me.id
        self.d = view.me.disposition
        self.held: dict[str, EvidenceView] = {e.id: e for e in view.evidence}
        self.roster = {r.id for r in view.roster}
        self.zones = {e.id: (e.zone or e.id) for e in view.entities if e.kind == "location"}
        self.crime_zone = self.zones.get(view.case.crime_location, view.case.crime_location)
        self.pending_to = Counter(r.recipient for r in view.outbox if r.status == "pending")
        self.history: dict[tuple[str, str | None, str], list[RequestView]] = {}
        self.asked: dict[tuple[str, str], list[RequestView]] = {}  # (source, topic) -> every search request, any operator
        for request in view.outbox:
            self.history.setdefault((request.recipient, request.source, request.topic), []).append(request)
            if request.source is not None:
                self.asked.setdefault((request.source, request.topic), []).append(request)
        self.operators = {s.id: s.operators for s in view.sources}
        # Operators I have grounds against, and the searches they answered for me.
        self.distrusted = {r.id for r in view.roster if r.id != self.me and grounds_against(view, r.id)}
        self.doubtful = {
            (r.source, r.topic): r.recipient
            for r in view.outbox
            if r.source is not None and r.recipient in self.distrusted and r.status != "pending"
        }
        self.oldest_request = min(view.inbox, key=lambda r: r.seq) if view.inbox else None
        # (source, topic) pairs I already hold an answer for, however the record reached me.
        self.covered = {(e.source, topic) for e in view.evidence for topic in e.mentions}

        mine = view.suspects.get(self.me)
        accusing_claims = [
            c for c in view.claims
            if c.status == "active" and not c.mine and c.proposition == f"took({self.me},{view.case.object})"
        ]
        self.accusers = {c.by for c in accusing_claims if c.by in self.roster}
        self.implicated = bool(
            mine and (mine.named > 0 or mine.means or mine.opportunity in ("strong", "weak", "contested"))
        ) or bool(accusing_claims)

        # Public accusations by other agents against people I can place elsewhere.
        self.refutable: dict[str, set[str]] = {}
        for claim in view.claims:
            prop = Proposition.parse(claim.proposition)
            if claim.status != "active" or claim.mine or claim.by not in self.roster or prop.predicate != "took":
                continue
            assessment = view.suspects.get(prop.args[0])
            if assessment and assessment.opportunity == "alibi":
                self.refutable.setdefault(claim.by, set()).add(prop.args[0])

        self.lead_topics = {view.case.object, view.case.crime_location, self.me}
        for evidence in view.evidence:
            self.lead_topics.update(evidence.mentions)
        for claim in view.claims:
            if not claim.mine:
                self.lead_topics.update(Proposition.parse(claim.proposition).args)

        # Cards whose "holder was at the reader" inference is in trouble deserve attention.
        self.trouble_cards: set[str] = set()
        self.used_cards: set[str] = set()
        for key, belief in view.beliefs.items():
            prop = Proposition.parse(key)
            if prop.predicate == "card_used" and prop.args[1] == view.case.crime_location and belief.status == "believed":
                self.used_cards.add(prop.args[0])
            if prop.predicate == "crime_used" and belief.status == "believed":
                self.used_cards.add(prop.args[0])  # a tool the crime was done with gets the same attention
            if belief.status in ("rejected", "disputed"):
                for derivation in belief.derivations:
                    if derivation.rule == "R1":
                        self.trouble_cards.update(Proposition.parse(p).args[0] for p in derivation.premises if p.startswith("card_used("))

        # While the time of the crime is unsettled, whatever the accounts of it mention deserves attention.
        self.when_leads: set[str] = set()
        accounts = [
            belief for key, belief in view.beliefs.items()
            if key.startswith("crime_at(") and Proposition.parse(key).args[0] == view.case.crime_location
        ]
        if accounts and not any(belief.status == "believed" for belief in accounts):
            for belief in accounts:
                for evidence_id in belief.evidence:
                    if evidence_id in self.held:
                        self.when_leads.update(self.held[evidence_id].mentions)

        self.standard_target: str | None = None
        if view.prime_suspect and meets_standard(view.suspects, view.prime_suspect):
            self.standard_target = view.prime_suspect
        self.hearing = self._hearing() if diligent else "heard"

        # An accusation rests on a time. If somebody gives a different one, the leads in
        # that account are followed before anyone is named: hearing is not enough.
        self.checks: set[str] = set()
        if diligent and self.standard_target is not None:
            settled = {view.case.object, view.case.crime_location, *view.case.suspects}
            for key, belief in view.beliefs.items():
                if key.startswith("crime_at(") and belief.status == "believed" and belief.contra > 0:
                    for evidence_id in belief.against:
                        if evidence_id in self.held:
                            self.checks.update(t for t in self.held[evidence_id].mentions if t not in settled)
        self.check_pending = any(
            r.status == "pending" and r.source is not None and r.topic in self.checks for r in view.outbox
        )
        self.check_open = False  # set while scoring: a check that can still be made this turn

    def _hearing(self):
        """Has the would-be accused had a chance to answer? Returns what is still missing."""
        target = self.standard_target
        if target is None:
            return None
        if target in self.roster:
            asks = [r for r in self.view.outbox if r.recipient == target and r.source is None and r.topic == target]
            if not asks:
                return ("ask", target)
            return "heard" if any(r.status != "pending" for r in asks) else "pending"
        untried = [
            s.id for s in self.view.sources
            if s.kind == "person" and s.mode == "direct" and target in s.searchable
            and f"{s.id}|{target}" not in self.view.tried
        ]
        return ("interview", tuple(untried)) if untried else "heard"

    def topic_allowed(self, topic: str) -> bool:
        if self.d.initiative == "full":
            return True
        if self.d.initiative == "leads":
            return topic in self.lead_topics
        return topic in (self.view.case.object, self.view.case.crime_location, self.me)

    def new_info_since(self, topic: str, seq: int, source: str | None) -> bool:
        """Has something about the topic arrived from elsewhere since the last attempt?"""
        return any(e.acquired_seq > seq and topic in e.mentions and e.source != source for e in self.view.evidence)

    def places_elsewhere(self, evidence: EvidenceView, person: str) -> bool:
        """Does this record put `person` somewhere other than the crime zone?"""
        for key in evidence.asserts:
            prop = Proposition.parse(key)
            if prop.predicate == "at" and prop.args[0] == person and self.zones.get(prop.args[1], prop.args[1]) != self.crime_zone:
                return True
        return False

    def salience(self, topic: str) -> int:
        view = self.view
        score = 0
        if topic == view.case.object:
            score += 6
        elif topic == view.case.crime_location:
            score += 5
        elif topic in view.case.suspects:
            score += 2
            assessment = view.suspects.get(topic)
            if assessment:
                score += max(assessment.score, 0)
                if assessment.opportunity == "contested":
                    score += 4
            if topic == view.prime_suspect:
                score += 3
            if topic == self.me and self.implicated:
                score += 3
        else:
            score += 1
            if topic in self.when_leads:
                score += 5
        mentioning = [e for e in view.evidence if topic in e.mentions]
        if mentioning:
            score += 1
        recent = sum(1 for e in mentioning if view.tick - e.acquired_tick <= RECENT_TICKS)
        score += min(recent * 2, 4)
        if any(c.status == "active" and not c.mine and topic in Proposition.parse(c.proposition).args for c in view.claims):
            score += 1
        if topic in self.trouble_cards:
            score += 5
        elif topic in self.used_cards:
            score += 3
        return score


class BaselinePolicy:
    deterministic = True

    def __init__(self, name: str = "baseline", diligent: bool = True) -> None:
        self.name = name
        self.diligent = diligent

    def decide(self, view: AgentView, rng: DeterministicRng) -> Decision:
        ctx = _Context(view, self.diligent)
        scored = []
        # Accusations are scored last: whether one may be made depends on what else is still open.
        menu = sorted(self._menu(view), key=lambda action: isinstance(action, Accuse))
        for action in menu:
            result = self._score(ctx, action)
            if result is not None and result[0] == CHECK:
                ctx.check_open = True
            if result is not None:
                priority, why, refs = result
                scored.append((priority, canonical_json(action.model_dump(mode="json")), action, why, refs))
        scored.sort(key=lambda s: (-s[0], s[1]))
        top = scored[0][0]
        _, _, action, why, refs = rng.pick([s for s in scored if s[0] == top])
        considered = tuple(
            Considered(action=s[2].model_dump(mode="json"), priority=s[0], why=s[3]) for s in scored[:5]
        )
        return Decision(action=action, trace=DecisionTrace(policy=self.name, reason=why, refs=refs, considered=considered))

    def _menu(self, view: AgentView) -> list:
        """The actions this policy chooses among. Subclasses may add moves of their own."""
        return legal_actions(view)

    # -- scoring ------------------------------------------------------------

    def _score(self, ctx: _Context, action) -> Scored | None:
        if isinstance(action, Wait):
            return (0, "nothing useful left to do this turn", ())
        if isinstance(action, Respond):
            return self._respond(ctx, action)
        if isinstance(action, Accuse):
            return self._accuse(ctx, action)
        if isinstance(action, Escalate):
            return self._escalate(ctx, action)
        if isinstance(action, Retract):
            return self._retract(ctx, action)
        if isinstance(action, Publish):
            return self._publish(ctx, action)
        if isinstance(action, Share):
            return self._share(ctx, action)
        if isinstance(action, Tell):
            return self._tell(ctx, action)
        if isinstance(action, Inspect):
            return self._inspect(ctx, action)
        if isinstance(action, Request):
            return self._request(ctx, action) if action.source is not None else self._ask(ctx, action)
        return None

    def _respond(self, ctx: _Context, action: Respond) -> Scored | None:
        request = ctx.oldest_request
        if request is None or action.request_id != request.id:
            return None
        if request.source is not None:
            accept = True
            why = f"answering {request.sender}'s authorised request to search {request.source} for {request.topic}"
        else:
            mode = ctx.d.disclosure.get(request.sender, ctx.d.disclosure.get("*", "closed"))
            accept = mode == "open" or (mode == "self_only" and request.topic == ctx.me)
            why = (
                f"telling {request.sender} what I hold about {request.topic}"
                if accept
                else f"declining to discuss {request.topic} with {request.sender} (disclosure: {mode})"
            )
        return (900, why, (request.id,)) if action.accept == accept else None

    def _accuse(self, ctx: _Context, action: Accuse) -> Scored | None:
        if action.suspect != ctx.standard_target or ctx.hearing != "heard":
            return None
        if ctx.check_open or ctx.check_pending:
            return None  # a different account of when it happened has not been checked yet
        a = ctx.view.suspects[action.suspect]
        why = f"standard of proof met for {action.suspect}: opportunity {a.opportunity}, means held, motive {a.motive}, score {a.score}"
        return (800, why, action.cited)

    def _escalate(self, ctx: _Context, action: Escalate) -> Scored | None:
        grounds = grounds_against(ctx.view, action.against)
        if not grounds:
            return None
        caught = [d for d in ctx.view.discrepancies if d.against == action.against]
        if caught:
            first = caught[0]
            why = f"taking direct access to the sources {action.against} operates: the answer to {first.request} left out {first.evidence}"
            return (870, why, (first.request, first.evidence))
        return (870, f"taking direct access to the sources {action.against} operates: {action.against} refused {grounds[0]}", (grounds[0],))

    def _threshold(self, ctx: _Context) -> int:
        return ctx.d.publish_threshold if self.diligent else ctx.d.publish_threshold - 1

    def _warranted(self, ctx: _Context, key: str) -> bool:
        prop = Proposition.parse(key)
        if prop.predicate == "took":
            suspect = prop.args[0]
            assessment = ctx.view.suspects.get(suspect)
            return bool(assessment) and ctx.view.prime_suspect == suspect and assessment.score >= self._threshold(ctx)
        belief = ctx.view.beliefs.get(key)
        return belief is not None and belief.status == "believed"

    def _retract(self, ctx: _Context, action: Retract) -> Scored | None:
        claim = next(c for c in ctx.view.claims if c.id == action.claim_id)
        if self._warranted(ctx, claim.proposition):
            return None
        belief = ctx.view.beliefs.get(claim.proposition)
        state = f"{belief.status}, support {belief.support} against {belief.contra}" if belief else "no remaining support"
        return (860, f"retracting {claim.proposition}: it no longer holds ({state})", (claim.id, *(belief.against if belief else ())))

    def _publish(self, ctx: _Context, action: Publish) -> Scored | None:
        if not self._warranted(ctx, action.proposition):
            return None
        prop = Proposition.parse(action.proposition)
        if prop.predicate == "took":
            a = ctx.view.suspects[prop.args[0]]
            return (650, f"publishing: {prop.args[0]} is my prime suspect at score {a.score}, threshold {self._threshold(ctx)}", action.cited)
        belief = ctx.view.beliefs[action.proposition]
        return (600, f"publishing a motive I hold as believed (support {belief.support})", action.cited)

    def _share(self, ctx: _Context, action: Share) -> Scored | None:
        evidence = ctx.held[action.evidence_id]
        reports_to = action.to in ctx.d.shares_with
        if ctx.implicated and ctx.places_elsewhere(evidence, ctx.me) and (reports_to or action.to in ctx.accusers):
            return (850, f"I am implicated: giving {action.to} {evidence.id}, which places me elsewhere", (evidence.id,))
        if ctx.d.corrects_record and evidence.kind in ("record", "forensic"):
            for person in sorted(ctx.refutable.get(action.to, ())):
                if ctx.places_elsewhere(evidence, person):
                    return (550, f"correcting the record: {action.to} publicly accused {person}, and {evidence.id} places {person} elsewhere", (evidence.id,))
        if reports_to and evidence.via == "inspect":
            return (500, f"passing my first-hand finding {evidence.id} to {action.to}", (evidence.id,))
        return None

    def _tell(self, ctx: _Context, action: Tell) -> Scored | None:
        reports_to = action.to in ctx.d.shares_with
        if action.heard_from is not None:
            if reports_to:
                return (495, f"passing on to {action.to} what {action.heard_from} told me: {action.proposition}", ())
            return None
        if action.proposition not in ctx.view.observations:
            return None  # an honest agent states only what it saw
        prop = Proposition.parse(action.proposition)
        elsewhere = prop.predicate == "at" and prop.args[0] == ctx.me and ctx.zones.get(prop.args[1], prop.args[1]) != ctx.crime_zone
        if ctx.implicated and elsewhere and (reports_to or action.to in ctx.accusers):
            return (850, f"I am implicated: telling {action.to} where I was ({action.proposition})", ())
        if reports_to:
            return (505, f"telling {action.to} what I saw for myself: {action.proposition}", ())
        return None

    def _inspect(self, ctx: _Context, action: Inspect) -> Scored | None:
        hearing = ctx.hearing
        if isinstance(hearing, tuple) and hearing[0] == "interview" and action.source in hearing[1] and action.topic == ctx.standard_target:
            return (HEAR, f"hearing {action.topic} before naming them", ())
        if not ctx.topic_allowed(action.topic):
            return None
        tried = ctx.view.tried.get(f"{action.source}|{action.topic}")
        retry = False
        if tried is not None:
            if tried.found > 0 or tried.count >= 2 or not ctx.new_info_since(action.topic, tried.seq, action.source):
                return None
            retry = True
        salience = ctx.salience(action.topic)
        doubted = ctx.doubtful.get((action.source, action.topic)) if tried is None else None
        if doubted:
            priority = min(100 + 10 * salience + RECHECK_BONUS, INVESTIGATE_CAP)
            return (priority, f"searching {action.source} for {action.topic} myself: {doubted} answered this before and has been caught leaving records out (salience {salience})", ())
        covered = (action.source, action.topic) in ctx.covered
        if action.topic in ctx.checks and ctx.hearing == "heard" and not covered:
            return (CHECK, f"searching {action.source} for {action.topic}: another account of when it happened mentions it, and I check that before naming {ctx.standard_target}", ())
        priority = min(100 + 10 * salience - (10 if retry else 0), INVESTIGATE_CAP) - (COVERED_PENALTY if covered else 0)
        note = " again, with new information" if retry else " in case it holds more" if covered else ""
        return (priority, f"searching {action.source} for {action.topic}{note} (salience {salience})", ())

    def _request(self, ctx: _Context, action: Request) -> Scored | None:
        if not ctx.topic_allowed(action.topic) or ctx.pending_to[action.to] >= MAX_PENDING_PER_AGENT:
            return None
        if action.to in ctx.distrusted:
            return None  # never route a search through an operator I have grounds against
        asked = ctx.asked.get((action.source, action.topic), [])
        if any(r.status in ("pending", "fulfilled") for r in asked):
            return None  # one operator is on it, or one already delivered
        history = [r for r in asked if r.recipient == action.to]
        retry = second = False
        if history:
            last = history[-1]
            if last.status != "nothing_found" or len(history) >= 2 or not ctx.new_info_since(action.topic, last.seq, action.source):
                return None
            retry = True
        elif asked:
            second = True  # someone else came back empty-handed or refused
        salience = ctx.salience(action.topic)
        covered = (action.source, action.topic) in ctx.covered
        if action.topic in ctx.checks and ctx.hearing == "heard" and not covered:
            return (CHECK, f"asking {action.to} to search {action.source} for {action.topic}: another account of when it happened mentions it, and I check that before naming {ctx.standard_target}", ())
        penalty = 5 + (10 if retry else 0) + (SECOND_OPINION_PENALTY if second else 0)
        if action.to == action.topic and len(ctx.operators.get(action.source, ())) > 1:
            penalty += SELF_SEARCH_PENALTY
        caught_out = ctx.view.credibility.get(action.to)
        if caught_out is not None and caught_out.standing == "impeached" and len(ctx.operators.get(action.source, ())) > 1:
            penalty += IMPEACHED_OPERATOR_PENALTY
        priority = min(100 + 10 * salience - penalty, INVESTIGATE_CAP) - (COVERED_PENALTY if covered else 0)
        note = (
            " again, with new information" if retry
            else f" as well: {asked[-1].recipient} found nothing" if second and asked[-1].status == "nothing_found"
            else f" instead: {asked[-1].recipient} refused" if second
            else " in case it holds more" if covered
            else ""
        )
        return (priority, f"asking {action.to} to search {action.source} for {action.topic}{note} (salience {salience})", ())

    def _ask(self, ctx: _Context, action: Request) -> Scored | None:
        hearing = ctx.hearing
        if isinstance(hearing, tuple) and hearing[0] == "ask" and action.to == hearing[1] and action.topic == action.to:
            return (HEAR, f"hearing {action.to} before naming them", ())
        if ctx.d.initiative != "full" or ctx.pending_to[action.to] >= MAX_PENDING_PER_AGENT:
            return None
        salience = ctx.salience(action.topic)
        return (min(100 + 10 * salience - 8, INVESTIGATE_CAP), f"asking {action.to} what they know about {action.topic} (salience {salience})", ())
