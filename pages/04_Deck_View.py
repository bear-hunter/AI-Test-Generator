import streamlit as st
import datetime
import random
import pandas as pd
from utils import (
    render_card_view, update_card_spaced_repetition, get_due_cards_for_deck,
    calculate_deck_overall_mastery, export_deck_to_csv,
    update_global_user_profile_stats, QUALITY_MAPPING,
    calculate_card_display_mastery_percentage,
    update_deck_metadata_in_db, delete_deck_from_db_and_session,
    play_sound # Added this import
)
import logging

logger = logging.getLogger(__name__)

# Define sound file names (you need to create these files in static/sounds/)
SOUND_CORRECT = "correct.mp3"
SOUND_INCORRECT = "incorrect.mp3"
SOUND_FINISH_SESSION = "finish_session.mp3"
SOUND_GRADED_FLASHCARD = "graded_flashcard.mp3"
SOUND_MILESTONE_HALFWAY = "milestone_halfway.mp3"
SOUND_MILESTONE_ALMOST_DONE = "milestone_almost_done.mp3"


st.title("📖 Deck Viewer & Study Area")

if 'current_deck_id' not in st.session_state or not st.session_state.current_deck_id:
    st.error("No deck selected. Select from 'My Decks' or create one.")
    if st.button("Go to My Decks"): st.switch_page("pages/03_Decks_List.py")
    st.stop()

deck_id = st.session_state.current_deck_id
if deck_id not in st.session_state.decks:
    st.error("Selected deck not found. It might have been deleted.")
    st.session_state.current_deck_id = None
    if st.button("Go to My Decks"): st.switch_page("pages/03_Decks_List.py")
    st.stop()

current_deck = st.session_state.decks[deck_id]
deck_cards = current_deck.get("cards", [])

if 'deck_view_deck_id_context' not in st.session_state:
    st.session_state.deck_view_deck_id_context = None

if st.session_state.deck_view_deck_id_context != deck_id:
    logger.info(f"Deck context for Deck View page changing from '{st.session_state.deck_view_deck_id_context}' to '{deck_id}'. Resetting relevant UI states.")
    states_to_clear = [
        'fc_review_set', 'fc_current_card_index', 'fc_session_graded_count',
        'test_review_set_active', 'test_current_card_idx', 'test_session_graded_count_val',
        'test_feedback_msg', 'test_selected_option_val', 'shuffled_opts_test',
        'current_test_card_id_opts'
    ]
    for state_key in states_to_clear:
        if state_key in st.session_state: del st.session_state[state_key]
    
    keys_to_delete_view = []
    for key in st.session_state.keys(): # Iterate over a copy
        if key.startswith("flashcard_flipped_") or \
           key.startswith("hint_expanded_") or \
           key.startswith("test_opt_selected_page_") or \
           key.startswith("cb_hint_expanded_") or \
           key.startswith(f"fc_milestone_50_played_{st.session_state.deck_view_deck_id_context}") or \
           key.startswith(f"fc_milestone_90_played_{st.session_state.deck_view_deck_id_context}") or \
           key.startswith(f"test_milestone_50_played_{st.session_state.deck_view_deck_id_context}") or \
           key.startswith(f"test_milestone_90_played_{st.session_state.deck_view_deck_id_context}"):
            keys_to_delete_view.append(key)
    for key_to_del in keys_to_delete_view:
        if key_to_del in st.session_state: del st.session_state[key_to_del]
    st.session_state.deck_view_deck_id_context = deck_id

st.header(f"Deck: {current_deck.get('title', 'Untitled Deck')}")
col_meta1, col_meta2, col_meta3 = st.columns(3)
col_meta1.metric("Total Cards", len(deck_cards))
col_meta2.metric("Deck Mastery", f"{calculate_deck_overall_mastery(deck_cards):.1f}%")
col_meta3.text(f"Created: {current_deck.get('created_at', 'N/A')[:10]}")
st.caption(f"Source: {current_deck.get('source_type', 'N/A')}")
st.divider()

