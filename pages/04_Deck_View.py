import streamlit as st
import datetime
import random
import pandas as pd
from utils import (
    render_card_view, update_card_spaced_repetition, get_due_cards_for_deck,
    calculate_deck_overall_mastery, export_deck_to_csv,
    update_global_user_profile_stats, QUALITY_MAPPING,
    calculate_card_display_mastery_percentage,
    update_deck_metadata_in_db, delete_deck_from_db_and_session # Added DB utils
)

st.title("📖 Deck Viewer & Study Area")

if 'current_deck_id' not in st.session_state or not st.session_state.current_deck_id:
    st.error("No deck selected. Select from 'My Decks' or create one.")
    if st.button("Go to My Decks"): st.switch_page("pages/03_Decks_List.py")
    st.stop()

deck_id = st.session_state.current_deck_id
if deck_id not in st.session_state.decks: # Check if deck exists in session (loaded from DB)
    st.error("Selected deck not found. It might have been deleted.")
    st.session_state.current_deck_id = None
    if st.button("Go to My Decks"): st.switch_page("pages/03_Decks_List.py")
    st.stop()

current_deck = st.session_state.decks[deck_id]
deck_cards = current_deck.get("cards", [])

# Update last_accessed_at for this deck in session and DB (if not just done on view button click)
# This can be done more selectively, but for now, viewing means accessing.
# update_deck_metadata_in_db(deck_id, last_accessed_at=datetime.datetime.now().isoformat())
# The above is better handled when clicking "View/Study" on the Decks_List page.

st.header(f"Deck: {current_deck.get('title', 'Untitled Deck')}")
# ... (metadata display as before) ...
col_meta1, col_meta2, col_meta3 = st.columns(3)
col_meta1.metric("Total Cards", len(deck_cards))
col_meta2.metric("Deck Mastery", f"{calculate_deck_overall_mastery(deck_cards):.1f}%")
col_meta3.text(f"Created: {current_deck.get('created_at', 'N/A')[:10]}")
st.caption(f"Source: {current_deck.get('source_type', 'N/A')}")
st.divider()


tab_flashcards, tab_test, tab_stats, tab_manage = st.tabs(["🃏 Flashcards", "🧪 Test Yourself", "📊 Stats", "⚙️ Manage Deck"])

with tab_manage:
    st.subheader("Deck Management")
    
    # Edit Title
    current_title = current_deck.get("title", "")
    new_title_input = st.text_input("Edit Deck Title:", value=current_title, key=f"edit_title_deck_view_{deck_id}")
    if st.button("Save Title Change", key=f"save_title_change_btn_{deck_id}"):
        if new_title_input and new_title_input != current_title:
            update_deck_metadata_in_db(deck_id, title=new_title_input) # Updates DB and session_state.decks[deck_id]
            # update_global_user_profile_stats() # To update recent decks list if title changed
            st.success("Deck title updated!")
            st.rerun() # Rerun to reflect title change in header and everywhere
        elif not new_title_input:
            st.error("Title cannot be empty.")
        else:
            st.info("No changes to save.")

    st.subheader("Bulk Actions")
    csv_data = export_deck_to_csv(current_deck)
    st.download_button(label="📥 Export Deck to CSV", data=csv_data,
                       file_name=f"{current_deck.get('title', 'deck').replace(' ', '_')}_export.csv",
                       mime='text/csv', key=f"export_deck_detail_view_{deck_id}", use_container_width=True)

    if st.button("🗑️ Delete This Deck", type="secondary", use_container_width=True, key=f"delete_this_deck_btn_{deck_id}"):
        st.session_state[f"confirm_delete_deck_detail_view_{deck_id}"] = True

    if st.session_state.get(f"confirm_delete_deck_detail_view_{deck_id}"):
        st.error(f"Delete '{current_deck.get('title', '')}' PERMANENTLY?")
        c1, c2, c3 = st.columns([1,1,2])
        if c1.button("✅ Yes, Delete Permanently", key=f"confirm_del_detail_yes_{deck_id}"):
            title_for_msg = current_deck.get("title", "") # Get before deletion
            delete_deck_from_db_and_session(deck_id) # Handles DB and session
            del st.session_state[f"confirm_delete_deck_detail_view_{deck_id}"]
            st.success(f"Deck '{title_for_msg}' deleted. Redirecting...")
            st.switch_page("pages/03_Decks_List.py") # Go to decks list
        if c2.button("❌ No, Keep Deck", key=f"confirm_del_detail_no_{deck_id}"):
            del st.session_state[f"confirm_delete_deck_detail_view_{deck_id}"]
            st.rerun()

