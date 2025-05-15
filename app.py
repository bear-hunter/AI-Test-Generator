import streamlit as st
from utils import (
    initialize_app_session_state, DEFAULT_GEMINI_API_KEY, GEMINI_MODEL_NAME, 
    configure_gemini_model, initialize_database # Added initialize_database
)
import logging

logger = logging.getLogger(__name__)

# --- Initialize Database First ---
# This should be one of the very first things your app does.
try:
    initialize_database()
    logger.info("Database check/initialization complete.")
except Exception as e:
    logger.error(f"CRITICAL: Database initialization failed: {e}")
    st.error(f"CRITICAL: Failed to initialize the application database: {e}. App may not function correctly.")
    # Optionally, st.stop() here if DB is absolutely critical for any page to load

# Page configuration (must be the first Streamlit command AFTER potential st.stop())
st.set_page_config(
    page_title="AI Q&A Flashcards",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state (this will now also load data from DB)
try:
    initialize_app_session_state()
    logger.info("Session state initialized (data loaded from DB).")
except Exception as e:
    logger.error(f"Error during session state initialization (DB loading): {e}")
    st.error(f"Error loading data: {e}. Some features might be affected.")


# Attempt initial model configuration if a non-placeholder key exists
if st.session_state.user_api_key and st.session_state.user_api_key != DEFAULT_GEMINI_API_KEY:
    if not st.session_state.get('gemini_model'):
        configure_gemini_model()

# Sidebar Content
st.sidebar.title("📝 AI Flashcard Generator")
st.sidebar.caption(f"Model: {st.session_state.get('gemini_model_name_config', GEMINI_MODEL_NAME)}")
st.sidebar.divider()

with st.sidebar.expander("⚙️ Profile & Settings", expanded=True):
    st.write("User Profile & App Settings")
    current_key_in_state = st.session_state.get('user_api_key', DEFAULT_GEMINI_API_KEY)
    display_value_for_input = "" if current_key_in_state == DEFAULT_GEMINI_API_KEY else current_key_in_state
    new_api_key_input = st.text_input(
        "Your Gemini API Key", value=display_value_for_input,
        placeholder="Enter your Google Gemini API Key", type="password",
        help="Get API key from Google AI Studio."
    )

    if st.button("Update API Key", key="update_api_key_btn_main"):
        if new_api_key_input and new_api_key_input != current_key_in_state:
            st.session_state.user_api_key = new_api_key_input
            st.session_state.gemini_model = None # Force re-init
            st.success("API Key submitted. Attempting to reconfigure...")
            if configure_gemini_model(force_reconfigure=True):
                st.success("Gemini model configured successfully!")
            # Error messages handled by configure_gemini_model or show_api_key_warning
            st.rerun()
        elif not new_api_key_input: st.warning("API Key field empty.")
        else: st.info("API Key is the same.")

    key_is_placeholder = (st.session_state.get('user_api_key') == DEFAULT_GEMINI_API_KEY or not st.session_state.get('user_api_key'))
    if key_is_placeholder:
        st.error("🛑 CRITICAL: Valid Gemini API Key required. AI features disabled.")
    elif st.session_state.get('show_api_key_warning', False):
        st.warning("⚠️ ATTENTION: Model configuration failed. Check API Key and permissions.")
    else:
        st.success("✅ Gemini API Key set & model appears configured.")
    st.info(f"Using Gemini model: `{st.session_state.get('gemini_model_name_config', GEMINI_MODEL_NAME)}`.")
    st.caption("Toggle Light/Dark mode via Streamlit's main menu (⋮) -> Settings.")

st.sidebar.divider()
st.sidebar.markdown("### Future-Proofing Ideas") # ... (as before)

# Main app content / landing page instruction
if 'page' not in st.query_params:
    st.markdown("## Welcome to the AI-Powered Q&A & Flashcard App!") # ... (as before)
    if st.session_state.get('show_api_key_warning', True):
        st.warning("Set your Gemini API Key in sidebar for AI features.", icon="🔑")
    else:
        st.info("Select a page from sidebar or go to 'Home'.")