tab_flashcards, tab_test, tab_stats, tab_manage = st.tabs(["🃏 Flashcards", "🧪 Test Yourself", "📊 Stats", "⚙️ Manage Deck"])

with tab_manage:
    # ... (tab_manage code as before, no sound changes here) ...
    st.subheader("Deck Management")
    current_title_manage = current_deck.get("title", "")
    new_title_input_manage = st.text_input("Edit Deck Title:", value=current_title_manage, key=f"edit_title_deck_manage_{deck_id}")
    if st.button("Save Title Change", key=f"save_title_btn_manage_{deck_id}"):
        if new_title_input_manage and new_title_input_manage.strip() and new_title_input_manage != current_title_manage:
            update_deck_metadata_in_db(deck_id, title=new_title_input_manage)
            st.success("Deck title updated!"); st.rerun()
        elif not new_title_input_manage.strip(): st.error("Title cannot be empty.")
        else: st.info("No changes to save.")
    st.subheader("Bulk Actions")
    csv_data_manage = export_deck_to_csv(current_deck)
    st.download_button(label="📥 Export Deck to CSV", data=csv_data_manage,
                       file_name=f"{current_deck.get('title', 'deck').replace(' ', '_')}_export.csv",
                       mime='text/csv', key=f"export_btn_manage_{deck_id}", use_container_width=True)
    if st.button("🗑️ Delete This Deck", type="secondary", use_container_width=True, key=f"delete_btn_manage_{deck_id}"):
        st.session_state[f"confirm_delete_manage_{deck_id}"] = True
    if st.session_state.get(f"confirm_delete_manage_{deck_id}"):
        st.error(f"Delete '{current_deck.get('title', '')}' PERMANENTLY?")
        c1m, c2m, c3m = st.columns([1,1,2])
        if c1m.button("✅ Yes, Delete Permanently", key=f"confirm_del_yes_manage_{deck_id}"):
            title_for_msg_manage = current_deck.get("title", "")
            delete_deck_from_db_and_session(deck_id)
            if f"confirm_delete_manage_{deck_id}" in st.session_state: del st.session_state[f"confirm_delete_manage_{deck_id}"]
            st.success(f"Deck '{title_for_msg_manage}' deleted. Redirecting..."); st.switch_page("pages/03_Decks_List.py")
        if c2m.button("❌ No, Keep Deck", key=f"confirm_del_no_manage_{deck_id}"):
            if f"confirm_delete_manage_{deck_id}" in st.session_state: del st.session_state[f"confirm_delete_manage_{deck_id}"]
            st.rerun()


