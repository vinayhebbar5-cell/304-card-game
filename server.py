import asyncio
import http
import json
import os
import random
import uuid
import websockets

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

# Global dict of active rooms
ROOMS = {}

def read_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

async def process_request(connection, request):
    # If it is a websocket upgrade request
    if "upgrade" in request.headers:
        if request.path.split("?")[0] == "/ws":
            return None  # Let handshake proceed
        else:
            return connection.respond(http.HTTPStatus.NOT_FOUND, "Not Found")
            
    # Regular HTTP static file serving
    path = request.path.split("?")[0]
    if path == "/":
        path = "/index.html"
        
    filename = path.lstrip("/")
    full_path = os.path.abspath(os.path.join(STATIC_DIR, filename))
    
    # Path traversal protection
    if not full_path.startswith(os.path.abspath(STATIC_DIR)):
        return connection.respond(http.HTTPStatus.FORBIDDEN, "Forbidden")
        
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        return connection.respond(http.HTTPStatus.NOT_FOUND, "Not Found")
        
    # Determine MIME type
    if path.endswith(".html"):
        mime_type = "text/html; charset=utf-8"
    elif path.endswith(".css"):
        mime_type = "text/css; charset=utf-8"
    elif path.endswith(".js"):
        mime_type = "application/javascript; charset=utf-8"
    else:
        mime_type = "text/plain; charset=utf-8"
        
    try:
        content = await asyncio.to_thread(read_file, full_path)
        response = connection.respond(http.HTTPStatus.OK, content)
        if "Content-Type" in response.headers:
            del response.headers["Content-Type"]
        response.headers["Content-Type"] = mime_type
        # Add cache control headers for local dev reload convenience
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
    except Exception as e:
        return connection.respond(http.HTTPStatus.INTERNAL_SERVER_ERROR, f"Error: {str(e)}")



CARD_VALUES = ["J", "9", "A", "10", "K", "Q"]
CARD_POINTS = {"J": 3, "9": 2, "A": 1, "10": 1, "K": 0, "Q": 0}
CARD_RANKS = {"J": 5, "9": 4, "A": 3, "10": 2, "K": 1, "Q": 0}
SUITS = ["H", "D", "C", "S"]  # Hearts, Diamonds, Clubs, Spades
SUIT_NAMES = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}

BID_LEVELS = ["Chance", "200", "10", "20", "30", "40"]
BID_TARGETS = {
    "Chance": 11,
    "200": 10,
    "10": 9,
    "20": 8,
    "30": 7,
    "40": 6
}

# --- Game Engine Helpers ---

def create_deck():
    deck = []
    for suit in SUITS:
        for val in CARD_VALUES:
            deck.append({"suit": suit, "value": val})
    return deck

def beats(card_a, card_b, led_suit, trump_suit):
    """Returns True if card_a beats card_b according to 304 priority rules."""
    # Trump suit beats any other suit
    if card_a["suit"] == trump_suit and card_b["suit"] != trump_suit:
        return True
    if card_b["suit"] == trump_suit and card_a["suit"] != trump_suit:
        return False
    
    # If both are trumps, compare ranks
    if card_a["suit"] == trump_suit and card_b["suit"] == trump_suit:
        return CARD_RANKS[card_a["value"]] > CARD_RANKS[card_b["value"]]
    
    # Led suit beats non-led, non-trump suits
    if card_a["suit"] == led_suit and card_b["suit"] != led_suit:
        return True
    if card_b["suit"] == led_suit and card_a["suit"] != led_suit:
        return False
    
    # If both are led suit, compare ranks
    if card_a["suit"] == led_suit and card_b["suit"] == led_suit:
        return CARD_RANKS[card_a["value"]] > CARD_RANKS[card_b["value"]]
    
    # Otherwise, same suit compare ranks
    if card_a["suit"] == card_b["suit"]:
        return CARD_RANKS[card_a["value"]] > CARD_RANKS[card_b["value"]]
    
    # Default: Card played first maintains priority
    return False

def check_marriages(hand):
    """Returns a list of suits in which the player holds a King & Queen marriage."""
    suits_with_marriage = []
    for suit in SUITS:
        has_k = any(c["suit"] == suit and c["value"] == "K" for c in hand)
        has_q = any(c["suit"] == suit and c["value"] == "Q" for c in hand)
        if has_k and has_q:
            suits_with_marriage.append(suit)
    return suits_with_marriage

# --- Game State Transitions ---

def init_game_state():
    return {
        "status": "LOBBY",
        "dealer_index": 0,
        "team_scores": {"1": 0, "2": 0},  # Team 1 (0 & 2), Team 2 (1 & 3)
        "round_number": 0,
        "hands": {0: [], 1: [], 2: [], 3: []},
        "bids": [],
        "highest_bid": None,      # {"player_index": int, "bid_level": str}
        "bid_winner": None,       # int (index)
        "bidding_turn": None,     # int (index)
        "bidding_passed": [],     # list of player indices who passed
        "trump_suit": None,       # str
        "trump_revealed": False,
        "trump_selection_method": None,  # "secret_first_deal", "secret_second_deal_chance", "vakkai"
        "chance_face_down_cards": None,  # For Chance selection
        "vakkai_caller": None,
        "vakkai_votes": {},       # {player_index: True/False}
        "vakkai_turn": None,
        "vakkai_decision_count": 0,
        "ready_players": [],
        "tricks": [],             # list of completed tricks
        "current_trick": None,    # {"lead_player_index": int, "plays": {player_index: card}}
        "turn": None,             # int (index)
        "marriages": {
            0: {"available": [], "shown": [], "broken": []},
            1: {"available": [], "shown": [], "broken": []},
            2: {"available": [], "shown": [], "broken": []},
            3: {"available": [], "shown": [], "broken": []}
        },
        "round_points": {"1": 0, "2": 0},       # Card points won in current round
        "marriage_points": {"1": 0, "2": 0},    # Marriage bonus points in current round
        "tricks_won_by_team": {"1": 0, "2": 0},  # Trick count
        "kotu_called": None,     # player_index or None
        "round_history": [],
        "last_trick_winner": None,
        "logs": []
    }

def add_log(game_state, message):
    game_state["logs"].append(message)
    if len(game_state["logs"]) > 25:
        game_state["logs"].pop(0)

