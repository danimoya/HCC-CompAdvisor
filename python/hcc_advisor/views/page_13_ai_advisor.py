"""
AI Advisor Page - HCC Compression Advisor
Local SLM analysis via Ollama for compression recommendations
"""

import streamlit as st
import pandas as pd
import json
import time
import urllib.request
import requests
from hcc_advisor.utils.central_queries import CentralQueries
from hcc_advisor.utils.target_queries import TargetQueries
from hcc_advisor.utils.central_connector import CentralConnector


def show_ai_advisor_page():
    st.title("AI Advisor")
    st.markdown("AI-powered compression analysis using a local language model (Ollama)")
    st.markdown("---")

    # Load Ollama config
    ollama_url = _get_config('ollama_url', 'http://localhost:11434')
    ollama_model = _get_config('ollama_model', 'llama3')

    if not ollama_url:
        st.warning("Configure Ollama URL in **Admin → AI / Ollama** tab first.")
        return

    db_id = st.session_state.get('active_database_id')

    # Scope selection
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        scope = st.selectbox("Scope", ["Full Estate", "Schema", "Single Table"], key="ai_scope")
    with col2:
        schema_filter = None
        table_filter = None
        if scope == "Schema":
            schemas = TargetQueries.get_available_schemas(db_id) if db_id else []
            schema_filter = st.selectbox("Schema", schemas, key="ai_schema") if schemas else None
        elif scope == "Single Table":
            table_filter = st.text_input("Owner.Table", placeholder="e.g., HR.EMPLOYEES", key="ai_table")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(f"Model: **{ollama_model}**")

    # Analyze + Diagnostic buttons
    col_a, col_b = st.columns([3, 1])
    with col_a:
        analyze_clicked = st.button(
            "Analyze", type="primary", use_container_width=True, key="ai_analyze"
        )
    with col_b:
        diag_clicked = st.button(
            "Test Generate", use_container_width=True, key="ai_test_generate",
            help="Send a trivial prompt to verify Ollama generation works"
        )

    if diag_clicked:
        _run_diagnostic(ollama_url, ollama_model)

    if analyze_clicked:
        try:
            with st.status("Running AI Analysis...", expanded=True) as status:
                # Step 1: Gather data
                st.write("1. Gathering estate data from central DB...")
                t0 = time.time()
                context = _gather_context(db_id, schema_filter, table_filter)
                gather_t = time.time() - t0
                st.write(
                    f"   Context ready in {gather_t:.1f}s: "
                    f"{len(context.get('candidates', []))} candidates, "
                    f"{len(context.get('failures', []))} failures, "
                    f"{len(context.get('growth_alerts', []))} growth alerts"
                )

                # Step 2: Build prompt
                st.write("2. Building structured prompt...")
                prompt = _build_prompt(context, scope)
                st.write(f"   Prompt: {len(prompt):,} chars (~{len(prompt) // 4:,} tokens)")

                # Step 3: Warm up model (load into RAM)
                st.write(f"3. Preloading **{ollama_model}**...")
                warm_out = st.empty()
                _warm_model(ollama_url, ollama_model,
                            lambda msg: warm_out.write(f"   {msg}"))

                # Step 4: Call Ollama (streaming)
                st.write(f"4. Querying model at {ollama_url}...")
                st.caption(
                    "Streaming response. TTFT (time to first token) depends on model size. "
                    "Model stays loaded for 30 min via keep_alive."
                )
                stream_placeholder = st.empty()
                response = _call_ollama_streaming(
                    prompt, ollama_url, ollama_model, stream_placeholder
                )
                status.update(label="AI Analysis Complete", state="complete", expanded=False)

            st.session_state['ai_last_response'] = response
            st.session_state['ai_last_context'] = context
            st.session_state['ai_chat_history'] = [
                {'role': 'user', 'content': f'Analyze {scope}'},
                {'role': 'assistant', 'content': response}
            ]
        except requests.exceptions.Timeout as e:
            st.error(f"Ollama request timed out: {e}")
            st.info(
                "The model did not respond within 10 minutes. Possible causes: "
                "(1) model is still loading on a slow disk, "
                "(2) firewall/proxy blocking `/api/generate` (tags endpoint works but generate doesn't), "
                "(3) Ollama is out of memory. "
                "Try **Test Generate** to verify basic connectivity, or switch to a smaller model (phi3:mini)."
            )
        except Exception as e:
            st.error(f"Ollama error: {e}")
            st.info(
                f"Verify Ollama is running at {ollama_url} with model {ollama_model}. "
                "Click **Test Generate** to run a quick diagnostic."
            )

    # Display last response
    last_response = st.session_state.get('ai_last_response')
    if last_response:
        st.markdown("---")
        st.markdown("### AI Analysis")
        st.markdown(last_response)

        # Follow-up chat
        st.markdown("---")
        st.markdown("### Follow-up Questions")
        followup = st.text_input("Ask a question about the analysis...",
                                  key="ai_followup", placeholder="e.g., Which tables should I compress first?")

        if followup and st.button("Ask", key="ai_ask"):
            history = st.session_state.get('ai_chat_history', [])
            context = st.session_state.get('ai_last_context', {})

            followup_prompt = _build_followup_prompt(context, history, followup)

            try:
                with st.status(f"Asking {ollama_model}...", expanded=True) as status:
                    st.write(f"Prompt: {len(followup_prompt):,} chars")
                    st.caption("Streaming response from Ollama...")
                    placeholder = st.empty()
                    answer = _call_ollama_streaming(
                        followup_prompt, ollama_url, ollama_model, placeholder
                    )
                    status.update(label="Answer ready", state="complete", expanded=False)
                history.append({'role': 'user', 'content': followup})
                history.append({'role': 'assistant', 'content': answer})
                st.session_state['ai_chat_history'] = history
                st.markdown("**Answer:**")
                st.markdown(answer)
            except Exception as e:
                st.error(f"Ollama error: {e}")

        # Show chat history
        history = st.session_state.get('ai_chat_history', [])
        if len(history) > 2:
            with st.expander("Conversation History", expanded=False):
                for msg in history[2:]:  # Skip initial analysis
                    if msg['role'] == 'user':
                        st.markdown(f"**You:** {msg['content']}")
                    else:
                        st.markdown(f"**AI:** {msg['content']}")
                    st.markdown("---")


