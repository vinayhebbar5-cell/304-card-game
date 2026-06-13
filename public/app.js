// 304 Card Game - Client Application

const SUIT_SYMBOLS = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"};
const SUIT_CLASSES = {"H": "red", "D": "red", "C": "black", "S": "black"};
const BID_LEVELS = ["Chance", "200", "10", "20", "30", "40"];
const SEAT_POSITIONS = ["bottom", "right", "top", "left"]; // Relative positions (Bottom is Self)

// App State
let ws = null;
let mySeat = null;
let myPlayerId = null;
let roomId = null;
let username = "";
let gameState = null;
let playersList = [];

// Media & WebRTC State
let localStream = null;
let micEnabled = false;
let camEnabled = false;
let peerConnections = {}; // { seat_index: RTCPeerConnection }
let iceCandidateQueue = {}; // { seat_index: [RTCIceCandidate] }
let canvasAnimIntervals = {};

// DOM Elements
const lobbyScreen = document.getElementById("lobby-screen");
const gameScreen = document.getElementById("game-screen");
const usernameInput = document.getElementById("username-input");
const roomIdInput = document.getElementById("room-id-input");
const createRoomBtn = document.getElementById("create-room-btn");
const joinRoomBtn = document.getElementById("join-room-btn");

const displayRoomId = document.getElementById("display-room-id");
const copyRoomIdBtn = document.getElementById("copy-room-id-btn");
const toggleMicBtn = document.getElementById("toggle-mic-btn");
const toggleCamBtn = document.getElementById("toggle-cam-btn");
const addBotBtn = document.getElementById("add-bot-btn");
const leaveRoomBtn = document.getElementById("leave-room-btn");

// Scoreboard Elements
const goldenScoreTeam1 = document.getElementById("golden-score-team1");
const goldenScoreTeam2 = document.getElementById("golden-score-team2");
const roundPointsTeam1 = document.getElementById("round-points-team1");
const roundPointsTeam2 = document.getElementById("round-points-team2");
const marriagePointsTeam1 = document.getElementById("marriage-points-team1");
const marriagePointsTeam2 = document.getElementById("marriage-points-team2");
const currentBidBadge = document.getElementById("current-bid-badge");
const trumpSuitIndicator = document.getElementById("trump-suit-indicator");
const trumpSuitText = document.getElementById("trump-suit-text");
const trumpSelectionHint = document.getElementById("trump-selection-hint");
const centerTurnIndicator = document.getElementById("center-turn-indicator");
const centerRoundText = document.getElementById("center-round-text");
const logsContainer = document.getElementById("logs-container");

// Modals
const biddingModal = document.getElementById("bidding-modal");
const trumpSelectModal = document.getElementById("trump-select-modal");
const chanceSelectModal = document.getElementById("chance-select-modal");
const vakkaiModal = document.getElementById("vakkai-modal");
const kotuModal = document.getElementById("kotu-modal");
const roundEndModal = document.getElementById("round-end-modal");
const gameOverModal = document.getElementById("game-over-modal");
const readyModal = document.getElementById("ready-modal");
const readyPlayersList = document.getElementById("ready-players-list");
const readyBtn = document.getElementById("ready-btn");
const openRulesBtn = document.getElementById("open-rules-btn");
const rulesModal = document.getElementById("rules-modal");
const closeRulesBtn = document.getElementById("close-rules-btn");
const closeRulesXBtn = document.getElementById("rules-close-x");

// Action Containers
const showMarriageBtn = document.getElementById("show-marriage-btn");
const playerHandContainer = document.getElementById("player-hand");
const playerHandFooter = document.querySelector(".player-hand-container");
const bidButtonsGrid = document.getElementById("bid-buttons-grid");
const passBidBtn = document.getElementById("pass-bid-btn");
const trumpCardsRow = document.getElementById("trump-cards-row");
const callVakkaiBtn = document.getElementById("call-vakkai-btn");
const declineVakkaiBtn = document.getElementById("decline-vakkai-btn");
const callKotuBtn = document.getElementById("call-kotu-btn");
const declineKotuBtn = document.getElementById("decline-kotu-btn");
const nextRoundBtn = document.getElementById("next-round-btn");
const restartGameBtn = document.getElementById("restart-game-btn");

// --- UTILITY FUNCTIONS ---

function getRelativeSeatPosition(seatIdx) {
    if (mySeat === null) return SEAT_POSITIONS[seatIdx]; // Fallback
    // Bottom (0), Right (1), Top (2), Left (3)
    const offset = (seatIdx - mySeat + 4) % 4;
    return SEAT_POSITIONS[offset];
}

function sendMsg(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(jsonStr(obj));
    }
}

function jsonStr(obj) {
    return JSON.stringify(obj);
}

