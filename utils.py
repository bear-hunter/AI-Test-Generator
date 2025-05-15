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
import sqlite3 # Import SQLite

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
DEFAULT_GEMINI_API_KEY = "placeholderAPI" # User-provided
GEMINI_MODEL_NAME = "gemini-2.5-flash-preview-04-17"      # User-provided
DB_NAME = "flashcard_ai_app.db"                           # Database file name

# --- Spaced Repetition Constants ---
DEFAULT_EF = 2.5
MIN_EF = 1.3
INITIAL_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6
MAX_INTERVAL_DAYS_DISPLAY_CAP = 365

QUALITY_MAPPING = {
    "Again (Soon)": 1, "Hard": 2, "Good": 4, "Easy": 5
}

# --- Database Setup and Connection ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # Access columns by name
    conn.execute("PRAGMA foreign_keys = ON") # Enforce foreign key constraints
    return conn

def initialize_database():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Decks Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        source_type TEXT,
        last_accessed_at TEXT,
        original_text TEXT
    )
    """)

    # Cards Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id TEXT PRIMARY KEY,
        deck_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        question_type TEXT,
        hint TEXT,
        options TEXT,           /* JSON string for list of options */
        tags TEXT,              /* JSON string for list of tags */
        easiness_factor REAL DEFAULT 2.5,
        interval_days INTEGER DEFAULT 0,
        repetitions INTEGER DEFAULT 0,
        last_quality_response INTEGER,
        last_reviewed_at TEXT,  /* ISO date */
        next_review_at TEXT,    /* ISO date */
        attempts INTEGER DEFAULT 0,
        correct_streak INTEGER DEFAULT 0,
        FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_card_deck_id ON cards (deck_id)")

    # App Profile Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_profile (
        profile_id INTEGER PRIMARY KEY DEFAULT 1,
        total_cards_overall INTEGER DEFAULT 0,
        mastery_percentage_overall REAL DEFAULT 0.0,
        cards_due_next_review_overall INTEGER DEFAULT 0,
        last_updated TEXT
    )
    """)
    cursor.execute("INSERT OR IGNORE INTO app_profile (profile_id) VALUES (1)")

    conn.commit()
    conn.close()
    logger.info("Database initialized (tables created if not existing).")

# --- Data Loading from DB ---
def load_decks_from_db():
    """Loads all decks and their cards from the database into session state."""
    decks_data = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM decks ORDER BY last_accessed_at DESC")
    db_decks = cursor.fetchall()

    for db_deck in db_decks:
        deck_id = db_deck['id']
        decks_data[deck_id] = dict(db_deck) # Convert sqlite3.Row to dict
        
        # Load cards for this deck
        cursor.execute("SELECT * FROM cards WHERE deck_id = ? ORDER BY id", (deck_id,)) # Order for consistency
        db_cards = cursor.fetchall()
        cards_list = []
        for db_card in db_cards:
            card_item = dict(db_card)
            try: # Safely parse JSON fields
                card_item['options'] = json.loads(db_card['options']) if db_card['options'] else []
                card_item['tags'] = json.loads(db_card['tags']) if db_card['tags'] else []
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON for card {db_card['id']} options/tags.")
                card_item['options'] = [] # Default to empty list on error
                card_item['tags'] = []
            cards_list.append(card_item)
        decks_data[deck_id]['cards'] = cards_list
    
    conn.close()
    st.session_state.decks = decks_data
    logger.info(f"Loaded {len(decks_data)} decks from database.")