def start_new_round(game_state):
    game_state["round_number"] += 1
    game_state["status"] = "DEALING_1"
    
    # Rotate dealer counter-clockwise (increment index by 1)
    if game_state["round_number"] > 1:
        game_state["dealer_index"] = (game_state["dealer_index"] + 1) % 4
        
    dealer = game_state["dealer_index"]
    add_log(game_state, f"Round {game_state['round_number']} started! Dealer is Player {dealer + 1}.")
    
    # Reset round variables
    game_state["hands"] = {0: [], 1: [], 2: [], 3: []}
    game_state["bids"] = []
    game_state["highest_bid"] = None
    game_state["bid_winner"] = None
    game_state["bidding_passed"] = []
    game_state["trump_suit"] = None
    game_state["trump_revealed"] = False
    game_state["trump_selection_method"] = None
    game_state["chance_face_down_cards"] = None
    game_state["vakkai_caller"] = None
    game_state["vakkai_votes"] = {}
    game_state["vakkai_turn"] = None
    game_state["vakkai_decision_count"] = 0
    game_state["ready_players"] = []
    game_state["tricks"] = []
    game_state["current_trick"] = None
    game_state["turn"] = None
    game_state["marriages"] = {
        0: {"available": [], "shown": [], "broken": []},
        1: {"available": [], "shown": [], "broken": []},
        2: {"available": [], "shown": [], "broken": []},
        3: {"available": [], "shown": [], "broken": []}
    }
    game_state["round_points"] = {"1": 0, "2": 0}
    game_state["marriage_points"] = {"1": 0, "2": 0}
    game_state["tricks_won_by_team"] = {"1": 0, "2": 0}
    game_state["kotu_called"] = None
    game_state["last_trick_winner"] = None
    game_state["vakkai_timer_started"] = False
    
    # Create and Shuffle Deck
    deck = create_deck()
    random.shuffle(deck)
    
    # Deal Part 1: 3 cards each (counter-clockwise, starting with player to dealer's right)
    # Seats are 0 (Bottom), 1 (Right), 2 (Top), 3 (Left)
    # Dealer's right is (dealer + 1) % 4
    deal_sequence = [(dealer + i) % 4 for i in [1, 2, 3, 0]]
    for player_idx in deal_sequence:
        game_state["hands"][player_idx] = [deck.pop(), deck.pop(), deck.pop()]
        
    game_state["remaining_deck"] = deck  # Temp storage for deck
    
    # Set bidding turn to dealer's right
    game_state["bidding_turn"] = (dealer + 1) % 4
    game_state["status"] = "BIDDING"
    add_log(game_state, f"First 3 cards dealt. Bidding started with Player {game_state['bidding_turn'] + 1}.")

def handle_bid(game_state, player_idx, bid_level):
    if game_state["status"] != "BIDDING" or game_state["bidding_turn"] != player_idx:
        return False
        
    # Validation
    is_first_bidder = player_idx == (game_state["dealer_index"] + 1) % 4
    has_bids = len(game_state["bids"]) > 0
    
    if bid_level == "Pass":
        if is_first_bidder and not has_bids:
            # First bidder cannot pass initially
            return False
        game_state["bidding_passed"].append(player_idx)
        add_log(game_state, f"Player {player_idx + 1} passed.")
    else:
        # Check if bid is valid in the scale
        if bid_level not in BID_LEVELS:
            return False
            
        current_highest_level = game_state["highest_bid"]["bid_level"] if game_state["highest_bid"] else None
        
        if current_highest_level is not None:
            # Chance Skip Rule: if current highest is Chance, next cannot be 200
            if current_highest_level == "Chance" and bid_level == "200":
                return False
            if BID_LEVELS.index(bid_level) <= BID_LEVELS.index(current_highest_level):
                # Must be higher
                return False
                
        game_state["highest_bid"] = {"player_index": player_idx, "bid_level": bid_level}
        add_log(game_state, f"Player {player_idx + 1} bids {bid_level}.")
        
    game_state["bids"].append({"player_index": player_idx, "bid_level": bid_level})
    
    # Move to next bidding turn (one-pass circuit)
    game_state["bidding_turn"] = (player_idx + 1) % 4
    
    # Check if bidding is complete
    # Strict One-Pass: completes when the dealer acts OR maximum bid (40) is reached
    is_max_bid = game_state["highest_bid"] and game_state["highest_bid"]["bid_level"] == "40"
    is_dealer_acted = player_idx == game_state["dealer_index"]
    
    if is_max_bid or is_dealer_acted:
        # Bidding complete!
        winning_bid = game_state["highest_bid"]
        if winning_bid:
            game_state["bid_winner"] = winning_bid["player_index"]
            bid_level = winning_bid["bid_level"]
            
            add_log(game_state, f"Bidding complete! Player {game_state['bid_winner'] + 1} wins the bid with {bid_level}.")
            
            # Transition
            if bid_level == "Chance":
                # No trump choice needed now, proceed to second deal
                game_state["trump_selection_method"] = "secret_second_deal_chance"
                deal_part_2(game_state)
            else:
                game_state["status"] = "SELECTING_TRUMP"
                game_state["trump_selection_method"] = "secret_first_deal"
                add_log(game_state, f"Player {game_state['bid_winner'] + 1} is choosing the Trump suit secretly...")
        else:
            add_log(game_state, "Bidding complete but no bid was placed! Starting new round.")
            start_new_round(game_state)
            
    return True

def select_trump_suit(game_state, player_idx, card_index):
    """Winning bidder chooses Trump secretly from first 3 cards."""
    if game_state["status"] != "SELECTING_TRUMP" or game_state["bid_winner"] != player_idx:
        return False
        
    hand = game_state["hands"][player_idx]
    if card_index < 0 or card_index >= len(hand):
        return False
        
    card = hand[card_index]
    game_state["trump_suit"] = card["suit"]
    # We do NOT reveal the trump suit yet to others
    add_log(game_state, f"Player {player_idx + 1} has secretly chosen the Trump card.")
    
    # Proceed to Second Deal
    deal_part_2(game_state)
    return True

def deal_part_2(game_state):
    game_state["status"] = "DEALING_2"
    deck = game_state["remaining_deck"]
    
    # Deal remaining 3 cards each (counter-clockwise starting with player to dealer's right)
    dealer = game_state["dealer_index"]
    deal_sequence = [(dealer + i) % 4 for i in [1, 2, 3, 0]]
    
    second_batches = {}
    for player_idx in deal_sequence:
        batch = [deck.pop(), deck.pop(), deck.pop()]
        second_batches[player_idx] = batch
        game_state["hands"][player_idx].extend(batch)
        
    del game_state["remaining_deck"]  # Clean up
    add_log(game_state, "Second batch of 3 cards dealt to all players (6 cards total).")
    
    # If Chance was the winning bid, the bidder must choose a Trump card face-down from their second batch
    if game_state["trump_selection_method"] == "secret_second_deal_chance":
        bidder = game_state["bid_winner"]
        # Save the 3 cards from the second batch so they can click one face down
        game_state["chance_face_down_cards"] = second_batches[bidder]
        game_state["status"] = "CHANCE_TRUMP_SELECT"
        add_log(game_state, f"Chance bid active: Player {bidder + 1} must pick a face-down card to set the Trump suit.")
    else:
        # Normal game, jump to Vakkai override option
        enter_vakkai_window(game_state)

def select_chance_trump(game_state, player_idx, card_index):
    """Under Chance bid, bidder picks one of the 3 second-deal cards face-down."""
    if game_state["status"] != "CHANCE_TRUMP_SELECT" or game_state["bid_winner"] != player_idx:
        return False
        
    face_down_cards = game_state["chance_face_down_cards"]
    if card_index < 0 or card_index >= len(face_down_cards):
        return False
        
    selected_card = face_down_cards[card_index]
    game_state["trump_suit"] = selected_card["suit"]
    game_state["chance_face_down_cards"] = None
    
    add_log(game_state, f"Player {player_idx + 1} selected a face-down card. Trump suit is set.")
    enter_vakkai_window(game_state)
    return True