function addLogEntry(text) {
    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML = text;
    logsContainer.appendChild(entry);
    logsContainer.scrollTop = logsContainer.scrollHeight;
}

// --- INITIALIZE WEBRTC MEDIA & MOCK STREAM FALLBACK ---

async function initMediaStream() {
    try {
        // Try getting actual camera & mic
        localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        // Disable tracks by default (mike and camera start off)
        localStream.getAudioTracks().forEach(t => t.enabled = micEnabled);
        localStream.getVideoTracks().forEach(t => t.enabled = camEnabled);
        document.getElementById("video-bottom").srcObject = localStream;
        document.getElementById("canvas-bottom").classList.add("hidden");
    } catch (e) {
        console.warn("Could not access camera/mic. Using mock fallback streams.", e);
        // Fallback: Generate custom canvas stream & Web Audio stream
        localStream = createMockMediaStream("Me");
        // Disable tracks by default (mike and camera start off)
        localStream.getAudioTracks().forEach(t => t.enabled = micEnabled);
        localStream.getVideoTracks().forEach(t => t.enabled = camEnabled);
        document.getElementById("video-bottom").srcObject = localStream;
        document.getElementById("canvas-bottom").classList.add("hidden");
    }
}

function createMockMediaStream(name) {
    // 1. Create silent Web Audio Node
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const destination = audioCtx.createMediaStreamDestination();
    const oscillator = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();
    gainNode.gain.value = 0.0; // Completely silent
    oscillator.connect(gainNode);
    gainNode.connect(destination);
    oscillator.start();
    
    // 2. Create Canvas Video track
    const canvas = document.createElement("canvas");
    canvas.width = 200;
    canvas.height = 150;
    const ctx = canvas.getContext("2d");
    
    let frame = 0;
    const draw = () => {
        frame++;
        ctx.fillStyle = "#111827";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw bouncing circles representing audio waveforms
        ctx.strokeStyle = "rgba(102, 252, 241, 0.4)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        const center = canvas.height / 2;
        for (let i = 0; i < canvas.width; i += 5) {
            const val = Math.sin(frame * 0.1 + i * 0.05) * 15;
            ctx.lineTo(i, center + val);
        }
        ctx.stroke();
        
        // Draw Initials
        ctx.fillStyle = "#66fcf1";
        ctx.font = "bold 24px Outfit, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(name.slice(0, 3).toUpperCase(), canvas.width / 2, canvas.height / 2 - 10);
        
        ctx.fillStyle = "#9ca3af";
        ctx.font = "10px Inter, sans-serif";
        ctx.fillText("VIDEO STREAMING", canvas.width / 2, canvas.height / 2 + 20);
        
        requestAnimationFrame(draw);
    };
    draw();
    
    const videoStream = canvas.captureStream(15); // 15 FPS
    
    return new MediaStream([
        videoStream.getVideoTracks()[0],
        destination.stream.getAudioTracks()[0]
    ]);
}

// Canvas Animator for Bot players and loading screens
function animateSeatCanvas(position, name, state) {
    const canvas = document.getElementById("canvas-" + position);
    const video = document.getElementById("video-" + position);
    
    if (!canvas) return;
    
    canvas.classList.remove("hidden");
    video.classList.add("hidden");
    
    if (canvasAnimIntervals[position]) {
        clearInterval(canvasAnimIntervals[position]);
    }
    
    const ctx = canvas.getContext("2d");
    let frame = 0;
    
    canvasAnimIntervals[position] = setInterval(() => {
        frame++;
        ctx.fillStyle = "#1e293b";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw icon/avatar based on state
        if (state === "bot") {
            ctx.fillStyle = "#6366f1"; // Indigo for Bot
            ctx.font = "bold 20px Outfit, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText("🤖", canvas.width / 2, canvas.height / 2 - 10);
            
            ctx.fillStyle = "#f3f4f6";
            ctx.font = "bold 13px Inter, sans-serif";
            ctx.fillText(name, canvas.width / 2, canvas.height / 2 + 15);
            
            ctx.fillStyle = "#818cf8";
            ctx.font = "9px monospace";
            ctx.fillText("AI AUTOMATED", canvas.width / 2, canvas.height / 2 + 32);
            
            // Pulsing bars
            ctx.fillStyle = "rgba(99, 102, 241, 0.4)";
            const val = Math.abs(Math.sin(frame * 0.1)) * 20;
            ctx.fillRect(canvas.width / 2 - 30, canvas.height - 25, 60, 4);
        } else if (state === "disconnected") {
            ctx.fillStyle = "#94a3b8";
            ctx.font = "14px Inter, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText("Disconnected", canvas.width / 2, canvas.height / 2 - 5);
            
            ctx.fillStyle = "#64748b";
            ctx.font = "bold 12px Inter, sans-serif";
            ctx.fillText(name, canvas.width / 2, canvas.height / 2 + 15);
        } else {
            // Loading/connecting
            ctx.fillStyle = "#45a29e";
            ctx.font = "14px Inter, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText("Connecting...", canvas.width / 2, canvas.height / 2 - 10);
            
            ctx.strokeStyle = "#45a29e";
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(canvas.width / 2, canvas.height / 2 + 20, 8, frame * 0.1, frame * 0.1 + Math.PI);
            ctx.stroke();
        }
    }, 100);
}

