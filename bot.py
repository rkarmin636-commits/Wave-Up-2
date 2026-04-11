#!/usr/bin/env python3
"""
Wave Up - TRX Prediction Bot
Formula: Hybrid Adaptive (W=10, LB=50) + Pattern Memory + Trap Detection
  - Uses Momentum(10) as base
  - Tie at W=10 → check W=41~50 → still tie → check W=50
  - Tracks recent momentum accuracy over last 50 predictions
  - If momentum accuracy < 50%, auto-switches to anti-momentum (reverse)
  - Pattern Memory: tracks repeating B/S sequences → predicts next
  - Trap Detection: detects extreme one-sided streaks → reverses safely
  - Post-win caution: extra trap check for 3 rounds after every WIN
Topic: https://t.me/c/2383423317/282961

- State persistence (survives restart)
- File-based dedup (prevents duplicate messages across restarts/overlaps)
- Win→counter 1, Loss→counter 2,3,4...
- Mode: {N}=Normal {R}=Reverse {T}=Trap {P}=Pattern
"""

import os
import sys
import requests
import json
import hashlib
import datetime
import time
import logging

# ── Load path from env ───────────────────────────────────────────────────────
_monitor_path = os.environ.get('BOT_MONITOR_PATH', '')
if _monitor_path and _monitor_path not in sys.path:
    sys.path.insert(0, _monitor_path)

try:
    from bot_monitor import BotMonitor
except ImportError:
    class BotMonitor:
        def __init__(self, name): pass
        def check_api_error(self, msg): pass
        def check_signal_sent(self, ok): pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN    = os.environ.get('BOT_TOKEN',  '8774016221:AAGN3Ue10KPdlKXxCgnYHncgOQ1mVhwSnUI')
CHAT_ID  = os.environ.get('CHAT_ID',    '-1002383423317')
TOPIC    = int(os.environ.get('TOPIC',   '282961'))
LOGIN_ID = os.environ.get('LOGIN_ID',   '959969637971')
PASSWORD = os.environ.get('PASSWORD',   'Waiyan203654')
API_BASE = "https://6lotteryapi.com/api/webapi"

STATE_FILE = 'wai1_state.json'

HYBRID_WINDOW = 10      # Momentum window size
HYBRID_LOOKBACK = 50    # How many recent momentum results to track

# ── Pattern Memory ────────────────────────────────────────────────────────────
PATTERN_SEQ_LEN   = 4   # Sequence length to match (e.g. BBSS)
PATTERN_MIN_HITS  = 3   # Min occurrences before trusting a pattern
PATTERN_CONF_MIN  = 0.65  # Min confidence to use pattern vote (65%)

# ── Trap Detection ────────────────────────────────────────────────────────────
TRAP_STREAK_LEN   = 7   # Consecutive same-side streak = trap zone
TRAP_W10_EXTREME  = 8   # W=10 one-side count >= this = post-win trap
POST_WIN_CAUTION  = 3   # How many rounds after WIN to apply extra caution