def enter_ready_check_phase(game_state):
    game_state["status"] = "READY_CHECK"
    game_state["ready_players"] = []
    add_log(game_state, "Ready check phase started. All players, please click Ready.")

def enter_vakkai_window(game_state):
    game_state["status"] = "VAKKAI_OR_PLAY"
    game_state["vakkai_votes"] = {}
    game_state["vakkai_decision_count"] = 0
    game_state["vakkai_turn"] = game_state["bid_winner"]
    add_log(game_state, f"Vakkai Call phase active. Player {game_state['vakkai_turn'] + 1} has the first opportunity to call Vakkai.")

def handle_vakkai_call(game_state, player_idx, call_vakkai):
    if game_state["status"] != "VAKKAI_OR_PLAY" or game_state["vakkai_turn"] != player_idx:
        return False
        
    if call_vakkai:
        # Player calls Vakkai!
        # It takes supreme priority, cancels all previous bids
        game_state["vakkai_caller"] = player_idx
        game_state["bid_winner"] = player_idx
        game_state["highest_bid"] = {"player_index": player_idx, "bid_level": "Vakkai"}
        game_state["trump_selection_method"] = "vakkai"
        game_state["trump_suit"] = None  # To be set by first lead card
        game_state["trump_revealed"] = False
        
        # Clean up any chance selection face down cards
        game_state["chance_face_down_cards"] = None
        
        add_log(game_state, f"🔴 VAKKAI CALL! Player {player_idx + 1} has called VAKKAI! All previous bids cancelled.")
        
        enter_ready_check_phase(game_state)
    else:
        # If not call_vakkai
        game_state["vakkai_votes"][player_idx] = False
        game_state["vakkai_decision_count"] += 1
        
        if game_state["vakkai_decision_count"] < 4:
            next_turn = (player_idx + 1) % 4
            game_state["vakkai_turn"] = next_turn
            add_log(game_state, f"Player {player_idx + 1} declined Vakkai. Opportunity moves to Player {next_turn + 1}.")
        else:
            add_log(game_state, "No Vakkai called. Standard game rules apply.")
            enter_ready_check_phase(game_state)
                
    return True

def redeal_round(game_state):
    dealer = game_state["dealer_index"]
    add_log(game_state, f"⚠️ Game called off! Opponent team has no Trump cards ({SUIT_NAMES[game_state['trump_suit']]}). Redealing with same dealer.")
    
    # Reset round variables but keep dealer_index and round_number
    game_state["hands"] = {0: [], 1: [], 2: [], 3: []}
    game_state["bids"] = []
    game_state["highest_bid"] = None
    game_state["bid_winner"] = None
    game_state["bidding_passed"] = []
    game_state["trump_suit"] = None
    game_state["trump_revealed"] = False
    game_state["trump_selection_method"] = None
    game_state["chance_face_down_cards"] = None
    game_state["vakkai_caller"] = None
    game_state["vakkai_votes"] = {}
    game_state["vakkai_turn"] = None
    game_state["vakkai_decision_count"] = 0
    game_state["ready_players"] = []
    game_state["tricks"] = []
    game_state["current_trick"] = None
    game_state["turn"] = None
    game_state["marriages"] = {
        0: {"available": [], "shown": [], "broken": []},
        1: {"available": [], "shown": [], "broken": []},
        2: {"available": [], "shown": [], "broken": []},
        3: {"available": [], "shown": [], "broken": []}
    }
    game_state["round_points"] = {"1": 0, "2": 0}
    game_state["marriage_points"] = {"1": 0, "2": 0}
    game_state["tricks_won_by_team"] = {"1": 0, "2": 0}
    game_state["kotu_called"] = None
    game_state["last_trick_winner"] = None
    
    # Create and Shuffle Deck
    deck = create_deck()
    random.shuffle(deck)
    
    # Deal Part 1: 3 cards each (counter-clockwise starting with player to dealer's right)
    deal_sequence = [(dealer + i) % 4 for i in [1, 2, 3, 0]]
    for player_idx in deal_sequence:
        game_state["hands"][player_idx] = [deck.pop(), deck.pop(), deck.pop()]
        
    game_state["remaining_deck"] = deck
    game_state["bidding_turn"] = (dealer + 1) % 4
    game_state["status"] = "BIDDING"
    add_log(game_state, f"First 3 cards dealt. Bidding started with Player {game_state['bidding_turn'] + 1}.")

def start_playing_phase(game_state):
    # Check if opposing team has no trump card (turpu)
    if game_state["vakkai_caller"] is None and game_state["trump_suit"] is not None:
        bidder = game_state["bid_winner"]
        bidder_team = "1" if bidder in [0, 2] else "2"
        opponents = [1, 3] if bidder_team == "1" else [0, 2]
        
        trump_suit = game_state["trump_suit"]
        opponent_trumps = sum(
            1 for p_idx in opponents
            for card in game_state["hands"][p_idx]
            if card["suit"] == trump_suit
        )
        if opponent_trumps == 0:
            redeal_round(game_state)
            return
            
    game_state["status"] = "PLAYING"
    game_state["tricks"] = []
    
    # Initialize Marriage capabilities
    for p_idx in range(4):
        suits = check_marriages(game_state["hands"][p_idx])
        game_state["marriages"][p_idx]["available"] = suits
        game_state["marriages"][p_idx]["shown"] = []
        game_state["marriages"][p_idx]["broken"] = []
        
    # Determine who leads Trick 1
    if game_state["vakkai_caller"] is not None:
        # Vakkai caller leads Trick 1
        lead_player = game_state["vakkai_caller"]
    else:
        # Standard: immediate right of the winning bidder leads
        lead_player = (game_state["bid_winner"] + 1) % 4
        
    game_state["current_trick"] = {"lead_player_index": lead_player, "plays": {}}
    game_state["turn"] = lead_player
    add_log(game_state, f"Trick 1 starts! Player {lead_player + 1}'s turn to lead.")