def load_app_profile_from_db():
    """Loads the app profile from the database into session state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM app_profile WHERE profile_id = 1")
    profile_data = cursor.fetchone()
    conn.close()

    if profile_data:
        st.session_state.user_profile = {
            "total_cards_overall": profile_data['total_cards_overall'],
            "mastery_percentage_overall": profile_data['mastery_percentage_overall'],
            "cards_due_next_review_overall": profile_data['cards_due_next_review_overall'],
            "recent_decks_info": [] # This will be populated by update_global_user_profile_stats
        }
        logger.info("Loaded app profile from database.")
    else: # Should not happen if initialize_database ran correctly
        st.session_state.user_profile = {
            "total_cards_overall": 0, "mastery_percentage_overall": 0.0,
            "cards_due_next_review_overall": 0, "recent_decks_info": []
        }
        logger.warning("App profile not found in DB, initialized to default.")

# --- Session State Initialization ---
def initialize_app_session_state():
    """Initializes session state, including loading data from the database."""
    # Basic session variables
    if 'user_api_key' not in st.session_state:
        st.session_state.user_api_key = DEFAULT_GEMINI_API_KEY
    if 'gemini_model_name_config' not in st.session_state:
        st.session_state.gemini_model_name_config = GEMINI_MODEL_NAME
    if 'gemini_model' not in st.session_state:
        st.session_state.gemini_model = None
    if 'show_api_key_warning' not in st.session_state:
        st.session_state.show_api_key_warning = (
            st.session_state.user_api_key == DEFAULT_GEMINI_API_KEY or
            not st.session_state.user_api_key
        )
    # Complex state loaded from DB
    if 'decks' not in st.session_state: # Load only if not already populated
        load_decks_from_db()
    if 'user_profile' not in st.session_state:
        load_app_profile_from_db()
    
    # Other UI-related session variables
    if 'current_deck_id' not in st.session_state:
        st.session_state.current_deck_id = None
    if 'test_feedback' not in st.session_state:
        st.session_state.test_feedback = None
    if 'test_selected_option' not in st.session_state:
        st.session_state.test_selected_option = None
    if 'review_session_summary' not in st.session_state:
        st.session_state.review_session_summary = None
    
    # Update global stats based on loaded decks
    update_global_user_profile_stats(save_to_db=False) # Don't save to DB yet, just calculate from loaded state

# --- AI Interaction (configure_gemini_model, clean_gemini_json_response, generate_qna_cards) ---
# These functions remain largely the same as in your previous version that worked.
# Ensure card initialization within generate_qna_cards sets all necessary SR fields correctly.
def configure_gemini_model(force_reconfigure=False):
    if not force_reconfigure and st.session_state.get('gemini_model'):
        if st.session_state.user_api_key == getattr(st.session_state.gemini_model, '_client_api_key_check_temp', None) and \
           st.session_state.gemini_model_name_config == getattr(st.session_state.gemini_model, '_model_name_check_temp', None):
            return st.session_state.gemini_model
    api_key = st.session_state.get('user_api_key')
    model_name_to_use = st.session_state.get('gemini_model_name_config', GEMINI_MODEL_NAME)
    if not api_key or api_key == DEFAULT_GEMINI_API_KEY:
        st.session_state.show_api_key_warning = True
        st.session_state.gemini_model = None
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name_to_use)
        model._client_api_key_check_temp = api_key
        model._model_name_check_temp = model_name_to_use
        st.session_state.gemini_model = model
        st.session_state.show_api_key_warning = False
        return model
    except Exception as e:
        st.session_state.gemini_model = None
        st.session_state.show_api_key_warning = True
        if api_key != DEFAULT_GEMINI_API_KEY: st.error(f"Failed to configure Gemini: {e}")
        logger.error(f"Gemini configuration error: {e}")
        return None

def clean_gemini_json_response(json_string):
    match = re.search(r"```json\s*(.*?)\s*```", json_string, re.DOTALL)
    if match: json_string = match.group(1)
    else:
        match = re.search(r"```\s*(.*?)\s*```", json_string, re.DOTALL)
        if match: json_string = match.group(1)
    return re.sub(r",\s*([\}\]])", r"\1", json_string).strip()

def generate_qna_cards(text_content): # Ensure SR fields are initialized
    model = configure_gemini_model()
    if not model: return None, "Gemini model not initialized. Check API Key."
    prompt = f"""
    You are an AI assistant that generates educational flashcards from provided text.
    Your task is to create questions of two types: "Identification" and "Fill-in-the-Blank".
    For each question, provide:
    1. "question_type": Either "Identification" or "Fill-in-the-Blank".
    2. "question": The question text. For Fill-in-the-Blank, use underscores like "_____" to denote the blank.
    3. "answer": The correct answer.
    4. "hint": A brief hint. Empty string if not applicable.
    5. "options": A list of 4 strings for multiple-choice. One MUST be the "answer".
    6. "tags": A list of 1-3 relevant topic tags. Empty list if not applicable.
    Output as a single JSON list of objects. No explanatory text. Well-formed JSON.
    Example: {{"question_type": "Fill-in-the-Blank", "question": "The powerhouse is the _____.", "answer": "mitochondria", "hint": "ATP.", "options": ["nucleus", "ribosome", "mitochondria", "chloroplast"], "tags": ["Biology"]}}
    Text: --- {text_content} ---
    """
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


# --- Spaced Repetition Logic (SM-2 Inspired) & DB Update ---
def update_card_spaced_repetition(card, quality_q):
    """Updates card's SR parameters and saves the card to the database."""
    card['last_quality_response'] = quality_q
    card['last_reviewed_at'] = datetime.date.today().isoformat()
    card['attempts'] = card.get('attempts', 0) + 1

    ef = float(card.get('easiness_factor', DEFAULT_EF))
    n = int(card.get('repetitions', 0))
    interval = int(card.get('interval_days', 0))

    if quality_q < 3:
        n = 0; interval = INITIAL_INTERVAL_DAYS; card['correct_streak'] = 0
    else:
        card['correct_streak'] = card.get('correct_streak', 0) + 1
        if n == 0: interval = INITIAL_INTERVAL_DAYS
        elif n == 1: interval = SECOND_INTERVAL_DAYS
        else: interval = math.ceil(interval * ef)
        n += 1
    
    ef_new = ef + (0.1 - (5 - quality_q) * (0.08 + (5 - quality_q) * 0.02))
    ef = max(MIN_EF, ef_new)

    card['easiness_factor'] = round(ef, 2)
    card['repetitions'] = n
    card['interval_days'] = interval
    card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=interval)).isoformat()
    
    # Save updated card to DB
    save_or_update_card_in_db(card) # New function to handle this
    logger.info(f"Card '{card['id'][:8]}' updated (SR & DB): q={quality_q}, EF={ef:.2f}, n={n}, I={interval}d.")
    return card

