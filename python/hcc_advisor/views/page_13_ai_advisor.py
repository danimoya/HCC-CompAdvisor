"""
AI Advisor Page - HCC Compression Advisor
Local SLM analysis via Ollama for compression recommendations
"""

import streamlit as st
import pandas as pd
import json
import urllib.request
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

    # Analyze button
    if st.button("Analyze", type="primary", use_container_width=True, key="ai_analyze"):
        with st.spinner(f"Gathering data and consulting {ollama_model}..."):
            context = _gather_context(db_id, schema_filter, table_filter)
            prompt = _build_prompt(context, scope)

            try:
                response = _call_ollama(prompt, ollama_url, ollama_model)
                st.session_state['ai_last_response'] = response
                st.session_state['ai_last_context'] = context
                st.session_state['ai_chat_history'] = [
                    {'role': 'user', 'content': f'Analyze {scope}'},
                    {'role': 'assistant', 'content': response}
                ]
            except Exception as e:
                st.error(f"Ollama error: {e}")
                st.info(f"Verify Ollama is running at {ollama_url} with model {ollama_model}")

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

            with st.spinner("Thinking..."):
                try:
                    answer = _call_ollama(followup_prompt, ollama_url, ollama_model)
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


def _call_ollama(prompt: str, url: str, model: str) -> str:
    """Call the Ollama API for text generation."""
    payload = json.dumps({
        'model': model,
        'prompt': prompt,
        'stream': False,
        'options': {'temperature': 0.3, 'num_predict': 2000}
    }).encode('utf-8')

    req = urllib.request.Request(
        f"{url}/api/generate",
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    return result.get('response', 'No response from model.')


if __name__ == "__main__":
    show_ai_advisor_page()