def handle_play_card(game_state, player_idx, card):
    """Executes playing a card for player_idx."""
    if game_state["status"] != "PLAYING" or game_state["turn"] != player_idx:
        return False
        
    hand = game_state["hands"][player_idx]
    
    # Verify player has the card
    card_in_hand = None
    for c in hand:
        if c["suit"] == card["suit"] and c["value"] == card["value"]:
            card_in_hand = c
            break
            
    if not card_in_hand:
        return False
        
    trick = game_state["current_trick"]
    plays = trick["plays"]
    
    # Rules Validation
    # If not leading, must follow suit if possible
    if len(plays) > 0:
        lead_card = plays[trick["lead_player_index"]]
        led_suit = lead_card["suit"]
        
        # Check if player has the led suit in hand
        has_led_suit = any(c["suit"] == led_suit for c in hand)
        if has_led_suit and card["suit"] != led_suit:
            # Must follow suit!
            return False
            
    # Remove from hand
    hand.remove(card_in_hand)
    
    # Place on trick
    plays[player_idx] = card_in_hand
    add_log(game_state, f"Player {player_idx + 1} played {card_in_hand['value']} of {SUIT_NAMES[card_in_hand['suit']]}.")
    
    # Vakkai First Lead card sets Trump suit!
    if game_state["vakkai_caller"] == player_idx and len(plays) == 1 and game_state["trump_suit"] is None:
        game_state["trump_suit"] = card_in_hand["suit"]
        game_state["trump_revealed"] = True
        add_log(game_state, f"Vakkai Trump suit set to {SUIT_NAMES[game_state['trump_suit']]}!")
        
    # Standard Trump Reveal: Immediately after first card is played in Trick 1, reveal Trump!
    if len(game_state["tricks"]) == 0 and len(plays) == 1 and not game_state["trump_revealed"]:
        game_state["trump_revealed"] = True
        add_log(game_state, f"Trump suit revealed: {SUIT_NAMES[game_state['trump_suit']]}!")
        
    # Check if this play breaks any marriages for this player
    # If team hasn't won a trick yet, playing K or Q of an available marriage breaks it.
    team = "1" if player_idx in [0, 2] else "2"
    if game_state["tricks_won_by_team"][team] == 0:
        available_marriages = list(game_state["marriages"][player_idx]["available"])
        for suit in available_marriages:
            if card_in_hand["suit"] == suit and card_in_hand["value"] in ["K", "Q"]:
                # Marriage is broken!
                game_state["marriages"][player_idx]["available"].remove(suit)
                game_state["marriages"][player_idx]["broken"].append(suit)
                add_log(game_state, f"Player {player_idx + 1}'s Marriage in {SUIT_NAMES[suit]} is BROKEN!")
                
    # Rotate turn counter-clockwise
    if len(plays) < 4:
        game_state["turn"] = (player_idx + 1) % 4
    else:
        # Trick complete!
        # We need to resolve the trick. We can do it asynchronously or immediately.
        # To let players see the full trick, we will pause briefly, or resolve on next action.
        # But server side we can resolve immediately and notify clients.
        # Clients can animate it.
        resolve_trick(game_state)
        
    return True

def resolve_trick(game_state):
    trick = game_state["current_trick"]
    plays = trick["plays"]
    lead_player = trick["lead_player_index"]
    led_suit = plays[lead_player]["suit"]
    trump_suit = game_state["trump_suit"]
    
    # Determine Trick Winner
    winner_idx = lead_player
    winning_card = plays[lead_player]
    
    for p_idx in plays:
        if p_idx == lead_player:
            continue
        card = plays[p_idx]
        if beats(card, winning_card, led_suit, trump_suit):
            winner_idx = p_idx
            winning_card = card
            
    # Check Vakkai Rules:
    # Vakkai bidder must win all tricks alone.
    # Partner sabotage: if partner plays a card higher than bidder's card.
    is_vakkai = game_state["vakkai_caller"] is not None
    vakkai_failed = False
    
    if is_vakkai:
        vakkai_caller = game_state["vakkai_caller"]
        partner = (vakkai_caller + 2) % 4
        
        # Check partner sabotage:
        partner_card = plays.get(partner)
        caller_card = plays.get(vakkai_caller)
        
        if partner_card and caller_card:
            if beats(partner_card, caller_card, led_suit, trump_suit):
                # Sabotage!
                vakkai_failed = True
                winner_idx = (vakkai_caller + 1) % 4  # Award trick to opposing team
                add_log(game_state, f"💥 PARTNER SABOTAGE! Player {partner + 1} played a card higher than Vakkai Caller {vakkai_caller + 1}.")
                add_log(game_state, "Trick awarded to opposing team. Vakkai bid FAILS instantly!")
                
        # Check if opponent won the trick
        if not vakkai_failed and winner_idx != vakkai_caller:
            vakkai_failed = True
            add_log(game_state, f"Opponent Player {winner_idx + 1} won the trick. Vakkai bid FAILS!")
            
    # Add trick points to the winning team
    winner_team = "1" if winner_idx in [0, 2] else "2"
    trick_points = sum(CARD_POINTS[c["value"]] for c in plays.values())
    
    # Update state
    game_state["round_points"][winner_team] += trick_points
    game_state["tricks_won_by_team"][winner_team] += 1
    game_state["last_trick_winner"] = winner_idx
    
    # Archive the trick
    trick["winner_player_index"] = winner_idx
    trick["points"] = trick_points
    game_state["tricks"].append(trick)
    
    add_log(game_state, f"Player {winner_idx + 1} wins the trick (+{trick_points} points for Team {winner_team}).")
    
    # Is it the team's first trick? If so, trigger potential marriage shows.
    first_trick_for_team = game_state["tricks_won_by_team"][winner_team] == 1
    
    # We pause game turn to allow marriage showing
    has_possible_marriage = False
    if first_trick_for_team and not is_vakkai:
        # Check if anyone on the winning team has available marriages
        for p_idx in [0, 2] if winner_team == "1" else [1, 3]:
            if len(game_state["marriages"][p_idx]["available"]) > 0:
                has_possible_marriage = True
                
    # Check for game end or next trick
    if vakkai_failed:
        # End round immediately in case of Vakkai failure
        resolve_round_end(game_state, vakkai_success=False)
    elif len(game_state["tricks"]) == 6:
        # 6 tricks completed, check Vakkai success
        if is_vakkai:
            resolve_round_end(game_state, vakkai_success=True)
        else:
            resolve_round_end(game_state)
    else:
        # Game continues to next trick
        # Set next lead turn to the winner of the previous trick
        game_state["current_trick"] = {"lead_player_index": winner_idx, "plays": {}}
        game_state["turn"] = winner_idx
        
        # If Kotu is eligible:
        # "If one team wins all tricks from Round 1 through Round 5, the player leading Round 6 can call 'Kotu'."
        if len(game_state["tricks"]) == 5:
            # Check if one team won all 5 tricks
            tricks_team_1 = game_state["tricks_won_by_team"]["1"]
            tricks_team_2 = game_state["tricks_won_by_team"]["2"]
            if (tricks_team_1 == 5 or tricks_team_2 == 5) and not is_vakkai:
                # The winner of Trick 5 can call Kotu!
                # Wait, the winner of Trick 5 is winner_idx.
                game_state["status"] = "KOTU_DECISION"
                add_log(game_state, f"Team won 5 tricks! Player {winner_idx + 1} can call KOTU for the final trick.")
        
        # If a marriage can be shown, client displays buttons, but turn flows.
        # We don't block the backend thread loop, we just enable the client-side button.

