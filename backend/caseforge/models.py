"""Typed contracts: scenario, propositions, beliefs, actions, events, agent views.

These models are the vocabulary shared by every other module. They contain no
behaviour beyond validation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bumped whenever the reducer reads an existing event type differently. A stored
# run records the version it was made with, and other versions refuse to load it.
#   2: the reducer keeps provenance stamps for beliefs, derivations, contradictions
#      and the prime suspect (BeliefsRevised, ContradictionRecognized).
#   3: spoken statements and speaker credibility. The reducer reads no old event
#      differently, but the engine now records StatementWeighed and
#      CredibilityRevised after a revision, and the reasoner discounts a speaker
#      who was caught out, so a version 2 log could not be re-simulated.
ENGINE_VERSION = "3"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------
# Propositions
# --------------------------------------------------------------------------

# predicate -> expected argument kinds. This is the whole ontology of facts.
PREDICATES: dict[str, tuple[str, ...]] = {
    "at": ("person", "location", "slot"),
    "crime_at": ("location", "slot"),
    "card_used": ("card", "location", "slot"),
    "card_holder": ("card", "person"),
    "card_cloned": ("card",),
    "card_written": ("card", "location", "slot"),
    "has_motive": ("person",),
    "took": ("person", "object"),
    "could_use": ("person", "card"),
    "crime_used": ("tool",),  # the crime was done with this thing
    "had": ("person", "tool", "slot"),  # custody of a tool during a time slot
}

# Predicates an agent may assert in a public claim.
PUBLISHABLE_PREDICATES = ("has_motive", "took")

# Predicates an agent may assert in a spoken statement (`Tell`). Both have a
# natural opposite (another place, another time), so a listener can come to
# hold evidence against what was said.
TELLABLE_PREDICATES = ("at", "crime_at")


class Proposition(Frozen):
    """A structured factual statement, e.g. at(whitlock, lab3, oct14_2145)."""

    predicate: str
    args: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, data: Any) -> Any:
        if isinstance(data, str):
            name, sep, rest = data.partition("(")
            if not sep or not rest.endswith(")"):
                raise ValueError(f"malformed proposition: {data!r}")
            inner = rest[:-1].strip()
            args = tuple(part.strip() for part in inner.split(",")) if inner else ()
            return {"predicate": name.strip(), "args": args}
        return data

    @model_validator(mode="after")
    def _check_arity(self) -> "Proposition":
        signature = PREDICATES.get(self.predicate)
        if signature is None:
            raise ValueError(f"unknown predicate: {self.predicate!r}")
        if len(self.args) != len(signature):
            raise ValueError(f"{self.predicate} expects {len(signature)} arguments, got {len(self.args)}")
        if any(not arg for arg in self.args):
            raise ValueError("empty proposition argument")
        return self

    @property
    def key(self) -> str:
        return f"{self.predicate}({','.join(self.args)})"

    @classmethod
    def parse(cls, key: str) -> "Proposition":
        return cls.model_validate(key)


# --------------------------------------------------------------------------
# Scenario
# --------------------------------------------------------------------------

EntityKind = Literal["person", "location", "object", "card", "tool"]
EvidenceKind = Literal["forensic", "record", "testimony", "hearsay"]
DisclosureMode = Literal["open", "self_only", "closed"]


class Entity(Frozen):
    id: str
    kind: EntityKind
    name: str
    description: str = ""
    zone: str | None = None  # locations only; places in different zones are mutually exclusive


class TimeSlot(Frozen):
    id: str
    label: str


class Disposition(Frozen):
    """How an agent weighs and acts. Data, not code: roles differ only here."""

    hearsay_weight: int = 1
    can_accuse: bool = False
    can_publish: bool = False
    publish_threshold: int = 3
    initiative: Literal["full", "leads", "reactive"] = "leads"
    shares_with: tuple[str, ...] = ()
    corrects_record: bool = False  # hands exonerating evidence to whoever publicly accused the wrong person
    can_compel: bool = False  # may take direct access to an operator's sources once that operator gave grounds
    disclosure: dict[str, DisclosureMode] = Field(default_factory=dict)  # agent id or "*"


class Agenda(Frozen):
    """A private commitment that works against the investigation.

    Scenario-private: it reaches exactly one agent, through that agent's own
    view, and only a policy that chooses to act on it (`deceptive`) does so.
    """

    protects: str  # person the agent keeps out of the record
    deflects_to: str | None = None  # person the agent steers suspicion towards
    leaks_to: str | None = None  # agent who is fed the records that do the steering
    note: str = ""  # why; shown to the observer only once the solution is revealed


class AgentSpec(Frozen):
    id: str  # must also be a person entity
    role: str
    goals: tuple[str, ...]
    disposition: Disposition


class SourceSpec(Frozen):
    """A place evidence can be found: a log system, a scene, a person to interview."""

    id: str
    name: str
    description: str = ""
    kind: Literal["system", "physical", "forensic", "person", "external"]
    operators: tuple[str, ...]  # agents able to run a query
    self_serve: bool = True  # operators may query on their own initiative
    requesters: tuple[str, ...] = ()  # agents who may ask an operator to query for them
    searchable: tuple[str, ...]  # entity ids the source can be queried about


class EvidenceSpec(Frozen):
    id: str  # opaque on purpose: ids must not describe content
    title: str
    text: str
    kind: EvidenceKind
    speaker: str | None = None
    source: str
    mentions: tuple[str, ...]  # entities named: both the query keys and the leads it yields
    asserts: tuple[Proposition, ...]
    requires: tuple[str, ...] = ()  # evidence the querying side must already hold
    shareable: bool = True


class InterventionSpec(Frozen):
    id: str
    label: str
    description: str
    kind: Literal["release_evidence", "spread_rumor", "grant_access"]
    evidence: str | None = None
    recipients: tuple[str, ...] = ()
    proposition: Proposition | None = None
    text: str | None = None
    agent: str | None = None
    source: str | None = None


class CaseInfo(Frozen):
    title: str
    briefing: str
    object: str
    crime_location: str
    suspects: tuple[str, ...]
    max_ticks: int


class Truth(Frozen):
    """What actually happened. Read only by evaluation and the scenario lint."""

    culprit: str
    solution: str
    facts: tuple[Proposition, ...]
    key_evidence: tuple[str, ...]
    key_facts: tuple[Proposition, ...]


class ScenarioPublic(Frozen):
    id: str
    version: str
    case: CaseInfo
    entities: tuple[Entity, ...]
    slots: tuple[TimeSlot, ...]
    agents: tuple[AgentSpec, ...]
    sources: tuple[SourceSpec, ...]
    interventions: tuple[InterventionSpec, ...] = ()


class ScenarioPrivate(Frozen):
    hidden_entities: tuple[Entity, ...] = ()  # revealed only when evidence mentions them
    evidence: tuple[EvidenceSpec, ...]
    initial_holdings: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    agendas: dict[str, Agenda] = Field(default_factory=dict)  # agent id -> what it would hide
    # agent id -> what it saw for itself. Each agent gets its own and nobody else's.
    observations: dict[str, tuple[Proposition, ...]] = Field(default_factory=dict)
    truth: Truth


# --------------------------------------------------------------------------
# Beliefs
# --------------------------------------------------------------------------

BeliefStatus = Literal["believed", "tentative", "disputed", "rejected", "withdrawn"]


class Derivation(Frozen):
    rule: str
    premises: tuple[str, ...]
    active: bool = True
    defeated_by: str | None = None


class BeliefEntry(Frozen):
    support: int
    contra: int
    status: BeliefStatus
    evidence: tuple[str, ...] = ()  # ids of items backing the proposition
    against: tuple[str, ...] = ()  # ids of items backing conflicting propositions
    derivations: tuple[Derivation, ...] = ()


class SuspectAssessment(Frozen):
    score: int
    opportunity: Literal["strong", "weak", "none", "contested", "alibi"]
    means: bool
    motive: Literal["strong", "weak", "none"]
    named: int  # weight of direct allegations, capped
    evidence: tuple[str, ...] = ()


Standing = Literal["corroborated", "impeached"]
Stance = Literal["accepted", "questioned", "rejected"]
Grounds = Literal["observed", "held", "heard", "none"]


class Credibility(Frozen):
    """What one listener has been able to check of one speaker's word.

    `refuted` and `corroborated` are judgments of single claims. `standing` is
    the judgment of the speaker that follows from them: impeached as soon as
    one claim is refuted, corroborated when some were checked and none failed.
    A speaker nothing is known about has no entry at all.
    """

    standing: Standing
    refuted: tuple[str, ...] = ()  # proposition keys the listener holds hard evidence against
    corroborated: tuple[str, ...] = ()  # proposition keys the listener holds hard evidence for


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


class Inspect(Frozen):
    type: Literal["inspect"] = "inspect"
    source: str
    topic: str


class Request(Frozen):
    """Ask another agent: run a query for me (source given) or tell me what you know (no source)."""

    type: Literal["request"] = "request"
    to: str
    topic: str
    source: str | None = None


class Respond(Frozen):
    type: Literal["respond"] = "respond"
    request_id: str
    accept: bool
    # Entities the responder keeps quiet about: records naming any of them are
    # looked at but not handed over, and the answer does not say so.
    withhold_about: tuple[str, ...] = ()


class Share(Frozen):
    type: Literal["share"] = "share"
    to: str
    evidence_id: str


class Publish(Frozen):
    type: Literal["publish"] = "publish"
    proposition: str
    cited: tuple[str, ...] = ()


class Retract(Frozen):
    type: Literal["retract"] = "retract"
    claim_id: str


class Accuse(Frozen):
    type: Literal["accuse"] = "accuse"
    suspect: str
    cited: tuple[str, ...] = ()


class Escalate(Frozen):
    """Take direct access to every source an operator runs. Needs grounds against that operator."""

    type: Literal["escalate"] = "escalate"
    against: str


class Tell(Frozen):
    """Say something to one other agent, on one's own word.

    The engine checks that the statement is well formed and names only things
    the speaker knows of. It never checks that it is true. With `heard_from`
    it is a report of what that person said, and the speaker must have heard it.
    """

    type: Literal["tell"] = "tell"
    to: str
    proposition: str
    heard_from: str | None = None


class Wait(Frozen):
    type: Literal["wait"] = "wait"


Action = Annotated[
    Union[Inspect, Request, Respond, Share, Publish, Retract, Accuse, Escalate, Tell, Wait],
    Field(discriminator="type"),
]


class Considered(Frozen):
    action: dict[str, Any]
    priority: int
    why: str


class DecisionTrace(Frozen):
    """A factual record of how an action was chosen. Not a chain of thought."""

    policy: str
    reason: str
    refs: tuple[str, ...] = ()  # evidence / claim / request ids the choice rested on
    considered: tuple[Considered, ...] = ()
    llm: dict[str, Any] | None = None


class Decision(Frozen):
    action: Action
    trace: DecisionTrace


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


class Event(Frozen):
    seq: int
    tick: int
    type: str
    actor: str  # agent id, "engine" or "user"
    cause: int | None = None  # seq of the event that led to this one
    data: dict[str, Any]
    hash: str

    def body(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "type": self.type,
            "actor": self.actor,
            "cause": self.cause,
            "data": self.data,
        }


class RunStartedData(Frozen):
    scenario_id: str
    scenario_version: str
    scenario_hash: str
    engine_version: str
    seed: int
    agents: tuple[str, ...]
    policies: dict[str, str]
    max_ticks: int


class TickStartedData(Frozen):
    order: tuple[str, ...]


class ActionTakenData(Frozen):
    agent: str
    action: dict[str, Any]
    trace: dict[str, Any]


class ActionRejectedData(Frozen):
    agent: str
    action: dict[str, Any]
    trace: dict[str, Any]
    code: str
    message: str


class SourceInspectedData(Frozen):
    agent: str
    source: str
    topic: str
    found: tuple[str, ...]
    new: tuple[str, ...]
    on_behalf_of: str | None = None


class EvidenceObservedData(Frozen):
    agent: str
    evidence: str
    source: str
    via: Literal["initial", "inspect"]


class EvidenceSharedData(Frozen):
    sender: str
    recipient: str
    evidence: str
    context: str  # "proactive" or "request:<id>"


class EvidenceReleasedData(Frozen):
    evidence: str
    recipient: str
    intervention: str


class RequestSentData(Frozen):
    request: str
    sender: str
    recipient: str
    topic: str
    source: str | None = None


class RequestAnsweredData(Frozen):
    request: str
    by: str
    outcome: Literal["fulfilled", "nothing_found", "declined"]
    evidence: tuple[str, ...] = ()


class EvidenceWithheldData(Frozen):
    """Records a search found and the responder chose not to hand over. Never shown to the requester."""

    request: str
    by: str
    requester: str
    evidence: tuple[str, ...]
    about: tuple[str, ...]


class DiscrepancyNoticedData(Frozen):
    """A requester came to hold a record that an earlier answer to it had left out."""

    agent: str
    against: str
    request: str
    evidence: str


class AccessEscalatedData(Frozen):
    agent: str
    source: str
    against: str
    grounds: tuple[str, ...]  # request ids


class ClaimPublishedData(Frozen):
    claim: str
    by: str  # agent id or "anonymous"
    proposition: str
    cited: tuple[str, ...] = ()
    audience: tuple[str, ...]
    text: str | None = None


class ClaimRetractedData(Frozen):
    claim: str
    by: str


class BeliefsRevisedData(Frozen):
    agent: str
    because: tuple[str, ...]  # ids of the evidence / claims that triggered the revision
    changes: dict[str, dict[str, Any] | None]  # proposition key -> new BeliefEntry, or None if dropped
    suspects: dict[str, dict[str, Any]]
    prime_before: str | None
    prime_after: str | None


class ContradictionRecognizedData(Frozen):
    agent: str
    a: str
    b: str


class StatementMadeData(Frozen):
    """One agent told another something.

    `grounds` and `backing` say what the speaker had for it when it spoke. They
    are the speaker's business: the recipient's view never carries them.
    """

    statement: str
    speaker: str
    recipient: str
    proposition: str
    origin: str | None = None  # whose word this is, when the speaker only passes it on
    relays: str | None = None  # the statement being passed on
    grounds: Grounds
    backing: tuple[str, ...] = ()  # evidence or statement ids behind it


class StatementWeighedData(Frozen):
    """What a listener makes of a statement, recorded when it first hears it and whenever that changes."""

    agent: str
    statement: str
    stance: Stance
    belief: str  # the listener's belief status for the proposition, or "unknown"


class CredibilityRevisedData(Frozen):
    """A listener's view of a speaker changed. `credibility` is None when nothing checkable is left."""

    agent: str
    speaker: str
    credibility: dict[str, Any] | None
    before: str | None  # previous standing
    because: tuple[str, ...]  # ids of the information that triggered the revision