function stopSeatCanvasAnimation(position) {
    if (canvasAnimIntervals[position]) {
        clearInterval(canvasAnimIntervals[position]);
        delete canvasAnimIntervals[position];
    }
    const canvas = document.getElementById("canvas-" + position);
    const video = document.getElementById("video-" + position);
    if (canvas) canvas.classList.add("hidden");
    if (video) video.classList.remove("hidden");
}

// --- WebRTC Peer-to-Peer AV Mechanics ---

function initPeerConnection(peerSeat) {
    if (peerConnections[peerSeat]) return peerConnections[peerSeat];
    
    console.log(`Creating RTCPeerConnection for seat ${peerSeat}`);
    
    // We use a public STUN server for ICE candidates discovery
    const configuration = {
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
    };
    
    const pc = new RTCPeerConnection(configuration);
    peerConnections[peerSeat] = pc;
    
    // Send local tracks
    if (localStream) {
        localStream.getTracks().forEach(track => pc.addTrack(track, localStream));
    }
    
    pc.onicecandidate = event => {
        if (event.candidate) {
            sendMsg({
                type: "webrtc_signal",
                target_seat: peerSeat,
                signal_data: {
                    type: "candidate",
                    candidate: event.candidate
                }
            });
        }
    };
    
    pc.ontrack = event => {
        console.log(`Received track from seat ${peerSeat}`);
        const pos = getRelativeSeatPosition(peerSeat);
        stopSeatCanvasAnimation(pos);
        const remoteVideo = document.getElementById("video-" + pos);
        if (remoteVideo) {
            remoteVideo.srcObject = event.streams[0];
        }
    };
    
    return pc;
}

async function handleSignalingMsg(senderSeat, signal) {
    const pc = initPeerConnection(senderSeat);
    
    if (signal.type === "offer") {
        await pc.setRemoteDescription(new RTCSessionDescription(signal.sdp));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        
        sendMsg({
            type: "webrtc_signal",
            target_seat: senderSeat,
            signal_data: {
                type: "answer",
                sdp: answer
            }
        });
        
        // Process queued ICE candidates
        if (iceCandidateQueue[senderSeat]) {
            for (const cand of iceCandidateQueue[senderSeat]) {
                await pc.addIceCandidate(new RTCIceCandidate(cand));
            }
            delete iceCandidateQueue[senderSeat];
        }
    } else if (signal.type === "answer") {
        await pc.setRemoteDescription(new RTCSessionDescription(signal.sdp));
        // Process queued ICE candidates
        if (iceCandidateQueue[senderSeat]) {
            for (const cand of iceCandidateQueue[senderSeat]) {
                await pc.addIceCandidate(new RTCIceCandidate(cand));
            }
            delete iceCandidateQueue[senderSeat];
        }
    } else if (signal.type === "candidate") {
        if (pc.remoteDescription) {
            await pc.addIceCandidate(new RTCIceCandidate(signal.candidate));
        } else {
            if (!iceCandidateQueue[senderSeat]) iceCandidateQueue[senderSeat] = [];
            iceCandidateQueue[senderSeat].push(signal.candidate);
        }
    }
}

// Connect peers dynamically depending on seat priority
function negotiateConnections() {
    // Politeness logic: lower seat index initiates connections to higher seat index humans.
    playersList.forEach(p => {
        if (p && !p.is_bot && p.seat !== mySeat) {
            const pc = initPeerConnection(p.seat);
            
            // If we are the lower seat, we create and send the offer
            if (mySeat < p.seat) {
                console.log(`Initiating WebRTC offer: Seat ${mySeat} -> Seat ${p.seat}`);
                pc.onnegotiationneeded = async () => {
                    try {
                        const offer = await pc.createOffer();
                        await pc.setLocalDescription(offer);
                        sendMsg({
                            type: "webrtc_signal",
                            target_seat: p.seat,
                            signal_data: {
                                type: "offer",
                                sdp: offer
                            }
                        });
                    } catch (err) {
                        console.error("WebRTC negotiation error: ", err);
                    }
                };
            }
        }
    });
}