def handle_show_marriage(game_state, player_idx, suit):
    """Player reveals a Marriage to the player on their left."""
    if game_state["status"] not in ["PLAYING", "KOTU_DECISION"]:
        return False
        
    # Verify player has the marriage
    marriages = game_state["marriages"][player_idx]
    if suit not in marriages["available"]:
        return False
        
    team = "1" if player_idx in [0, 2] else "2"
    
    # Must have won exactly 1 trick to show (the 1st pattu)
    if game_state["tricks_won_by_team"][team] != 1:
        return False
        
    # Check if a Vakkai bid is active (skip marriage in Vakkai)
    if game_state["vakkai_caller"] is not None:
        return False
        
    # Move marriage from available to shown
    marriages["available"].remove(suit)
    marriages["shown"].append(suit)
    
    # Calculate bonus points: 4 if trump suit, 2 if other suit
    is_trump = suit == game_state["trump_suit"]
    bonus = 4 if is_trump else 2
    game_state["marriage_points"][team] += bonus
    
    left_player = (player_idx + 3) % 4  # Player to the left (counter-clockwise is 0->1->2->3)
    # Wait, in our layout:
    # 0's left is 3. 1's left is 0. 2's left is 1. 3's left is 2.
    # Indeed, left is (idx + 3) % 4.
    
    add_log(game_state, f"💍 MARRIAGE SHOWN! Player {player_idx + 1} reveals K & Q of {SUIT_NAMES[suit]} to Player {left_player + 1} (+{bonus} Golden Points/Bonus!)")
    return True

def handle_kotu_call(game_state, player_idx, call_kotu):
    if game_state["status"] != "KOTU_DECISION" or game_state["turn"] != player_idx:
        return False
        
    if call_kotu:
        game_state["kotu_called"] = player_idx
        add_log(game_state, f"🔥 KOTU CALLED! Player {player_idx + 1} calls Kotu for the final trick!")
    else:
        add_log(game_state, f"Player {player_idx + 1} declines Kotu.")
        
    # Move to playing status for the final trick
    game_state["status"] = "PLAYING"
    return True

def adjust_team_scores(scores, bidding_team, opposing_team, diff):
    if diff == 0:
        return
        
    s_bid = scores[bidding_team]
    s_opp = scores[opposing_team]
    
    if diff > 0:
        # Bidding team wins points
        points = diff
        
        # 1. First use points to reduce bidding team's negative score to 0
        used = 0
        if s_bid < 0:
            used = min(points, -s_bid)
            s_bid += used
        points_left = points - used
        
        # 2. Next, deduct points from opposing team's positive score
        deducted = 0
        if points_left > 0 and s_opp > 0:
            deducted = min(points_left, s_opp)
            s_opp -= deducted
        points_left -= deducted
        
        # 3. Add any remaining points to bidding team's score
        if points_left > 0:
            s_bid += points_left
            
    else:
        # Bidding team loses points
        points = -diff
        
        # 1. First, bidding team loses points from their positive score
        lost = 0
        if s_bid > 0:
            lost = min(points, s_bid)
            s_bid -= lost
        points_left = points - lost
        
        # 2. Next, if points left to lose, apply capping rules
        if points_left > 0:
            if s_opp < 0:
                # Bidding team cannot go negative, opposing team's negative score is reduced
                s_opp += points_left
            else:
                # Bidding team goes negative
                s_bid -= points_left
                
    scores[bidding_team] = s_bid
    scores[opposing_team] = s_opp

def resolve_round_end(game_state, vakkai_success=None):
    game_state["status"] = "ROUND_END"
    
    # Determine points and adjust team scores
    bidding_player = game_state["bid_winner"]
    bidding_team = "1" if bidding_player in [0, 2] else "2"
    opposing_team = "2" if bidding_team == "1" else "1"
    
    bid_level = game_state["highest_bid"]["bid_level"]
    is_vakkai = bid_level == "Vakkai"
    
    golden_points_diff = 0
    winner_msg = ""
    
    if is_vakkai:
        if vakkai_success:
            golden_points_diff = 3
            adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, 3)
            winner_msg = f"Vakkai Success! Team {bidding_team} wins +3 Golden Points."
        else:
            golden_points_diff = -3
            adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, -3)
            # Opponent team does not get +3 points
            winner_msg = f"Vakkai Failed! Team {bidding_team} loses -3 Golden Points."
    else:
        # Standard game mode
        # Calculate team point totals: marriage points shown by a team are subtracted from the opposing team's points (capped at 0)
        total_pts_bid_team = max(0, game_state["round_points"][bidding_team] - game_state["marriage_points"][opposing_team])
        total_pts_opp_team = max(0, game_state["round_points"][opposing_team] - game_state["marriage_points"][bidding_team])
        
        # Check target win condition for opposing team based on the bid
        opp_target = BID_TARGETS[bid_level]
        
        # Kotu adjustments
        kotu_active = game_state["kotu_called"] is not None
        if kotu_active:
            kotu_caller = game_state["kotu_called"]
            kotu_team = "1" if kotu_caller in [0, 2] else "2"
            opp_kotu_team = "2" if kotu_team == "1" else "1"
            last_trick = game_state["tricks"][-1]
            kotu_success = last_trick["winner_player_index"] == kotu_caller
            
            if kotu_success:
                # Success!
                winner_msg = f"Kotu Success! Player {kotu_caller + 1} swept all tricks."
                if kotu_team == bidding_team:
                    golden_points_diff = 2
                    adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, 2)
                else:
                    golden_points_diff = -2
                    adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, -2)
            else:
                # Failure! Penalize calling team -1
                winner_msg = f"Kotu Failed! Player {kotu_caller + 1} lost the final trick."
                golden_points_diff = -1
                adjust_team_scores(game_state["team_scores"], kotu_team, opp_kotu_team, -1)
        else:
            # Standard points check
            if total_pts_opp_team >= opp_target:
                # Opposing team met or exceeded target -> Bidding team loses 1 Golden Point
                golden_points_diff = -1
                adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, -1)
                winner_msg = f"Opposing Team {opposing_team} reached target of {opp_target} points (Got {total_pts_opp_team} pts). Bidding Team {bidding_team} loses 1 Golden Point."
            else:
                # Bidding team successfully held them off -> Bidding team wins 1 Golden Point
                golden_points_diff = 1
                adjust_team_scores(game_state["team_scores"], bidding_team, opposing_team, 1)
                winner_msg = f"Bidding Team {bidding_team} held Opposing Team {opposing_team} below {opp_target} points (Opponents got {total_pts_opp_team} pts). Bidding Team wins 1 Golden Point."
                
    add_log(game_state, f"Round ended! {winner_msg}")
    add_log(game_state, f"Scores: Team 1 (P1/P3): {game_state['team_scores']['1']} | Team 2 (P2/P4): {game_state['team_scores']['2']}")
    
    # Store round summary
    game_state["round_history"].append({
        "round_number": game_state["round_number"],
        "bid": bid_level,
        "bid_winner": bidding_player,
        "trump": game_state["trump_suit"],
        "points": dict(game_state["round_points"]),
        "marriages": dict(game_state["marriage_points"]),
        "scores": dict(game_state["team_scores"])
    })
    
    # Check Ultimate Game End conditions:
    # Condition A: One team >= +5 AND opposite team >= -1
    # Condition B: One team <= -5 AND opposite team >= +1
    score1 = game_state["team_scores"]["1"]
    score2 = game_state["team_scores"]["2"]
    
    team_1_wins = (score1 >= 5 and score2 >= -1) or (score2 <= -5 and score1 >= 1)
    team_2_wins = (score2 >= 5 and score1 >= -1) or (score1 <= -5 and score2 >= 1)
    
    if team_1_wins:
        game_state["status"] = "GAME_OVER"
        game_state["winner_team"] = "1"
        add_log(game_state, "🏆 MATCH OVER! Team 1 (Player 1 & 3) is crowned the final WINNING team of the game!")
    elif team_2_wins:
        game_state["status"] = "GAME_OVER"
        game_state["winner_team"] = "2"
        add_log(game_state, "🏆 MATCH OVER! Team 2 (Player 2 & 4) is crowned the final WINNING team of the game!")

