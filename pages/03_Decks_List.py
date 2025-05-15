import streamlit as st
from utils import update_global_user_profile_stats, export_deck_to_csv, delete_deck_from_db_and_session, update_deck_metadata_in_db
import datetime

st.title("📚 My Decks")

# update_global_user_profile_stats() # Called by initialize_app_session_state, and after deletions/creations

decks = st.session_state.get('decks', {})

if not decks:
    st.info("No decks yet. Go to 'Input Content' to create one!")
    if st.button("➕ Create New Deck"): st.switch_page("pages/02_Input_Content.py")
else:
    st.markdown(f"You have **{len(decks)}** deck(s).")
    sort_options = {
        "Last Accessed (Newest First)": lambda d: d.get("last_accessed_at", d.get("created_at", "")),
        "Creation Date (Newest First)": lambda d: d.get("created_at", ""),
        "Title (A-Z)": lambda d: d.get("title", "").lower(),
        "Number of Cards (High to Low)": lambda d: len(d.get("cards", [])),
    }
    sort_key_name = st.selectbox("Sort decks by:", list(sort_options.keys()), key="deck_sort_selector")
    search_term = st.text_input("Search decks by title:", key="deck_search_input")

    # Get deck items and sort them based on session state data
    # The DB load already sorts by last_accessed_at, but UI sort provides more options
    deck_items = list(decks.items())
    sorted_deck_items = sorted(
        deck_items,
        key=lambda item: sort_options[sort_key_name](item[1]), # item[1] is the deck dict
        reverse=("Date" in sort_key_name or "Newest" in sort_key_name or "High to Low" in sort_key_name)
    )
    
    for deck_id, deck in sorted_deck_items:
        if search_term.lower() not in deck.get("title", "").lower():
            continue

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(deck.get("title", "Untitled Deck"))
                card_count = len(deck.get("cards", []))
                st.caption(f"{card_count} cards | Created: {deck.get('created_at', 'N/A')[:10]} | Source: {deck.get('source_type', 'N/A')}")
                last_acc = deck.get("last_accessed_at", deck.get("created_at", 'Never'))
                if last_acc != 'Never': last_acc = datetime.datetime.fromisoformat(last_acc).strftime('%Y-%m-%d %H:%M')
                st.caption(f"Last accessed: {last_acc}")
            with col2:
                if st.button("👁️ View / Study", key=f"view_deck_{deck_id}", use_container_width=True, type="primary"):
                    st.session_state.current_deck_id = deck_id
                    # Update last accessed time in DB and session
                    now_iso = datetime.datetime.now().isoformat()
                    update_deck_metadata_in_db(deck_id, last_accessed_at=now_iso)
                    st.switch_page("pages/04_Deck_View.py")

                csv_data = export_deck_to_csv(deck)
                st.download_button(label="📥 Export CSV", data=csv_data,
                                   file_name=f"{deck.get('title', 'deck').replace(' ', '_')}_export.csv",
                                   mime='text/csv', key=f"export_deck_list_{deck_id}", use_container_width=True)
                if st.button("🗑️ Delete Deck", key=f"delete_deck_list_{deck_id}", use_container_width=True):
                    st.session_state[f"confirm_delete_list_{deck_id}"] = True # Trigger confirmation

            if st.session_state.get(f"confirm_delete_list_{deck_id}"):
                st.warning(f"Delete '{deck.get('title', '')}'? Cannot be undone.")
                c1, c2, c3 = st.columns([1,1,2])
                if c1.button("✅ Yes, Delete", key=f"confirm_del_list_yes_{deck_id}"):
                    delete_deck_from_db_and_session(deck_id) # This now handles DB and session
                    del st.session_state[f"confirm_delete_list_{deck_id}"]
                    st.success(f"Deck '{deck.get('title', '')}' deleted.")
                    st.rerun()
                if c2.button("❌ No, Cancel", key=f"confirm_del_list_no_{deck_id}"):
                    del st.session_state[f"confirm_delete_list_{deck_id}"]
                    st.rerun()
            st.markdown("---")
    # No need for "Refresh Deck List" button as state is loaded from DB on init
    # and updated on actions.