function cleanupPeerConnection(seatIdx) {
    if (peerConnections[seatIdx]) {
        peerConnections[seatIdx].close();
        delete peerConnections[seatIdx];
    }
    if (iceCandidateQueue[seatIdx]) {
        delete iceCandidateQueue[seatIdx];
    }
}

// --- STATE SYNC & RENDERING ENGINE ---

function updateRoomState(data) {
    gameState = data.game_state;
    mySeat = data.my_seat;
    playersList = data.players;
    
    // Set headers
    displayRoomId.textContent = roomId;
    
    // Draw players and assign canvas animations
    playersList.forEach((p, idx) => {
        const pos = getRelativeSeatPosition(idx);
        const nameText = document.getElementById("name-" + pos);
        const cardsCount = document.getElementById("cards-count-" + pos);
        const dealerBadge = document.getElementById("dealer-" + pos);
        
        if (nameText) {
            if (p) {
                nameText.textContent = p.name;
                if (p.is_bot) {
                    animateSeatCanvas(pos, p.name, "bot");
                } else if (!p.connected && idx !== mySeat) {
                    animateSeatCanvas(pos, p.name, "disconnected");
                } else if (idx !== mySeat) {
                    // It's a connected human. If we don't have their stream yet, show loading
                    const video = document.getElementById("video-" + pos);
                    if (!video.srcObject) {
                        animateSeatCanvas(pos, p.name, "connecting");
                    }
                }
            } else {
                nameText.textContent = "Empty Slot";
                animateSeatCanvas(pos, "Open", "disconnected");
            }
        }
        
        // Show cards count for others
        if (cardsCount && idx !== mySeat) {
            if (p && gameState.hands[idx]) {
                const count = gameState.hands[idx].length;
                cardsCount.textContent = count > 0 ? `(${count} cards)` : "";
            } else {
                cardsCount.textContent = "";
            }
        }
        
        // Show dealer badge
        if (dealerBadge) {
            if (gameState.dealer_index === idx) {
                dealerBadge.classList.add("active");
            } else {
                dealerBadge.classList.remove("active");
            }
        }
    });
    
    // Establish WebRTC calls
    negotiateConnections();
    
    // Sync logs
    logsContainer.innerHTML = "";
    gameState.logs.forEach(log => {
        addLogEntry(log);
    });
    
    // Scoreboard
    goldenScoreTeam1.textContent = (gameState.team_scores["1"] >= 0 ? "+" : "") + gameState.team_scores["1"];
    goldenScoreTeam2.textContent = (gameState.team_scores["2"] >= 0 ? "+" : "") + gameState.team_scores["2"];
    roundPointsTeam1.textContent = gameState.round_points["1"];
    roundPointsTeam2.textContent = gameState.round_points["2"];
    marriagePointsTeam1.textContent = `+${gameState.marriage_points["1"]}`;
    marriagePointsTeam2.textContent = `+${gameState.marriage_points["2"]}`;
    
    if (gameState.highest_bid) {
        currentBidBadge.textContent = `Bid: ${gameState.highest_bid.bid_level} (P${gameState.highest_bid.player_index + 1})`;
        currentBidBadge.classList.remove("hidden");
    } else {
        currentBidBadge.textContent = "Bid: None";
    }
    
    // Trump Display
    if (gameState.trump_suit) {
        if (gameState.trump_suit === "HIDDEN") {
            trumpSuitIndicator.classList.add("hidden");
            trumpSuitText.textContent = "HIDDEN";
            trumpSuitText.className = "text-muted";
            trumpSelectionHint.textContent = "Revealed on Trick 1";
        } else {
            trumpSuitIndicator.textContent = SUIT_SYMBOLS[gameState.trump_suit];
            trumpSuitIndicator.className = `trump-suit-indicator suit-${gameState.trump_suit}`;
            trumpSuitIndicator.classList.remove("hidden");
            trumpSuitText.textContent = gameState.trump_suit === "H" ? "Hearts" :
                                       gameState.trump_suit === "D" ? "Diamonds" :
                                       gameState.trump_suit === "C" ? "Clubs" : "Spades";
            trumpSuitText.className = SUIT_CLASSES[gameState.trump_suit];
            trumpSelectionHint.textContent = gameState.vakkai_caller !== null ? "Vakkai Trump" : "Standard Trump";
        }
    } else {
        trumpSuitIndicator.classList.add("hidden");
        trumpSuitText.textContent = "NONE";
        trumpSuitText.className = "text-muted";
        trumpSelectionHint.textContent = "";
    }
    
    // Center Indicator
    centerRoundText.textContent = `Round ${gameState.round_number}`;
    if (gameState.status === "PLAYING") {
        const activeName = playersList[gameState.turn] ? playersList[gameState.turn].name : `Player ${gameState.turn + 1}`;
        centerTurnIndicator.textContent = `${activeName}'s Turn`;
    } else {
        centerTurnIndicator.textContent = gameState.status.replace(/_/g, " ");
    }
    
    // Draw Trick Pile (Center table cards)
    const trick = gameState.current_trick;
    SEAT_POSITIONS.forEach(pos => {
        document.getElementById("played-card-" + pos).innerHTML = "";
    });
    
    if (trick && trick.plays) {
        Object.entries(trick.plays).forEach(([pIdx, card]) => {
            const seatIdx = parseInt(pIdx);
            const pos = getRelativeSeatPosition(seatIdx);
            const slot = document.getElementById("played-card-" + pos);
            if (slot) {
                slot.appendChild(renderCardElement(card));
            }
        });
    }
    
    // Draw Player Hand
    renderPlayerHand();
    
    // Show/hide player hand container based on game status
    if (gameState && gameState.status !== "LOBBY") {
        playerHandFooter.classList.remove("hidden");
    } else {
        playerHandFooter.classList.add("hidden");
    }
    
    // Render Action Overlays/Modals
    renderModals();
}