# --- AI Bot Strategy (Server-Side) ---

def run_bot_decision(game_state, bot_index):
    """Decides and executes actions for a bot player."""
    status = game_state["status"]
    
    if status == "BIDDING" and game_state["bidding_turn"] == bot_index:
        # Bot bidding logic
        hand = game_state["hands"][bot_index]
        # Evaluate hand strength: J=3, 9=2, A=1, 10=1, K/Q=0
        strength = sum(CARD_POINTS[c["value"]] for c in hand)
        
        current_highest_level = game_state["highest_bid"]["bid_level"] if game_state["highest_bid"] else None
        is_first_bidder = bot_index == (game_state["dealer_index"] + 1) % 4
        
        if is_first_bidder and current_highest_level is None:
            # Must bid at least Chance
            bid_level = "Chance"
        else:
            # Evaluate if bot wants to bid
            if strength >= 5:
                # Good hand, bid next level
                if current_highest_level is None:
                    bid_level = "Chance"
                else:
                    curr_idx = BID_LEVELS.index(current_highest_level)
                    next_idx = curr_idx + 1
                    # Chance Skip Rule: skip "200" (index 1) if current is "Chance" (index 0)
                    if current_highest_level == "Chance":
                        next_idx = BID_LEVELS.index("10")
                        
                    if next_idx < len(BID_LEVELS):
                        bid_level = BID_LEVELS[next_idx]
                    else:
                        bid_level = "Pass"
            else:
                bid_level = "Pass"
                
        handle_bid(game_state, bot_index, bid_level)
        return True
        
    elif status == "SELECTING_TRUMP" and game_state["bid_winner"] == bot_index:
        # Bot trump selection (from first 3 cards)
        hand = game_state["hands"][bot_index]
        # Choose the suit of the highest rank card
        best_card_idx = 0
        best_rank = -1
        for idx, card in enumerate(hand):
            rank = CARD_RANKS[card["value"]]
            if rank > best_rank:
                best_rank = rank
                best_card_idx = idx
                
        select_trump_suit(game_state, bot_index, best_card_idx)
        return True
        
    elif status == "CHANCE_TRUMP_SELECT" and game_state["bid_winner"] == bot_index:
        # Choose a random face-down card from second deal
        select_chance_trump(game_state, bot_index, random.randint(0, 2))
        return True
        
    elif status == "VAKKAI_OR_PLAY" and game_state["vakkai_turn"] == bot_index:
        # Bot Vakkai Call evaluation:
        # Bot checks full 6 card hand. If they hold at least 3 Jacks, or 2 Jacks and 2 9s, they call Vakkai!
        hand = game_state["hands"][bot_index]
        jacks_count = sum(1 for c in hand if c["value"] == "J")
        nines_count = sum(1 for c in hand if c["value"] == "9")
        
        # High likelihood of Vakkai if they have super strong cards
        call_vakkai = (jacks_count >= 3) or (jacks_count >= 2 and nines_count >= 2)
        # Add a tiny random chance for fun
        if not call_vakkai and random.random() < 0.05:
            call_vakkai = True
            
        handle_vakkai_call(game_state, bot_index, call_vakkai)
        return True
        
    elif status == "KOTU_DECISION" and game_state["turn"] == bot_index:
        # Bot Kotu decision:
        # Since the bot won all 5 tricks, check if they have a very high card (like J or 9) left in hand
        hand = game_state["hands"][bot_index]
        has_j_or_9 = any(c["value"] in ["J", "9"] for c in hand)
        
        # Call Kotu if we have a strong card or random 40% chance
        call_kotu = has_j_or_9 or random.random() < 0.4
        handle_kotu_call(game_state, bot_index, call_kotu)
        return True
        
    elif status == "PLAYING" and game_state["turn"] == bot_index:
        # Bot playing a card!
        hand = game_state["hands"][bot_index]
        trick = game_state["current_trick"]
        plays = trick["plays"]
        
        # Find valid cards
        if len(plays) == 0:
            # Leading, can play any card
            valid_cards = list(hand)
        else:
            lead_card = plays[trick["lead_player_index"]]
            led_suit = lead_card["suit"]
            
            # Follow suit if possible
            matching_cards = [c for c in hand if c["suit"] == led_suit]
            if len(matching_cards) > 0:
                valid_cards = matching_cards
            else:
                # Can play any card
                valid_cards = list(hand)
                
        # Play strategy:
        # If leading, usually play a high card (especially if we hold a J or 9)
        # If following, either try to win (play high) or dump low cards (play Q/K)
        # For simplicity and robust game flow, pick a card that makes logical sense:
        # Sort valid cards by priority.
        # Let's sort by ranks.
        valid_cards.sort(key=lambda c: CARD_RANKS[c["value"]], reverse=True)
        
        # Determine if we want to play highest or lowest
        # If leading: play highest card.
        # If partner has already played a card, and partner is winning: play lowest card (discard/save high cards)
        # If opponent is winning and we can beat them: play winning card
        # Else: play lowest card.
        chosen_card = valid_cards[0]  # default to highest
        
        if len(plays) > 0:
            lead_player = trick["lead_player_index"]
            led_suit_c = plays[lead_player]["suit"]
            trump_s = game_state["trump_suit"]
            
            # Find current winning card
            curr_winner = lead_player
            curr_winning_card = plays[lead_player]
            for p_idx, card in plays.items():
                if beats(card, curr_winning_card, led_suit_c, trump_s):
                    curr_winner = p_idx
                    curr_winning_card = card
                    
            partner = (bot_index + 2) % 4
            is_partner_winning = curr_winner == partner
            
            if is_partner_winning:
                # Partner is winning, throw a low card (save our high cards)
                chosen_card = valid_cards[-1]
            else:
                # Opponent is winning, try to beat them
                playable_winners = [c for c in valid_cards if beats(c, curr_winning_card, led_suit_c, trump_s)]
                if len(playable_winners) > 0:
                    # Play the lowest card that still beats the opponent
                    playable_winners.sort(key=lambda c: CARD_RANKS[c["value"]])
                    chosen_card = playable_winners[0]
                else:
                    # Can't win, throw lowest card
                    chosen_card = valid_cards[-1]
                    
        # Apply special Partner Sabotage logic check for Vakkai:
        # If Vakkai is active, and our partner is the Vakkai caller, we must NOT play a card higher than their card!
        is_vakkai = game_state["vakkai_caller"] is not None
        if is_vakkai:
            v_caller = game_state["vakkai_caller"]
            partner_of_v = (v_caller + 2) % 4
            if bot_index == partner_of_v:
                # We are the partner. We must play a card LOWER than what the caller played!
                caller_card = plays.get(v_caller)
                if caller_card:
                    # Filter out cards that would beat the caller's card to avoid sabotage
                    non_sabotage_cards = [c for c in valid_cards if not beats(c, caller_card, trick["plays"][trick["lead_player_index"]]["suit"], game_state["trump_suit"])]
                    if len(non_sabotage_cards) > 0:
                        chosen_card = non_sabotage_cards[-1]  # Play the lowest non-sabotage card
                        
        handle_play_card(game_state, bot_index, chosen_card)
        return True
        
    # Check if a bot has a marriage to show
    # Needs to happen during PLAYING/KOTU_DECISION and when team won at least one trick.
    team = "1" if bot_index in [0, 2] else "2"
    if game_state["tricks_won_by_team"][team] > 0 and game_state["vakkai_caller"] is None:
        mar_avail = game_state["marriages"][bot_index]["available"]
        if len(mar_avail) > 0:
            # Automatically show the first available marriage!
            handle_show_marriage(game_state, bot_index, mar_avail[0])
            return True
            
    return False

