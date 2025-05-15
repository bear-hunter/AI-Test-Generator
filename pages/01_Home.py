import streamlit as st
from utils import update_global_user_profile_stats # Import from utils.py

# Ensure user profile stats are up-to-date when home page loads
update_global_user_profile_stats()

st.title("🏠 Home / Dashboard")

# Welcome Banner
st.header("Generate flashcards from your text in seconds!")
st.markdown("Upload a `.txt` file or paste your text to automatically create Q&A cards and tests.")

st.divider()

# Primary Actions
st.subheader("🚀 Get Started")
col1, col2 = st.columns(2)
with col1:
    if st.button("➕ Upload Text File (.txt only)", use_container_width=True, type="primary"):
        st.switch_page("pages/02_Input_Content.py")
with col2:
    if st.button("✍️ Paste Text", use_container_width=True, type="primary"):
        st.switch_page("pages/02_Input_Content.py")

st.divider()

# Recent Decks
st.subheader("📚 Recent Decks")
recent_decks_info = st.session_state.user_profile.get("recent_decks_info", [])

if not recent_decks_info:
    st.info("No decks created yet. Go to 'Input Content' to create your first deck!")
else:
    num_recent_to_show = min(len(recent_decks_info), 3) # Show up to 3
    deck_cols = st.columns(num_recent_to_show)
    for i in range(num_recent_to_show):
        deck_info = recent_decks_info[i] # Already sorted by recency in utils
        with deck_cols[i]:
            with st.container(border=True):
                st.markdown(f"**{deck_info['title']}**")
                st.caption(f"{deck_info['card_count']} cards | Created: {deck_info['created_at'][:10]}")
                if st.button(f"Continue  स्टडी Deck", key=f"continue_deck_home_{deck_info['id']}", use_container_width=True):
                    st.session_state.current_deck_id = deck_info['id']
                    st.switch_page("pages/04_Deck_View.py")

st.divider()

# Performance Overview
st.subheader("📊 Performance Overview")
profile = st.session_state.user_profile
total_cards = profile.get("total_cards_overall", 0)
mastery_perc = profile.get("mastery_percentage_overall", 0.0)
next_review_count = profile.get("cards_due_next_review_overall", 0)

perf_col1, perf_col2, perf_col3 = st.columns(3)
perf_col1.metric("Total Cards Created", f"{total_cards} 🃏")
perf_col2.metric("Overall Mastery", f"{mastery_perc:.1f}% 💪")
perf_col3.metric("Cards Due for Review", f"{next_review_count} 🗓️")

st.caption("Mastery and review counts are based on all your decks and practice sessions.")

if st.button("🔄 Refresh Stats"):
    update_global_user_profile_stats()
    st.rerun()