# ========== LOGGING ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wai1_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class WaveUpBot:
    def __init__(self):
        self.auth_token = None
        self.fail_count = 0
        self.monitor = BotMonitor("wave_up")

        # ── Defaults ──────────────────────────────────────────────────────
        self.last_issue = None
        self.last_prediction = None
        self.last_pred_issue = None
        self.consecutive_losses = 0
        self.bet_counter = 0
        self.last_sent_sig = None
        self.last_sent_win = None

        # ── Hybrid Adaptive tracking ─────────────────────────────────────
        self.momentum_results = []   # list of 1(correct) / 0(wrong) for pure momentum
        self.last_momentum_pred = None  # what pure momentum predicted (before adaptive flip)

        # ── Pattern Memory tracking ───────────────────────────────────────
        self.result_history = []     # actual B/S results in order (oldest→newest)

        # ── Trap / Post-win tracking ──────────────────────────────────────
        self.post_win_rounds = 0     # counts rounds since last WIN (0 = not in caution)

        self._load_state()
        logger.info("✅ Wave Up Bot Ready!")

    # ── State persistence ─────────────────────────────────────────────────
    def _save_state(self):
        state = {
            'consecutive_losses': self.consecutive_losses,
            'bet_counter': self.bet_counter,
            'last_prediction': self.last_prediction,
            'last_pred_issue': self.last_pred_issue,
            'last_issue': self.last_issue,
            'last_sent_sig': self.last_sent_sig,
            'last_sent_win': self.last_sent_win,
            'momentum_results': self.momentum_results[-100:],
            'last_momentum_pred': self.last_momentum_pred,
            'result_history': self.result_history[-100:],
            'post_win_rounds': self.post_win_rounds,
        }
        try:
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                self.consecutive_losses = state.get('consecutive_losses', 0)
                self.bet_counter = state.get('bet_counter', 0)
                self.last_prediction = state.get('last_prediction', None)
                self.last_pred_issue = state.get('last_pred_issue', None)
                self.last_issue = state.get('last_issue', None)
                self.last_sent_sig = state.get('last_sent_sig', None)
                self.last_sent_win = state.get('last_sent_win', None)
                self.momentum_results = state.get('momentum_results', [])
                self.last_momentum_pred = state.get('last_momentum_pred', None)
                self.result_history = state.get('result_history', [])
                self.post_win_rounds = state.get('post_win_rounds', 0)
                logger.info(
                    f"📂 State loaded: losses={self.consecutive_losses}, "
                    f"last_sig={self.last_sent_sig}, pred_issue={self.last_pred_issue}, "
                    f"mom_history={len(self.momentum_results)}, "
                    f"pat_history={len(self.result_history)}, post_win={self.post_win_rounds}"
                )
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

    # ── Signature ─────────────────────────────────────────────────────────
    def _create_sig(self, data):
        mutable = {k: v for k, v in data.items() if k not in ('signature', 'timestamp')}
        s = json.dumps(mutable, sort_keys=True, separators=(',', ':'))
        mutable['signature'] = hashlib.md5(s.encode()).hexdigest().upper()
        mutable['timestamp'] = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        return mutable

    # ── Login ─────────────────────────────────────────────────────────────
    def login(self, max_retries=5):
        for attempt in range(max_retries):
            try:
                data = {
                    "language": 0, "logintype": "mobile", "phonetype": 0,
                    "pwd": PASSWORD,
                    "random": str(int(time.time() * 1_000_000)),
                    "username": LOGIN_ID
                }
                r = requests.post(
                    f"{API_BASE}/Login",
                    json=self._create_sig(data),
                    headers={'Content-Type': 'application/json',
                             'Referer': 'https://www.6lottery.com/'},
                    timeout=15
                )
                result = r.json()
                if result.get('code') == 0 and result.get('data'):
                    self.auth_token = result['data']['token']
                    logger.info("✅ Login successful")
                    return True
                else:
                    logger.warning(f"Login failed: {result.get('message', 'Unknown')}")
            except requests.exceptions.Timeout:
                logger.warning(f"Login timeout ({attempt+1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Login conn error ({attempt+1}/{max_retries})")
            except Exception as e:
                logger.warning(f"Login error: {e} ({attempt+1}/{max_retries})")
            time.sleep(3)
        return False

    # ── Get Data ──────────────────────────────────────────────────────────
    def get_live_data(self, max_retries=5):
        if not self.auth_token and not self.login():
            return None

        for attempt in range(max_retries):
            try:
                params = {
                    "pageSize": 50, "pageNo": 1, "typeId": 13, "language": 0,
                    "random": str(int(time.time() * 1_000_000))
                }
                r = requests.post(
                    f"{API_BASE}/GetTRXNoaverageEmerdList",
                    json=self._create_sig(params),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {self.auth_token}',
                        'Referer': 'https://www.6lottery.com/'
                    },
                    timeout=15
                )
                result = r.json()

                if result.get('code') == 0 and result.get('data'):
                    gameslist = result['data']['data']['gameslist']
                    if gameslist:
                        self.fail_count = 0
                        return gameslist

                elif result.get('code') in [4, 5]:
                    logger.warning(f"🔄 API code {result.get('code')}, re-login...")
                    self.auth_token = None
                    if self.login():
                        continue
                    else:
                        time.sleep(5)
                        continue
                else:
                    logger.warning(f"API error: {result.get('code')}: {result.get('message', 'Unknown')}")

            except requests.exceptions.Timeout:
                logger.warning(f"Data timeout ({attempt+1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Data conn error ({attempt+1}/{max_retries})")
            except json.JSONDecodeError:
                logger.warning(f"JSON error ({attempt+1}/{max_retries})")
            except Exception as e:
                logger.warning(f"Data error: {e} ({attempt+1}/{max_retries})")
            time.sleep(3)

        self.fail_count += 1
        if self.fail_count >= 2:
            logger.warning("Too many failures, forcing re-login...")
            self.auth_token = None
            self.fail_count = 0
        return None

    # ── Telegram ──────────────────────────────────────────────────────────
    def send_msg(self, text, max_retries=3):
        for attempt in range(max_retries):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    json={
                        "chat_id": CHAT_ID,
                        "text": text,
                        "message_thread_id": TOPIC
                    },
                    timeout=10
                )
                result = r.json()
                if result.get('ok'):
                    logger.info(f"✅ Sent: {text[:50]}")
                    self.monitor.check_signal_sent(True)
                    return True
                else:
                    logger.warning(f"Telegram error: {result.get('description')}")
                    self.monitor.check_signal_sent(False)
            except requests.exceptions.Timeout:
                logger.warning(f"Telegram timeout ({attempt+1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Telegram conn error ({attempt+1}/{max_retries})")
            except Exception as e:
                logger.warning(f"Telegram error: {e} ({attempt+1}/{max_retries})")
            time.sleep(2)
        return False

    # ── Pattern Memory ────────────────────────────────────────────────────
    def pattern_memory_vote(self):
        """
        Scan result_history for the last PATTERN_SEQ_LEN sequence.
        Count how many times that sequence appeared and what came after.
        Returns: ('B'|'S'|None, confidence_float)
        """
        hist = self.result_history
        seq_len = PATTERN_SEQ_LEN
        if len(hist) < seq_len + 1:
            return None, 0.0

        key = tuple(hist[-seq_len:])
        follow_b = 0
        follow_s = 0

        for i in range(len(hist) - seq_len - 1):
            if tuple(hist[i:i + seq_len]) == key:
                nxt = hist[i + seq_len]
                if nxt == 'B':
                    follow_b += 1
                else:
                    follow_s += 1

        total = follow_b + follow_s
        if total < PATTERN_MIN_HITS:
            logger.info(f"🔵 Pattern '{' '.join(key)}': only {total} hits (need {PATTERN_MIN_HITS}) → skip")
            return None, 0.0

        conf_b = follow_b / total
        conf_s = follow_s / total

        if conf_b >= PATTERN_CONF_MIN:
            logger.info(f"🔵 Pattern '{' '.join(key)}': B={follow_b}/{total} ({conf_b:.0%}) → vote B")
            return 'B', conf_b
        elif conf_s >= PATTERN_CONF_MIN:
            logger.info(f"🔵 Pattern '{' '.join(key)}': S={follow_s}/{total} ({conf_s:.0%}) → vote S")
            return 'S', conf_s
        else:
            logger.info(f"🔵 Pattern '{' '.join(key)}': B={follow_b} S={follow_s} → no clear vote")
            return None, 0.0

    # ── Trap Detection ────────────────────────────────────────────────────
    def trap_detection(self, games):
        """
        Two trap checks:
          A) Streak trap: last TRAP_STREAK_LEN results all same side → reverse
          B) Post-win extreme: within POST_WIN_CAUTION rounds after WIN and
             W=10 one-side >= TRAP_W10_EXTREME → reverse
        Returns: (trapped: bool, trap_side: 'B'|'S'|None)
        """
        hist = self.result_history

        # ── A) Pure streak trap ───────────────────────────────────────────
        if len(hist) >= TRAP_STREAK_LEN:
            recent = hist[-TRAP_STREAK_LEN:]
            if all(r == 'B' for r in recent):
                logger.info(f"🚨 Trap A: {TRAP_STREAK_LEN} consecutive B streak → reverse to S")
                return True, 'B'
            if all(r == 'S' for r in recent):
                logger.info(f"🚨 Trap A: {TRAP_STREAK_LEN} consecutive S streak → reverse to B")
                return True, 'S'

        # ── B) Post-win extreme check ─────────────────────────────────────
        if self.post_win_rounds > 0:
            try:
                b_w10 = sum(
                    1 for i in range(HYBRID_WINDOW)
                    if int(games[i].get('number', -1)) >= 5
                )
                s_w10 = HYBRID_WINDOW - b_w10
                if b_w10 >= TRAP_W10_EXTREME:
                    logger.info(
                        f"🚨 Trap B (post-win {self.post_win_rounds}): "
                        f"W=10 B={b_w10}/10 extreme → reverse to S"
                    )
                    return True, 'B'
                if s_w10 >= TRAP_W10_EXTREME:
                    logger.info(
                        f"🚨 Trap B (post-win {self.post_win_rounds}): "
                        f"W=10 S={s_w10}/10 extreme → reverse to B"
                    )
                    return True, 'S'
            except (ValueError, TypeError):
                pass

        return False, None

    # ── Formula: Hybrid Adaptive + Voting System (W=10, LB=50) ─────────
    def hybrid_adaptive_formula(self, games):
        """
        Balanced Voting System (3 equal votes):
          Vote 1 — Momentum(10) + auto-reverse if accuracy < 50%
          Vote 2 — Pattern Memory (only if conf >= 65% and hits >= 3)
          Vote 3 — Trap Detection (streak trap + post-win extreme)

          3/3 agree  → very strong signal
          2/3 agree  → follow majority
          1/1/1 split (all different — impossible with B/S so means
                       2 say X, 1 abstains OR all 3 split)
                     → fallback to momentum (safe default)

        Mode labels:
          {N}  = Momentum only
          {R}  = Momentum reversed (accuracy < 50%)
          {P}  = Pattern tipped the balance
          {T}  = Trap tipped the balance
          {PT} = Pattern + Trap both voted same (strongest)
          {3}  = All 3 voted same (maximum confidence)
        """
        if not games or len(games) < HYBRID_WINDOW:
            return None, None, 'N'

        # ── VOTE 1: Momentum(10) ──────────────────────────────────────────
        b_count = 0
        for i in range(HYBRID_WINDOW):
            try:
                num = int(games[i].get('number', -1))
                if num >= 5:
                    b_count += 1
            except (ValueError, TypeError):
                return None, None, 'N'

        if b_count > HYBRID_WINDOW / 2:
            mom_pred = 'B'
        elif b_count < HYBRID_WINDOW / 2:
            mom_pred = 'S'
        else:
            # Tie at W=10 → check W=41~50
            if len(games) >= 50:
                try:
                    b_count_mid = sum(
                        1 for i in range(40, 50)
                        if int(games[i].get('number', -1)) >= 5
                    )
                except (ValueError, TypeError):
                    b_count_mid = 5

                if b_count_mid > 5:
                    mom_pred = 'B'
                    logger.info(f"🔍 W=10 Tie → W=41~50: B={b_count_mid}/10 → {mom_pred}")
                elif b_count_mid < 5:
                    mom_pred = 'S'
                    logger.info(f"🔍 W=10 Tie → W=41~50: B={b_count_mid}/10 → {mom_pred}")
                else:
                    # Still tie → W=50
                    try:
                        b_count_wide = sum(
                            1 for i in range(50)
                            if int(games[i].get('number', -1)) >= 5
                        )
                    except (ValueError, TypeError):
                        b_count_wide = 25
                    mom_pred = 'B' if b_count_wide >= 25 else 'S'
                    logger.info(
                        f"🔍 W=10 Tie → W=41~50 Tie → W=50: B={b_count_wide}/50 → {mom_pred}"
                    )
            else:
                try:
                    last_num = int(games[0].get('number', -1))
                    mom_pred = 'B' if last_num >= 5 else 'S'
                except (ValueError, TypeError):
                    mom_pred = 'B'
                logger.info(f"🔍 W=10 Tie (data<50) → most recent: {mom_pred}")

        # Apply auto-reverse if momentum accuracy < 50%
        if len(self.momentum_results) >= HYBRID_LOOKBACK:
            recent_accuracy = sum(self.momentum_results[-HYBRID_LOOKBACK:]) / HYBRID_LOOKBACK
            if recent_accuracy < 0.50:
                mom_vote = 'S' if mom_pred == 'B' else 'B'
                mom_reversed = True
                logger.info(f"🔄 Momentum accuracy {recent_accuracy:.1%} < 50% → vote REVERSED to {mom_vote}")
            else:
                mom_vote = mom_pred
                mom_reversed = False
                logger.info(f"📈 Momentum accuracy {recent_accuracy:.1%} → vote {mom_vote}")
        else:
            mom_vote = mom_pred
            mom_reversed = False
            logger.info(f"📊 Momentum: building history ({len(self.momentum_results)}/{HYBRID_LOOKBACK}) → vote {mom_vote}")

        # ── VOTE 2: Pattern Memory ────────────────────────────────────────
        pat_vote, pat_conf = self.pattern_memory_vote()
        # None = abstain (not enough data / no clear pattern)

        # ── VOTE 3: Trap Detection ────────────────────────────────────────
        trapped, trap_side = self.trap_detection(games)
        if trapped and trap_side is not None:
            trap_vote = 'S' if trap_side == 'B' else 'B'
        else:
            trap_vote = None  # abstain

        # ── TALLY VOTES ───────────────────────────────────────────────────
        votes_b = sum([
            1 if mom_vote  == 'B' else 0,
            1 if pat_vote  == 'B' else 0,
            1 if trap_vote == 'B' else 0,
        ])
        votes_s = sum([
            1 if mom_vote  == 'S' else 0,
            1 if pat_vote  == 'S' else 0,
            1 if trap_vote == 'S' else 0,
        ])
        active_votes = sum([1, pat_vote is not None, trap_vote is not None])

        logger.info(
            f"🗳️ Votes → Momentum:{mom_vote} | "
            f"Pattern:{'abstain' if pat_vote is None else pat_vote} | "
            f"Trap:{'abstain' if trap_vote is None else trap_vote} | "
            f"B={votes_b} S={votes_s}"
        )

        # ── DECIDE ────────────────────────────────────────────────────────
        # Count which extra votes (Pattern / Trap) agreed with momentum
        pat_agrees  = (pat_vote  is not None and pat_vote  == mom_vote)
        trap_agrees = (trap_vote is not None and trap_vote == mom_vote)
        pat_opposes  = (pat_vote  is not None and pat_vote  != mom_vote)
        trap_opposes = (trap_vote is not None and trap_vote != mom_vote)

        if votes_b > votes_s:
            prediction = 'B'
        elif votes_s > votes_b:
            prediction = 'S'
        else:
            # Perfect split or all abstained → safe default = momentum vote
            prediction = mom_vote

        # ── MODE LABEL ────────────────────────────────────────────────────
        if pat_agrees and trap_agrees:
            # All 3 agree
            mode = '3'
        elif pat_agrees and trap_vote is None:
            mode = 'P' if not mom_reversed else 'R'
        elif trap_agrees and pat_vote is None:
            mode = 'T' if not mom_reversed else 'R'
        elif pat_agrees and trap_opposes:
            # Pattern sided with momentum, Trap opposed → majority wins (mom+pat)
            mode = 'P'
        elif trap_agrees and pat_opposes:
            # Trap sided with momentum, Pattern opposed → majority wins (mom+trap)
            mode = 'T'
        elif pat_opposes and trap_opposes:
            # Both Pattern and Trap oppose momentum → they win 2v1
            mode = 'PT'
        elif pat_vote is not None and trap_vote is not None and pat_vote != trap_vote:
            # Pattern and Trap disagree with each other → only momentum active
            mode = 'R' if mom_reversed else 'N'
        elif mom_reversed:
            mode = 'R'
        else:
            mode = 'N'

        logger.info(f"✅ Final: {prediction} | Mode={mode} | B={votes_b} S={votes_s}")
        return prediction, mom_pred, mode

    # ── Main Loop ─────────────────────────────────────────────────────────
    def run(self):
        logger.info("🚀 Wave Up Bot Running...")
        logger.info(f"📡 Topic {TOPIC}")

        while True:
            try:
                games = self.get_live_data()

                if not games or len(games) < HYBRID_WINDOW:
                    logger.warning("No data, retrying in 10s...")
                    time.sleep(10)
                    continue

                latest = games[0]
                try:
                    issue = str(latest.get('issueNumber'))
                except (ValueError, TypeError):
                    logger.warning("Invalid issue number")
                    time.sleep(5)
                    continue

                try:
                    current_num = int(latest.get('number', -1))
                except (ValueError, TypeError):
                    current_num = -1

                if current_num < 0:
                    time.sleep(5)
                    continue

                if self.last_issue == issue:
                    time.sleep(5)
                    continue

                actual = 'B' if current_num >= 5 else 'S'
                logger.info(f"📊 WU {issue}: {current_num}({actual})")

                # ── Check previous prediction (WIN / LOSS) ────────────────
                if self.last_pred_issue == issue and self.last_prediction:
                    # Track pure momentum accuracy
                    if self.last_momentum_pred is not None:
                        mom_correct = 1 if self.last_momentum_pred == actual else 0
                        self.momentum_results.append(mom_correct)
                        # Keep list bounded
                        if len(self.momentum_results) > 100:
                            self.momentum_results = self.momentum_results[-100:]

                    # ── Update result_history for Pattern Memory ──────────
                    self.result_history.append(actual)
                    if len(self.result_history) > 100:
                        self.result_history = self.result_history[-100:]

                    if self.last_prediction == actual:
                        # ===== WIN =====
                        self.consecutive_losses = 0
                        self.bet_counter = 0
                        self.post_win_rounds = POST_WIN_CAUTION  # start caution countdown
                        if self.last_sent_win != issue:
                            self.send_msg("🌈🏆🥇W I N🍾🍺🥃🍷🍸🍹🍻🥂")
                            self.last_sent_win = issue
                        logger.info(f"🎉 WIN! Counter reset to 1 | post-win caution={POST_WIN_CAUTION} rounds")
                    else:
                        # ===== LOSS =====
                        self.consecutive_losses += 1
                        if self.post_win_rounds > 0:
                            self.post_win_rounds -= 1
                            logger.info(f"💔 LOSS #{self.consecutive_losses} (post-win caution left={self.post_win_rounds})")
                        else:
                            logger.info(f"💔 LOSS #{self.consecutive_losses} → next bet={self.consecutive_losses + 1}")

                    self.last_prediction = None
                    self.last_pred_issue = None
                    self.last_momentum_pred = None
                    self._save_state()

                # ── Generate new prediction using Hybrid Adaptive ─────────
                prediction, mom_pred, mode = self.hybrid_adaptive_formula(games)

                if prediction is None:
                    logger.info("⚠️ No prediction")
                    self.last_issue = issue
                    self._save_state()
                    time.sleep(5)
                    continue

                pred_text = "BIG" if prediction == 'B' else "SMALL"

                try:
                    next_issue = str(int(issue) + 1)[-3:]
                except (ValueError, TypeError):
                    next_issue = "XXX"

                self.bet_counter = self.consecutive_losses + 1

                # ── File-based dedup: only send signal once per issue ─────
                if self.last_sent_sig == issue:
                    logger.info(f"⏭️ Signal for {issue} already sent, skip")
                    self.last_issue = issue
                    time.sleep(5)
                    continue

                signal_msg = (
                    f"🎯Trx {next_issue} ♐️ {pred_text} {self.bet_counter}🍀\n"
                    f"📊 Wave Up Formula {{{mode}}}"
                )

                if self.send_msg(signal_msg):
                    logger.info(
                        f"📤 Trx {next_issue} ♐️ {pred_text} {self.bet_counter}"
                    )
                    self.last_prediction = prediction
                    self.last_momentum_pred = mom_pred
                    self.last_pred_issue = str(int(issue) + 1)
                    self.last_sent_sig = issue

                self.last_issue = issue
                self._save_state()
                time.sleep(5)

            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                raise
            except Exception as e:
                logger.error(f"❌ Main loop error: {type(e).__name__}: {e}")
                self.monitor.check_api_error(str(e))
                time.sleep(10)


def main():
    logger.info("Starting Wave Up Bot...")
    bot = WaveUpBot()
    while True:
        try:
            bot.run()
        except KeyboardInterrupt:
            logger.info("Bot terminated")
            break
        except Exception as e:
            logger.error(f"🚨 Critical error: {type(e).__name__}: {e}")
            logger.info("Restarting in 10 seconds...")
            time.sleep(10)
            bot.auth_token = None
            bot.login()


if __name__ == "__main__":
    main()
