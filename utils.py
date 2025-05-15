import streamlit as st
import google.generativeai as genai
import json
import re
import datetime
import uuid
import pandas as pd
import logging
import math
import io
import sqlite3
import streamlit.components.v1 as components # Added for HTML components
import os # Added for path joining

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
DEFAULT_GEMINI_API_KEY = "placeholder"
GEMINI_MODEL_NAME = "gemini-2.5-pro-preview-05-06"
DB_NAME = "flashcard_ai_app.db"

# --- Spaced Repetition Constants ---
DEFAULT_EF = 2.5
MIN_EF = 1.3
INITIAL_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6
MAX_INTERVAL_DAYS_DISPLAY_CAP = 365

QUALITY_MAPPING = {
    "Again (Soon)": 1, "Hard": 2, "Good": 4, "Easy": 5
}

SOUND_FILES_PATH = "static/sounds"

# --- Sound Playing Function (Corrected) ---
def play_sound(sound_filename: str):
    """
    Embeds an HTML audio player to autoplay a sound.
    sound_filename: e.g., "correct.mp3"
    The sound file must be in the SOUND_FILES_PATH directory (e.g., static/sounds/).
    """
    sound_url = f"/{SOUND_FILES_PATH}/{sound_filename}" # Path for the browser

    # Use a session state counter to make the audio element ID unique per play attempt.
    # This helps if multiple sounds are played or the same sound is re-triggered.
    audio_player_id_counter_key = f"audio_player_id_counter_for_{sound_filename.split('.')[0]}"
    if audio_player_id_counter_key not in st.session_state:
        st.session_state[audio_player_id_counter_key] = 0
    st.session_state[audio_player_id_counter_key] = (st.session_state[audio_player_id_counter_key] + 1) % 1000 # Increment and wrap to prevent huge numbers
    
    player_id = f"audioPlayer_{sound_filename.split('.')[0]}_{st.session_state[audio_player_id_counter_key]}"

    # Adding a random query string to the src can also help ensure the browser re-fetches or re-evaluates,
    # especially if the same sound is played consecutively.
    # However, for distinct events triggered by Streamlit re-runs, simply rendering a new audio element
    # with a unique ID is often enough.
    # sound_url_with_buster = f"{sound_url}?v={datetime.datetime.now().timestamp()}" # Optional cache buster

    audio_html = f"""
        <audio id="{player_id}" autoplay="true" style="display:none;">
            <source src="{sound_url}" type="audio/mpeg">
            Your browser does not support the audio element.
        </audio>
        <script>
            var audio = document.getElementById('{player_id}');
            if (audio) {{
                audio.volume = 0.6; // Set volume (0.0 to 1.0) - adjust as needed
                audio.play().catch(function(error) {{
                    // Autoplay was prevented. This is common in browsers.
                    // console.warn("Audio autoplay failed for {sound_filename} (player_id: {player_id}):", error);
                    // You might want to provide a UI element to enable sounds if autoplay is consistently blocked.
                }});
            }} else {{
                // console.warn("Audio element with ID {player_id} not found for {sound_filename}.");
            }}
        </script>
    """
    # REMOVED the 'key' argument from components.html
    components.html(audio_html, height=0, width=0)
    logger.info(f"Attempted to play sound: {sound_url} with unique player ID {player_id}")