# --- Room Serialization & Sanitization ---

def sanitize_game_state(game_state, player_idx):
    """Filters out secret information (e.g. other hands, hidden Trump) for player_idx."""
    sanitized = {}
    for key, value in game_state.items():
        if key == "hands":
            # Show only player's hand, hide others
            san_hands = {}
            for p_key, hand in value.items():
                p_idx = int(p_key)
                if p_idx == player_idx:
                    san_hands[p_idx] = hand
                else:
                    san_hands[p_idx] = [{"hidden": True} for _ in range(len(hand))]
            sanitized["hands"] = san_hands
        elif key == "trump_suit":
            # Hide trump suit if not revealed and this player is not the bidder/winner
            is_winner = game_state["bid_winner"] == player_idx
            is_revealed = game_state["trump_revealed"]
            if is_revealed or is_winner:
                sanitized["trump_suit"] = value
            else:
                sanitized["trump_suit"] = "HIDDEN"
        elif key == "chance_face_down_cards":
            # Only show to bidder
            if game_state["bid_winner"] == player_idx:
                sanitized["chance_face_down_cards"] = value
            else:
                sanitized["chance_face_down_cards"] = [{"hidden": True} for _ in range(3)]
        else:
            sanitized[key] = value
            
    return sanitized

# --- WebSocket Server Connection Management ---

async def broadcast_state(room):
    game_state = room["game_state"]
    connections = room["connections"]
    players = room["players"]
    
    # Send state to each active player connection
    for seat_idx, player in enumerate(players):
        if player and not player["is_bot"] and player["id"] in connections:
            ws = connections[player["id"]]
            san_state = sanitize_game_state(game_state, seat_idx)
            try:
                await ws.send(json.dumps({
                    "type": "state_update",
                    "game_state": san_state,
                    "my_seat": seat_idx,
                    "players": [
                        {"name": p["name"], "is_bot": p["is_bot"], "seat": idx, "connected": p["id"] in connections} if p else None
                        for idx, p in enumerate(players)
                    ]
                }))
            except Exception as e:
                print(f"Error sending state to seat {seat_idx}: {e}")

async def game_loop_trigger(room):
    """Triggers AI bots or transitions that run automatically on the server."""
    game_state = room["game_state"]
    players = room["players"]
    
    # If game not started yet, wait until 4 players exist
    active_count = sum(1 for p in players if p is not None)
    if game_state["status"] == "LOBBY":
        if active_count == 4:
            start_new_round(game_state)
            await broadcast_state(room)
            await game_loop_trigger(room)
        return
        
    # Check if active turn player is a bot
    status = game_state["status"]
    
    if status == "BIDDING":
        turn_player = game_state["bidding_turn"]
        if players[turn_player] and players[turn_player]["is_bot"]:
            await asyncio.sleep(1.2)  # Add realistic delay
            run_bot_decision(game_state, turn_player)
            await broadcast_state(room)
            await game_loop_trigger(room)  # Recurse to see if next is also a bot
            
    elif status == "SELECTING_TRUMP" or status == "CHANCE_TRUMP_SELECT":
        bidder = game_state["bid_winner"]
        if players[bidder] and players[bidder]["is_bot"]:
            await asyncio.sleep(1.2)
            run_bot_decision(game_state, bidder)
            await broadcast_state(room)
            await game_loop_trigger(room)
            
    elif status == "VAKKAI_OR_PLAY":
        vakkai_turn = game_state["vakkai_turn"]
        if vakkai_turn is not None and players[vakkai_turn] and players[vakkai_turn]["is_bot"]:
            await asyncio.sleep(1.2)
            run_bot_decision(game_state, vakkai_turn)
            await broadcast_state(room)
            await game_loop_trigger(room)
            
    elif status == "READY_CHECK":
        did_bot_ready = False
        for idx, p in enumerate(players):
            if p and p["is_bot"] and idx not in game_state["ready_players"]:
                game_state["ready_players"].append(idx)
                did_bot_ready = True
                add_log(game_state, f"Player {p['name']} is ready.")
                
        if did_bot_ready:
            if len(game_state["ready_players"]) == 4:
                start_playing_phase(game_state)
            await broadcast_state(room)
            await game_loop_trigger(room)
            
    elif status == "PLAYING" or status == "KOTU_DECISION":
        turn_player = game_state["turn"]
        if players[turn_player] and players[turn_player]["is_bot"]:
            await asyncio.sleep(1.5)  # Let cards linger a bit so human can follow
            run_bot_decision(game_state, turn_player)
            await broadcast_state(room)
            await game_loop_trigger(room)
            
        # Also let bots show marriages if they hold them
        did_show = False
        for idx, p in enumerate(players):
            if p and p["is_bot"]:
                team = "1" if idx in [0, 2] else "2"
                if game_state["tricks_won_by_team"][team] > 0 and len(game_state["marriages"][idx]["available"]) > 0:
                    run_bot_decision(game_state, idx)
                    did_show = True
        if did_show:
            await broadcast_state(room)