def save_or_update_card_in_db(card_data):
    """Saves a new card or updates an existing one in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Convert lists to JSON strings for DB storage
    options_json = json.dumps(card_data.get('options', []))
    tags_json = json.dumps(card_data.get('tags', []))
    
    sql = """
    INSERT OR REPLACE INTO cards (
        id, deck_id, question, answer, question_type, hint, options, tags,
        easiness_factor, interval_days, repetitions, last_quality_response,
        last_reviewed_at, next_review_at, attempts, correct_streak
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        card_data['id'], card_data['deck_id'], card_data['question'], card_data['answer'],
        card_data.get('question_type'), card_data.get('hint'), options_json, tags_json,
        card_data.get('easiness_factor'), card_data.get('interval_days'), card_data.get('repetitions'),
        card_data.get('last_quality_response'), card_data.get('last_reviewed_at'),
        card_data.get('next_review_at'), card_data.get('attempts'), card_data.get('correct_streak')
    )
    cursor.execute(sql, params)
    conn.commit()
    conn.close()

# --- Deck Management & DB Interaction ---
def create_new_deck(title, source_type, original_text, cards_list):
    """Creates a new deck, saves it and its cards to the database, and updates session state."""
    deck_id = str(uuid.uuid4())
    now_iso = datetime.datetime.now().isoformat()
    new_deck_data = {
        "id": deck_id, "title": title, "created_at": now_iso, "source_type": source_type,
        "original_text": original_text, "last_accessed_at": now_iso, "cards": []
    }
    # Save deck metadata to DB
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO decks (id, title, created_at, source_type, last_accessed_at, original_text)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (deck_id, title, now_iso, source_type, now_iso, original_text))
    conn.commit()
    
    # Prepare and save cards
    processed_cards = []
    for card_item in cards_list:
        card_item['deck_id'] = deck_id # Assign deck_id to each card
        save_or_update_card_in_db(card_item) # Save individual card
        processed_cards.append(card_item) # Add to list for session state
    
    conn.close()
    new_deck_data['cards'] = processed_cards
    st.session_state.decks[deck_id] = new_deck_data # Update session state
    update_global_user_profile_stats() # Recalculate and save global stats
    logger.info(f"Created new deck '{title}' (ID: {deck_id}) with {len(processed_cards)} cards and saved to DB.")
    return deck_id

def update_deck_metadata_in_db(deck_id, title=None, last_accessed_at=None):
    """Updates deck's title or last_accessed_at time in the database."""
    if not title and not last_accessed_at: return

    conn = get_db_connection()
    cursor = conn.cursor()
    updates = []
    params = []
    if title:
        updates.append("title = ?")
        params.append(title)
    if last_accessed_at:
        updates.append("last_accessed_at = ?")
        params.append(last_accessed_at)
    
    params.append(deck_id)
    sql = f"UPDATE decks SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(sql, tuple(params))
    conn.commit()
    conn.close()
    logger.info(f"Updated metadata for deck ID {deck_id} in DB.")
    # Also update session state
    if deck_id in st.session_state.decks:
        if title: st.session_state.decks[deck_id]['title'] = title
        if last_accessed_at: st.session_state.decks[deck_id]['last_accessed_at'] = last_accessed_at