with tab_flashcards:
    st.subheader("Flashcard Practice (Spaced Repetition)")
    if not deck_cards:
        st.warning(f"The deck '{current_deck.get('title')}' has no cards for flashcard practice.")
    else:
        fc_milestone_50_key = f"fc_milestone_50_played_{deck_id}"
        fc_milestone_90_key = f"fc_milestone_90_played_{deck_id}"

        if 'fc_review_set' not in st.session_state:
            st.session_state.fc_review_set = []
            st.session_state.fc_current_card_index = 0
            st.session_state.fc_session_graded_count = 0
            st.session_state[fc_milestone_50_key] = False # Initialize milestone flags
            st.session_state[fc_milestone_90_key] = False
        due_cards_flash = get_due_cards_for_deck(deck_cards)
        if not st.session_state.fc_review_set and due_cards_flash:
            st.session_state.fc_review_set = due_cards_flash
            st.session_state.fc_current_card_index = 0
            st.session_state.fc_session_graded_count = 0
            st.session_state[fc_milestone_50_key] = False # Reset on new set
            st.session_state[fc_milestone_90_key] = False
        active_review_set = st.session_state.get('fc_review_set', [])
        if not active_review_set:
            st.success("🎉 No cards currently due for review in this deck's flashcard mode!")
            if st.button("Review New Cards (Not Yet Seen)", key=f"fc_review_new_cards_tab_{deck_id}"):
                new_cards = [c for c in deck_cards if c.get('interval_days', 0) == 0 and c.get('last_reviewed_at') is None]
                if new_cards:
                    st.session_state.fc_review_set = new_cards
                    st.session_state.fc_current_card_index = 0
                    st.session_state.fc_session_graded_count = 0
                    st.session_state[fc_milestone_50_key] = False # Reset for new cards session
                    st.session_state[fc_milestone_90_key] = False
                    st.rerun()
                else: st.info("No new cards to review in this deck.")
        elif 'fc_current_card_index' in st.session_state and st.session_state.fc_current_card_index < len(active_review_set):
            current_flash_card = active_review_set[st.session_state.fc_current_card_index]
            is_flipped_key = f"flashcard_flipped_{current_flash_card['id']}_{deck_id}"
            if is_flipped_key not in st.session_state: st.session_state[is_flipped_key] = False
            render_card_view(current_flash_card, st.session_state[is_flipped_key], key_suffix=f"_flash_view_{deck_id}")
            
            # Milestone Check
            if len(active_review_set) > 1: # Avoid division by zero and for trivial sets
                progress_percent = (st.session_state.fc_current_card_index / len(active_review_set)) * 100
                if progress_percent >= 50 and progress_percent < 60 and not st.session_state.get(fc_milestone_50_key, False): # Play around 50% once
                    play_sound(SOUND_MILESTONE_HALFWAY)
                    st.session_state[fc_milestone_50_key] = True
                elif progress_percent >= 90 and progress_percent < 100 and not st.session_state.get(fc_milestone_90_key, False): # Play around 90% once
                    play_sound(SOUND_MILESTONE_ALMOST_DONE)
                    st.session_state[fc_milestone_90_key] = True

            fc_progress_display = (st.session_state.fc_current_card_index + 1) / len(active_review_set) * 100
            st.progress(int(fc_progress_display), text=f"Card {st.session_state.fc_current_card_index + 1} of {len(active_review_set)}")

            if not st.session_state[is_flipped_key]:
                if st.button("↪️ Reveal Answer", key=f"fc_reveal_btn_tab_{current_flash_card['id']}_{deck_id}", use_container_width=True, type="primary"):
                    st.session_state[is_flipped_key] = True; st.rerun()
            else:
                st.markdown("**How well did you recall this?**")
                quality_cols = st.columns(len(QUALITY_MAPPING))
                for i, (label, q_value) in enumerate(QUALITY_MAPPING.items()):
                    if quality_cols[i].button(label, key=f"fc_quality_btn_tab_{q_value}_{current_flash_card['id']}_{deck_id}", use_container_width=True):
                        play_sound(SOUND_GRADED_FLASHCARD) # Sound for grading
                        updated_card = update_card_spaced_repetition(current_flash_card, q_value)
                        active_review_set[st.session_state.fc_current_card_index] = updated_card
                        try:
                            main_deck_card_idx = next(idx for idx, card_in_main_deck in enumerate(st.session_state.decks[deck_id]['cards']) if card_in_main_deck['id'] == updated_card['id'])
                            st.session_state.decks[deck_id]['cards'][main_deck_card_idx] = updated_card
                        except StopIteration: logger.warning(f"Card {updated_card['id']} not found in main deck.")
                        st.session_state.fc_current_card_index += 1
                        st.session_state[is_flipped_key] = False
                        st.session_state.fc_session_graded_count = st.session_state.get("fc_session_graded_count",0) + 1
                        update_global_user_profile_stats(); st.rerun()
        else:
            graded_count_fc = st.session_state.get("fc_session_graded_count", 0)
            if graded_count_fc > 0:
                st.success("✨ Flashcard session complete!"); st.write(f"You graded {graded_count_fc} cards.")
                play_sound(SOUND_FINISH_SESSION)
            st.session_state.review_session_summary = f"Flashcard session: {graded_count_fc} cards."
            st.session_state.fc_review_set = []
            st.session_state.fc_session_graded_count = 0
            st.session_state[fc_milestone_50_key] = False # Reset for next session
            st.session_state[fc_milestone_90_key] = False
            if 'fc_current_card_index' in st.session_state: del st.session_state.fc_current_card_index
            if st.button("Start New Flashcard Session with Due Cards", key=f"fc_restart_due_btn_tab_{deck_id}"): st.rerun()