class InterventionAppliedData(Frozen):
    intervention: str
    kind: str


class AccessGrantedData(Frozen):
    agent: str
    source: str
    intervention: str


class PolicyChangedData(Frozen):
    agent: str
    policy: str


class AccusationMadeData(Frozen):
    by: str
    suspect: str
    cited: tuple[str, ...]


class CaseClosedData(Frozen):
    reason: Literal["accusation", "tick_limit"]


EVENT_TYPES: dict[str, type[Frozen]] = {
    "RunStarted": RunStartedData,
    "TickStarted": TickStartedData,
    "ActionTaken": ActionTakenData,
    "ActionRejected": ActionRejectedData,
    "SourceInspected": SourceInspectedData,
    "EvidenceObserved": EvidenceObservedData,
    "EvidenceShared": EvidenceSharedData,
    "EvidenceReleased": EvidenceReleasedData,
    "RequestSent": RequestSentData,
    "RequestAnswered": RequestAnsweredData,
    "EvidenceWithheld": EvidenceWithheldData,
    "DiscrepancyNoticed": DiscrepancyNoticedData,
    "AccessEscalated": AccessEscalatedData,
    "ClaimPublished": ClaimPublishedData,
    "ClaimRetracted": ClaimRetractedData,
    "BeliefsRevised": BeliefsRevisedData,
    "ContradictionRecognized": ContradictionRecognizedData,
    "StatementMade": StatementMadeData,
    "StatementWeighed": StatementWeighedData,
    "CredibilityRevised": CredibilityRevisedData,
    "InterventionApplied": InterventionAppliedData,
    "AccessGranted": AccessGrantedData,
    "PolicyChanged": PolicyChangedData,
    "AccusationMade": AccusationMadeData,
    "CaseClosed": CaseClosedData,
}