async def handle_websocket(websocket):
    player_id = str(uuid.uuid4())
    current_room_id = None
    my_seat_index = None
    
    print(f"New client connected: {player_id}")
    
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "create_room":
                room_id = data.get("room_id", str(random.randint(1000, 9999)))
                if room_id in ROOMS:
                    await websocket.send(json.dumps({"type": "error", "message": "Room already exists"}))
                    continue
                    
                ROOMS[room_id] = {
                    "room_id": room_id,
                    "players": [None, None, None, None],
                    "game_state": init_game_state(),
                    "connections": {}
                }
                current_room_id = room_id
                add_log(ROOMS[room_id]["game_state"], f"Room {room_id} created.")
                
                # Assign to Seat 0
                player_name = data.get("username", "Host")
                my_seat_index = 0
                player_obj = {"id": player_id, "name": player_name, "is_bot": False}
                ROOMS[room_id]["players"][0] = player_obj
                ROOMS[room_id]["connections"][player_id] = websocket
                
                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "room_id": room_id,
                    "my_seat": 0
                }))
                await broadcast_state(ROOMS[room_id])
                
            elif msg_type == "join_room":
                room_id = data.get("room_id")
                if room_id not in ROOMS:
                    await websocket.send(json.dumps({"type": "error", "message": "Room not found"}))
                    continue
                    
                room = ROOMS[room_id]
                players = room["players"]
                
                # Check if player is already in this room (reconnection)
                existing_seat = None
                for idx, p in enumerate(players):
                    if p and p["id"] == player_id:
                        existing_seat = idx
                        break
                        
                if existing_seat is not None:
                    # Reconnect
                    my_seat_index = existing_seat
                    room["connections"][player_id] = websocket
                    current_room_id = room_id
                    await websocket.send(json.dumps({
                        "type": "room_joined",
                        "room_id": room_id,
                        "my_seat": my_seat_index
                    }))
                    await broadcast_state(room)
                    continue
                
                # Find an empty seat or a bot to replace
                assigned_seat = None
                for idx, p in enumerate(players):
                    if p is None:
                        assigned_seat = idx
                        break
                        
                if assigned_seat is None:
                    # Try to replace a bot player if a human joins
                    for idx, p in enumerate(players):
                        if p and p["is_bot"]:
                            assigned_seat = idx
                            break
                            
                if assigned_seat is None:
                    await websocket.send(json.dumps({"type": "error", "message": "Room is full"}))
                    continue
                    
                player_name = data.get("username", f"Player {assigned_seat + 1}")
                my_seat_index = assigned_seat
                player_obj = {"id": player_id, "name": player_name, "is_bot": False}
                
                room["players"][assigned_seat] = player_obj
                room["connections"][player_id] = websocket
                current_room_id = room_id
                
                add_log(room["game_state"], f"Player {player_name} joined at seat {assigned_seat + 1}.")
                
                await websocket.send(json.dumps({
                    "type": "room_joined",
                    "room_id": room_id,
                    "my_seat": assigned_seat
                }))
                await broadcast_state(room)
                await game_loop_trigger(room)
                
            elif msg_type == "add_bot":
                if not current_room_id:
                    continue
                room = ROOMS[current_room_id]
                players = room["players"]
                
                # Find empty seat
                empty_seat = None
                for idx, p in enumerate(players):
                    if p is None:
                        empty_seat = idx
                        break
                        
                if empty_seat is None:
                    await websocket.send(json.dumps({"type": "error", "message": "Room is already full"}))
                    continue
                    
                bot_names = ["ApexBot", "AlphaBot", "DeltaBot", "OmegaBot", "ZetaBot"]
                bot_name = random.choice(bot_names)
                bot_obj = {"id": f"bot_{uuid.uuid4().hex[:6]}", "name": f"🤖 {bot_name}", "is_bot": True}
                players[empty_seat] = bot_obj
                
                add_log(room["game_state"], f"Bot {bot_name} added to seat {empty_seat + 1}.")
                await broadcast_state(room)
                await game_loop_trigger(room)
                
            elif msg_type == "place_bid":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                bid_level = data.get("bid_level")
                
                success = handle_bid(room["game_state"], my_seat_index, bid_level)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "select_trump":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                card_index = data.get("card_index")
                
                success = select_trump_suit(room["game_state"], my_seat_index, card_index)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "select_chance_trump":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                card_index = data.get("card_index")
                
                success = select_chance_trump(room["game_state"], my_seat_index, card_index)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "call_vakkai":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                call_vakkai = data.get("call_vakkai", False)
                
                success = handle_vakkai_call(room["game_state"], my_seat_index, call_vakkai)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "player_ready":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                game_state = room["game_state"]
                if game_state["status"] == "READY_CHECK" and my_seat_index not in game_state["ready_players"]:
                    game_state["ready_players"].append(my_seat_index)
                    add_log(game_state, f"Player {room['players'][my_seat_index]['name']} is ready.")
                    
                    if len(game_state["ready_players"]) == 4:
                        start_playing_phase(game_state)
                        
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "play_card":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                card = data.get("card")
                
                success = handle_play_card(room["game_state"], my_seat_index, card)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "show_marriage":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                suit = data.get("suit")
                
                success = handle_show_marriage(room["game_state"], my_seat_index, suit)
                if success:
                    await broadcast_state(room)
                    
            elif msg_type == "call_kotu":
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                call_kotu = data.get("call_kotu", False)
                
                success = handle_kotu_call(room["game_state"], my_seat_index, call_kotu)
                if success:
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "next_round":
                if not current_room_id:
                    continue
                room = ROOMS[current_room_id]
                if room["game_state"]["status"] == "ROUND_END":
                    start_new_round(room["game_state"])
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "restart_game":
                if not current_room_id:
                    continue
                room = ROOMS[current_room_id]
                if room["game_state"]["status"] == "GAME_OVER":
                    room["game_state"] = init_game_state()
                    start_new_round(room["game_state"])
                    await broadcast_state(room)
                    await game_loop_trigger(room)
                    
            elif msg_type == "webrtc_signal":
                # Relay AV WebRTC signaling to other players in the room
                if not current_room_id or my_seat_index is None:
                    continue
                room = ROOMS[current_room_id]
                target_seat = data.get("target_seat")
                signal_data = data.get("signal_data")
                
                # Find the websocket of the target player
                target_player = room["players"][target_seat]
                if target_player and not target_player["is_bot"] and target_player["id"] in room["connections"]:
                    target_ws = room["connections"][target_player["id"]]
                    try:
                        await target_ws.send(json.dumps({
                            "type": "webrtc_signal",
                            "sender_seat": my_seat_index,
                            "signal_data": signal_data
                        }))
                    except Exception as e:
                        print(f"Error forwarding WebRTC signal to seat {target_seat}: {e}")
                        
    except websockets.exceptions.ConnectionClosed:
        print(f"Client disconnected: {player_id}")
    finally:
        # Cleanup player connections
        if current_room_id and current_room_id in ROOMS:
            room = ROOMS[current_room_id]
            if player_id in room["connections"]:
                del room["connections"][player_id]
                
            # If room becomes entirely empty of human players, clean it up after a while
            active_humans = sum(1 for p in room["players"] if p and not p["is_bot"] and p["id"] in room["connections"])
            if active_humans == 0:
                print(f"Room {current_room_id} has no human players. Destroying room.")
                del ROOMS[current_room_id]
            else:
                # If a player disconnected during an active game, convert them to a bot
                # so the remaining players can continue!
                if room["game_state"]["status"] != "LOBBY" and my_seat_index is not None:
                    p = room["players"][my_seat_index]
                    if p and not p["is_bot"]:
                        add_log(room["game_state"], f"Player {p['name']} disconnected. AI bot taking over.")
                        room["players"][my_seat_index] = {
                            "id": f"bot_replaces_{p['id']}",
                            "name": f"🤖 {p['name']}",
                            "is_bot": True
                        }
                        await broadcast_state(room)
                        await game_loop_trigger(room)

# --- Single-Port Server Start ---

async def start_server():
    port = int(os.environ.get("PORT", 8000))
    async with websockets.serve(handle_websocket, "0.0.0.0", port, process_request=process_request):
        print(f"Server running on port {port} (serving both HTTP and WebSockets)")
        await asyncio.Future()  # run forever

def main():
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("Server shutting down.")

if __name__ == "__main__":
    main()
