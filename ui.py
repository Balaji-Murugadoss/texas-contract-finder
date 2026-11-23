"""Streamlit front end. It talks only to YOUR API, so the API key decides what a user can see.
Run:  streamlit run ui.py   (with the API running in another tab)"""
import os

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")      # Docker and Azure set this to the API's address
EXAMPLES = ["What contracts are open for us right now?",
            "Check the fit of the best 2 for us.",
            "Who usually wins contracts like ours, and how big are they?"]

st.set_page_config(page_title="Texas Contract Finder", page_icon=":material/travel_explore:", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 1.6rem; max-width: 1150px;}
#MainMenu, footer {visibility: hidden;}
.hero {background: #0B2545; border-radius: 18px; padding: 1.6rem 1.9rem 1.3rem; margin-bottom: 1.2rem;}
.hero h1 {color: #FFFFFF; font-size: 2rem; margin: 0; letter-spacing: -0.5px;}
.hero p {color: #C8D6EA; margin: .35rem 0 .2rem; font-size: 1.02rem;}
.pill {display: inline-block; background: rgba(255,255,255,.10); color: #E8F0FA; border: 1px solid rgba(255,255,255,.18);
       border-radius: 999px; padding: .18rem .7rem; font-size: .78rem; margin: .55rem .35rem 0 0;}
.card {background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px; padding: 1rem 1.15rem; height: 100%;}
.card h4 {margin: 0 0 .3rem; color: #0B2545;}
.card p {margin: 0; color: #4A5568; font-size: .92rem;}
.profile {background: #EEF6F3; border: 1px solid #CFE6DD; border-radius: 12px; padding: .8rem .9rem; font-size: .9rem;}
.profile b {color: #0B2545;}
</style>""", unsafe_allow_html=True)


def api(method: str, path: str, key: str, **kwargs):
    """Every call goes through the API with the key: the UI never touches the database itself."""
    try:
        return httpx.request(method, f"{API_URL}{path}", headers={"X-API-Key": key}, timeout=180, **kwargs)
    except httpx.HTTPError:
        st.error(f"Can't reach the API at {API_URL}. Is it running?")
        st.stop()


if "messages" not in st.session_state:
    st.session_state.messages = []          # each: {"role", "content", optional "meta"}

# ---------- Sidebar: sign in, profile, shortlist ----------
with st.sidebar:
    st.markdown("### :material/lock: Sign in")
    key = st.text_input("Business API key", type="password", label_visibility="collapsed",
                        placeholder="Paste your business API key")
    profile = None
    if key:
        r = api("GET", "/me", key)
        if r.status_code == 200:
            profile = r.json()
            st.markdown(f"""<div class="profile"><b>{profile['name']}</b><br>
                NAICS {profile['naics_codes']} &middot; {profile['state']} &middot; {profile['employees']} people<br>
                <span style="color:#4A5568">{profile['notes'] or ''}</span></div>""", unsafe_allow_html=True)
        else:
            st.error("That key isn't recognized.")
    if profile:
        st.markdown("### :material/bookmark: Saved shortlist")
        if st.button("Show shortlist", width="stretch"):
            rows = api("GET", "/matches", key).json()
            if rows:
                st.dataframe(rows, hide_index=True, width="stretch")
            else:
                st.caption("Nothing saved yet. Ask the assistant to save a match.")
        if st.button(":material/refresh: New conversation", width="stretch"):
            st.session_state.messages = []
            st.rerun()
    st.divider()
    st.caption("Every answer is limited to your business's data. Deadlines are US Central. "
               "Texas ESBD documents can't be read automatically; open the links.")

# ---------- Header ----------
st.markdown("""<div class="hero">
  <h1>Texas Contract Finder</h1>
  <p>Federal and Texas opportunities, matched to your business, checked against the bid documents.</p>
  <span class="pill">SAM.gov</span><span class="pill">USAspending</span><span class="pill">Texas ESBD</span>
  <span class="pill">Fit scores with citations</span>
</div>""", unsafe_allow_html=True)

if not profile:
    cols = st.columns(3)
    for col, (title, text) in zip(cols, [
            ("Find", "Open federal and Texas bids that match your industry codes, with time left to prepare."),
            ("Read", "Pulls the relevant pages from long bid packages and cites file and page."),
            ("Judge", "Scores fit against your profile and flags blockers like bonding or service area.")]):
        col.markdown(f'<div class="card"><h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)
    st.info("Paste your business API key in the sidebar to start.", icon=":material/key:")
    st.stop()

# ---------- Chat ----------
if not st.session_state.messages:
    st.markdown("##### Try one of these")
    for col, example in zip(st.columns(len(EXAMPLES)), EXAMPLES):
        if col.button(example, width="stretch"):
            st.session_state.pending = example
            st.rerun()

for m in st.session_state.messages:
    with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/smart_toy:"):
        st.markdown(m["content"])
        if m.get("meta"):
            meta = m["meta"]
            with st.expander(":material/troubleshoot: How I got this answer"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Tools used", len(meta["steps"]))
                c2.metric("Time", f"{meta['seconds']} s")
                c3.metric("Cost", f"${meta['cost_usd']:.4f}")
                if meta["steps"]:
                    st.dataframe([{"tool": s["tool"], "arguments": str(s["args"]), "seconds": s["seconds"],
                                   "error": s["error"] or ""} for s in meta["steps"]],
                                 hide_index=True, width="stretch")
                st.caption(f"Model: {meta['model']}")

question = st.chat_input("Ask about contracts, deadlines, documents or fit...") or st.session_state.pop("pending", None)
if question:
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    history = [{"role": m["role"], "content": m["content"][:4000]}     # the API accepts 10 turns, 4,000 chars each
               for m in st.session_state.messages[-10:]]
    with st.chat_message("assistant", avatar=":material/smart_toy:"):
        with st.spinner("Searching, reading and checking fit..."):
            r = api("POST", "/ask", key, json={"question": question, "history": history})
        if r.status_code != 200:
            st.error(f"{r.status_code}: {r.text}")
            st.stop()
        data = r.json()
    st.session_state.messages += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": data["answer"],
         "meta": {k: data[k] for k in ("steps", "seconds", "cost_usd", "model")}}]
    st.rerun()
