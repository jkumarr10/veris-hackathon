import { useMemo, useState } from 'react';

const DEFAULT_ADDRESS =
  'Rosamond, Kern County, CA 93560';
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

function decisionLabel(value) {
  if (value === 'deploy_crew') return 'Deploy Crew';
  if (value === 'wait_and_monitor') return 'Wait and Monitor';
  if (value === 'alert_only') return 'Alert Only';
  return 'Recommendation Pending';
}

function decisionTone(value) {
  if (value === 'deploy_crew') return 'deploy';
  if (value === 'alert_only') return 'alert';
  return 'wait';
}

function fmtNumber(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '-';
  return Number(v).toFixed(digits);
}

function tryParseDecisionJson(text) {
  if (!text) return null;
  const trimmed = text.trim();
  const match = trimmed.match(/\{[\s\S]*\}/);
  const candidate = match ? match[0] : trimmed;
  try {
    const parsed = JSON.parse(candidate);
    if (!parsed || typeof parsed !== 'object') return null;
    return {
      decision: parsed.decision,
      reasoning: parsed.reasoning
    };
  } catch {
    return null;
  }
}

export default function App() {
  const [address, setAddress] = useState(DEFAULT_ADDRESS);
  const [cleaningCost, setCleaningCost] = useState('15000');
  const [lookaheadDays, setLookaheadDays] = useState('7');
  const [energyPrice, setEnergyPrice] = useState('0.08');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [streamStatus, setStreamStatus] = useState([]);
  const [iterationText, setIterationText] = useState({ 1: '', 2: '' });
  const [iterationMeta, setIterationMeta] = useState({ 1: null, 2: null });

  const recommendation = result?.manager_decision?.decision;
  const tone = useMemo(() => decisionTone(recommendation), [recommendation]);

  async function runAnalysis(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    setStreamStatus([]);
    setIterationText({ 1: '', 2: '' });
    setIterationMeta({ 1: null, 2: null });

    try {
      const payload = {
        address,
        cleaning_cost_usd: cleaningCost ? Number(cleaningCost) : null,
        lookahead_days: lookaheadDays ? Number(lookaheadDays) : null,
        energy_price_per_kwh: energyPrice ? Number(energyPrice) : null,
        use_llm_manager: true
      };

      const res = await fetch(`${API_BASE}/decision/run-by-address/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || 'Request failed');
      }
      if (!res.body) {
        throw new Error('Streaming response not available in this browser');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      const consumeEvent = (rawEvent) => {
        const lines = rawEvent.split('\n').filter(Boolean);
        let eventName = 'message';
        let dataText = '';
        for (const line of lines) {
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          if (line.startsWith('data:')) dataText += line.slice(5).trim();
        }
        if (!dataText) return;

        let payload = null;
        try {
          payload = JSON.parse(dataText);
        } catch {
          return;
        }

        if (eventName === 'status') {
          setStreamStatus((prev) => [...prev, payload.message]);
          return;
        }
        if (eventName === 'iteration_start') {
          setStreamStatus((prev) => [...prev, `Iteration ${payload.iteration}: ${payload.phase}`]);
          return;
        }
        if (eventName === 'token') {
          const idx = payload.iteration;
          if (idx === 1 || idx === 2) {
            setIterationText((prev) => ({ ...prev, [idx]: `${prev[idx] || ''}${payload.delta || ''}` }));
          }
          return;
        }
        if (eventName === 'iteration_done') {
          const idx = payload.iteration;
          if (idx === 1 || idx === 2) {
            setIterationMeta((prev) => ({
              ...prev,
              [idx]: {
                decision: payload?.candidate?.decision,
                reasoning: payload?.candidate?.reasoning,
                valid: payload?.valid,
                critique: payload?.critique
              }
            }));
          }
          return;
        }
        if (eventName === 'final') {
          setResult(payload.result);
          return;
        }
        if (eventName === 'error') {
          throw new Error(payload.message || 'Streaming failed');
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        for (const evt of events) {
          consumeEvent(evt);
        }
      }
    } catch (err) {
      setError(err?.message || 'Unexpected error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <nav className="top-nav">
        <div className="top-nav-left">
          <div className="brand-icon">S</div>
        </div>
        <h1 className="top-title">Solar Soiling Detection Agent</h1>
        <button className="ghost-btn" onClick={() => setResult(null)}>
          New Analysis
        </button>
      </nav>

      <main className="layout">
        <section className="panel form-panel">
          <h2>Configure Analysis</h2>
          <p className="help-line">
            Weather horizon uses lookahead days (max 7) for near-term forecast confidence. Gain horizon is
            fixed at 30 days for economic recovery projection.
          </p>

          <form onSubmit={runAnalysis}>
            <label>
              Solar Farm Address
              <textarea value={address} onChange={(e) => setAddress(e.target.value)} rows={3} />
            </label>

            <div className="row3">
              <label>
                Cleaning Budget ($)
                <input
                  type="number"
                  step="100"
                  value={cleaningCost}
                  onChange={(e) => setCleaningCost(e.target.value)}
                />
              </label>

              <label>
                Lookahead Days (1-7)
                <input
                  type="number"
                  min="1"
                  max="7"
                  value={lookaheadDays}
                  onChange={(e) => setLookaheadDays(e.target.value)}
                />
              </label>

              <label>
                Energy Price ($/kWh)
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={energyPrice}
                  onChange={(e) => setEnergyPrice(e.target.value)}
                />
              </label>
            </div>

            <button type="submit" className="run-btn" disabled={loading || !address.trim()}>
              {loading ? 'Running Analysis...' : 'Run Analysis'}
            </button>
          </form>

          {error ? <p className="error">{error}</p> : null}

          <div className="trace-panel">
            <h3>Agent Trace</h3>
            <p className="muted">
              Iteration 1 writes the plan. Iteration 2 takes the final action decision.
            </p>
            {streamStatus.length ? (
              <div className="trace-status">
                {streamStatus.map((msg, idx) => (
                  <p key={`${msg}-${idx}`}>{msg}</p>
                ))}
              </div>
            ) : (
              <p className="muted">Run analysis to watch live manager reasoning.</p>
            )}
            <div className="trace-grid">
              {[1, 2].map((idx) => {
                const parsed = tryParseDecisionJson(iterationText[idx]);
                const meta = iterationMeta[idx];
                const decision = meta?.decision || parsed?.decision;
                const reasoning = meta?.reasoning || parsed?.reasoning;
                return (
                  <article key={idx}>
                    <p className="metric-label">Iteration {idx}</p>
                    <p className="trace-phase">{idx === 1 ? 'Plan' : 'Action'}</p>
                    <p className="trace-decision">
                      {decision ? decisionLabel(decision) : 'Drafting recommendation...'}
                    </p>
                    <p className="trace-reasoning">
                      {reasoning || 'The manager agent is evaluating economics, weather, and policy.'}
                    </p>
                    {meta ? (
                      <p className="trace-meta">
                        Valid: {String(meta.valid)}
                        {meta.critique ? ` | ${meta.critique}` : ''}
                      </p>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        <section className="panel result-panel">
          <h2>Recommendation</h2>
          {!result ? <p className="muted">Submit analysis to generate an operational recommendation.</p> : null}

          {result ? (
            <>
              <div className={`decision-banner ${tone}`}>
                <div>
                  <p className="decision-kicker">Manager Decision</p>
                  <p className="decision-text">{decisionLabel(result.manager_decision.decision)}</p>
                  <p className="decision-reason">{result.manager_decision.reasoning}</p>
                </div>
                <div className="roi-box">
                  <p className="roi-label">ROI Ratio</p>
                  <p className="roi-value">{fmtNumber(result.manager_decision.roi_ratio, 3)}</p>
                </div>
              </div>

              <div className="metrics-grid">
                <article>
                  <p className="metric-label">
                    Loss if Not Cleaned ({result.environment.lookahead_days}d Weather Horizon)
                  </p>
                  <p className="metric-value">
                    ${fmtNumber(result.manager_decision.projected_loss_without_cleaning_usd)}
                  </p>
                </article>
                <article>
                  <p className="metric-label">
                    Gain if Cleaned ({result.manager_decision.gain_horizon_days}d Gain Horizon)
                  </p>
                  <p className="metric-value">${fmtNumber(result.manager_decision.projected_gain_usd)}</p>
                </article>
                <article>
                  <p className="metric-label">Cleaning Budget</p>
                  <p className="metric-value">${fmtNumber(result.manager_decision.clean_cost_usd)}</p>
                </article>
                <article>
                  <p className="metric-label">Avg Soiling Loss</p>
                  <p className="metric-value">{fmtNumber(result.yield_report.avg_soiling_loss_pct)}%</p>
                </article>
              </div>

              <div className="metrics-grid three">
                <article>
                  <p className="metric-label">Weather Horizon</p>
                  <p className="metric-note">{fmtNumber(result.environment.lookahead_days, 0)} days</p>
                </article>
                <article>
                  <p className="metric-label">Gain Horizon</p>
                  <p className="metric-note">
                    {fmtNumber(result.manager_decision.gain_horizon_days, 0)} days
                  </p>
                </article>
                <article>
                  <p className="metric-label">Resolved Site</p>
                  <p className="metric-note">{result.resolved_location.name}</p>
                </article>
                <article>
                  <p className="metric-label">Rain (Next 7 Days)</p>
                  <p className="metric-note">{result.environment.rainy_days_next_7_days} rainy days</p>
                </article>
              </div>

              <div className="metrics-grid three">
                <article>
                  <p className="metric-label">PM2.5 / PM10</p>
                  <p className="metric-note">
                    {fmtNumber(result.environment.pm25)} / {fmtNumber(result.environment.pm10)}
                  </p>
                </article>
                <article>
                  <p className="metric-label">Rain (Past 7 Days)</p>
                  <p className="metric-note">{result.environment.rainy_days_prev_7_days} rainy days</p>
                </article>
                <article>
                  <p className="metric-label">Humidity</p>
                  <p className="metric-note">{fmtNumber(result.environment.humidity_pct)}%</p>
                </article>
                <article>
                  <p className="metric-label">Rain Total (Next 7d)</p>
                  <p className="metric-note">
                    {fmtNumber(result.environment.total_precipitation_next_7_days_mm)} mm
                  </p>
                </article>
              </div>

              <div className="metrics-grid three">
                <article>
                  <p className="metric-label">Estimated Plant Capacity</p>
                  <p className="metric-note">
                    {result.yield_report.estimated_plant_capacity_mw === null
                      ? '-'
                      : `${fmtNumber(result.yield_report.estimated_plant_capacity_mw, 3)} MW`}
                  </p>
                </article>
                <article>
                  <p className="metric-label">Inverters / Units</p>
                  <p className="metric-note">{fmtNumber(result.yield_report.panel_count, 0)}</p>
                </article>
              </div>
            </>
          ) : null}
        </section>
      </main>
    </div>
  );
}