def _get_config(key: str, default: str = '') -> str:
    """Load a config value from t_schema_metadata."""
    val = st.session_state.get(key, '')
    if not val:
        try:
            df = CentralConnector.execute_query(
                "SELECT value FROM t_schema_metadata WHERE key = :k", {'k': key}
            )
            if not df.empty:
                val = df.iloc[0]['VALUE'] or default
                st.session_state[key] = val
        except Exception:
            val = default
    return val


def _gather_context(db_id, schema_filter=None, table_filter=None) -> dict:
    """Gather all available data for the AI prompt."""
    context = {}

    # Progress
    context['progress'] = CentralQueries.get_compression_progress(database_id=db_id)

    # Forecast
    context['forecast'] = CentralQueries.get_forecast_data(database_id=db_id)

    # Recommendations
    schema_param = schema_filter
    if table_filter and '.' in table_filter:
        schema_param = table_filter.split('.')[0]

    recs = CentralQueries.get_recommendations(
        schema=schema_param, database_id=db_id, show_executed=True,
        min_savings_pct=0, limit=200
    )
    if not recs.empty:
        recs.columns = [c.lower() for c in recs.columns]
        if table_filter and '.' in table_filter:
            tbl = table_filter.split('.')[1].upper()
            recs = recs[recs['table_name'] == tbl]
        context['candidates'] = recs.to_dict('records')
    else:
        context['candidates'] = []

    # Failures
    history = CentralQueries.get_execution_history(limit=20, database_id=db_id)
    if not history.empty:
        history.columns = [c.lower() for c in history.columns]
        failures = history[history['status'] == 'FAILED']
        context['failures'] = failures.to_dict('records') if not failures.empty else []
    else:
        context['failures'] = []

    # Growth alerts
    growth = CentralQueries.get_growth_alerts(database_id=db_id)
    if not growth.empty:
        growth.columns = [c.lower() for c in growth.columns]
        context['growth_alerts'] = growth.to_dict('records')
    else:
        context['growth_alerts'] = []

    return context


