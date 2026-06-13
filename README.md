# Sri Lankan 304 Card Game

A real-time multiplayer implementation of the traditional Sri Lankan card game "304", featuring interactive audio/video WebRTC feeds, AI bot fallbacks, and a fluid responsive table UI.

---

## 🎮 Game Overview

* **Players**: 4 players divided into 2 teams. 
  * Partners sit opposite each other (e.g., Player 1 & Player 3 form Team 1; Player 2 & Player 4 form Team 2).
* **Deck**: 24 cards (6 cards from each of the 4 suits: J, 9, A, 10, K, Q).
* **Goal**: Win tricks containing high-point cards to either complete your team's bid target or hold the opposing team below their target. The first team to reach **+5 Golden Points** wins the match!

---

## 🎴 Card Rankings & Point Values

Unlike standard card games, the point values and rankings in 304 are highly specialized:

| Card | Point Value | Rank Priority (Highest to Lowest) |
| :--- | :---: | :---: |
| **Jack (J)** | **3 points** | 1st (Highest rank in the suit) |
| **Nine (9)** | **2 points** | 2nd |
| **Ace (A)** | **1 point** | 3rd |
| **Ten (10)** | **1 point** | 4th |
| **King (K)** | **0 points** | 5th |
| **Queen (Q)** | **0 points** | 6th (Lowest rank in the suit) |

*Total points in the deck:* **32 points** (8 points per suit).

---

## 📣 Bidding Phase ("Aata")

1. Each player is dealt **3 cards** initially.
2. The bidding starts with the player to the dealer's right and goes counter-clockwise.
3. Each player can place a bid from the scale below or **Pass**. A placed bid must be strictly higher than the current highest bid:

| Bid Level | Opponent's Max Allowed Points (Target) | Bidder's Minimum Required Points |
| :--- | :---: | :---: |
| **Chance** | **< 11 points** | **≥ 22 points** |
| **200** | **< 10 points** | **≥ 23 points** |
| **10** | **< 9 points** | **≥ 24 points** |
| **20** | **< 8 points** | **≥ 25 points** |
| **30** | **< 7 points** | **≥ 26 points** |
| **40** | **< 6 points** | **≥ 27 points** |

* Note: If a player bids **Chance**, the next bidder cannot bid **200** (they must skip to 10 or higher).
* The player with the highest bid wins the contract and selects the **Trump Suit ("Turpu")** secretly from their first 3 cards.
* If a **Chance** bid is won, the bidder does not choose a trump suit yet. Instead, the remaining 3 cards are dealt, and they choose one of their second-deal cards face-down to set the trump.

---

## 💍 Special Mechanics

### 1. Marriages (King & Queen Combo)
If a player holds both the **King (K)** and **Queen (Q)** of the same suit in their hand:
* **Showing**: After their team wins its **first trick (Pattu)**, they can "Show" the marriage to the player on their left before playing a card.
* **Bonus Points**: 
  * If it's the **Trump suit**, it adds **+4 points** to their round total.
  * If it's any **other suit**, it adds **+2 points** to their round total.
  * *Note: Marriage points shown by a team are directly subtracted from the opposing team's points at the end of the round (capped at 0).*
* **Broken Marriages**: If a player plays either the King or Queen of a marriage suit *before* their team wins a trick, the marriage is **broken** and cannot be shown.

### 2. Vakkai (Solo Contract)
After all 6 cards are dealt, any player can shout **Vakkai** on their turn:
* Calling Vakkai cancels all previous bids.
* The Vakkai caller must **win all 6 tricks completely alone**.
* **Partner Sabotage**: The caller's partner is not allowed to win a trick. If the partner plays a card that beats the caller's card, the Vakkai contract **fails instantly**.
* **Reward/Penalty**: Winning Vakkai awards **+3 Golden Points** to the team. Failing loses **-3 Golden Points**.

### 3. Kotu (Double or Nothing)
If one team successfully wins all of the first **5 tricks**, the player who won Trick 5 and has the lead for Trick 6 can call **Kotu**:
* The caller claims they will win the final trick.
* **Success**: The calling team wins **+2 Golden Points** (if they are the bidding team) or inflicts **-2 Golden Points** on the opponents.
* **Failure**: The calling team is penalized **-1 Golden Point**.
* If Kotu is declined, the final trick is played normally.

---

## 🏆 Scoring & Match Win Conditions

At the end of each round:
* If the opposing team reaches or exceeds their target limit (defined by the bid), the bidding team **loses 1 Golden Point**.
* If the opposing team is held below their target limit, the bidding team **wins 1 Golden Point**.

### Match Resolution:
* The first team to reach **≥ +5 Golden Points** wins the match, provided the opponents are at **≥ -1**.
* Alternatively, if a team sinks to **≤ -5 Golden Points**, the opponents win the match, provided they are at **≥ +1`.