# --- Flashcards Tab (No DB specific changes needed here, update_card_spaced_repetition handles it) ---
# ... (Flashcards tab code as in your "enhanced SR" version) ...
with tab_flashcards:
    st.subheader("Flashcard Practice (Spaced Repetition)")
    if not deck_cards:
        st.warning(f"The deck '{current_deck.get('title')}' has no cards.")
        st.stop()

    due_cards_flash = get_due_cards_for_deck(deck_cards)
    if 'fc_review_set' not in st.session_state: st.session_state.fc_review_set = []

    if not due_cards_flash and not st.session_state.fc_review_set:
        st.success("🎉 No cards currently due for review!")
        if st.button("Review New Cards (Not Yet Seen)", key="fc_review_new_cards"):
            new_cards = [c for c in deck_cards if c.get('interval_days', 0) == 0 and c.get('last_reviewed_at') is None]
            if new_cards:
                st.session_state.fc_review_set = new_cards
                st.session_state.fc_current_card_index = 0
                st.session_state.fc_session_graded_count = 0
                st.rerun()
            else: st.info("No new cards to review.")
    elif not st.session_state.fc_review_set and due_cards_flash: # Populate if empty but due cards exist
         st.session_state.fc_review_set = due_cards_flash
         st.session_state.fc_current_card_index = 0
         st.session_state.fc_session_graded_count = 0


    active_review_set = st.session_state.get('fc_review_set', [])
    if active_review_set:
        if 'fc_current_card_index' not in st.session_state or st.session_state.fc_current_card_index >= len(active_review_set):
            # Session ended or index out of bounds, reset for next time or show summary
            if st.session_state.get("fc_session_graded_count", 0) > 0 :
                st.success("✨ Flashcard session complete!")
                st.write(f"You graded {st.session_state.fc_session_graded_count} cards.")
                st.session_state.review_session_summary = f"Flashcard session: {st.session_state.fc_session_graded_count} cards reviewed."
            # Clear session set to re-evaluate due cards on next interaction/rerun
            st.session_state.fc_review_set = []
            st.session_state.fc_session_graded_count = 0 # Reset counter
            if st.button("Start New Flashcard Session with Due Cards", key="fc_restart_due_cards_btn"):
                st.rerun() # Will repopulate due_cards_flash and fc_review_set
        else:
            current_flash_card = active_review_set[st.session_state.fc_current_card_index]
            is_flipped_key = f"flashcard_flipped_{current_flash_card['id']}"
            if is_flipped_key not in st.session_state: st.session_state[is_flipped_key] = False

            render_card_view(current_flash_card, st.session_state[is_flipped_key], key_suffix="_flash_view")
            
            fc_progress = (st.session_state.fc_current_card_index + 1) / len(active_review_set) * 100
            st.progress(int(fc_progress), text=f"Card {st.session_state.fc_current_card_index + 1} of {len(active_review_set)}")

            if not st.session_state[is_flipped_key]:
                if st.button("↪️ Reveal Answer", key=f"fc_reveal_btn_{current_flash_card['id']}", use_container_width=True, type="primary"):
                    st.session_state[is_flipped_key] = True
                    st.rerun()
            else:
                st.markdown("**How well did you recall this?**")
                quality_cols = st.columns(len(QUALITY_MAPPING))
                for i, (label, q_value) in enumerate(QUALITY_MAPPING.items()):
                    if quality_cols[i].button(label, key=f"fc_quality_btn_{q_value}_{current_flash_card['id']}", use_container_width=True):
                        # update_card_spaced_repetition handles DB saving for the card
                        updated_card = update_card_spaced_repetition(current_flash_card, q_value)
                        # Update the card in the current session's review set and main deck list
                        active_review_set[st.session_state.fc_current_card_index] = updated_card
                        try: # Update in main deck_cards list in session_state
                            main_deck_card_idx = st.session_state.decks[deck_id]['cards'].index(next(c for c in st.session_state.decks[deck_id]['cards'] if c['id'] == updated_card['id']))
                            st.session_state.decks[deck_id]['cards'][main_deck_card_idx] = updated_card
                        except StopIteration: pass # Card not found by ID, should not happen

                        st.session_state.fc_current_card_index += 1
                        st.session_state[is_flipped_key] = False # Reset flip for next card or if reviewed again
                        st.session_state.fc_session_graded_count = st.session_state.get("fc_session_graded_count",0) + 1
                        update_global_user_profile_stats() # Recalculate global stats (and save if configured)
                        st.rerun()
    elif not due_cards_flash : # No due cards and no active review set (already handled by initial check)
        pass # Message already shown
    else: # Due cards exist but no review set active (e.g., after a full session)
        if st.button("Start Flashcard Session with Due Cards", key="fc_start_due_cards_btn_else"):
             st.session_state.fc_review_set = due_cards_flash
             st.session_state.fc_current_card_index = 0
             st.session_state.fc_session_graded_count = 0
             st.rerun()