function renderCardElement(card) {
    const cardEl = document.createElement("div");
    cardEl.className = `game-card ${SUIT_CLASSES[card.suit]}`;
    
    if (card.hidden) {
        cardEl.className = "game-card disabled";
        cardEl.innerHTML = `<div class="card-center-suit"><i class="fa-solid fa-circle-question"></i></div>`;
    } else {
        cardEl.innerHTML = `
            <div class="card-top-left">
                ${card.value}
                <span class="suit-icon">${SUIT_SYMBOLS[card.suit]}</span>
            </div>
            <div class="card-center-suit">${SUIT_SYMBOLS[card.suit]}</div>
        `;
        // Glow if it's the Trump suit
        if (gameState && gameState.trump_suit && card.suit === gameState.trump_suit) {
            cardEl.classList.add("trump-card-glow");
        }
    }
    
    return cardEl;
}

function renderPlayerHand() {
    playerHandContainer.innerHTML = "";
    const rawHand = gameState.hands[mySeat] || [];
    
    // Sort hand: Group by suit (Hearts, Diamonds, Clubs, Spades) and sort by rank hierarchy
    const SUIT_ORDER = {"H": 0, "D": 1, "C": 2, "S": 3};
    const CARD_HIERARCHY = {"J": 5, "9": 4, "A": 3, "10": 2, "K": 1, "Q": 0};
    
    const hand = [...rawHand].sort((a, b) => {
        const suitDiff = SUIT_ORDER[a.suit] - SUIT_ORDER[b.suit];
        if (suitDiff !== 0) return suitDiff;
        return CARD_HIERARCHY[b.value] - CARD_HIERARCHY[a.value];
    });
    
    // Validation: cards we are allowed to play during PLAYING phase
    let playableIndices = [];
    if (gameState.status === "PLAYING" && gameState.turn === mySeat) {
        const trick = gameState.current_trick;
        if (trick && Object.keys(trick.plays).length > 0) {
            const leadCard = trick.plays[trick.lead_player_index];
            const ledSuit = leadCard.suit;
            
            // Check follow suit
            const hasLedSuit = hand.some(c => c.suit === ledSuit);
            hand.forEach((c, idx) => {
                if (!hasLedSuit || c.suit === ledSuit) {
                    playableIndices.push(idx);
                }
            });
        } else {
            // We lead, everything is playable
            playableIndices = hand.map((_, idx) => idx);
        }
    }
    
    hand.forEach((card, idx) => {
        const cardEl = renderCardElement(card);
        
        // Handle playing action
        if (gameState.status === "PLAYING") {
            if (gameState.turn === mySeat && playableIndices.includes(idx)) {
                cardEl.addEventListener("click", () => {
                    sendMsg({ type: "play_card", card: card });
                });
            } else {
                cardEl.classList.add("disabled");
            }
        } else {
            // During other phases (like BIDDING or SELECTING_TRUMP), keep cards visible and not dimmed
        }
        
        playerHandContainer.appendChild(cardEl);
    });
}

