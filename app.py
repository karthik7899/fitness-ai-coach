import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone
import google.generativeai as genai
from dotenv import load_dotenv

# Import our integration modules
import db
import google_auth
import sync_gdrive
import sync_googlefit
import sync_strava
import publish_gdrive

# Load local environment configuration
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

# Setup page config
st.set_page_config(
    page_title="Aura // Personal Fitness Coach",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Advanced CSS overrides to create a premium, clean, high-end SaaS product
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@400;500;700&display=swap');
    
    /* Clean Hide Streamlit Default UI elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .viewerBadge {display: none !important;}
    
    /* Main Layout Framework */
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1250px !important;
    }
    
    .stApp {
        background: radial-gradient(circle at 50% 50%, rgba(18, 14, 32, 1) 0%, rgba(8, 8, 12, 1) 100%);
        color: #f1f5f9;
    }
    
    /* Sidebar styling overrides */
    [data-testid="stSidebar"] {
        background-color: #0b0816 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Typography */
    .glow-header {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 700;
        background: linear-gradient(135deg, #a855f7 0%, #10b981 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.5rem;
        margin-bottom: 0px;
        letter-spacing: -1.5px;
    }
    
    .glow-subheader {
        font-family: 'Space Grotesk', sans-serif;
        color: #64748b;
        font-size: 0.8rem;
        margin-bottom: 1.5rem;
        text-transform: uppercase;
        letter-spacing: 3px;
        font-weight: 500;
    }
    
    /* Modern Glassmorphic Cards */
    .glass-card {
        background: rgba(22, 18, 38, 0.45);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.04);
        border-radius: 16px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 10px 30px 0 rgba(0, 0, 0, 0.35);
        transition: border 0.3s ease, box-shadow 0.3s ease;
    }
    
    .glass-card:hover {
        border: 1px solid rgba(168, 85, 247, 0.25);
        box-shadow: 0 10px 35px 0 rgba(168, 85, 247, 0.05);
    }
    
    /* Metrics block formatting */
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
        margin: 2px 0;
        letter-spacing: -0.5px;
    }
    
    .metric-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        color: #64748b;
        letter-spacing: 1.5px;
        font-weight: 600;
    }
    
    /* Subtle neon border indicators */
    .border-purple { border-left: 4px solid #a855f7; }
    .border-emerald { border-left: 4px solid #10b981; }
    .border-blue { border-left: 4px solid #3b82f6; }
    .border-coral { border-left: 4px solid #f97316; }
    
    /* Connection Status Badges */
    .status-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .status-connected {
        background-color: rgba(16, 185, 129, 0.1);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.2);
    }
    
    .status-disconnected {
        background-color: rgba(239, 68, 68, 0.1);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.2);
    }
    
    /* Custom tab bars */
    .stTabs [data-baseweb="tab-list"] {
        gap: 16px;
        background-color: transparent;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        background-color: transparent;
        color: #94a3b8;
        font-weight: 500;
        font-size: 0.95rem;
        border: none;
    }
    
    .stTabs [aria-selected="true"] {
        color: #10b981 !important;
        border-bottom: 2px solid #10b981 !important;
        font-weight: 600;
    }
    
    /* Custom Streamlit Buttons styling */
    .stButton>button {
        background: linear-gradient(135deg, rgba(168, 85, 247, 0.12) 0%, rgba(16, 185, 129, 0.12) 100%) !important;
        border: 1px solid rgba(168, 85, 247, 0.3) !important;
        color: #f1f5f9 !important;
        font-weight: 600 !important;
        padding: 0.4rem 0.8rem !important;
        border-radius: 10px !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 12px rgba(168, 85, 247, 0.05);
    }
    
    .stButton>button:hover {
        transform: translateY(-1px);
        background: linear-gradient(135deg, rgba(168, 85, 247, 0.25) 0%, rgba(16, 185, 129, 0.25) 100%) !important;
        border-color: #10b981 !important;
        box-shadow: 0 6px 20px rgba(16, 185, 129, 0.15);
    }
    
    /* Expander boxes styling */
    .streamlit-expanderHeader {
        background-color: rgba(22, 18, 38, 0.35) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 10px !important;
        color: #f1f5f9 !important;
    }
    .streamlit-expanderContent {
        background-color: rgba(22, 18, 38, 0.15) !important;
        border: 1px solid rgba(255, 255, 255, 0.03) !important;
        border-top: none !important;
        border-radius: 0 0 10px 10px !important;
    }
    
    /* Text input styling */
    div[data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.02) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 10px !important;
    }
    
    /* Sidebar text input overrides */
    [data-testid="stSidebar"] div[data-baseweb="input"] {
        background-color: rgba(255, 255, 255, 0.05) !important;
    }
    
    /* Chat message container styling */
    .stChatMessage {
        background-color: rgba(22, 18, 38, 0.3) !important;
        border: 1px solid rgba(255, 255, 255, 0.04) !important;
        border-radius: 12px !important;
        padding: 0.75rem 1rem !important;
        margin-bottom: 0.75rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# OAuth Flow Intercept (Strava)
# ----------------------------------------------------
query_params = st.query_params
if 'code' in query_params:
    auth_code = query_params['code']
    try:
        sync_strava.exchange_code_for_token(auth_code)
        st.toast("🎉 Strava Connected!", icon="🏃")
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Strava Auth Error: {e}")

# ----------------------------------------------------
# Sidebar Setup (Connections Hub)
# ----------------------------------------------------
with st.sidebar:
    st.markdown("<h2 style='font-family:Space Grotesk; font-weight:700; color:#ffffff; font-size:1.4rem; letter-spacing:-0.5px;'>CONNECTIONS</h2>", unsafe_allow_html=True)
    st.markdown("Link your fitness accounts below.")
    st.markdown("---")
    
    # 1. Gemini Config
    st.markdown("### ⚡ Gemini Engine")
    api_key_env = os.getenv("GEMINI_API_KEY")
    # Clean quotes
    if api_key_env:
        api_key_env = api_key_env.strip('"').strip("'").strip()
        
    if api_key_env and api_key_env != "your_gemini_api_key_here" and api_key_env != "":
        gemini_api_key = api_key_env
        st.markdown("<span class='status-badge status-connected'>ACTIVE (.env)</span>", unsafe_allow_html=True)
    else:
        # Fallback to secrets
        try:
            gemini_api_key = st.secrets["GEMINI_API_KEY"].strip('"').strip("'").strip()
            st.markdown("<span class='status-badge status-connected'>ACTIVE (secrets)</span>", unsafe_allow_html=True)
        except Exception:
            gemini_api_key = st.text_input("Enter Gemini API Key:", type="password")
            if gemini_api_key:
                st.markdown("<span class='status-badge status-connected'>ACTIVE (manual)</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='status-badge status-disconnected'>KEYS MISSING</span>", unsafe_allow_html=True)
            
    st.markdown("---")
    
    # 2. Google Connection (Drive & Fit)
    st.markdown("### 🔑 Google Services")
    google_ok = google_auth.is_google_connected()
    if google_ok:
        st.markdown("<span class='status-badge status-connected'>CONNECTED</span>", unsafe_allow_html=True)
        if st.button("Disconnect Google", use_container_width=True):
            db.delete_token('google')
            st.rerun()
    else:
        st.markdown("<span class='status-badge status-disconnected'>NOT CONNECTED</span>", unsafe_allow_html=True)
        if st.button("Connect Google Account", use_container_width=True):
            try:
                google_auth.get_google_credentials()
                st.success("Google connected!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
                
    st.markdown("---")
    
    # 3. Strava Connection
    st.markdown("### 🏃 Strava Account")
    strava_ok = sync_strava.is_strava_connected()
    if strava_ok:
        st.markdown("<span class='status-badge status-connected'>CONNECTED</span>", unsafe_allow_html=True)
        if st.button("Disconnect Strava", use_container_width=True):
            db.delete_token('strava')
            st.rerun()
    else:
        st.markdown("<span class='status-badge status-disconnected'>NOT CONNECTED</span>", unsafe_allow_html=True)
        client_id, _ = sync_strava.get_credentials()
        if client_id and client_id != "your_strava_client_id_here" and client_id != "":
            redirect_uri = "http://localhost:8501/"
            strava_auth_url = f"https://www.strava.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=activity:read_all"
            st.markdown(f'<a href="{strava_auth_url}" target="_self"><button style="width:100%; border:none; padding:10px; background-color:#fc5200; color:white; border-radius:8px; font-weight:600; cursor:pointer;">Authorize Strava</button></a>', unsafe_allow_html=True)
        else:
            st.warning("Please configure client_id in secrets/env.")
            
    st.markdown("---")
    
    # 4. Sync Buttons
    st.markdown("### 🔄 Sync Controller")
    if google_ok or strava_ok:
        if st.button("SYNC ALL FITNESS DATA", use_container_width=True, type="primary"):
            with st.spinner("Synchronizing telemetry..."):
                sync_summary = []
                
                # Fitnotes Google Drive Sync
                if google_ok:
                    try:
                        fitnotes_count = sync_gdrive.sync_fitnotes()
                        sync_summary.append(f"💪 FitNotes: {fitnotes_count} sets synced")
                    except Exception as e:
                        sync_summary.append(f"❌ FitNotes error: {str(e)[:50]}")
                        
                    # Google Fit Sync
                    try:
                        fit_ok = sync_googlefit.sync_googlefit()
                        if fit_ok:
                            sync_summary.append("❤️ Google Fit metrics synced")
                        else:
                            sync_summary.append("⚠️ Google Fit: No data")
                    except Exception as e:
                        sync_summary.append(f"❌ Google Fit error: {str(e)[:50]}")
                        
                # Strava Sync
                if strava_ok:
                    try:
                        strava_count = sync_strava.sync_strava_activities()
                        sync_summary.append(f"🏃 Strava: {strava_count} activities synced")
                    except Exception as e:
                        sync_summary.append(f"❌ Strava error: {str(e)[:50]}")
                        
                # Google Drive Telemetry File Publish (For Gemini App Extension)
                if google_ok:
                    try:
                        pub_ok = publish_gdrive.publish_report_to_gdrive()
                        if pub_ok:
                            sync_summary.append("📤 Gemini app profile updated on Drive")
                        else:
                            sync_summary.append("⚠️ Gemini profile: Sync failed")
                    except Exception as e:
                        sync_summary.append(f"❌ Gemini Profile publish error: {str(e)[:50]}")
                        
                st.session_state['last_sync'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Show Toast Summary
                st.toast("Sync complete!", icon="✅")
                for s in sync_summary:
                    st.sidebar.info(s)
    else:
        st.info("Authenticate Google or Strava to enable Sync.")
        
    if 'last_sync' in st.session_state:
        st.caption(f"Last Sync: {st.session_state['last_sync']}")

# ----------------------------------------------------
# Main Layout Header
# ----------------------------------------------------
st.markdown("<h1 class='glow-header'>⚡ AURA</h1>", unsafe_allow_html=True)
st.markdown("<div class='glow-subheader'>Premium Fitness Dashboard & Gemini AI Coach</div>", unsafe_allow_html=True)

# Load Data for Visualizations
conn = db.get_db_connection()
df_fitnotes = pd.read_sql_query("SELECT * FROM fitnotes_workouts ORDER BY date DESC", conn)
df_strava = pd.read_sql_query("SELECT * FROM strava_activities ORDER BY start_date DESC", conn)
df_daily = pd.read_sql_query("SELECT * FROM google_fit_daily ORDER BY date DESC", conn)
conn.close()

# ----------------------------------------------------
# Metric Cards Row (Last 7 Days Highlights)
# ----------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    last_steps = 0
    if not df_daily.empty:
        last_steps = df_daily.iloc[0]['steps']
    st.markdown(f"""
    <div class='glass-card border-emerald'>
        <div class='metric-label'>Daily Steps (Today)</div>
        <div class='metric-value'>{last_steps:,}</div>
        <div style='font-size:0.75rem; color:#34d399;'>Goal: 10,000 steps</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    last_sleep = 0.0
    if not df_daily.empty and 'sleep_hours' in df_daily.columns:
        last_sleep = df_daily.iloc[0]['sleep_hours']
    st.markdown(f"""
    <div class='glass-card border-purple'>
        <div class='metric-label'>Sleep (Last Night)</div>
        <div class='metric-value'>{last_sleep:.1f} hrs</div>
        <div style='font-size:0.75rem; color:#c084fc;'>Goal: 8.0 hrs</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    recent_runs = df_strava[df_strava['type'] == 'Run']
    last_run_dist = 0.0
    if not recent_runs.empty:
        last_run_dist = recent_runs.iloc[0]['distance'] / 1000.0  # to km
    st.markdown(f"""
    <div class='glass-card border-blue'>
        <div class='metric-label'>Last Run (Strava)</div>
        <div class='metric-value'>{last_run_dist:.2f} km</div>
        <div style='font-size:0.75rem; color:#60a5fa;'>Telemetry Cached</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    sets_count = 0
    if not df_fitnotes.empty:
        latest_date = df_fitnotes.iloc[0]['date']
        sets_count = len(df_fitnotes[df_fitnotes['date'] == latest_date])
    st.markdown(f"""
    <div class='glass-card border-coral'>
        <div class='metric-label'>Latest Workout Sets</div>
        <div class='metric-value'>{sets_count} sets</div>
        <div style='font-size:0.75rem; color:#fb923c;'>FitNotes Database</div>
    </div>
    """, unsafe_allow_html=True)

# ----------------------------------------------------
# Multi-Tab Section
# ----------------------------------------------------
tab_coach, tab_strength, tab_cardio, tab_daily = st.tabs([
    "🤖 Gemini AI Coach", 
    "💪 Strength Volume (FitNotes)", 
    "🏃 Cardio Engine (Strava)", 
    "❤️ Daily Tracking (Google Fit)"
])

# Assemble context helper
def compile_fitness_context():
    cutoff_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    fit_recent = df_fitnotes[df_fitnotes['date'] >= cutoff_date]
    strava_recent = df_strava[df_strava['start_date'] >= cutoff_date]
    daily_recent = df_daily[df_daily['date'] >= cutoff_date]
    
    context = "## USER FITNESS DATA (LAST 14 DAYS)\n\n"
    
    context += "### Daily Activity (Steps, Sleep):\n"
    if not daily_recent.empty:
        for _, row in daily_recent.iterrows():
            context += f"- Date: {row['date']}, Steps: {row['steps']:,}, Sleep: {row['sleep_hours']:.1f} hrs, Active Minutes: {row['active_minutes']:.1f} mins\n"
    else:
        context += "- No Google Fit steps/sleep telemetry available.\n"
    context += "\n"
    
    context += "### Strava Cardio Activities:\n"
    if not strava_recent.empty:
        for _, row in strava_recent.iterrows():
            dist_km = row['distance'] / 1000.0
            duration_mins = row['moving_time'] / 60.0
            avg_pace = ""
            if row['type'] == 'Run' and dist_km > 0:
                pace_dec = duration_mins / dist_km
                pace_min = int(pace_dec)
                pace_sec = int((pace_dec - pace_min) * 60)
                avg_pace = f", Pace: {pace_min}:{pace_sec:02d} min/km"
            context += f"- Date: {row['start_date'][:10]}, Type: {row['type']}, Name: {row['name']}, Distance: {dist_km:.2f} km, Duration: {duration_mins:.1f} mins{avg_pace}\n"
    else:
        context += "- No Strava cardio history found.\n"
    context += "\n"
    
    context += "### FitNotes Strength Workouts:\n"
    if not fit_recent.empty:
        grouped = fit_recent.groupby(['date', 'exercise', 'category'])
        current_date = ""
        for (date, exercise, category), group in grouped:
            if date != current_date:
                context += f"\n- Workout Date: {date}\n"
                current_date = date
            
            sets_str = []
            for _, row in group.iterrows():
                if row['reps'] > 0:
                    sets_str.append(f"{row['reps']}r @ {row['weight']}{row['weight_unit']}")
                elif row['distance'] > 0:
                    sets_str.append(f"{row['distance']}{row['distance_unit']} in {row['time']}")
            context += f"  * {exercise} ({category}): " + ", ".join(sets_str) + "\n"
    else:
        context += "- No FitNotes strength workouts recorded.\n"
        
    return context

# ====================================================
# TAB 1: GEMINI COACH CHAT
# ====================================================
with tab_coach:
    st.markdown("### Talk with Aura, your AI Fitness Coach")
    
    # 📋 Clipboard Copy Panel for official Gemini App
    with st.expander("📋 Copy Fitness Profile for Official Gemini App"):
        st.markdown("<small style='color:#94a3b8;'>Click the copy icon in the codeblock below to copy your recent data, and paste it directly into your official Gemini App chat!</small>", unsafe_allow_html=True)
        try:
            raw_telemetry = compile_fitness_context()
            st.code(raw_telemetry, language="markdown")
        except Exception as e:
            st.error(f"Error gathering telemetry context: {e}")
            
    st.markdown("---")
    
    if not gemini_api_key:
        st.warning("Please configure your Gemini API Key in the sidebar to activate the local AI Coach Chat.")
    else:
        try:
            genai.configure(api_key=gemini_api_key)
        except Exception as e:
            st.error(f"Error configuring Gemini SDK: {e}")

        # Init chat state
        if "messages" not in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "Welcome back! I have parsed your training database. Ask me about your strength progression, pacing, sleep recovery patterns, or planning your next training blocks based on your telemetry."}
            ]
            
        # Display chat history
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
                
        # Accept User Input
        if user_query := st.chat_input("Ask Aura..."):
            st.session_state.messages.append({"role": "user", "content": user_query})
            with st.chat_message("user"):
                st.write(user_query)
                
            with st.spinner("Aura is analyzing telemetry..."):
                try:
                    fitness_context = compile_fitness_context()
                    
                    system_prompt = f"""
                    You are "Aura", an elite, world-class personal fitness coach, sports physician, and strength training expert.
                    Your goal is to guide the athlete using evidence-based training principles, exercise physiology, and data analytics.
                    
                    Below is the user's actual health and training telemetry compiled from their FitNotes, Google Fit, and Strava accounts over the last 14 days.
                    
                    {fitness_context}
                    
                    INSTRUCTIONS:
                    1. Refer to their actual telemetry parameters (pacing, steps, lift volumes, sleep duration, exercise selection) directly in your answers.
                    2. Keep answers concise, highly structured, encouraging, and tailored to their logs.
                    3. If they ask about recovery, correlate it with their sleep and step load.
                    4. Suggest specific progression guidelines (e.g. progressive overload, pacing strategies, active recovery) based on their data.
                    """
                    
                    model = genai.GenerativeModel(
                        model_name="gemini-1.5-flash",
                        system_instruction=system_prompt
                    )
                    
                    gemini_history = []
                    for msg in st.session_state.messages[1:-1]:
                        gemini_history.append({
                            "role": "user" if msg["role"] == "user" else "model",
                            "parts": [msg["content"]]
                        })
                    
                    chat = model.start_chat(history=gemini_history)
                    response = chat.send_message(user_query)
                    
                    with st.chat_message("assistant"):
                        st.write(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                except Exception as e:
                    st.error(f"Chat error: {e}")

# ====================================================
# TAB 2: STRENGTH ANALYTICS
# ====================================================
with tab_strength:
    st.markdown("### 💪 Strength Telemetry (FitNotes Database)")
    
    with st.expander("📁 Import FitNotes Backup (.fitnotes / .csv) Manually"):
        uploaded_file = st.file_uploader("Upload backup file:", type=["fitnotes", "db", "sqlite", "csv"], key="strength_tab_uploader")
        if uploaded_file is not None:
            with st.spinner("Parsing logs..."):
                try:
                    file_bytes = uploaded_file.read()
                    file_name = uploaded_file.name
                    workouts = []
                    if file_name.endswith('.csv'):
                        workouts = sync_gdrive.parse_fitnotes_csv(file_bytes)
                    else:
                        workouts = sync_gdrive.parse_fitnotes_sqlite(file_bytes)
                        
                    if workouts:
                        db.save_fitnotes_workouts(workouts)
                        
                        # Update Drive telemetry file if Google is connected
                        google_ok = google_auth.is_google_connected()
                        if google_ok:
                            try:
                                publish_gdrive.publish_report_to_gdrive()
                            except Exception:
                                pass
                                
                        st.toast(f"Parsed {len(workouts)} sets successfully!", icon="💪")
                        st.success(f"Loaded {len(workouts)} sets! Reloading...")
                        st.rerun()
                    else:
                        st.error("No workouts found in file.")
                except Exception as e:
                    st.error(f"Failed to parse file: {e}")

    if df_fitnotes.empty:
        st.info("No strength workout records available. Sync your FitNotes backups in the sidebar or upload a file above.")
    else:
        df_fitnotes['date'] = pd.to_datetime(df_fitnotes['date'])
        df_fitnotes['volume'] = df_fitnotes['weight'] * df_fitnotes['reps']
        
        col_s1, col_s2 = st.columns([2, 1])
        
        with col_s1:
            st.markdown("#### Workout Lift Volume Trend")
            volume_df = df_fitnotes.groupby('date')['volume'].sum().reset_index()
            fig_vol = px.line(
                volume_df, x='date', y='volume',
                labels={'volume': 'Total Volume', 'date': 'Date'},
                template='plotly_dark'
            )
            fig_vol.update_traces(line_color='#f97316', line_width=3, hovertemplate='Date: %{x}<br>Volume: %{y:,.0f} kg')
            fig_vol.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=10, b=10),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)', showgrid=True),
                xaxis=dict(showgrid=False)
            )
            st.plotly_chart(fig_vol, use_container_width=True)
            
        with col_s2:
            st.markdown("#### Target Muscle Group Breakdown")
            cat_df = df_fitnotes.groupby('category').size().reset_index(name='sets')
            fig_cat = px.pie(
                cat_df, values='sets', names='category',
                hole=0.5, template='plotly_dark',
                color_discrete_sequence=px.colors.sequential.Sunsetdark
            )
            fig_cat.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=10, r=10, t=10, b=10),
                legend=dict(font=dict(size=10))
            )
            st.plotly_chart(fig_cat, use_container_width=True)
            
        st.markdown("#### Individual Exercise Progression Tracker")
        exercise_list = sorted(df_fitnotes['exercise'].unique())
        selected_ex = st.selectbox("Select Exercise:", exercise_list)
        
        ex_df = df_fitnotes[df_fitnotes['exercise'] == selected_ex].sort_values('date')
        
        ex_df['est_1rm'] = ex_df.apply(
            lambda r: r['weight'] / (1.0278 - (0.0278 * r['reps'])) if r['reps'] > 0 else r['weight'],
            axis=1
        )
        
        prog_df = ex_df.groupby('date').agg({'weight': 'max', 'est_1rm': 'max'}).reset_index()
        
        fig_prog = go.Figure()
        fig_prog.add_trace(go.Scatter(x=prog_df['date'], y=prog_df['weight'], name='Max Weight Loaded', line=dict(color='#3b82f6', width=2.5)))
        fig_prog.add_trace(go.Scatter(x=prog_df['date'], y=prog_df['est_1rm'], name='Estimated 1RM', line=dict(color='#ef4444', width=2, dash='dot')))
        
        fig_prog.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis_title="Date",
            yaxis_title=f"Weight ({df_fitnotes['weight_unit'].iloc[0]})",
            margin=dict(l=20, r=20, t=10, b=10),
            yaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10))
        )
        st.plotly_chart(fig_prog, use_container_width=True)

# ====================================================
# TAB 3: CARDIO ANALYTICS
# ====================================================
with tab_cardio:
    st.markdown("### 🏃 Cardio Performance Telemetry (Strava API)")
    if df_strava.empty:
        st.info("No cardio records available. Authorize and sync your Strava account.")
    else:
        df_strava['start_date'] = pd.to_datetime(df_strava['start_date'])
        df_strava['distance_km'] = df_strava['distance'] / 1000.0
        df_strava['duration_mins'] = df_strava['moving_time'] / 60.0
        
        def calc_pace(row):
            if row['type'] == 'Run' and row['distance_km'] > 0:
                pace_dec = row['duration_mins'] / row['distance_km']
                return pace_dec
            return None
        df_strava['pace_min_km'] = df_strava.apply(calc_pace, axis=1)
        
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.markdown("#### Activity Mileage Summary")
            mileage_df = df_strava.groupby('type')['distance_km'].sum().reset_index()
            fig_mile = px.bar(
                mileage_df, x='type', y='distance_km',
                labels={'distance_km': 'Total Distance (km)', 'type': 'Activity Type'},
                template='plotly_dark', color='type',
                color_discrete_sequence=px.colors.sequential.Agsunset
            )
            fig_mile.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=10, b=10),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                showlegend=False
            )
            st.plotly_chart(fig_mile, use_container_width=True)
            
        with col_c2:
            st.markdown("#### Running Pace Progression Trend")
            runs_df = df_strava[df_strava['type'] == 'Run'].dropna(subset=['pace_min_km']).sort_values('start_date')
            
            if runs_df.empty:
                st.info("No running pace logs found. Record runs on Strava to view pace trends.")
            else:
                # Custom pace formatter for hover labels
                runs_df['pace_label'] = runs_df['pace_min_km'].apply(
                    lambda p: f"{int(p)}:{int((p-int(p))*60):02d} /km"
                )
                
                fig_pace = px.line(
                    runs_df, x='start_date', y='pace_min_km',
                    labels={'pace_min_km': 'Pace (Minutes/km)', 'start_date': 'Date'},
                    template='plotly_dark',
                    custom_data=['pace_label']
                )
                fig_pace.update_traces(
                    line_color='#a855f7', 
                    line_width=3, 
                    hovertemplate='Date: %{x}<br>Pace: %{customdata[0]}'
                )
                fig_pace.update_yaxes(autorange="reverse")
                fig_pace.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(0,0,0,0)',
                    margin=dict(l=20, r=20, t=10, b=10),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
                )
                st.plotly_chart(fig_pace, use_container_width=True)

# ====================================================
# TAB 4: DAILY METRICS
# ====================================================
with tab_daily:
    st.markdown("### ❤️ Daily Activity Telemetry (Google Fit Sync)")
    if df_daily.empty:
        st.info("No wellness telemetry available. Connect your Google account and sync.")
    else:
        df_daily['date'] = pd.to_datetime(df_daily['date'])
        df_daily = df_daily.sort_values('date')
        
        col_d1, col_d2 = st.columns(2)
        
        with col_d1:
            st.markdown("#### Daily Step Counts")
            fig_steps = px.bar(
                df_daily, x='date', y='steps',
                labels={'steps': 'Steps Count', 'date': 'Date'},
                template='plotly_dark'
            )
            fig_steps.update_traces(marker_color='#10b981', hovertemplate='Date: %{x}<br>Steps: %{y:,}')
            fig_steps.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=10, b=10),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig_steps, use_container_width=True)
            
        with col_d2:
            st.markdown("#### Sleep Log (Hours/Night)")
            fig_sleep = px.area(
                df_daily, x='date', y='sleep_hours',
                labels={'sleep_hours': 'Sleep Duration (hrs)', 'date': 'Date'},
                template='plotly_dark'
            )
            fig_sleep.update_traces(
                line_color='#8b5cf6', 
                fillcolor='rgba(139, 92, 246, 0.1)', 
                hovertemplate='Date: %{x}<br>Sleep: %{y:.1f} hrs'
            )
            fig_sleep.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=20, r=20, t=10, b=10),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig_sleep, use_container_width=True)