# --- Test Tab (SR update handled by update_card_spaced_repetition) ---
# ... (Test tab code as in your "enhanced SR" version, no direct DB changes needed here) ...
with tab_test:
    st.subheader("Test Your Knowledge (Multiple Choice)")
    if not deck_cards:
        st.warning(f"The deck '{current_deck.get('title')}' has no cards.")
        st.stop()
    
    # Use a separate review set for test mode to avoid conflicts with flashcard mode's set
    if 'test_review_set_active' not in st.session_state: st.session_state.test_review_set_active = []

    due_cards_for_test_tab = get_due_cards_for_deck(deck_cards)

    if not due_cards_for_test_tab and not st.session_state.test_review_set_active:
        st.success("🎉 No cards currently due for testing!")
    elif not st.session_state.test_review_set_active and due_cards_for_test_tab: # Initialize review set
        st.session_state.test_review_set_active = due_cards_for_test_tab
        st.session_state.test_current_card_idx = 0
        st.session_state.test_session_graded_count_val = 0 # Explicitly name for clarity
        st.session_state.test_feedback_msg = None
        st.session_state.test_selected_option_val = None

    
    current_active_test_set = st.session_state.get('test_review_set_active', [])
    if current_active_test_set:
        current_test_idx = st.session_state.get('test_current_card_idx', 0)

        if current_test_idx >= len(current_active_test_set):
            if st.session_state.get("test_session_graded_count_val", 0) > 0:
                st.success("✨ Test session complete!")
                st.write(f"You attempted {st.session_state.test_session_graded_count_val} questions.")
            st.session_state.review_session_summary = f"Test session: {st.session_state.get('test_session_graded_count_val',0)} questions."
            st.session_state.test_review_set_active = [] # Clear the set
            st.session_state.test_session_graded_count_val = 0
            if st.button("Start New Test with Due Cards", key="test_restart_due_btn"):
                st.rerun()
        else:
            current_test_card = current_active_test_set[current_test_idx]
            # ... (rest of the test card rendering, option selection, submission logic as before) ...
            # Ensure update_card_spaced_repetition is called on submit
            with st.container(border=True):
                st.markdown(f"**Question {current_test_idx + 1} of {len(current_active_test_set)}:**")
                st.subheader(current_test_card['question'])
                options = current_test_card.get('options', [])
                # ... (option handling logic) ...
                if len(options) != 4: options = (options + [current_test_card['answer'], "OptX", "OptY", "OptZ"])[:4]
                if current_test_card['answer'] not in options: options[-1] = current_test_card['answer']
                
                opt_key_prefix = f"test_opt_{current_test_card['id']}"
                if 'shuffled_opts_test' not in st.session_state or st.session_state.get('current_test_card_id_opts') != current_test_card['id']:
                    random.shuffle(options)
                    st.session_state.shuffled_opts_test = options
                    st.session_state.current_test_card_id_opts = current_test_card['id']
                display_options = st.session_state.shuffled_opts_test

                option_cols_r1 = st.columns(2); option_cols_r2 = st.columns(2)
                selected_opt_key_page = f"test_opt_selected_page_{current_test_card['id']}"

                for i, opt_text in enumerate(display_options):
                    col = option_cols_r1[0] if i==0 else option_cols_r1[1] if i==1 else option_cols_r2[0] if i==2 else option_cols_r2[1]
                    dis_stat = st.session_state.get('test_feedback_msg') is not None
                    btn_typ = "primary" if st.session_state.get(selected_opt_key_page) == opt_text else "secondary"
                    if col.button(opt_text, key=f"{opt_key_prefix}_{i}", use_container_width=True, disabled=dis_stat, type=btn_typ):
                        st.session_state[selected_opt_key_page] = opt_text
                        st.session_state.test_feedback_msg = None; st.rerun()
                st.session_state.test_selected_option_val = st.session_state.get(selected_opt_key_page)

            ctrl_cols_test = st.columns(2)
            hint_dis_test = not current_test_card.get('hint') or st.session_state.get('test_feedback_msg') is not None
            if ctrl_cols_test[0].button("💡 Hint", key=f"test_hint_btn_{current_test_card['id']}", use_container_width=True, disabled=hint_dis_test):
                st.toast(f"Hint: {current_test_card['hint']}", icon="💡")

            submit_dis_test = st.session_state.get('test_selected_option_val') is None or st.session_state.get('test_feedback_msg') is not None
            if ctrl_cols_test[1].button("➡️ Submit Answer", key=f"test_submit_btn_{current_test_card['id']}", use_container_width=True, type="primary", disabled=submit_dis_test):
                is_correct = (st.session_state.test_selected_option_val == current_test_card['answer'])
                msg = "✅ Correct!" if is_correct else f"❌ Incorrect. Ans: **{current_test_card['answer']}**"
                st.session_state.test_feedback_msg = {"correct": is_correct, "message": msg}
                
                q_sr = QUALITY_MAPPING["Good"] if is_correct else QUALITY_MAPPING["Again (Soon)"]
                updated_card = update_card_spaced_repetition(current_test_card, q_sr) # This saves to DB
                current_active_test_set[current_test_idx] = updated_card
                try:
                    main_idx = st.session_state.decks[deck_id]['cards'].index(next(c for c in st.session_state.decks[deck_id]['cards'] if c['id'] == updated_card['id']))
                    st.session_state.decks[deck_id]['cards'][main_idx] = updated_card
                except StopIteration: pass
                st.session_state.test_session_graded_count_val = st.session_state.get("test_session_graded_count_val", 0) + 1
                update_global_user_profile_stats()
                st.rerun()

            if st.session_state.get('test_feedback_msg'):
                feedback = st.session_state.test_feedback_msg
                if feedback["correct"]: st.success(feedback["message"])
                else: st.error(feedback["message"])
                if st.button("Next Question ❯", key=f"test_next_q_btn_{current_test_card['id']}", use_container_width=True):
                    st.session_state.test_current_card_idx = current_test_idx + 1
                    st.session_state.test_feedback_msg = None
                    st.session_state.test_selected_option_val = None
                    if selected_opt_key_page in st.session_state: del st.session_state[selected_opt_key_page]
                    st.rerun()
    elif not due_cards_for_test_tab: # Already handled
        pass
    else: # Due cards exist, but no active test set (e.g., after a full session)
        if st.button("Start Test with Due Cards", key="test_start_due_cards_btn_else"):
             st.session_state.test_review_set_active = due_cards_for_test_tab
             st.session_state.test_current_card_idx = 0
             st.session_state.test_session_graded_count_val = 0
             st.rerun()