def normalize_event_data(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate a payload against its contract and return plain JSON data."""
    model = EVENT_TYPES.get(event_type)
    if model is None:
        raise ValueError(f"unknown event type: {event_type}")
    return model.model_validate(data).model_dump(mode="json")


# --------------------------------------------------------------------------
# Agent view: the only thing a policy ever receives
# --------------------------------------------------------------------------


class EvidenceView(Frozen):
    id: str
    title: str
    text: str
    kind: EvidenceKind
    speaker: str | None
    source: str
    mentions: tuple[str, ...]
    asserts: tuple[str, ...]
    shareable: bool
    acquired_seq: int
    acquired_tick: int
    via: str
    from_agent: str | None
    chain: tuple[str, ...]


class ClaimView(Frozen):
    id: str
    by: str
    proposition: str
    cited: tuple[str, ...]
    tick: int
    status: Literal["active", "retracted"]
    mine: bool


class RequestView(Frozen):
    id: str
    sender: str
    recipient: str
    topic: str
    source: str | None
    status: Literal["pending", "fulfilled", "nothing_found", "declined"]
    seq: int
    tick: int
    evidence: tuple[str, ...] = ()


class SourceView(Frozen):
    id: str
    name: str
    kind: str
    mode: Literal["direct", "request", "none"]
    operators: tuple[str, ...]
    searchable: tuple[str, ...]  # filtered to entities this agent knows about


class TriedView(Frozen):
    seq: int
    found: int
    count: int


class DiscrepancyView(Frozen):
    against: str
    request: str
    evidence: str
    seq: int
    tick: int


class StatementView(Frozen):
    """A statement as its speaker and its recipient both know it. What the speaker had for it is not here."""

    id: str
    speaker: str
    recipient: str
    proposition: str
    origin: str | None
    seq: int
    tick: int
    mine: bool


class SelfView(Frozen):
    id: str
    name: str
    role: str
    goals: tuple[str, ...]
    disposition: Disposition
    agenda: Agenda | None = None  # this agent's own private commitment, if the scenario gives it one


class RosterEntry(Frozen):
    id: str
    name: str
    role: str


class CaseView(Frozen):
    title: str
    briefing: str
    object: str
    crime_location: str
    suspects: tuple[str, ...]
    max_ticks: int


class AgentView(Frozen):
    me: SelfView
    tick: int
    case: CaseView
    roster: tuple[RosterEntry, ...]
    entities: tuple[Entity, ...]  # only entities this agent knows exist
    sources: tuple[SourceView, ...]
    evidence: tuple[EvidenceView, ...]
    claims: tuple[ClaimView, ...]
    beliefs: dict[str, BeliefEntry]
    suspects: dict[str, SuspectAssessment]
    prime_suspect: str | None
    contradictions: tuple[str, ...]
    tried: dict[str, TriedView]  # "source|topic" -> last own query
    inbox: tuple[RequestView, ...]  # pending requests addressed to me
    outbox: tuple[RequestView, ...]  # every request I have sent
    shared: tuple[str, ...]  # "recipient|evidence" pairs I have already sent
    discrepancies: tuple[DiscrepancyView, ...] = ()  # answers to my requests that I caught leaving a record out
    observations: tuple[str, ...] = ()  # what I saw for myself (proposition keys)
    statements: tuple[StatementView, ...] = ()  # what I was told and what I told others
    credibility: dict[str, Credibility] = Field(default_factory=dict)  # speaker -> what I could check of their word
