import streamlit as st
from utils import update_global_user_profile_stats, export_deck_to_csv, delete_deck_from_db_and_session, update_deck_metadata_in_db
import datetime
import logging # Added for logging

logger = logging.getLogger(__name__) # Added for logging

st.title("📚 My Decks")

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
    sort_key_name = st.selectbox("Sort decks by:", list(sort_options.keys()), key="deck_sort_selector_listpage") # Unique key
    search_term = st.text_input("Search decks by title:", key="deck_search_input_listpage") # Unique key

    deck_items = list(decks.items())
    sorted_deck_items = sorted(
        deck_items,
        key=lambda item: sort_options[sort_key_name](item[1]),
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
                if last_acc != 'Never' and isinstance(last_acc, str): # Ensure it's a string before isoformat
                    try:
                        last_acc = datetime.datetime.fromisoformat(last_acc).strftime('%Y-%m-%d %H:%M')
                    except ValueError:
                        last_acc = "Invalid date format" # Or handle as appropriate
                elif last_acc == 'Never':
                    pass # Keep as 'Never'
                else: # If it's already a datetime object (less likely from DB direct load)
                    last_acc = last_acc.strftime('%Y-%m-%d %H:%M')


                st.caption(f"Last accessed: {last_acc}")
            with col2:
                if st.button("👁️ View / Study", key=f"view_deck_btn_{deck_id}", use_container_width=True, type="primary"):
                    # --- Section to clear old deck-specific view state ---
                    if st.session_state.get('current_deck_id') != deck_id:
                        logger.info(f"Switching deck view. Old deck ID: {st.session_state.get('current_deck_id')}, New deck ID: {deck_id}. Clearing deck-specific UI states.")
                        
                        # Flashcard related states
                        if 'fc_review_set' in st.session_state: del st.session_state.fc_review_set
                        if 'fc_current_card_index' in st.session_state: del st.session_state.fc_current_card_index
                        if 'fc_session_graded_count' in st.session_state: del st.session_state.fc_session_graded_count
                        
                        # Test related states
                        if 'test_review_set_active' in st.session_state: del st.session_state.test_review_set_active
                        if 'test_current_card_idx' in st.session_state: del st.session_state.test_current_card_idx
                        if 'test_session_graded_count_val' in st.session_state: del st.session_state.test_session_graded_count_val
                        if 'test_feedback_msg' in st.session_state: del st.session_state.test_feedback_msg
                        if 'test_selected_option_val' in st.session_state: del st.session_state.test_selected_option_val
                        if 'shuffled_opts_test' in st.session_state: del st.session_state.shuffled_opts_test
                        if 'current_test_card_id_opts' in st.session_state: del st.session_state.current_test_card_id_opts
                        if 'deck_view_deck_id_context' in st.session_state: del st.session_state.deck_view_deck_id_context


                        # Dynamically created keys (iterate over a copy)
                        keys_to_delete = []
                        for key in st.session_state.keys():
                            if key.startswith("flashcard_flipped_") or \
                               key.startswith("hint_expanded_") or \
                               key.startswith("test_opt_selected_page_") or \
                               key.startswith("cb_hint_expanded_"): # Checkbox for hint
                                keys_to_delete.append(key)
                        
                        for key_to_del in keys_to_delete:
                            if key_to_del in st.session_state: # Check again before deleting
                                del st.session_state[key_to_del]
                        logger.info(f"Cleared {len(keys_to_delete)} dynamic UI state keys.")
                    # --- End of state clearing section ---

                    st.session_state.current_deck_id = deck_id
                    now_iso = datetime.datetime.now().isoformat()
                    update_deck_metadata_in_db(deck_id, last_accessed_at=now_iso)
                    st.switch_page("pages/04_Deck_View.py")

                csv_data = export_deck_to_csv(deck)
                st.download_button(label="📥 Export CSV", data=csv_data,
                                   file_name=f"{deck.get('title', 'deck').replace(' ', '_')}_export.csv",
                                   mime='text/csv', key=f"export_deck_btn_list_{deck_id}", use_container_width=True)
                if st.button("🗑️ Delete Deck", key=f"delete_deck_btn_list_{deck_id}", use_container_width=True):
                    st.session_state[f"confirm_delete_list_{deck_id}"] = True

            if st.session_state.get(f"confirm_delete_list_{deck_id}"):
                st.warning(f"Delete '{deck.get('title', '')}'? Cannot be undone.")
                c1, c2, c3 = st.columns([1,1,2])
                if c1.button("✅ Yes, Delete", key=f"confirm_del_list_yes_btn_{deck_id}"):
                    title_for_msg = deck.get("title", "")
                    delete_deck_from_db_and_session(deck_id)
                    if f"confirm_delete_list_{deck_id}" in st.session_state:
                        del st.session_state[f"confirm_delete_list_{deck_id}"]
                    st.success(f"Deck '{title_for_msg}' deleted.")
                    st.rerun()
                if c2.button("❌ No, Cancel", key=f"confirm_del_list_no_btn_{deck_id}"):
                    if f"confirm_delete_list_{deck_id}" in st.session_state:
                        del st.session_state[f"confirm_delete_list_{deck_id}"]
                    st.rerun()
            st.markdown("---")