# --- Database Setup and Connection ---
# ... (get_db_connection, initialize_database as before) ...
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decks (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
        source_type TEXT, last_accessed_at TEXT, original_text TEXT )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id TEXT PRIMARY KEY, deck_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
        question_type TEXT, hint TEXT, options TEXT, tags TEXT,
        easiness_factor REAL DEFAULT 2.5, interval_days INTEGER DEFAULT 0, repetitions INTEGER DEFAULT 0,
        last_quality_response INTEGER, last_reviewed_at TEXT, next_review_at TEXT,
        attempts INTEGER DEFAULT 0, correct_streak INTEGER DEFAULT 0,
        FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_card_deck_id ON cards (deck_id)")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_profile (
        profile_id INTEGER PRIMARY KEY DEFAULT 1, total_cards_overall INTEGER DEFAULT 0,
        mastery_percentage_overall REAL DEFAULT 0.0, cards_due_next_review_overall INTEGER DEFAULT 0,
        last_updated TEXT )
    """)
    cursor.execute("INSERT OR IGNORE INTO app_profile (profile_id) VALUES (1)")
    conn.commit(); conn.close()
    # logger.info("Database initialized.") # Keep logging minimal for release

# --- Data Loading from DB ---
# ... (load_decks_from_db, load_app_profile_from_db as before) ...
def load_decks_from_db():
    decks_data = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM decks ORDER BY last_accessed_at DESC")
    db_decks = cursor.fetchall()
    for db_deck in db_decks:
        deck_id = db_deck['id']
        decks_data[deck_id] = dict(db_deck)
        cursor.execute("SELECT * FROM cards WHERE deck_id = ? ORDER BY id", (deck_id,))
        db_cards = cursor.fetchall()
        cards_list = []
        for db_card in db_cards:
            card_item = dict(db_card)
            try:
                card_item['options'] = json.loads(db_card['options']) if db_card['options'] else []
                card_item['tags'] = json.loads(db_card['tags']) if db_card['tags'] else []
            except json.JSONDecodeError:
                card_item['options'] = []; card_item['tags'] = []
            cards_list.append(card_item)
        decks_data[deck_id]['cards'] = cards_list
    conn.close()
    st.session_state.decks = decks_data
    # logger.info(f"Loaded {len(decks_data)} decks from DB.")

def load_app_profile_from_db():
    conn = get_db_connection()
    profile_data = conn.cursor().execute("SELECT * FROM app_profile WHERE profile_id = 1").fetchone()
    conn.close()
    if profile_data:
        st.session_state.user_profile = {
            "total_cards_overall": profile_data['total_cards_overall'],
            "mastery_percentage_overall": profile_data['mastery_percentage_overall'],
            "cards_due_next_review_overall": profile_data['cards_due_next_review_overall'],
            "recent_decks_info": []
        }
    else: # Default if table empty
        st.session_state.user_profile = {
            "total_cards_overall": 0, "mastery_percentage_overall": 0.0,
            "cards_due_next_review_overall": 0, "recent_decks_info": []
        }


# --- Session State Initialization ---
# ... (initialize_app_session_state as before, ensuring it calls load functions) ...
def initialize_app_session_state():
    if 'user_api_key' not in st.session_state: st.session_state.user_api_key = DEFAULT_GEMINI_API_KEY
    if 'gemini_model_name_config' not in st.session_state: st.session_state.gemini_model_name_config = GEMINI_MODEL_NAME
    if 'gemini_model' not in st.session_state: st.session_state.gemini_model = None
    if 'show_api_key_warning' not in st.session_state:
        st.session_state.show_api_key_warning = (st.session_state.user_api_key == DEFAULT_GEMINI_API_KEY or not st.session_state.user_api_key)
    if 'decks' not in st.session_state: load_decks_from_db()
    if 'user_profile' not in st.session_state: load_app_profile_from_db()
    if 'current_deck_id' not in st.session_state: st.session_state.current_deck_id = None
    # No need to initialize test_feedback, test_selected_option, review_session_summary here if they are page specific.
    update_global_user_profile_stats(save_to_db=False)


# --- AI Interaction (configure_gemini_model, clean_gemini_json_response, generate_qna_cards) ---
# ... (These functions remain the same) ...
def configure_gemini_model(force_reconfigure=False):
    if not force_reconfigure and st.session_state.get('gemini_model'):
        if st.session_state.user_api_key == getattr(st.session_state.gemini_model, '_client_api_key_check_temp', None) and \
           st.session_state.gemini_model_name_config == getattr(st.session_state.gemini_model, '_model_name_check_temp', None):
            return st.session_state.gemini_model
    api_key = st.session_state.get('user_api_key')
    model_name_to_use = st.session_state.get('gemini_model_name_config', GEMINI_MODEL_NAME)
    if not api_key or api_key == DEFAULT_GEMINI_API_KEY:
        st.session_state.show_api_key_warning = True; st.session_state.gemini_model = None; return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name_to_use)
        model._client_api_key_check_temp = api_key; model._model_name_check_temp = model_name_to_use
        st.session_state.gemini_model = model; st.session_state.show_api_key_warning = False; return model
    except Exception as e:
        st.session_state.gemini_model = None; st.session_state.show_api_key_warning = True
        if api_key != DEFAULT_GEMINI_API_KEY: st.error(f"Failed to configure Gemini: {e}")
        logger.error(f"Gemini configuration error: {e}"); return None

def clean_gemini_json_response(json_string):
    match = re.search(r"```json\s*(.*?)\s*```", json_string, re.DOTALL)
    if match: json_string = match.group(1)
    else:
        match = re.search(r"```\s*(.*?)\s*```", json_string, re.DOTALL)
        if match: json_string = match.group(1)
    return re.sub(r",\s*([\}\]])", r"\1", json_string).strip()

def generate_qna_cards(text_content):
    model = configure_gemini_model()
    if not model: return None, "Gemini model not initialized. Check API Key."
    prompt = f"""
    You are an AI assistant that generates educational flashcards from provided text.
    Task: Create "Identification" and "Fill-in-the-Blank" questions.
    For each: "question_type", "question" (use "_____" for blanks), "answer", "hint" (empty if none),
    "options" (list of 4 strings, one MUST be the "answer"), "tags" (list of 1-3, empty if none).
    Output: Single JSON list of card objects. No extra text. Well-formed JSON.
    Example: {{"question_type": "Fill-in-the-Blank", "question": "Capital of France is _____.", "answer": "Paris", "hint": "City of Lights.", "options": ["Paris", "London", "Berlin", "Rome"], "tags": ["Geography"]}}
    Text: --- {text_content} --- """
    safety_settings = [{"category": c, "threshold": "BLOCK_NONE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
    try:
        response = model.generate_content(prompt, safety_settings=safety_settings)
        generated_cards_data = json.loads(clean_gemini_json_response(response.text))
        validated_cards = []
        for card_data in generated_cards_data:
            if not all(k in card_data for k in ["question_type", "question", "answer", "options"]): continue
            if not isinstance(card_data["options"], list) or len(card_data["options"]) != 4:
                card_data["options"] = (card_data.get("options", []) + [card_data["answer"], "OptA", "OptB", "OptC"])[:4]
            if card_data["answer"] not in card_data["options"]: card_data["options"][-1] = card_data["answer"]
            card_data["options"] = list(dict.fromkeys(card_data["options"]))
            while len(card_data["options"]) < 4: card_data["options"].append(f"DefOpt{len(card_data['options'])+1}")
            card_data.update({
                'id': str(uuid.uuid4()), 'easiness_factor': DEFAULT_EF, 'interval_days': 0,
                'repetitions': 0, 'last_quality_response': None, 'last_reviewed_at': None,
                'next_review_at': datetime.date.today().isoformat(), 'attempts': 0, 'correct_streak': 0,
                'hint': card_data.get('hint', ''), 'tags': card_data.get('tags', [])
            })
            validated_cards.append(card_data)
        return validated_cards, None
    except Exception as e: return None, f"Q&A generation error: {e}"

# --- Spaced Repetition Logic & DB Update ---
# ... (update_card_spaced_repetition, save_or_update_card_in_db as before) ...
def update_card_spaced_repetition(card, quality_q):
    card['last_quality_response'] = quality_q
    card['last_reviewed_at'] = datetime.date.today().isoformat()
    card['attempts'] = card.get('attempts', 0) + 1
    ef = float(card.get('easiness_factor', DEFAULT_EF))
    n = int(card.get('repetitions', 0))
    interval = int(card.get('interval_days', 0))
    if quality_q < 3: n = 0; interval = INITIAL_INTERVAL_DAYS; card['correct_streak'] = 0
    else:
        card['correct_streak'] = card.get('correct_streak', 0) + 1
        if n == 0: interval = INITIAL_INTERVAL_DAYS
        elif n == 1: interval = SECOND_INTERVAL_DAYS
        else: interval = math.ceil(interval * ef)
        n += 1
    ef_new = ef + (0.1 - (5 - quality_q) * (0.08 + (5 - quality_q) * 0.02))
    ef = max(MIN_EF, ef_new)
    card['easiness_factor'] = round(ef, 2); card['repetitions'] = n; card['interval_days'] = interval
    card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=interval)).isoformat()
    save_or_update_card_in_db(card)
    return card

def save_or_update_card_in_db(card_data):
    conn = get_db_connection()
    options_json = json.dumps(card_data.get('options', [])); tags_json = json.dumps(card_data.get('tags', []))
    sql = """INSERT OR REPLACE INTO cards (id, deck_id, question, answer, question_type, hint, options, tags,
        easiness_factor, interval_days, repetitions, last_quality_response, last_reviewed_at, next_review_at, attempts, correct_streak)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    params = (card_data['id'], card_data['deck_id'], card_data['question'], card_data['answer'], card_data.get('question_type'),
              card_data.get('hint'), options_json, tags_json, card_data.get('easiness_factor'), card_data.get('interval_days'),
              card_data.get('repetitions'), card_data.get('last_quality_response'), card_data.get('last_reviewed_at'),
              card_data.get('next_review_at'), card_data.get('attempts'), card_data.get('correct_streak'))
    conn.cursor().execute(sql, params); conn.commit(); conn.close()

