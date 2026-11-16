import type { Evaluation, Snapshot } from "../api";
import { Chip, Empty, EvidenceRef, GROUNDS_TEXT, RatioBar, Section, StanceTrail } from "./ui";
import type { NameOf } from "./ui";

interface Props {
  evaluation: Evaluation | null;
  snapshot: Snapshot;
  nameOf: NameOf;
  busy: boolean;
  onReveal: () => void;
  onSelectNode: (nodeId: string) => void;
}

const OUTCOME: Record<string, { title: string; tone: string }> = {
  solved: { title: "Solved", tone: "good" },
  wrong_accusation: { title: "Wrong accusation", tone: "bad" },
  unresolved: { title: "Unresolved", tone: "mid" },
};

export default function EvaluationPanel({ evaluation, snapshot, nameOf, busy, onReveal, onSelectNode }: Props) {
  if (!evaluation) return <Empty>Loading evaluation...</Empty>;
  const p = evaluation.progress;

  if (!evaluation.available || !evaluation.result) {
    return (
      <div className="evaluation">
        <div className="callout">
          <b>The case is still open.</b>
          <div>Scores that depend on the hidden solution stay locked until the case closes, so watching the run cannot spoil it. The counters below reveal nothing about what actually happened.</div>
        </div>
        <div className="stat-grid">
          <div className="stat">
            <b>
              {p.tick}/{p.max_ticks}
            </b>
            <span>ticks used</span>
          </div>
          <div className="stat">
            <b>
              {p.evidence_discovered}/{p.evidence_total}
            </b>
            <span>evidence found</span>
          </div>
          <div className="stat">
            <b>{p.claims_published}</b>
            <span>public claims</span>
          </div>
          <div className="stat">
            <b>{p.contradictions_recognized}</b>
            <span>contradictions seen</span>
          </div>
          <div className="stat">
            <b>{p.requests}</b>
            <span>requests</span>
          </div>
          <div className="stat">
            <b>{p.actions}</b>
            <span>actions</span>
          </div>
        </div>
        <button onClick={onReveal} disabled={busy} title="Unlocks the evaluation and marks graph statements true or false. The run can still continue.">
          Reveal the solution now
        </button>
      </div>
    );
  }

  const r = evaluation.result;
  const outcome = OUTCOME[r.outcome];
  const stillOpen = snapshot.run.status === "running";

  return (
    <div className="evaluation">
      <div className={`verdict verdict-${outcome.tone}`}>
        <div className="verdict-title">{outcome.title}{stillOpen ? " so far" : ""}</div>
        <div>
          {r.accused ? (
            <>
              {nameOf(r.lead)} accused <b>{nameOf(r.accused)}</b> at tick {r.accusation_tick}.
            </>
          ) : stillOpen ? (
            <>No accusation yet. The solution was revealed early.</>
          ) : (
            <>No accusation was made before the tick limit.</>
          )}{" "}
          The culprit is <b>{nameOf(r.culprit)}</b>.
        </div>
        {r.accusation_supported !== null && (
          <div className="small">
            Standard of proof on what the accuser held:{" "}
            <Chip tone={r.accusation_supported ? "believed" : "rejected"}>{r.accusation_supported ? "met" : "not met"}</Chip>{" "}
            <span className="muted" data-testid="outcome-category">({r.category.replace("_", ", ")})</span>
            {r.outcome === "wrong_accusation" && r.accusation_supported && " The evidence in hand pointed the wrong way: exculpatory evidence was never obtained."}
            {r.outcome === "solved" && !r.accusation_supported && " Right person, but not on the evidence: a guess."}
          </div>
        )}
      </div>

      <Section title="What happened">
        <p className="quote">{r.solution}</p>
      </Section>

      <Section title="Evidence">
        <RatioBar label="Key evidence found by anyone" ratio={r.evidence.key_discovered} hint="Records on the canonical chain to the solution" />
        <RatioBar label={`Key evidence held by ${nameOf(r.lead)}`} ratio={r.evidence.key_held_by_lead} />
        <RatioBar label="All evidence found" ratio={r.evidence.all_discovered} />
        <RatioBar label={`Key facts ${nameOf(r.lead)} established`} ratio={r.key_facts.established_by_lead} hint="Key true statements the lead holds as believed" />
        {r.evidence.undiscovered.length > 0 && (
          <details>
            <summary>Never found ({r.evidence.undiscovered.length})</summary>
            <ul className="plain small">
              {r.evidence.undiscovered.map((e) => (
                <li key={e.id}>
                  {e.id} {e.title} {e.key && <Chip tone="disputed">key</Chip>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Section>

      <Section title="Public claims">
        {r.claims.items.length === 0 ? (
          <Empty>Nobody published anything.</Empty>
        ) : (
          <>
            <RatioBar label="Claims by agents that were false" ratio={r.claims.false} invert />
            <RatioBar label="False claims later retracted" ratio={r.claims.false_retracted} />
            <RatioBar label="Accusations published without meeting the standard" ratio={r.claims.unsupported_guilt} invert />
            <table className="table small">
              <tbody>
                {r.claims.items.map((c) => (
                  <tr key={c.id}>
                    <td className="nowrap muted">t{c.tick}</td>
                    <td>
                      <EvidenceRef id={c.id} onSelect={onSelectNode} /> {c.by === "anonymous" ? "Rumor" : nameOf(c.by)}: {snapshot.propositions[c.proposition] ?? c.proposition}
                    </td>
                    <td className="nowrap">
                      <Chip tone={c.true === true ? "believed" : c.true === false ? "rejected" : "neutral"}>{c.true === true ? "true" : c.true === false ? "false" : "unsettled"}</Chip>{" "}
                      {!c.supported && <Chip tone="disputed">unsupported</Chip>} {c.retracted && <Chip tone="withdrawn">retracted t{c.retracted_tick}</Chip>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Section>

      <Section title="Contradictions">
        <RatioBar label="Contradictions in the evidence that someone noticed" ratio={r.contradictions.inherent_recognized_by_team} />
        <RatioBar label="Noticed contradictions resolved correctly (all agents)" ratio={r.contradictions.resolved_correctly} hint="The true side believed and the false side rejected at the end" />
      </Section>

      {(r.deception.answers_with_withholding > 0 || r.deception.escalations.length > 0) && (
        <Section title="Deception">
          {Object.entries(r.deception.agendas)
            .filter(([, agenda]) => agenda.policy === "deceptive")
            .map(([id, agenda]) => (
              <p key={id} className="small" data-testid="deception-agenda">
                <b>{nameOf(id)}</b> was covering for <b>{nameOf(agenda.protects)}</b>
                {agenda.deflects_to && <> and steering suspicion towards {nameOf(agenda.deflects_to)}</>}. <span className="muted">{agenda.note}</span>
              </p>
            ))}
          <RatioBar label="Key evidence that was held back from someone" ratio={r.deception.key_records_withheld} invert hint="Key records that at least one answer left out" />
          <RatioBar label="Answers that held records back, noticed by the requester" ratio={r.deception.noticed} />
          <RatioBar label="Withheld records that reached the requester anyway" ratio={r.deception.recovered} />
          <table className="table small" data-testid="deception-items">
            <tbody>
              {r.deception.items.map((item) => (
                <tr key={item.request}>
                  <td className="nowrap muted">t{item.tick}</td>
                  <td>
                    {nameOf(item.by)} kept{" "}
                    {item.evidence.map((id) => (
                      <EvidenceRef key={id} id={id} onSelect={onSelectNode} />
                    ))}{" "}
                    from {nameOf(item.from)} <span className="muted">({item.request})</span>
                  </td>
                  <td className="nowrap">{item.noticed_tick !== null ? <Chip tone="believed">noticed t{item.noticed_tick}</Chip> : <Chip tone="rejected">never noticed</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.deception.escalations.map((e) => (
            <p key={`${e.by}-${e.tick}`} className="small">
              Tick {e.tick}: {nameOf(e.by)} took direct access to {e.sources.length} sources over {nameOf(e.against)}'s head.
            </p>
          ))}
          <p className="muted small">Counted from the event log: what a search found and did not hand over, and whether the requester later held it.</p>
        </Section>
      )}

      {r.testimony.statements > 0 && (
        <Section title="Testimony" aside={<span className="muted">{r.testimony.statements} statements, {r.testimony.passed_on} passed on</span>}>
          <RatioBar label="Statements that were false" ratio={r.testimony.false} invert />
          <RatioBar label="First-hand statements the speaker had nothing for" ratio={r.testimony.without_grounds} invert />
          <RatioBar label="False statements the listener accepted at some point" ratio={r.testimony.false_ever_accepted} invert />
          <RatioBar label="False statements still accepted when the case closed" ratio={r.testimony.false_accepted_at_close} invert />
          <RatioBar label="Listeners who came to doubt someone who told them something false" ratio={r.testimony.false_speakers_impeached} hint="Pairs of listener and speaker" />
          <RatioBar label="Listeners who came to doubt someone who told them only the truth" ratio={r.testimony.truthful_speakers_impeached} invert hint="Pairs of listener and speaker" />
          <table className="table small" data-testid="testimony-items">
            <tbody>
              {r.testimony.items.map((item) => (
                <tr key={item.id}>
                  <td className="nowrap muted">t{item.tick}</td>
                  <td>
                    <EvidenceRef id={item.id} onSelect={onSelectNode} /> {nameOf(item.speaker)} to {nameOf(item.recipient)}
                    {item.passed_on && <span className="muted"> (passing on {nameOf(item.voice)})</span>}: {snapshot.propositions[item.proposition] ?? item.proposition}
                    <div className="muted">{item.passed_on ? "second hand" : `the speaker ${GROUNDS_TEXT[item.grounds]}`}</div>
                  </td>
                  <td className="nowrap">{item.true === true ? <Chip tone="believed">true</Chip> : item.true === false ? <Chip tone="rejected">false</Chip> : <Chip>not settled</Chip>}</td>
                  <td>
                    <StanceTrail stances={item.stances} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            No figure here rewards speaking or agreeing. Credibility was worked out by each listener from its own records; of the claims listeners counted as refuted,{" "}
            {r.testimony.refuted_claims_false.num}/{r.testimony.refuted_claims_false.den} were in fact false.
          </p>
        </Section>
      )}

      <Section title="Agents">
        <table className="table small">
          <thead>
            <tr>
              <th>Agent</th>
              <th title="Of the statements the agent decided (believed or rejected), how many match the truth">Decided beliefs correct</th>
              <th>False beliefs</th>
              <th>Prime suspect</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(r.agents).map(([id, a]) => (
              <tr key={id}>
                <td>{nameOf(id)}</td>
                <td>
                  {a.belief_accuracy.num}/{a.belief_accuracy.den}
                  <span className="muted"> {a.belief_accuracy.pct === null ? "n/a" : `${a.belief_accuracy.pct}%`}</span>
                </td>
                <td title={a.false_beliefs.map((k) => snapshot.propositions[k] ?? k).join("\n")}>{a.false_beliefs.length}</td>
                <td>
                  {a.prime_suspect ? nameOf(a.prime_suspect) : "nobody"} {a.prime_correct === true && <Chip tone="believed">right</Chip>}
                  {a.prime_correct === false && <Chip tone="rejected">wrong</Chip>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">Only decided beliefs are counted, so an agent gains nothing by asserting more.</p>
      </Section>

      <Section title="Effort">
        <div className="stat-grid">
          <div className="stat">
            <b>{r.effort.ticks}</b>
            <span>ticks</span>
          </div>
          <div className="stat">
            <b>{r.effort.actions}</b>
            <span>actions ({r.effort.waits} waits)</span>
          </div>
          <div className="stat">
            <b>{r.effort.inspections}</b>
            <span>
              searches ({r.effort.empty_inspections} empty, {r.effort.redundant_inspections} redundant)
            </span>
          </div>
          <div className="stat">
            <b>{r.effort.requests}</b>
            <span>requests</span>
          </div>
          <div className="stat">
            <b>{r.effort.rejected_actions}</b>
            <span>rejected actions</span>
          </div>
          <div className="stat">
            <b>{r.effort.interventions.length}</b>
            <span>interventions</span>
          </div>
        </div>
      </Section>

      {r.provenance.length > 0 && (
        <Section title="Evidence behind the accusation">
          <ul className="cards">
            {r.provenance.map((item) => (
              <li key={item.id} className="card">
                <div className="card-head">
                  <EvidenceRef id={item.id} onSelect={onSelectNode} />
                  <b>{item.title}</b>
                  <Chip tone={`kind-${item.kind}`}>{item.kind}</Chip>
                  {item.key && <Chip tone="disputed">key</Chip>}
                </div>
                <div className="muted small">
                  First found by {nameOf(item.first_found_by)} at tick {item.first_found_tick}; reached the accuser at tick {item.reached_accuser_tick} via {item.chain.map((id) => nameOf(id)).join(" → ")}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