with tab_test:
    st.subheader("Test Your Knowledge (Multiple Choice)")
    if not deck_cards:
        st.warning(f"The deck '{current_deck.get('title')}' has no cards for testing.")
    else:
        test_milestone_50_key = f"test_milestone_50_played_{deck_id}"
        test_milestone_90_key = f"test_milestone_90_played_{deck_id}"

        if 'test_review_set_active' not in st.session_state:
            st.session_state.test_review_set_active = []
            st.session_state.test_current_card_idx = 0
            st.session_state.test_session_graded_count_val = 0
            st.session_state.test_feedback_msg = None
            st.session_state.test_selected_option_val = None
            st.session_state[test_milestone_50_key] = False # Initialize
            st.session_state[test_milestone_90_key] = False
        due_cards_for_test_tab = get_due_cards_for_deck(deck_cards)
        if not st.session_state.test_review_set_active and due_cards_for_test_tab:
            st.session_state.test_review_set_active = due_cards_for_test_tab
            st.session_state.test_current_card_idx = 0
            st.session_state.test_session_graded_count_val = 0
            st.session_state.test_feedback_msg = None
            st.session_state.test_selected_option_val = None
            st.session_state[test_milestone_50_key] = False # Reset
            st.session_state[test_milestone_90_key] = False
        current_active_test_set = st.session_state.get('test_review_set_active', [])
        if not current_active_test_set:
            st.success("🎉 No cards currently due for testing in this deck!")
        elif 'test_current_card_idx' in st.session_state and st.session_state.test_current_card_idx < len(current_active_test_set):
            current_test_idx = st.session_state.test_current_card_idx
            current_test_card = current_active_test_set[current_test_idx]

            # Milestone Check for Test
            if len(current_active_test_set) > 1:
                test_progress_percent = (current_test_idx / len(current_active_test_set)) * 100
                if test_progress_percent >= 50 and test_progress_percent < 60 and not st.session_state.get(test_milestone_50_key, False):
                    play_sound(SOUND_MILESTONE_HALFWAY)
                    st.session_state[test_milestone_50_key] = True
                elif test_progress_percent >= 90 and test_progress_percent < 100 and not st.session_state.get(test_milestone_90_key, False):
                    play_sound(SOUND_MILESTONE_ALMOST_DONE)
                    st.session_state[test_milestone_90_key] = True
            
            # ... (rest of test card rendering logic from previous correct version) ...
            with st.container(border=True):
                st.markdown(f"**Question {current_test_idx + 1} of {len(current_active_test_set)}:**")
                st.subheader(current_test_card['question'])
                options = list(current_test_card.get('options', []))
                if len(options) != 4: options = (options + [current_test_card['answer'], "OptX", "OptY", "OptZ"])[:4]
                if current_test_card['answer'] not in options: options[-1] = current_test_card['answer']
                opt_shuffled_key = f"shuffled_opts_test_{current_test_card['id']}_{deck_id}"
                current_card_id_opts_key = f"current_test_card_id_opts_{current_test_card['id']}_{deck_id}"
                if opt_shuffled_key not in st.session_state or st.session_state.get(current_card_id_opts_key) != current_test_card['id']:
                    random.shuffle(options)
                    st.session_state[opt_shuffled_key] = options
                    st.session_state[current_card_id_opts_key] = current_test_card['id']
                display_options = st.session_state.get(opt_shuffled_key, options)
                option_col_1, option_col_2 = st.columns(2); option_col_3, option_col_4 = st.columns(2)
                option_button_columns = [option_col_1, option_col_2, option_col_3, option_col_4]
                selected_opt_key_page_test = f"test_opt_selected_page_{current_test_card['id']}_{deck_id}"
                for i, opt_text in enumerate(display_options):
                    if i < 4:
                        target_column = option_button_columns[i]
                        dis_stat_test = st.session_state.get('test_feedback_msg') is not None
                        btn_typ_test = "primary" if st.session_state.get(selected_opt_key_page_test) == opt_text else "secondary"
                        if target_column.button(opt_text, key=f"test_opt_btn_{i}_{current_test_card['id']}_{deck_id}", use_container_width=True, disabled=dis_stat_test, type=btn_typ_test):
                            st.session_state[selected_opt_key_page_test] = opt_text
                            st.session_state.test_feedback_msg = None; st.rerun()
                st.session_state.test_selected_option_val = st.session_state.get(selected_opt_key_page_test)
            ctrl_cols_test_btns = st.columns(2)
            hint_dis_test_btn = not current_test_card.get('hint') or st.session_state.get('test_feedback_msg') is not None
            if ctrl_cols_test_btns[0].button("💡 Hint", key=f"test_hint_btn_tab_{current_test_card['id']}_{deck_id}", use_container_width=True, disabled=hint_dis_test_btn):
                st.toast(f"Hint: {current_test_card['hint']}", icon="💡")
            submit_dis_test_btn = st.session_state.get('test_selected_option_val') is None or st.session_state.get('test_feedback_msg') is not None
            if ctrl_cols_test_btns[1].button("➡️ Submit Answer", key=f"test_submit_btn_tab_{current_test_card['id']}_{deck_id}", use_container_width=True, type="primary", disabled=submit_dis_test_btn):
                is_correct = (st.session_state.test_selected_option_val == current_test_card['answer'])
                msg = "✅ Correct!" if is_correct else f"❌ Incorrect. Answer was: **{current_test_card['answer']}**"
                st.session_state.test_feedback_msg = {"correct": is_correct, "message": msg}
                
                if is_correct: play_sound(SOUND_CORRECT) # Play correct sound
                else: play_sound(SOUND_INCORRECT) # Play incorrect sound
                    
                q_sr = QUALITY_MAPPING["Good"] if is_correct else QUALITY_MAPPING["Again (Soon)"]
                updated_card_test = update_card_spaced_repetition(current_test_card, q_sr)
                current_active_test_set[current_test_idx] = updated_card_test
                try:
                    main_idx_test = next(idx_t for idx_t, card_in_main_deck_t in enumerate(st.session_state.decks[deck_id]['cards']) if card_in_main_deck_t['id'] == updated_card_test['id'])
                    st.session_state.decks[deck_id]['cards'][main_idx_test] = updated_card_test
                except StopIteration: logger.warning(f"Card {updated_card_test['id']} not found in main deck (test).")
                st.session_state.test_session_graded_count_val = st.session_state.get("test_session_graded_count_val", 0) + 1
                update_global_user_profile_stats(); st.rerun()
            if st.session_state.get('test_feedback_msg'):
                feedback_test = st.session_state.test_feedback_msg
                if feedback_test["correct"]: st.success(feedback_test["message"])
                else: st.error(feedback_test["message"])
                if st.button("Next Question ❯", key=f"test_next_q_btn_tab_{current_test_card['id']}_{deck_id}", use_container_width=True):
                    st.session_state.test_current_card_idx = current_test_idx + 1
                    st.session_state.test_feedback_msg = None
                    st.session_state.test_selected_option_val = None
                    if selected_opt_key_page_test in st.session_state: del st.session_state[selected_opt_key_page_test]
                    st.rerun()
        else:
            graded_count_test = st.session_state.get("test_session_graded_count_val", 0)
            if graded_count_test > 0:
                st.success("✨ Test session complete!"); st.write(f"You attempted {graded_count_test} questions.")
                play_sound(SOUND_FINISH_SESSION) # Play finish sound
            st.session_state.review_session_summary = f"Test session: {graded_count_test} questions."
            st.session_state.test_review_set_active = []
            st.session_state.test_session_graded_count_val = 0
            st.session_state[test_milestone_50_key] = False # Reset for next session
            st.session_state[test_milestone_90_key] = False
            if 'test_current_card_idx' in st.session_state: del st.session_state.test_current_card_idx
            if st.button("Start New Test with Due Cards", key=f"test_restart_due_btn_tab_{deck_id}"): st.rerun()