# --- Deck Management & DB Interaction ---
# ... (create_new_deck, update_deck_metadata_in_db, delete_deck_from_db_and_session as before) ...
def create_new_deck(title, source_type, original_text, cards_list):
    deck_id = str(uuid.uuid4()); now_iso = datetime.datetime.now().isoformat()
    new_deck_data = {"id": deck_id, "title": title, "created_at": now_iso, "source_type": source_type,
                     "original_text": original_text, "last_accessed_at": now_iso, "cards": []}
    conn = get_db_connection()
    conn.cursor().execute("INSERT INTO decks (id, title, created_at, source_type, last_accessed_at, original_text) VALUES (?, ?, ?, ?, ?, ?)",
                          (deck_id, title, now_iso, source_type, now_iso, original_text))
    conn.commit()
    processed_cards = []
    for card_item in cards_list:
        card_item['deck_id'] = deck_id
        save_or_update_card_in_db(card_item)
        processed_cards.append(card_item)
    conn.close()
    new_deck_data['cards'] = processed_cards
    st.session_state.decks[deck_id] = new_deck_data
    update_global_user_profile_stats()
    return deck_id

def update_deck_metadata_in_db(deck_id, title=None, last_accessed_at=None):
    if not title and not last_accessed_at: return
    conn = get_db_connection(); updates = []; params = []
    if title: updates.append("title = ?"); params.append(title)
    if last_accessed_at: updates.append("last_accessed_at = ?"); params.append(last_accessed_at)
    params.append(deck_id)
    conn.cursor().execute(f"UPDATE decks SET {', '.join(updates)} WHERE id = ?", tuple(params))
    conn.commit(); conn.close()
    if deck_id in st.session_state.decks:
        if title: st.session_state.decks[deck_id]['title'] = title
        if last_accessed_at: st.session_state.decks[deck_id]['last_accessed_at'] = last_accessed_at