def delete_deck_from_db_and_session(deck_id):
    """Deletes a deck and its cards from the database and session state."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Foreign key ON DELETE CASCADE should handle cards, but explicit can be safer or for logging
    # cursor.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
    cursor.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    conn.commit()
    conn.close()
    
    # Remove from session state
    if deck_id in st.session_state.decks:
        del st.session_state.decks[deck_id]
    if st.session_state.get('current_deck_id') == deck_id:
        st.session_state.current_deck_id = None
    
    update_global_user_profile_stats() # Recalculate and save global stats
    logger.info(f"Deleted deck ID {deck_id} from DB and session.")

# --- Global Stats Calculation & DB Update ---
def update_global_user_profile_stats(save_to_db=True):
    """Calculates global user stats and optionally saves them to the database."""
    decks = st.session_state.get('decks', {})
    all_cards = [card for deck_id in decks for card in decks[deck_id].get('cards', [])]
    
    total_overall_cards = len(all_cards)
    overall_mastery_perc = calculate_deck_overall_mastery(all_cards) if all_cards else 0.0
    today_iso = datetime.date.today().isoformat()
    due_overall_count = sum(1 for card in all_cards if not card.get('next_review_at') or card.get('next_review_at') <= today_iso)

    # Update recent decks info (this part is purely for session display, not DB profile table)
    recent_decks_info = sorted(
        [{"id": did, "title": d.get("title", "Untitled Deck"), 
          "card_count": len(d.get("cards", [])), 
          "created_at": d.get("created_at"),
          "last_accessed_at": d.get("last_accessed_at")} # for sorting by access
         for did, d in decks.items() if d.get("created_at")],
        key=lambda x: x.get("last_accessed_at", x.get("created_at", "")), # Sort by last accessed, then created
        reverse=True
    )[:5]

    st.session_state.user_profile.update({
        "total_cards_overall": total_overall_cards,
        "mastery_percentage_overall": overall_mastery_perc,
        "cards_due_next_review_overall": due_overall_count,
        "recent_decks_info": recent_decks_info # This is for UI, not directly in app_profile table
    })

    if save_to_db:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE app_profile SET
            total_cards_overall = ?,
            mastery_percentage_overall = ?,
            cards_due_next_review_overall = ?,
            last_updated = ?
        WHERE profile_id = 1
        """, (total_overall_cards, overall_mastery_perc, due_overall_count, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        logger.info("Global app profile stats updated in DB.")


# --- Other Helper Functions (calculate_card_display_mastery, get_due_cards, etc.) ---
# These remain largely the same, but ensure they operate on the card dictionaries correctly.
def get_due_cards_for_deck(deck_cards):
    today_iso = datetime.date.today().isoformat()
    due_cards = [c for c in deck_cards if not c.get('next_review_at') or c.get('next_review_at') <= today_iso]
    due_cards.sort(key=lambda c: (c.get('interval_days', 0), c.get('next_review_at', '')))
    return due_cards

def calculate_card_display_mastery_percentage(card): # No change needed here
    interval = card.get('interval_days', 0)
    if interval <= 0: return 0
    if interval >= MAX_INTERVAL_DAYS_DISPLAY_CAP : return 100
    if interval < 1: return 5;  # ... (rest of the logic)
    if interval < 3: return 20
    if interval < 7: return 40
    if interval < 14: return 60
    if interval < 30: return 75
    if interval < 90: return 90
    if interval < 180: return 95
    return 100

def calculate_deck_overall_mastery(deck_cards): # No change needed here
    if not deck_cards: return 0.0
    return sum(calculate_card_display_mastery_percentage(c) for c in deck_cards) / len(deck_cards)

def render_card_view(card, show_answer, key_suffix=""): # No change needed here
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
            st.divider()
            st.markdown(f"**Answer:** {card['answer']}")
            if card.get('hint'): st.caption(f"Hint was: {card['hint']}")
        mastery_percent = calculate_card_display_mastery_percentage(card)
        st.progress(int(mastery_percent), text=f"Mastery: {int(mastery_percent)}% (Next review in {card.get('interval_days',0)} days)")

def export_deck_to_csv(deck): # No change needed here if it reads from session state deck
    if not deck or not deck.get('cards'): return ""
    # ... (rest of the function as before)
    cards_data = []
    for card in deck['cards']:
        cards_data.append({
            'Question Type': card.get('question_type'),
            'Question': card.get('question'),
            'Answer': card.get('answer'),
            'Hint': card.get('hint'),
            'Options': "; ".join(card.get('options', [])), # Options are already a list in session
            'Tags': "; ".join(card.get('tags', [])),      # Tags are already a list in session
            'Easiness Factor': f"{card.get('easiness_factor', DEFAULT_EF):.2f}",
            'Repetitions': card.get('repetitions', 0),
            'Current Interval (days)': card.get('interval_days', 0),
            'Next Review Date': card.get('next_review_at'),
            'Last Review Date': card.get('last_reviewed_at'),
            'Last Quality (q)': card.get('last_quality_response', ''),
            'Attempts': card.get('attempts',0),
            'Correct Streak': card.get('correct_streak',0),
            'Display Mastery (%)': calculate_card_display_mastery_percentage(card),
        })
    df = pd.DataFrame(cards_data)
    return df.to_csv(index=False).encode('utf-8')

# --- CSV Import Logic ---
def parse_csv_to_cards(uploaded_file_content_stream): # No DB interaction here, just parsing
    # ... (this function remains the same as in your previous version)
    try:
        df = pd.read_csv(uploaded_file_content_stream)
        df.columns = df.columns.str.lower().str.strip()
    except Exception as e:
        return None, f"Error reading CSV: {e}."
    imported_cards, errors_found = [], []
    req_cols = ['question', 'answer', 'options']
    for idx, row in df.iterrows():
        missing = [c for c in req_cols if c not in row or pd.isna(row[c])]
        if missing:
            errors_found.append(f"Row {idx+2}: Missing: {', '.join(missing)}.")
            continue
        try:
            card = {'question': str(row['question']), 'answer': str(row['answer']),
                    'question_type': str(row.get('question_type', 'Identification')),
                    'hint': str(row.get('hint', '')) if pd.notna(row.get('hint')) else ''}
            opts_str = str(row.get('options', ''))
            opts = [o.strip() for o in opts_str.split(';') if o.strip()]
            if len(opts) < 2:
                errors_found.append(f"Row {idx+2}: 'options' needs >=2 values.")
                continue
            if card['answer'] not in opts: opts.append(card['answer'])
            opts = list(dict.fromkeys(opts))
            while len(opts) < 4: opts.append(f"DefOpt{len(opts)+1}")
            card['options'] = opts[:4]
            card['tags'] = [t.strip() for t in str(row.get('tags','')).split(';') if t.strip()] if pd.notna(row.get('tags')) else []
            card.update({
                'id': str(uuid.uuid4()), # New ID for imported card
                'easiness_factor': float(row.get('easiness_factor', DEFAULT_EF)) if pd.notna(row.get('easiness_factor')) else DEFAULT_EF,
                'interval_days': int(row.get('interval_days', 0)) if pd.notna(row.get('interval_days')) else 0,
                'repetitions': int(row.get('repetitions', 0)) if pd.notna(row.get('repetitions')) else 0,
                'last_quality_response': int(row.get('last_quality_response')) if pd.notna(row.get('last_quality_response')) else None,
                'last_reviewed_at': str(row.get('last_reviewed_at')) if pd.notna(row.get('last_reviewed_at')) else None,
                'attempts': int(row.get('attempts',0)) if pd.notna(row.get('attempts')) else 0,
                'correct_streak': int(row.get('correct_streak',0)) if pd.notna(row.get('correct_streak')) else 0
            })
            if pd.notna(row.get('next_review_at')): card['next_review_at'] = str(row.get('next_review_at'))
            elif card['last_reviewed_at'] and card['interval_days'] > 0:
                try: card['next_review_at'] = (datetime.date.fromisoformat(card['last_reviewed_at']) + datetime.timedelta(days=card['interval_days'])).isoformat()
                except: card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=card['interval_days'])).isoformat()
            else: card['next_review_at'] = (datetime.date.today() + datetime.timedelta(days=card['interval_days'])).isoformat()
            imported_cards.append(card)
        except Exception as e: errors_found.append(f"Row {idx+2}: Error - {e}.")
    err_summary = ("Issues:\n" + "\n".join(errors_found)) if errors_found else None
    return imported_cards, err_summary