// Render dynamic overlays for bidding, trump selection, etc.
function renderModals() {
    const status = gameState.status;
    
    // 1. Bidding Modal
    if (status === "BIDDING" && gameState.bidding_turn === mySeat) {
        biddingModal.classList.add("active");
        
        // Highest bid indicator
        const high = gameState.highest_bid;
        const modalHighestBid = document.getElementById("modal-highest-bid");
        if (high) {
            modalHighestBid.textContent = `${high.bid_level} by Player ${high.player_index + 1}`;
        } else {
            modalHighestBid.textContent = "None";
        }
        
        // Build bidding buttons grid
        bidButtonsGrid.innerHTML = "";
        const curLevel = high ? high.bid_level : null;
        const curIdx = curLevel ? BID_LEVELS.indexOf(curLevel) : -1;
        
        BID_LEVELS.forEach((level, idx) => {
            const btn = document.createElement("button");
            btn.className = "bid-btn";
            btn.textContent = level;
            
            // Must outbid the current level (Chance Skip Rule: disallow 200 after Chance)
            let disabled = idx <= curIdx;
            if (curLevel === "Chance" && level === "200") {
                disabled = true;
            }
            btn.disabled = disabled;
            
            btn.addEventListener("click", () => {
                sendMsg({ type: "place_bid", bid_level: level });
            });
            bidButtonsGrid.appendChild(btn);
        });
        
        // First bidder cannot pass initially
        const isFirstBidder = mySeat === (gameState.dealer_index + 1) % 4;
        const hasBids = gameState.bids.length > 0;
        passBidBtn.disabled = isFirstBidder && !hasBids;
    } else {
        biddingModal.classList.remove("active");
    }
    
    // 2. Secret Trump Selection Modal
    if (status === "SELECTING_TRUMP" && gameState.bid_winner === mySeat) {
        trumpSelectModal.classList.add("active");
        trumpCardsRow.innerHTML = "";
        
        const rawHand = gameState.hands[mySeat] || [];
        
        // Map to keep track of original index
        const handWithIndex = rawHand.map((card, idx) => ({ ...card, originalIndex: idx }));
        
        // Sort
        const SUIT_ORDER = {"H": 0, "D": 1, "C": 2, "S": 3};
        const CARD_HIERARCHY = {"J": 5, "9": 4, "A": 3, "10": 2, "K": 1, "Q": 0};
        handWithIndex.sort((a, b) => {
            const suitDiff = SUIT_ORDER[a.suit] - SUIT_ORDER[b.suit];
            if (suitDiff !== 0) return suitDiff;
            return CARD_HIERARCHY[b.value] - CARD_HIERARCHY[a.value];
        });
        
        handWithIndex.forEach((card) => {
            const cardEl = renderCardElement(card);
            cardEl.addEventListener("click", () => {
                sendMsg({ type: "select_trump", card_index: card.originalIndex });
            });
            trumpCardsRow.appendChild(cardEl);
        });
    } else {
        trumpSelectModal.classList.remove("active");
    }
    
    // 3. Chance Trump Selection Modal
    if (status === "CHANCE_TRUMP_SELECT" && gameState.bid_winner === mySeat) {
        chanceSelectModal.classList.add("active");
        
        // Capture choices
        const cardSlots = document.querySelectorAll(".card-back-selection");
        cardSlots.forEach(slot => {
            // Remove previous event listeners
            const newSlot = slot.cloneNode(true);
            slot.parentNode.replaceChild(newSlot, slot);
            
            newSlot.addEventListener("click", () => {
                const idx = parseInt(newSlot.getAttribute("data-index"));
                sendMsg({ type: "select_chance_trump", card_index: idx });
            });
        });
    } else {
        chanceSelectModal.classList.remove("active");
    }
    
    // 4. Vakkai Call Override Modal
    if (status === "VAKKAI_OR_PLAY" && gameState.vakkai_turn === mySeat) {
        vakkaiModal.classList.add("active");
    } else {
        vakkaiModal.classList.remove("active");
    }
    
    // 5. Kotu Decision Modal
    if (status === "KOTU_DECISION" && gameState.turn === mySeat) {
        kotuModal.classList.add("active");
    } else {
        kotuModal.classList.remove("active");
    }
    
    // 6. Round End Modal
    if (status === "ROUND_END") {
        roundEndModal.classList.add("active");
        
        const lastRound = gameState.round_history[gameState.round_history.length - 1];
        if (lastRound) {
            const bidWinnerName = playersList[lastRound.bid_winner] ? playersList[lastRound.bid_winner].name : `Player ${lastRound.bid_winner + 1}`;
            document.getElementById("round-end-title").textContent = `Round ${lastRound.round_number} Finished`;
            document.getElementById("round-end-outcome").textContent = `Bid was: ${lastRound.bid} by ${bidWinnerName}`;
            document.getElementById("round-end-score-team1").textContent = lastRound.scores["1"];
            document.getElementById("round-end-score-team2").textContent = lastRound.scores["2"];
        }
    } else {
        roundEndModal.classList.remove("active");
    }
    
    // 7. Game Over Modal
    if (status === "GAME_OVER") {
        gameOverModal.classList.add("active");
        
        const winner = gameState.winner_team;
        document.getElementById("game-over-title").textContent = `Team ${winner} Wins!`;
        document.getElementById("game-over-desc").textContent = `Congratulations to Team ${winner} on winning the match!`;
    } else {
        gameOverModal.classList.remove("active");
    }

    // 8. Ready Check Modal
    if (status === "READY_CHECK") {
        readyModal.classList.add("active");
        readyPlayersList.innerHTML = "";
        
        playersList.forEach((p, idx) => {
            if (!p) return;
            const isReady = gameState.ready_players.includes(idx);
            
            const item = document.createElement("div");
            item.className = `ready-player-item ${isReady ? "is-ready" : ""}`;
            
            const nameSpan = document.createElement("span");
            nameSpan.className = "player-name";
            nameSpan.innerHTML = `${p.name} ${idx === mySeat ? "<strong>(You)</strong>" : ""}`;
            
            const badgeSpan = document.createElement("span");
            badgeSpan.className = `ready-status-badge ${isReady ? "ready" : "waiting"}`;
            if (isReady) {
                badgeSpan.innerHTML = `<i class="fa-solid fa-circle-check"></i> Ready`;
            } else {
                badgeSpan.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Waiting...`;
            }
            
            item.appendChild(nameSpan);
            item.appendChild(badgeSpan);
            readyPlayersList.appendChild(item);
        });
        
        // Disable button if this player is already ready
        const amIReady = gameState.ready_players.includes(mySeat);
        if (amIReady) {
            readyBtn.disabled = true;
            readyBtn.textContent = "Waiting for other players...";
            readyBtn.classList.remove("btn-primary");
            readyBtn.classList.add("btn-secondary");
        } else {
            readyBtn.disabled = false;
            readyBtn.textContent = "I'm Ready";
            readyBtn.classList.add("btn-primary");
            readyBtn.classList.remove("btn-secondary");
        }
    } else {
        readyModal.classList.remove("active");
    }
    
    // --- DYNAMIC CONTROL BUTTONS ---
    // Marriage Button
    const team = mySeat !== null ? ([0, 2].includes(mySeat) ? "1" : "2") : null;
    const marriages = mySeat !== null ? gameState.marriages[mySeat] : null;
    
    if (marriages && marriages.available.length > 0 && gameState.tricks_won_by_team[team] === 1 && gameState.vakkai_caller === null) {
        showMarriageBtn.classList.remove("hidden");
        
        // Re-bind click event with the first available suit
        const suitToShow = marriages.available[0];
        showMarriageBtn.onclick = () => {
            sendMsg({ type: "show_marriage", suit: suitToShow });
        };
    } else {
        showMarriageBtn.classList.add("hidden");
    }
    
    // Turn actions panel helpers
    const turnActionsPanel = document.getElementById("turn-actions-panel");
    if (status === "PLAYING" && gameState.turn === mySeat) {
        turnActionsPanel.innerHTML = `<span class="badge badge-indigo animate-pulse">It's Your Turn! Play a card.</span>`;
    } else {
        turnActionsPanel.innerHTML = `<span class="no-actions-text">Wait for your turn...</span>`;
    }
}

// --- CLIENT LOBBY ACTIONS AND CONNECTION HANDLERS ---

function connectWebSocket() {
    const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
    // Connect to WebSocket on the same host and port at the path /ws
    const wsUrl = `${wsProtocol}//${location.host}/ws`;
    
    addLogEntry("Connecting to server...");
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        addLogEntry("<span class='text-green'>Connected to Server!</span>");
    };
    
    ws.onmessage = async (event) => {
        const msg = JSON.parse(event.data);
        
        if (msg.type === "room_joined") {
            roomId = msg.room_id;
            mySeat = msg.my_seat;
            
            lobbyScreen.classList.remove("active");
            gameScreen.classList.add("active");
            
            addLogEntry(`Successfully joined Room ID: ${roomId}`);
            
            // Setup Web Audio and Video Fallback
            await initMediaStream();
            
            // Trigger layout scaling once elements become visible
            setTimeout(resizeTable, 80);
        } else if (msg.type === "state_update") {
            updateRoomState(msg);
        } else if (msg.type === "webrtc_signal") {
            await handleSignalingMsg(msg.sender_seat, msg.signal_data);
        } else if (msg.type === "error") {
            alert(msg.message);
            addLogEntry(`<span class='text-red'>Error: ${msg.message}</span>`);
        }
    };
    
    ws.onclose = () => {
        addLogEntry("<span class='text-red'>Disconnected from Server!</span>");
        
        // Clean up connections
        Object.keys(peerConnections).forEach(cleanupPeerConnection);
        
        // Reconnection attempt
        setTimeout(connectWebSocket, 3000);
    };
}

// --- DOM EVENT LISTENERS ---

createRoomBtn.addEventListener("click", () => {
    username = usernameInput.value.trim() || "Host";
    // Send Create Room request
    sendMsg({
        type: "create_room",
        username: username
    });
});

joinRoomBtn.addEventListener("click", () => {
    username = usernameInput.value.trim() || "Player";
    const enteredRoomId = roomIdInput.value.trim();
    if (!enteredRoomId) {
        alert("Please enter a Room ID");
        return;
    }
    
    roomId = enteredRoomId;
    sendMsg({
        type: "join_room",
        room_id: enteredRoomId,
        username: username
    });
});

copyRoomIdBtn.addEventListener("click", () => {
    if (roomId) {
        navigator.clipboard.writeText(roomId).then(() => {
            alert("Room ID copied to clipboard!");
        });
    }
});

addBotBtn.addEventListener("click", () => {
    sendMsg({ type: "add_bot" });
});

leaveRoomBtn.addEventListener("click", () => {
    location.reload();
});

// Mic/Cam toggles
toggleMicBtn.addEventListener("click", () => {
    if (localStream) {
        micEnabled = !micEnabled;
        localStream.getAudioTracks().forEach(t => t.enabled = micEnabled);
        
        toggleMicBtn.innerHTML = micEnabled ? `<i class="fa-solid fa-microphone"></i>` : `<i class="fa-solid fa-microphone-slash"></i>`;
        if (micEnabled) toggleMicBtn.classList.remove("muted");
        else toggleMicBtn.classList.add("muted");
    }
});

toggleCamBtn.addEventListener("click", () => {
    if (localStream) {
        camEnabled = !camEnabled;
        localStream.getVideoTracks().forEach(t => t.enabled = camEnabled);
        
        toggleCamBtn.innerHTML = camEnabled ? `<i class="fa-solid fa-video"></i>` : `<i class="fa-solid fa-video-slash"></i>`;
        if (camEnabled) toggleCamBtn.classList.remove("muted");
        else toggleCamBtn.classList.add("muted");
    }
});

// Bidding Pass
passBidBtn.addEventListener("click", () => {
    sendMsg({ type: "place_bid", bid_level: "Pass" });
});

// Vakkai Actions
callVakkaiBtn.addEventListener("click", () => {
    sendMsg({ type: "call_vakkai", call_vakkai: true });
});

declineVakkaiBtn.addEventListener("click", () => {
    sendMsg({ type: "call_vakkai", call_vakkai: false });
});

// Kotu Actions
callKotuBtn.addEventListener("click", () => {
    sendMsg({ type: "call_kotu", call_kotu: true });
});

declineKotuBtn.addEventListener("click", () => {
    sendMsg({ type: "call_kotu", call_kotu: false });
});

// Next Round / Restart Actions
nextRoundBtn.addEventListener("click", () => {
    sendMsg({ type: "next_round" });
});

restartGameBtn.addEventListener("click", () => {
    sendMsg({ type: "restart_game" });
});

readyBtn.addEventListener("click", () => {
    sendMsg({ type: "player_ready" });
});

// Rules Modal Actions
if (openRulesBtn && rulesModal && closeRulesBtn) {
    openRulesBtn.addEventListener("click", () => {
        rulesModal.classList.add("active");
    });
    closeRulesBtn.addEventListener("click", () => {
        rulesModal.classList.remove("active");
    });
    if (closeRulesXBtn) {
        closeRulesXBtn.addEventListener("click", () => {
            rulesModal.classList.remove("active");
        });
    }
    // Close when clicking outside of rules-modal-content
    rulesModal.addEventListener("click", (e) => {
        if (e.target === rulesModal) {
            rulesModal.classList.remove("active");
        }
    });
}

// --- Dynamic Scaling Engine ---
function resizeTable() {
    const tableArea = document.querySelector(".table-area");
    const cardTable = document.querySelector(".card-table");
    if (!tableArea || !cardTable) return;
    
    // We add small safety paddings (10px on each side)
    const availableWidth = tableArea.clientWidth - 20;
    const availableHeight = tableArea.clientHeight - 20;
    
    // Bounding dimensions including seat overhang (desktop table is 600x500)
    // Left/right seats overhang by ~80px on each side, top/bottom overhang by ~40px
    const baseWidth = 760;
    const baseHeight = 580;
    
    const scaleX = availableWidth / baseWidth;
    const scaleY = availableHeight / baseHeight;
    
    // Pick the smaller scale factor to ensure no overflow on either axis
    let scale = Math.min(scaleX, scaleY);
    
    // Clamp values: max 1.0 (no scaling up past default), min 0.4 (keep text readable)
    scale = Math.min(1.0, scale);
    scale = Math.max(0.4, scale);
    
    cardTable.style.setProperty("--table-scale", scale);
}

// Window resizing updates the scale immediately
window.addEventListener("resize", resizeTable);

// Connect to Websocket server automatically
connectWebSocket();