# --- Stats Tab (No DB specific changes needed here, reads from session state) ---
# ... (Stats tab code as in your "enhanced SR" version) ...
with tab_stats:
    st.subheader("Deck Performance Statistics")
    if not deck_cards:
        st.info("No cards in this deck for stats.")
    else:
        # ... (rest of the stats display logic using calculate_card_display_mastery_percentage etc.) ...
        mastery_values = [calculate_card_display_mastery_percentage(c) for c in deck_cards]
        bins = [0, 20, 40, 60, 80, 100]; labels = ['0-19%', '20-39%', '40-59%', '60-79%', '80-100%']
        mastery_dist = pd.cut(mastery_values, bins=bins, labels=labels, right=True, include_lowest=True).value_counts().sort_index()
        df_mastery_dist = pd.DataFrame({"Category": mastery_dist.index, "Number of Cards": mastery_dist.values})
        st.markdown("#### Card Mastery Distribution");
        if not df_mastery_dist.empty: st.bar_chart(df_mastery_dist.set_index("Category"))
        else: st.info("No mastery data for chart.")
        st.caption(f"Deck Overall Avg Mastery: {calculate_deck_overall_mastery(deck_cards):.1f}%")

        st.markdown("#### Card Details (SR Info)")
        cards_display_data = []
        for card in deck_cards:
            cards_display_data.append({
                "Question": card.get('question', 'N/A')[:70] + ("..." if len(card.get('question', 'N/A')) > 70 else ""),
                "Mastery (%)": f"{calculate_card_display_mastery_percentage(card):.0f}",
                "EF": f"{card.get('easiness_factor', 0):.2f}", "Reps (n)": card.get('repetitions', 0),
                "Interval (d)": card.get('interval_days', 0), "Next Review": card.get('next_review_at', 'N/A'),
                "Last Review": card.get('last_reviewed_at', 'N/A'), "Last q": card.get('last_quality_response', 'N/A'),
                "Attempts": card.get('attempts', 0),
            })
        if cards_display_data:
            df_cards = pd.DataFrame(cards_display_data)
            # ... (sorting logic as before) ...
            sort_stat_opts = {"Next Review (Soonest)": ("Next Review", True), "Mastery (% Low-High)": ("Mastery (%)", True)}
            sel_sort_stat = st.selectbox("Sort by:", list(sort_stat_opts.keys()), key="stat_sorter_sr_db")
            sort_col, asc = sort_stat_opts[sel_sort_stat]
            if sort_col == "Mastery (%)": df_cards["Mastery (%)"] = pd.to_numeric(df_cards["Mastery (%)"])
            if sort_col == "Next Review": df_cards["Next Review"] = pd.to_datetime(df_cards["Next Review"], errors='coerce')
            df_cards = df_cards.sort_values(by=sort_col, ascending=asc, na_position='last')
            st.dataframe(df_cards, use_container_width=True, height=350)
        else: st.info("No card details.")


if st.session_state.get('review_session_summary'):
    st.toast(st.session_state.review_session_summary, icon="🎉")
    st.session_state.review_session_summary = None # Clear after showing