def delete_deck_from_db_and_session(deck_id):
    conn = get_db_connection()
    conn.cursor().execute("DELETE FROM decks WHERE id = ?", (deck_id,)) # Cascade should delete cards
    conn.commit(); conn.close()
    if deck_id in st.session_state.decks: del st.session_state.decks[deck_id]
    if st.session_state.get('current_deck_id') == deck_id: st.session_state.current_deck_id = None
    update_global_user_profile_stats()

# --- Global Stats Calculation & DB Update ---
# ... (update_global_user_profile_stats as before) ...
def update_global_user_profile_stats(save_to_db=True):
    decks = st.session_state.get('decks', {})
    all_cards = [card for deck_id in decks for card in decks[deck_id].get('cards', [])]
    total_overall_cards = len(all_cards)
    overall_mastery_perc = calculate_deck_overall_mastery(all_cards) if all_cards else 0.0
    today_iso = datetime.date.today().isoformat()
    due_overall_count = sum(1 for card in all_cards if not card.get('next_review_at') or card.get('next_review_at') <= today_iso)
    recent_decks_info = sorted(
        [{"id": did, "title": d.get("title", "Untitled Deck"), "card_count": len(d.get("cards", [])),
          "created_at": d.get("created_at"), "last_accessed_at": d.get("last_accessed_at")}
         for did, d in decks.items() if d.get("created_at")],
        key=lambda x: x.get("last_accessed_at", x.get("created_at", "")), reverse=True)[:5]
    st.session_state.user_profile.update({
        "total_cards_overall": total_overall_cards, "mastery_percentage_overall": overall_mastery_perc,
        "cards_due_next_review_overall": due_overall_count, "recent_decks_info": recent_decks_info})
    if save_to_db:
        conn = get_db_connection()
        conn.cursor().execute("UPDATE app_profile SET total_cards_overall = ?, mastery_percentage_overall = ?, cards_due_next_review_overall = ?, last_updated = ? WHERE profile_id = 1",
                              (total_overall_cards, overall_mastery_perc, due_overall_count, datetime.datetime.now().isoformat()))
        conn.commit(); conn.close()