with tab_stats:
    # ... (tab_stats code as before, no sound changes here) ...
    st.subheader("Deck Performance Statistics")
    if not deck_cards: st.info("No cards in this deck for stats.")
    else:
        mastery_values = [calculate_card_display_mastery_percentage(c) for c in deck_cards]
        bins = [0, 20, 40, 60, 80, 100]; labels = ['0-19% (Learning)', '20-39% (Newish)', '40-59% (Familiar)', '60-79% (Strong)', '80-100% (Mastered)']
        mastery_dist = pd.cut(mastery_values, bins=bins, labels=labels, right=True, include_lowest=True).value_counts().sort_index()
        df_mastery_dist = pd.DataFrame({"Category": mastery_dist.index, "Number of Cards": mastery_dist.values})
        st.markdown("#### Card Mastery Distribution (Based on Review Intervals)")
        if not df_mastery_dist.empty: st.bar_chart(df_mastery_dist.set_index("Category"))
        else: st.info("No card mastery data for chart.")
        st.caption(f"Deck Overall Avg Mastery: {calculate_deck_overall_mastery(deck_cards):.1f}%")
        st.markdown("#### Card Details (with Spaced Repetition Info)")
        cards_display_data = []
        for card_in_stats in deck_cards:
            cards_display_data.append({
                "Question": card_in_stats.get('question', 'N/A')[:70] + ("..." if len(card_in_stats.get('question', 'N/A')) > 70 else ""),
                "Mastery (%)": f"{calculate_card_display_mastery_percentage(card_in_stats):.0f}",
                "EF": f"{card_in_stats.get('easiness_factor', 0):.2f}", "Reps (n)": card_in_stats.get('repetitions', 0),
                "Interval (d)": card_in_stats.get('interval_days', 0), "Next Review": card_in_stats.get('next_review_at', 'N/A'),
                "Last Review": card_in_stats.get('last_reviewed_at', 'N/A'), "Last q": card_in_stats.get('last_quality_response', 'N/A'),
                "Attempts": card_in_stats.get('attempts', 0), })
        if cards_display_data:
            df_cards_stats = pd.DataFrame(cards_display_data)
            sort_stat_options_stats = {"Next Review (Soonest First)": ("Next Review", True), "Mastery (% Low to High)": ("Mastery (%)", True)}
            selected_sort_stat_stats = st.selectbox("Sort cards by:", list(sort_stat_options_stats.keys()), key=f"stat_sort_sr_db_{deck_id}")
            sort_col_stats, asc_stats = sort_stat_options_stats[selected_sort_stat_stats]
            if sort_col_stats == "Mastery (%)": df_cards_stats["Mastery (%)"] = pd.to_numeric(df_cards_stats["Mastery (%)"])
            if sort_col_stats == "Next Review": df_cards_stats["Next Review"] = pd.to_datetime(df_cards_stats["Next Review"], errors='coerce')
            df_cards_stats = df_cards_stats.sort_values(by=sort_col_stats, ascending=asc_stats, na_position='last')
            st.dataframe(df_cards_stats, use_container_width=True, height=350)
        else: st.info("No card details.")

if st.session_state.get('review_session_summary'):
    st.toast(st.session_state.review_session_summary, icon="🎉")
    st.session_state.review_session_summary = None
