import streamlit as st
# No change to imports needed specifically for DB here, utils handles it.
from utils import (
    generate_qna_cards, create_new_deck, update_global_user_profile_stats,
    DEFAULT_GEMINI_API_KEY, GEMINI_MODEL_NAME, parse_csv_to_cards
)
import io

st.title("✍️ Input Content & Generate/Import Q&A")

api_key_ok = True
if st.session_state.get('user_api_key', DEFAULT_GEMINI_API_KEY) == DEFAULT_GEMINI_API_KEY or st.session_state.get('show_api_key_warning', True):
    st.error(f"🛑 Gemini API Key not configured. AI generation disabled. Set key in 'Profile & Settings'. (CSV import works). Model: `{st.session_state.get('gemini_model_name_config', GEMINI_MODEL_NAME)}`.", icon="🚨")
    api_key_ok = False

st.info("Provide text for AI generation, or upload a CSV to import an existing deck.")

current_input_options = ["Upload .txt File (AI Generate)", "Paste Text (AI Generate)", "Import Deck from CSV"]
if not api_key_ok: current_input_options = ["Import Deck from CSV"]

input_method = st.radio("Select input method:", current_input_options, horizontal=True, key="input_method_selector")

text_content = None
source_filename = "Pasted Text"
parsed_cards_from_csv = None
error_message_from_parsing = None

if input_method == "Upload .txt File (AI Generate)":
    st.subheader("📁 File Upload Panel (AI Generation)")
    uploaded_txt_file = st.file_uploader("Select .txt file for AI Q&A", type=["txt"], key="txt_uploader_widget")
    if uploaded_txt_file:
        try:
            text_content = uploaded_txt_file.read().decode("utf-8")
            source_filename = uploaded_txt_file.name
            st.text_area("Preview:", text_content[:500], height=100, disabled=True)
        except Exception as e: st.error(f"Error reading .txt: {e}"); text_content = None

elif input_method == "Paste Text (AI Generate)":
    st.subheader("📝 Paste Text Panel (AI Generation)")
    text_content = st.text_area("Paste text (min 50 chars for AI):", height=250, key="paste_text_widget")
    if text_content and len(text_content) < 50:
        st.warning("Text too short for AI generation."); text_content = None

elif input_method == "Import Deck from CSV":
    st.subheader(" M  csv Import CSV Panel")
    st.markdown("""
    Upload CSV. Headers case-insensitive. Required: `question`, `answer`, `options` (semicolon-sep, e.g., `OptA;OptB;Ans`).
    Optional: `question_type`, `hint`, `tags` (semicolon-sep). SR fields also optional.
    """)
    uploaded_csv_file = st.file_uploader("Select .csv to import", type=["csv"], key="csv_uploader_widget")
    if uploaded_csv_file:
        source_filename = uploaded_csv_file.name
        try:
            csv_content_stream = io.BytesIO(uploaded_csv_file.getvalue())
            with st.spinner("🔄 Processing CSV..."):
                parsed_cards_from_csv, error_message_from_parsing = parse_csv_to_cards(csv_content_stream)
            if error_message_from_parsing: st.warning(f"CSV Parsing Issues:\n{error_message_from_parsing}")
            if not parsed_cards_from_csv:
                if not error_message_from_parsing: st.error("No valid cards imported. Check CSV format.")
            else: st.success(f"Parsed {len(parsed_cards_from_csv)} cards from '{source_filename}'. Create deck below.")
        except Exception as e: st.error(f"Critical error with CSV: {e}"); parsed_cards_from_csv = None

# Common Deck Creation UI
proceed_to_deck_creation_ui = False
action_button_label = ""
if input_method.endswith("(AI Generate)") and text_content and len(text_content) >= 50:
    proceed_to_deck_creation_ui = True
    action_button_label = "✨ Analyze & Generate Q&A with AI"
elif input_method == "Import Deck from CSV" and parsed_cards_from_csv:
    proceed_to_deck_creation_ui = True
    action_button_label = "➕ Create Deck from Imported CSV"

if proceed_to_deck_creation_ui:
    deck_title_default = source_filename.replace(".txt", "").replace(".csv", "") if source_filename not in ["Pasted Text", ""] else "My New Deck"
    deck_title = st.text_input("Deck title:", value=deck_title_default, key="deck_title_input_area")

    if st.button(action_button_label, type="primary", use_container_width=True, key="create_deck_action_button"):
        if not deck_title.strip(): st.error("Deck title cannot be empty.")
        else:
            final_cards, ai_err_msg, src_type = None, None, input_method
            if input_method == "Import Deck from CSV":
                final_cards = parsed_cards_from_csv
                src_type = f"CSV Import ({source_filename})"
            elif text_content:
                with st.spinner("🔄 AI Generating Q&A..."):
                    final_cards, ai_err_msg = generate_qna_cards(text_content)
                src_type = input_method + (f" ({source_filename})" if source_filename != "Pasted Text" else "")
            
            if ai_err_msg: st.error(f"AI Q&A Failed: {ai_err_msg}")
            elif final_cards and len(final_cards) > 0:
                st.success(f"🎉 Prepared {len(final_cards)} cards!")
                # create_new_deck now handles DB saving
                new_deck_id = create_new_deck(
                    title=deck_title, source_type=src_type,
                    original_text=text_content if text_content else f"Imported from {source_filename}",
                    cards_list=final_cards
                )
                st.session_state.current_deck_id = new_deck_id # For immediate navigation
                st.balloons()
                st.markdown("---")
                st.subheader("New Deck Summary:")
                st.write(f"**Title:** {st.session_state.decks[new_deck_id]['title']}")
                st.write(f"**Cards:** {len(st.session_state.decks[new_deck_id]['cards'])}")
                st.write(f"**Source:** {st.session_state.decks[new_deck_id]['source_type']}")
                if st.button("➡️ Go to Deck", use_container_width=True, key="go_to_created_deck_button"):
                    st.switch_page("pages/04_Deck_View.py")
            elif final_cards is not None and len(final_cards) == 0:
                st.warning("No cards created/imported. For AI, try different text. For CSV, check format.")
            else: st.error("Unexpected issue. Content not processed.")
else:
    if input_method.endswith("(AI Generate)") and not text_content: st.markdown("Provide content for AI.")
    elif input_method == "Import Deck from CSV" and not parsed_cards_from_csv:
        # Check if a file was even uploaded before saying "upload a file"
        # This uses a trick since file_uploader resets; better to check if the variable holding parsed cards is empty.
        # No specific message needed here if parsing failed, as errors/warnings are shown above.
        if 'uploaded_csv_file' not in st.session_state or st.session_state.uploaded_csv_file is None:
             st.markdown("Upload a CSV file to import a deck.")