def _build_prompt(context: dict, scope: str) -> str:
    """Build the analysis prompt from gathered data."""
    p = context.get('progress', {})
    f = context.get('forecast', {})

    prompt = f"""You are an Oracle DBA compression advisor. Analyze this compression estate data and provide actionable recommendations.

ESTATE SUMMARY:
- Total objects analyzed: {p.get('total', 0)}
- Already compressed: {p.get('compressed', 0)} (saved {p.get('saved_mb', 0) / 1024:.2f} GB)
- Pending candidates: {p.get('pending', 0)} ({p.get('uncompressed_mb', 0) / 1024:.2f} GB uncompressed)
- Skipped (not recommended): {p.get('skipped', 0)}

FORECAST:
- Pending objects: {f.get('pending_count', 0)}
- Current size of pending: {f.get('pending_current_mb', 0) / 1024:.2f} GB
- Projected after compression: {f.get('pending_projected_mb', 0) / 1024:.2f} GB
- Average compression duration: {f.get('avg_duration_sec', 0)}s per object

"""

    # Top candidates
    candidates = context.get('candidates', [])
    if candidates:
        prompt += "TOP CANDIDATES (by size):\n"
        prompt += "| Owner | Table | Size MB | Hotness | Current | Advised | Status |\n"
        prompt += "|-------|-------|---------|---------|---------|---------|--------|\n"
        for c in candidates[:50]:
            prompt += (f"| {c.get('table_owner', '')} | {c.get('table_name', '')} "
                      f"| {c.get('current_size_mb', 0):.0f} | {c.get('hotness_score', 0):.0f} "
                      f"| {c.get('current_compression', '')} | {c.get('recommended_strategy', '')} "
                      f"| {c.get('execution_status', '')} |\n")
        prompt += "\n"

    # Failures
    failures = context.get('failures', [])
    if failures:
        prompt += "RECENT FAILURES:\n"
        for fl in failures[:10]:
            prompt += f"- {fl.get('table_owner', '')}.{fl.get('table_name', '')}: {fl.get('error_message', 'unknown')}\n"
        prompt += "\n"

    # Growth alerts
    growth = context.get('growth_alerts', [])
    if growth:
        prompt += "GROWTH ALERTS (tables that grew >20% since compression):\n"
        for g in growth:
            prompt += f"- {g.get('owner', '')}.{g.get('object_name', '')}: was {g.get('compressed_mb', 0)} MB, now {g.get('current_mb', 0)} MB (+{g.get('growth_pct', 0)}%)\n"
        prompt += "\n"

    prompt += """Provide your analysis in this format:
1. **Priority Recommendations** — Top 5 tables to compress first and why
2. **Risk Assessment** — Any concerns or tables to avoid
3. **Savings Estimate** — Expected total savings and timeline
4. **Execution Strategy** — Recommended order and throttle level
5. **Anomalies** — Anything unusual in the data
"""

    return prompt


def _build_followup_prompt(context: dict, history: list, question: str) -> str:
    """Build a follow-up prompt with conversation context."""
    prompt = "You are an Oracle DBA compression advisor. Previous analysis context:\n\n"

    # Add abbreviated context
    p = context.get('progress', {})
    prompt += f"Estate: {p.get('total', 0)} objects, {p.get('compressed', 0)} compressed, {p.get('pending', 0)} pending.\n"
    prompt += f"Saved so far: {p.get('saved_mb', 0) / 1024:.2f} GB.\n\n"

    # Add conversation history (last 4 exchanges max)
    recent = history[-8:] if len(history) > 8 else history
    for msg in recent:
        role = "User" if msg['role'] == 'user' else "AI"
        prompt += f"{role}: {msg['content'][:500]}\n\n"

    prompt += f"User: {question}\n\nProvide a helpful, concise answer:"
    return prompt