# --- Other Helper Functions (calculate_card_display_mastery, get_due_cards, etc.) ---
# ... (These remain the same) ...
def get_due_cards_for_deck(deck_cards):
    today_iso = datetime.date.today().isoformat()
    due_cards = [c for c in deck_cards if not c.get('next_review_at') or c.get('next_review_at') <= today_iso]
    due_cards.sort(key=lambda c: (c.get('interval_days', 0), c.get('next_review_at', '')))
    return due_cards

def calculate_card_display_mastery_percentage(card):
    interval = card.get('interval_days', 0)
    if interval <= 0: return 0;
    if interval >= MAX_INTERVAL_DAYS_DISPLAY_CAP : return 100
    if interval < 1: return 5;
    if interval < 3: return 20
    if interval < 7: return 40;
    if interval < 14: return 60
    if interval < 30: return 75;
    if interval < 90: return 90
    if interval < 180: return 95;
    return 100

def calculate_deck_overall_mastery(deck_cards):
    if not deck_cards: return 0.0
    return sum(calculate_card_display_mastery_percentage(c) for c in deck_cards) / len(deck_cards)

def render_card_view(card, show_answer, key_suffix=""):
    with st.container(border=True):
        st.subheader("Question:" if not show_answer else "Question & Answer:")
        st.markdown(f"**{card['question']}**")
        hint_key = f"hint_expanded_{card['id']}{key_suffix}"
        if card.get('hint') and not show_answer:
            if hint_key not in st.session_state: st.session_state[hint_key] = False
            show_hint_cb = st.checkbox("Show Hint?", value=st.session_state[hint_key], key=f"cb_{hint_key}")
            st.session_state[hint_key] = show_hint_cb
            if show_hint_cb: st.caption(f"Hint: {card['hint']}")
        if show_answer:
            st.divider(); st.markdown(f"**Answer:** {card['answer']}")
            if card.get('hint'): st.caption(f"Hint was: {card['hint']}")
        mastery_percent = calculate_card_display_mastery_percentage(card)
        st.progress(int(mastery_percent), text=f"Mastery: {int(mastery_percent)}% (Next review in {card.get('interval_days',0)} days)")