def _run_diagnostic(url: str, model: str):
    """Run a minimal test generation and show detailed diagnostics.
    Helps isolate connectivity vs model loading vs generation issues."""
    with st.status("Running diagnostic...", expanded=True) as status:
        # Step 1: /api/tags (list models)
        st.write("1. Testing /api/tags (list models)...")
        try:
            t0 = time.time()
            r = requests.get(f"{url}/api/tags", timeout=10)
            r.raise_for_status()
            tags = r.json().get('models', [])
            st.write(f"   [OK] {len(tags)} models available ({time.time() - t0:.2f}s)")
            model_names = [m.get('name') for m in tags]
            if model_names:
                st.caption(f"   Models: {', '.join(model_names)}")
            if model not in model_names and f"{model}:latest" not in model_names:
                st.warning(f"   Model '{model}' not in list. Run `ollama pull {model}` first.")
        except Exception as e:
            st.error(f"   [FAIL] /api/tags unreachable: {e}")
            status.update(label="Diagnostic FAILED", state="error", expanded=True)
            return

        # Step 2: /api/show (model info)
        st.write(f"2. Testing /api/show for '{model}'...")
        try:
            t0 = time.time()
            r = requests.post(f"{url}/api/show", json={'name': model}, timeout=30)
            r.raise_for_status()
            info = r.json()
            fmt = info.get('details', {}).get('format', '?')
            family = info.get('details', {}).get('family', '?')
            params = info.get('details', {}).get('parameter_size', '?')
            st.write(f"   [OK] family={family}, params={params}, format={fmt} ({time.time() - t0:.2f}s)")
        except Exception as e:
            st.error(f"   [FAIL] /api/show error: {e}")
            status.update(label="Diagnostic FAILED", state="error", expanded=True)
            return

        # Step 3: Minimal generation (stream=false, num_predict=20)
        st.write("3. Testing /api/generate with trivial prompt (non-streaming)...")
        try:
            t0 = time.time()
            r = requests.post(
                f"{url}/api/generate",
                json={
                    'model': model,
                    'prompt': 'Say hi in 3 words.',
                    'stream': False,
                    'keep_alive': '30m',
                    'options': {'num_predict': 20}
                },
                timeout=300
            )
            r.raise_for_status()
            data = r.json()
            elapsed = time.time() - t0
            resp_text = (data.get('response') or '').strip()
            load_dur = data.get('load_duration', 0) / 1e9  # ns -> s
            eval_count = data.get('eval_count', 0)
            eval_dur = data.get('eval_duration', 0) / 1e9
            tok_per_sec = eval_count / eval_dur if eval_dur > 0 else 0
            st.write(f"   [OK] Generated in {elapsed:.1f}s "
                     f"(load: {load_dur:.1f}s, {eval_count} tokens at {tok_per_sec:.1f} tok/s)")
            st.code(resp_text or '(empty response)', language='text')
        except requests.exceptions.Timeout:
            st.error("   [FAIL] Generation timed out after 300s — likely model load failed or OOM")
            status.update(label="Diagnostic FAILED", state="error", expanded=True)
            return
        except Exception as e:
            st.error(f"   [FAIL] Generation error: {e}")
            status.update(label="Diagnostic FAILED", state="error", expanded=True)
            return

        # Step 4: Streaming test
        st.write("4. Testing /api/generate with streaming...")
        try:
            t0 = time.time()
            tokens = 0
            first_token_at = None
            with requests.post(
                f"{url}/api/generate",
                json={
                    'model': model,
                    'prompt': 'Count from 1 to 5.',
                    'stream': True,
                    'keep_alive': '30m',
                    'options': {'num_predict': 30}
                },
                stream=True,
                timeout=300
            ) as sr:
                sr.raise_for_status()
                for line in sr.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    if chunk.get('response'):
                        if first_token_at is None:
                            first_token_at = time.time()
                        tokens += 1
                    if chunk.get('done'):
                        break
            elapsed = time.time() - t0
            ttft = (first_token_at - t0) if first_token_at else None
            if tokens > 0:
                st.write(f"   [OK] Streamed {tokens} tokens in {elapsed:.1f}s "
                         f"(TTFT: {ttft:.1f}s)" if ttft else f"   [OK] Streamed {tokens} tokens in {elapsed:.1f}s")
            else:
                st.error("   [FAIL] No tokens received from stream")
        except Exception as e:
            st.error(f"   [FAIL] Streaming error: {e}")
            status.update(label="Diagnostic FAILED (streaming)", state="error", expanded=True)
            return

        status.update(label="Diagnostic: all checks passed", state="complete", expanded=False)
        st.success("Ollama is reachable and generating correctly. "
                   "If the main Analyze still fails, the prompt may be too large for the model's context window.")


def _call_ollama(prompt: str, url: str, model: str, timeout: int = 600) -> str:
    """Call the Ollama API (non-streaming)."""
    payload = {
        'model': model,
        'prompt': prompt,
        'stream': False,
        'keep_alive': '30m',
        'options': {'temperature': 0.3, 'num_predict': 2000}
    }
    resp = requests.post(f"{url}/api/generate", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get('response', 'No response from model.')


def _warm_model(url: str, model: str, status_write, timeout: int = 600) -> bool:
    """Preload the model into memory so the first real call returns fast.
    Uses an empty prompt which Ollama treats as a load-only request."""
    try:
        status_write("Warming up model (loading into RAM)...")
        t0 = time.time()
        # Ollama accepts an empty prompt to just load the model
        resp = requests.post(
            f"{url}/api/generate",
            json={'model': model, 'prompt': '', 'stream': False, 'keep_alive': '30m'},
            timeout=timeout
        )
        resp.raise_for_status()
        elapsed = time.time() - t0
        status_write(f"Model loaded in {elapsed:.1f}s")
        return True
    except Exception as e:
        status_write(f"Warmup failed ({str(e)[:100]}); continuing anyway...")
        return False


def _call_ollama_streaming(prompt: str, url: str, model: str, placeholder,
                            timeout: int = 600) -> str:
    """Call Ollama with stream=true using requests for reliable chunked streaming.
    Updates the placeholder incrementally. Returns the full response text."""
    payload = {
        'model': model,
        'prompt': prompt,
        'stream': True,
        'keep_alive': '30m',
        'options': {'temperature': 0.3, 'num_predict': 2000}
    }

    start = time.time()
    first_token_at = None
    full_text = ''
    token_count = 0
    last_update = start
    placeholder.markdown("*Connecting to Ollama...*")

    with requests.post(f"{url}/api/generate", json=payload, stream=True,
                        timeout=timeout) as resp:
        resp.raise_for_status()
        placeholder.markdown("*Waiting for first token (model may be loading)...*")

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue

            piece = chunk.get('response', '')
            if piece:
                if first_token_at is None:
                    first_token_at = time.time()
                full_text += piece
                token_count += 1

            # Refresh placeholder every ~200ms
            now = time.time()
            if now - last_update > 0.2 or chunk.get('done'):
                elapsed = now - start
                if first_token_at:
                    gen_elapsed = now - first_token_at
                    tok_per_sec = token_count / gen_elapsed if gen_elapsed > 0 else 0
                    ttft = first_token_at - start
                    header = (f"*Generating... {token_count} tokens, "
                             f"{elapsed:.1f}s total (TTFT: {ttft:.1f}s, {tok_per_sec:.1f} tok/s)*\n\n---\n\n")
                else:
                    header = f"*Loading model... {elapsed:.1f}s elapsed*\n\n---\n\n"
                placeholder.markdown(header + full_text)
                last_update = now

            if chunk.get('done'):
                placeholder.markdown(full_text)
                break

    return full_text


if __name__ == "__main__":
    show_ai_advisor_page()