def export_deck_to_csv(deck):
    if not deck or not deck.get('cards'): return ""
    cards_data = []
    for card in deck['cards']:
        cards_data.append({
            'Question Type': card.get('question_type'), 'Question': card.get('question'), 'Answer': card.get('answer'),
            'Hint': card.get('hint'), 'Options': "; ".join(card.get('options', [])), 'Tags': "; ".join(card.get('tags', [])),
            'Easiness Factor': f"{card.get('easiness_factor', DEFAULT_EF):.2f}", 'Repetitions': card.get('repetitions', 0),
            'Current Interval (days)': card.get('interval_days', 0), 'Next Review Date': card.get('next_review_at'),
            'Last Review Date': card.get('last_reviewed_at'), 'Last Quality (q)': card.get('last_quality_response', ''),
            'Attempts': card.get('attempts',0), 'Correct Streak': card.get('correct_streak',0),
            'Display Mastery (%)': calculate_card_display_mastery_percentage(card),
        })
    return pd.DataFrame(cards_data).to_csv(index=False).encode('utf-8')

# --- CSV Import Logic ---
def parse_csv_to_cards(uploaded_file_content_stream):
    try:
        df = pd.read_csv(uploaded_file_content_stream)
        df.columns = df.columns.str.lower().str.strip()
    except Exception as e: return None, f"Error reading CSV: {e}."
    imported_cards, errors_found = [], []
    req_cols = ['question', 'answer', 'options']
    for idx, row in df.iterrows():
        missing = [c for c in req_cols if c not in row or pd.isna(row[c])]
        if missing: errors_found.append(f"Row {idx+2}: Missing: {', '.join(missing)}."); continue
        try:
            card = {'question': str(row['question']), 'answer': str(row['answer']),
                    'question_type': str(row.get('question_type', 'Identification')),
                    'hint': str(row.get('hint', '')) if pd.notna(row.get('hint')) else ''}
            opts_str = str(row.get('options', ''))
            opts = [o.strip() for o in opts_str.split(';') if o.strip()]
            if len(opts) < 2: errors_found.append(f"Row {idx+2}: 'options' needs >=2 values."); continue
            if card['answer'] not in opts: opts.append(card['answer'])
            opts = list(dict.fromkeys(opts))
            while len(opts) < 4: opts.append(f"DefOpt{len(opts)+1}")
            card['options'] = opts[:4]
            card['tags'] = [t.strip() for t in str(row.get('tags','')).split(';') if t.strip()] if pd.notna(row.get('tags')) else []
            card.update({
                'id': str(uuid.uuid4()), 'easiness_factor': float(row.get('easiness_factor', DEFAULT_EF)) if pd.notna(row.get('easiness_factor')) else DEFAULT_EF,
                'interval_days': int(row.get('interval_days', 0)) if pd.notna(row.get('interval_days')) else 0,
                'repetitions': int(row.get('repetitions', 0)) if pd.notna(row.get('repetitions')) else 0,
                'last_quality_response': int(row.get('last_quality_response')) if pd.notna(row.get('last_quality_response')) else None,
                'last_reviewed_at': str(row.get('last_reviewed_at')) if pd.notna(row.get('last_reviewed_at')) else None,
                'attempts': int(row.get('attempts',0)) if pd.notna(row.get('attempts')) else 0,
                'correct_streak': int(row.get('correct_streak',0)) if pd.notna(row.get('correct_streak')) else 0 })
            if pd.notna(row.get('next_review_at')): card['next_review_at'] = str(row.get('next_review_at'))
            elif card['last_reviewed_at'] and card['interval_days'] > 0:
                try: card['next_review_at'] = (datetime.date.fromisoformat(card['last_reviewed_at']) + datetime.timedelta(days=card['interval_days'])).isoformat()
                except: card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=card['interval_days'])).isoformat()
            else: card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=card['interval_days'])).isoformat()
            imported_cards.append(card)
        except Exception as e: errors_found.append(f"Row {idx+2}: Error - {e}.")
    err_summary = ("Issues:\n" + "\n".join(errors_found)) if errors_found else None
    return imported_cards, err_summary
