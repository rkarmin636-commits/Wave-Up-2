import os,sys,requests,json,hashlib,datetime,time,logging,base64
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

VERSION  = 'V5.16.3'
TOKEN    = os.environ.get('BOT_TOKEN','8774016221:AAGN3Ue10KPdlKXxCgnYHncgOQ1mVhwSnUI')
CHAT_ID  = os.environ.get('CHAT_ID','-1002383423317')
TOPIC    = int(os.environ.get('TOPIC','282961'))
LOGIN_ID = os.environ.get('LOGIN_ID','959969637971')
PASSWORD = os.environ.get('PASSWORD','Waiyan203654')
API_BASE = "https://6lotteryapi.com/api/webapi"
STATE_FILE   = 'waveup_state.json'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN','')
GITHUB_REPO  = 'rkarmin636-commits/Wave-Up-Bot'
EXPORT_FILE  = 'bot_state_export.json'
EXPORT_EVERY = 10
ROLLING_MAX  = 500
PHASE2_START = 200
PHASE3_START = 500
RECAL_P2=50; RECAL_P3=100
SEQ3_CONF_B,SEQ3_CONF_S=0.57,0.55
SEQ4_CONF_B,SEQ4_CONF_S=0.60,0.58
SEQ5_CONF_B,SEQ5_CONF_S=0.62,0.60
SEQ3_MIN_N=2; SEQ4_MIN_N=2; SEQ5_MIN_N=1
STREAK_CONF_B=0.57; STREAK_CONF_S=0.55
PW_SEQ3_CONF_B,PW_SEQ3_CONF_S=0.64,0.62
PW_SEQ4_CONF_B,PW_SEQ4_CONF_S=0.67,0.65
PW_SEQ5_CONF_B,PW_SEQ5_CONF_S=0.70,0.68
PW_STREAK_CONF_B=0.64; PW_STREAK_CONF_S=0.62
CONF_FLOOR=0.55; ANTI_MOM_W=10; POST_WIN_ROUNDS=3
MINI_RECAL_WINDOW=50
ACCURACY_WINDOW=20; ACCURACY_FLOOR=0.45
PREDICTOR_TRACK_N=30; PREDICTOR_MIN_PREDS=10
BASE_WEIGHTS={'S5':4.0,'S4':3.0,'S3':2.5,'ST':2.0,'SW':1.5,'AM':0.8}
SIGNAL_COOLDOWN=55
REV_PROB={
    'B':{1:0.45,2:0.48,3:0.52,4:0.65,5:0.70,6:0.55,7:0.40,8:0.35},
    'S':{1:0.45,2:0.48,3:0.52,4:0.58,5:0.74,6:0.60,7:0.45,8:0.38},
}
REV_WARNING_THRESHOLD=0.60; MOM_THRESHOLD=0.42

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('waveup_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger=logging.getLogger(__name__)

def normalize_issue(issue):
    try: return str(int(str(issue)))
    except: return str(issue)

class WaveUpBot:
    def __init__(self):
        self.auth_token=None; self.fail_count=0; self.last_issue=None
        self.last_prediction=None; self.last_pred_issue=None; self.last_pred_mode=None
        self.consecutive_losses=0; self.bet_counter=0
        self.last_sent_sig=None; self.last_sent_win=None; self.last_sent_time=0.0
        self.result_history=[]; self.total_results=0; self.bootstrapped=False
        self.calibrated_patterns={}; self.last_calibration_at=0
        self.wins=0; self.losses_total=0; self.post_win_rounds=0
        self.pre_win_loss_streak=0; self.last_win_side=None
        self.prediction_log=[]
        self.predictor_log={'S5':[],'S4':[],'S3':[],'ST':[],'SW':[],'AM':[]}
        self.pred_count_b=0; self.pred_count_s=0
        self.rev_warning_active=False; self.rev_warning_side=None
        self.rev_warning_prob=0.0; self.rev_confirmed=False
        self._load_state()
        logger.info(f"{VERSION} Ready! history={len(self.result_history)} total={self.total_results} wins={self.wins} losses={self.losses_total}")

    def _save_state(self):
        state={'consecutive_losses':self.consecutive_losses,'bet_counter':self.bet_counter,
               'last_prediction':self.last_prediction,'last_pred_issue':self.last_pred_issue,
               'last_pred_mode':self.last_pred_mode,'last_issue':self.last_issue,
               'last_sent_sig':self.last_sent_sig,'last_sent_win':self.last_sent_win,
               'last_sent_time':self.last_sent_time,'result_history':self.result_history,
               'total_results':self.total_results,'post_win_rounds':self.post_win_rounds,
               'pre_win_loss_streak':self.pre_win_loss_streak,'last_win_side':self.last_win_side,
               'calibrated_patterns':self.calibrated_patterns,'last_calibration_at':self.last_calibration_at,
               'wins':self.wins,'losses_total':self.losses_total,'bootstrapped':self.bootstrapped,
               'prediction_log':self.prediction_log[-50:],
               'predictor_log':{k:v[-PREDICTOR_TRACK_N:] for k,v in self.predictor_log.items()},
               'pred_count_b':self.pred_count_b,'pred_count_s':self.pred_count_s,
               'rev_warning_active':self.rev_warning_active,'rev_warning_side':self.rev_warning_side,
               'rev_warning_prob':self.rev_warning_prob}
        try:
            tmp=STATE_FILE+'.tmp'
            with open(tmp,'w') as f: json.dump(state,f)
            os.replace(tmp,STATE_FILE)
        except Exception as e: logger.warning(f"Save state failed: {e}")
        if self.total_results>0 and self.total_results%EXPORT_EVERY==0:
            self._export_to_github()

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE,'r') as f: state=json.load(f)
                self.consecutive_losses=state.get('consecutive_losses',0)
                self.bet_counter=state.get('bet_counter',0)
                self.last_prediction=state.get('last_prediction',None)
                self.last_pred_issue=state.get('last_pred_issue',None)
                self.last_pred_mode=state.get('last_pred_mode',None)
                self.last_issue=state.get('last_issue',None)
                raw_sig=state.get('last_sent_sig',None)
                self.last_sent_sig=normalize_issue(raw_sig) if raw_sig is not None else None
                raw_win=state.get('last_sent_win',None)
                self.last_sent_win=normalize_issue(raw_win) if raw_win is not None else None
                self.last_sent_time=float(state.get('last_sent_time',0.0))
                self.result_history=state.get('result_history',[])
                self.total_results=state.get('total_results',len(self.result_history))
                self.post_win_rounds=state.get('post_win_rounds',0)
                self.pre_win_loss_streak=state.get('pre_win_loss_streak',0)
                self.last_win_side=state.get('last_win_side',None)
                self.calibrated_patterns=state.get('calibrated_patterns',{})
                self.last_calibration_at=state.get('last_calibration_at',0)
                self.wins=state.get('wins',0); self.losses_total=state.get('losses_total',0)
                self.bootstrapped=state.get('bootstrapped',False)
                self.prediction_log=state.get('prediction_log',[])
                saved_plog=state.get('predictor_log',{})
                for k in self.predictor_log: self.predictor_log[k]=saved_plog.get(k,[])
                self.pred_count_b=state.get('pred_count_b',0)
                self.pred_count_s=state.get('pred_count_s',0)
                self.rev_warning_active=state.get('rev_warning_active',False)
                self.rev_warning_side=state.get('rev_warning_side',None)
                self.rev_warning_prob=state.get('rev_warning_prob',0.0)
        except Exception as e: logger.warning(f"Load state failed: {e}")

    def _add_result(self,result):
        self.result_history.append(result); self.total_results+=1
        if len(self.result_history)>ROLLING_MAX: self.result_history=self.result_history[-ROLLING_MAX:]

    def _log_predictor(self,mode,predicted,actual):
        clean=mode.rstrip('*')
        if clean in self.predictor_log:
            self.predictor_log[clean].append((predicted,actual))
            if len(self.predictor_log[clean])>PREDICTOR_TRACK_N:
                self.predictor_log[clean]=self.predictor_log[clean][-PREDICTOR_TRACK_N:]

    def _get_predictor_weight(self,mode):
        clean=mode.rstrip('*'); log=self.predictor_log.get(clean,[])
        if len(log)<PREDICTOR_MIN_PREDS: return 1.0
        recent=log[-PREDICTOR_TRACK_N:]; correct=sum(1 for p,a in recent if p==a); acc=correct/len(recent)
        if acc>=0.62: return 1.5
        elif acc>=0.58: return 1.2
        elif acc>=0.52: return 1.0
        elif acc>=0.47: return 0.7
        else: return 0.3

    def _log_prediction(self,predicted,actual):
        self.prediction_log.append((predicted,actual))
        if len(self.prediction_log)>50: self.prediction_log=self.prediction_log[-50:]

    def _recent_accuracy(self):
        window=self.prediction_log[-ACCURACY_WINDOW:]
        if len(window)<10: return 1.0
        return sum(1 for p,a in window if p==a)/len(window)

    def _check_accuracy_floor(self):
        if self._recent_accuracy()<ACCURACY_FLOOR:
            logger.warning("Accuracy below floor -> full recalibrate"); self.calibrate(); return True
        return False

    def _create_sig(self,data):
        mutable={k:v for k,v in data.items() if k not in ('signature','timestamp')}
        s=json.dumps(mutable,sort_keys=True,separators=(',',':'))
        mutable['signature']=hashlib.md5(s.encode()).hexdigest().upper()
        mutable['timestamp']=int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        return mutable

    def _get_current_streak(self):
        hist=self.result_history
        if not hist: return None,0
        side=hist[-1]; length=0
        for r in reversed(hist):
            if r==side: length+=1
            else: break
        return side,length

    def _get_rev_prob(self,side,length):
        return REV_PROB.get(side,{}).get(min(length,8),0.50)

    def _update_reversal_state(self,actual):
        self.rev_confirmed=False
        side,length=self._get_current_streak()
        if side is None: return
        prob=self._get_rev_prob(side,length)
        if self.rev_warning_active:
            if actual!=self.rev_warning_side:
                self.rev_confirmed=True
                logger.info(f"REV CONFIRMED: {self.rev_warning_side} broke -> {actual} (prob={self.rev_warning_prob:.0%})")
            else:
                logger.info(f"REV false alarm: {side} streak continues at {length}")
            self.rev_warning_active=False; self.rev_warning_side=None; self.rev_warning_prob=0.0
        if prob>=REV_WARNING_THRESHOLD and not self.rev_warning_active:
            self.rev_warning_active=True; self.rev_warning_side=side; self.rev_warning_prob=prob
            logger.info(f"REV WARNING: {side} streak={length} prob={prob:.0%}")

    def _get_reversal_signal(self):
        side,length=self._get_current_streak()
        if side is None: return None,None,''
        prob=self._get_rev_prob(side,length)
        opposite='S' if side=='B' else 'B'
        if self.rev_confirmed:
            return opposite,'REV',f"\u2705Rev:{int(prob*100)}%"
        if self.rev_warning_active and self.rev_warning_prob>=REV_WARNING_THRESHOLD:
            return opposite,'WARN',f"\u26a0\ufe0fRev:{int(self.rev_warning_prob*100)}%"
        if prob<=MOM_THRESHOLD:
            return side,'MOM',"\U0001f525Mom"
        return None,None,''

    def login(self,max_retries=5):
        for attempt in range(max_retries):
            try:
                data={"language":0,"logintype":"mobile","phonetype":0,"pwd":PASSWORD,
                      "random":str(int(time.time()*1_000_000)),"username":LOGIN_ID}
                r=requests.post(f"{API_BASE}/Login",json=self._create_sig(data),
                    headers={'Content-Type':'application/json','Referer':'https://www.6lottery.com/'},timeout=15)
                result=r.json()
                if result.get('code')==0 and result.get('data'):
                    self.auth_token=result['data']['token']; logger.info("Login OK"); return True
                logger.warning(f"Login failed: {result.get('message','?')}")
            except Exception as e: logger.warning(f"Login error ({attempt+1}): {e}")
            time.sleep(3)
        return False

    def bootstrap_history(self):
        if self.bootstrapped: logger.info("Already bootstrapped."); return True
        logger.info("Bootstrapping 500 historical results...")
        if not self.auth_token and not self.login():
            logger.warning("Bootstrap: login failed — sending Telegram alert")
            self.send_msg(f"⚠️ {VERSION} Bootstrap failed: login error. Running in Phase 1.")
            return False
        all_results=[]
        try:
            params={"pageSize":500,"pageNo":1,"typeId":13,"language":0,"random":str(int(time.time()*1_000_000))}
            r=requests.post(f"{API_BASE}/GetTRXNoaverageEmerdList",json=self._create_sig(params),
                headers={'Content-Type':'application/json','Authorization':f'Bearer {self.auth_token}','Referer':'https://www.6lottery.com/'},timeout=30)
            result=r.json()
            if result.get('code')==0 and result.get('data'): all_results=result['data']['data']['gameslist']
        except Exception as e: logger.warning(f"Bootstrap error: {e}")
        if len(all_results)<100:
            all_results=[]
            for page in range(1,11):
                try:
                    params={"pageSize":50,"pageNo":page,"typeId":13,"language":0,"random":str(int(time.time()*1_000_000))}
                    r=requests.post(f"{API_BASE}/GetTRXNoaverageEmerdList",json=self._create_sig(params),
                        headers={'Content-Type':'application/json','Authorization':f'Bearer {self.auth_token}','Referer':'https://www.6lottery.com/'},timeout=15)
                    result=r.json()
                    if result.get('code')==0 and result.get('data'):
                        games=result['data']['data']['gameslist']
                        if not games: break
                        all_results.extend(games)
                        if len(all_results)>=500: break
                    else: break
                    time.sleep(0.5)
                except Exception as e: logger.warning(f"Bootstrap page {page} error: {e}"); break
        if not all_results:
            logger.warning("Bootstrap: no data")
            self.send_msg(f"⚠️ {VERSION} Bootstrap: no historical data. Running in Phase 1.")
            return False
        all_results=list(reversed(all_results))[-500:]
        parsed=[]
        for g in all_results:
            try:
                num=int(g.get('number',-1))
                if num>=0: parsed.append('B' if num>=5 else 'S')
            except: continue
        if len(parsed)<50:
            logger.warning("Bootstrap: not enough results")
            self.send_msg(f"⚠️ {VERSION} Bootstrap: only {len(parsed)} results. Running in Phase 1.")
            return False
        self.result_history=parsed[-ROLLING_MAX:]; self.total_results=len(self.result_history)
        self.bootstrapped=True; logger.info(f"Bootstrap done: {len(self.result_history)} results")
        self.calibrate(); self._save_state(); return True

    def _build_weighted_counts(self,hist,seq_len):
        n=len(hist); counts={}; cutoff=max(0,n-50)
        for i in range(n-seq_len):
            k=''.join(hist[i:i+seq_len]); nxt=hist[i+seq_len]; w=2.0 if i>=cutoff else 0.7
            if k not in counts: counts[k]={'B':0.0,'S':0.0}
            counts[k][nxt]+=w
        return counts

    def mini_calibrate(self,label="post-win"):
        hist=self.result_history[-MINI_RECAL_WINDOW:]
        if len(hist)<15: return
        logger.info(f"Mini-calibrate [{label}] n={len(hist)}")
        for seq_len in [3,4,5]:
            counts=self._build_weighted_counts(hist,seq_len); good={}
            conf_min_b=(SEQ3_CONF_B if seq_len==3 else SEQ4_CONF_B if seq_len==4 else SEQ5_CONF_B)
            conf_min_s=(SEQ3_CONF_S if seq_len==3 else SEQ4_CONF_S if seq_len==4 else SEQ5_CONF_S)
            for k,v in counts.items():
                total=v['B']+v['S']
                if total<1: continue
                cb,cs=v['B']/total,v['S']/total
                if cb>=conf_min_b: good[k]=('B',round(cb,4),int(total))
                elif cs>=conf_min_s: good[k]=('S',round(cs,4),int(total))
            key=str(seq_len); merged=dict(self.calibrated_patterns.get(key,{})); merged.update(good)
            self.calibrated_patterns[key]=merged
        self._save_state()

    def calibrate(self):
        hist=self.result_history; n=len(hist); logger.info(f"Calibrating {n} results...")
        new_patterns={}
        for seq_len,min_n in [(3,SEQ3_MIN_N),(4,SEQ4_MIN_N),(5,SEQ5_MIN_N)]:
            counts=self._build_weighted_counts(hist,seq_len); good={}
            conf_min_b=(SEQ3_CONF_B if seq_len==3 else SEQ4_CONF_B if seq_len==4 else SEQ5_CONF_B)
            conf_min_s=(SEQ3_CONF_S if seq_len==3 else SEQ4_CONF_S if seq_len==4 else SEQ5_CONF_S)
            for k,v in counts.items():
                total=v['B']+v['S']
                if total<min_n: continue
                cb,cs=v['B']/total,v['S']/total
                if cb>=conf_min_b: good[k]=('B',round(cb,4),int(total))
                elif cs>=conf_min_s: good[k]=('S',round(cs,4),int(total))
            new_patterns[str(seq_len)]=good
        streak_stats={}; cutoff=max(0,n-50)
        for streak_len in range(2,8):
            for side in ['B','S']:
                b_after=s_after=0.0; i=0
                while i<=n-streak_len-1:
                    if all(hist[i+j]==side for j in range(streak_len)):
                        nxt=hist[i+streak_len]; w=2.0 if i>=cutoff else 0.7
                        if nxt=='B': b_after+=w
                        else: s_after+=w
                        i+=streak_len
                    else: i+=1
                total=b_after+s_after
                if total>=2:
                    best='B' if b_after>s_after else 'S'; conf=max(b_after,s_after)/total
                    threshold=STREAK_CONF_B if best=='B' else STREAK_CONF_S
                    if conf>=threshold: streak_stats[f"{streak_len}{side}"]=(best,round(conf,4),int(total))
        new_patterns['streak']=streak_stats
        best_w=ANTI_MOM_W; best_acc=0.0
        for w in range(5,20):
            correct=total=0
            for i in range(w,n):
                window=hist[i-w:i]; b_cnt=window.count('B')
                if b_cnt>w/2: pred='S'
                elif b_cnt<w/2: pred='B'
                else: continue
                total+=1
                if pred==hist[i]: correct+=1
            if total>0:
                acc=correct/total
                if acc>best_acc: best_acc,best_w=acc,w
        new_patterns['best_anti_w']=best_w; new_patterns['best_anti_acc']=round(best_acc,4)
        new_patterns['b_pct']=round(hist.count('B')/n*100,2) if n>0 else 50.0
        new_patterns['s_pct']=round(hist.count('S')/n*100,2) if n>0 else 50.0
        rev_points={}
        for side in ['B','S']:
            for streak_len in range(1,9):
                reversed_count=total_count=0
                for i in range(n-streak_len-1):
                    if all(hist[i+j]==side for j in range(streak_len)) and (i==0 or hist[i-1]!=side):
                        total_count+=1
                        if hist[i+streak_len]!=side: reversed_count+=1
                if total_count>=3: rev_points[f"{side}{streak_len}"]=round(reversed_count/total_count,4)
        new_patterns['rev_points']=rev_points
        self.calibrated_patterns=new_patterns; self.last_calibration_at=self.total_results
        self._save_state(); logger.info(f"Calibration done! B={new_patterns['b_pct']}% S={new_patterns['s_pct']}%")

    def _should_calibrate(self):
        n=self.total_results
        if n<PHASE2_START: return False
        since=n-self.last_calibration_at
        return since>=(RECAL_P3 if n>=PHASE3_START else RECAL_P2)

    def _get_phase(self):
        n=self.total_results
        if n>=PHASE3_START: return 3
        elif n>=PHASE2_START: return 2
        return 1

    def _seq_lookup(self,seq_len,caution=False):
        hist=self.result_history
        if len(hist)<seq_len: return None,0.0,0
        key=''.join(hist[-seq_len:]); pat=self.calibrated_patterns.get(str(seq_len),{})
        if caution:
            conf_min_b=(PW_SEQ3_CONF_B if seq_len==3 else PW_SEQ4_CONF_B if seq_len==4 else PW_SEQ5_CONF_B)
            conf_min_s=(PW_SEQ3_CONF_S if seq_len==3 else PW_SEQ4_CONF_S if seq_len==4 else PW_SEQ5_CONF_S)
        else:
            conf_min_b=(SEQ3_CONF_B if seq_len==3 else SEQ4_CONF_B if seq_len==4 else SEQ5_CONF_B)
            conf_min_s=(SEQ3_CONF_S if seq_len==3 else SEQ4_CONF_S if seq_len==4 else SEQ5_CONF_S)
        if key in pat:
            best,conf,cnt=pat[key]
            threshold=conf_min_b if best=='B' else conf_min_s
            if conf>=threshold: return best,conf,cnt
        return None,0.0,0

    def _streak_lookup(self,caution=False):
        hist=self.result_history
        if not hist: return None,0.0,0
        side=hist[-1]; streak=1
        for i in range(len(hist)-2,-1,-1):
            if hist[i]==side: streak+=1
            else: break
        pat=self.calibrated_patterns.get('streak',{})
        for sl in range(streak,1,-1):
            k=f"{sl}{side}"
            if k in pat:
                vote,conf,cnt=pat[k]
                if caution: threshold=PW_STREAK_CONF_B if vote=='B' else PW_STREAK_CONF_S
                else: threshold=STREAK_CONF_B if vote=='B' else STREAK_CONF_S
                if conf>=threshold and cnt>=2: return vote,conf,cnt
                break
        return None,0.0,0

    def _anti_momentum(self,games):
        w=self.calibrated_patterns.get('best_anti_w',ANTI_MOM_W)
        # FIX: guard against games shorter than window
        if not games or len(games)<w: w=min(ANTI_MOM_W,len(games)) if games else 0
        if w==0: return None,0.0
        try: b=sum(1 for i in range(w) if int(games[i].get('number',-1))>=5)
        except: return None,0.0
        acc=self.calibrated_patterns.get('best_anti_acc',0.55)
        if b>w/2: return 'S',acc
        elif b<w/2: return 'B',acc
        return None,0.0

    def predict(self,games):
        phase=self._get_phase(); n=self.total_results; w=len(self.result_history)
        caution=self.post_win_rounds>0
        if phase==1 or not self.calibrated_patterns:
            if not games or len(games)<ANTI_MOM_W:
                return None,'N',f"collecting {n}/{PHASE2_START}",''
            b=sum(1 for i in range(ANTI_MOM_W) if int(games[i].get('number',-1))>=5)
            if b>ANTI_MOM_W/2: pred='S'
            elif b<ANTI_MOM_W/2: pred='B'
            else: pred='S' if self.result_history and self.result_history[-1]=='B' else 'B'
            return pred,'AM',f"collecting {n}/{PHASE2_START}",''
        v5,c5,n5=self._seq_lookup(5,caution); v4,c4,n4=self._seq_lookup(4,caution)
        v3,c3,n3=self._seq_lookup(3,caution); vs,cs,ns=self._streak_lookup(caution)
        va,ca=self._anti_momentum(games)
        streak_switch_vote=None
        if caution and self.pre_win_loss_streak>=3 and self.last_win_side:
            streak_switch_vote='B' if self.last_win_side=='S' else 'S'
        seq_vote=seq_conf=seq_n=None; seq_mode='AM'
        if v5 and c5>=CONF_FLOOR: seq_vote,seq_conf,seq_n,seq_mode=v5,c5,n5,'S5'
        elif v4 and c4>=CONF_FLOOR: seq_vote,seq_conf,seq_n,seq_mode=v4,c4,n4,'S4'
        elif v3 and c3>=CONF_FLOOR: seq_vote,seq_conf,seq_n,seq_mode=v3,c3,n3,'S3'
        candidates=[]
        if seq_vote:
            base_w=BASE_WEIGHTS.get(seq_mode,2.5); dyn_w=self._get_predictor_weight(seq_mode)
            occ_m=0.5 if seq_n<5 else (0.8 if seq_n<15 else 1.0)
            candidates.append((seq_vote,base_w*dyn_w*occ_m*seq_conf,seq_mode))
        if vs and cs>=CONF_FLOOR:
            base_w=BASE_WEIGHTS['ST']; dyn_w=self._get_predictor_weight('ST')
            occ_m=0.5 if ns<5 else (0.8 if ns<15 else 1.0)
            candidates.append((vs,base_w*dyn_w*occ_m*cs,'ST'))
        if streak_switch_vote:
            candidates.append((streak_switch_vote,BASE_WEIGHTS['SW']*self._get_predictor_weight('SW'),'SW'))
        if va:
            candidates.append((va,BASE_WEIGHTS['AM']*self._get_predictor_weight('AM')*ca,'AM'))
        status=f"{n} w{w}"
        if not candidates:
            pred=va if va else ('S' if self.result_history and self.result_history[-1]=='B' else 'B')
            return pred,'AM',status,''
        votes_b=sum(wt for vote,wt,_ in candidates if vote=='B')
        votes_s=sum(wt for vote,wt,_ in candidates if vote=='S')
        total_v=votes_b+votes_s
        b_pct=self.calibrated_patterns.get('b_pct',50.0)
        if b_pct>52.0:
            bias_penalty=min((b_pct-50.0)*0.015,0.08)
            votes_b=votes_b*(1.0-bias_penalty)
        rev_dir,rev_tag,rev_suffix=self._get_reversal_signal()
        if rev_dir:
            if rev_tag=='REV': rev_weight=5.0
            elif rev_tag=='WARN': rev_weight=2.5
            elif rev_tag=='MOM': rev_weight=2.0
            else: rev_weight=0.0
            if rev_weight>0:
                if rev_dir=='B': votes_b+=rev_weight
                else: votes_s+=rev_weight
        if total_v>0 and abs(votes_b-votes_s)/total_v<0.15 and va and not rev_dir:
            return va,'AM',status,''
        if votes_b>votes_s: pred='B'
        elif votes_s>votes_b: pred='S'
        else: pred=max(candidates,key=lambda x:x[1])[0]
        if rev_tag=='REV': mode='REV'
        elif rev_tag=='MOM': mode='MOM'
        else:
            agreeing=[(v,wt,lbl) for v,wt,lbl in candidates if v==pred]
            mode=max(agreeing,key=lambda x:x[1])[2] if agreeing else 'AM'
            if caution and mode not in ('S5',): mode+='*'
        if pred=='B': self.pred_count_b+=1
        else: self.pred_count_s+=1
        self.rev_confirmed=False
        return pred,mode,status,rev_suffix

    def get_live_data(self,max_retries=5):
        if not self.auth_token and not self.login(): return None
        for attempt in range(max_retries):
            try:
                params={"pageSize":50,"pageNo":1,"typeId":13,"language":0,"random":str(int(time.time()*1_000_000))}
                r=requests.post(f"{API_BASE}/GetTRXNoaverageEmerdList",json=self._create_sig(params),
                    headers={'Content-Type':'application/json','Authorization':f'Bearer {self.auth_token}','Referer':'https://www.6lottery.com/'},timeout=15)
                result=r.json()
                if result.get('code')==0 and result.get('data'):
                    self.fail_count=0; return result['data']['data']['gameslist']
                elif result.get('code') in [4,5]:
                    self.auth_token=None
                    if self.login(): continue
            except Exception as e: logger.warning(f"Data error ({attempt+1}): {e}")
            time.sleep(3)
        self.fail_count+=1
        if self.fail_count>=2: self.auth_token=None; self.fail_count=0
        return None

    def send_msg(self,text,max_retries=3):
        for attempt in range(max_retries):
            try:
                r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    json={"chat_id":CHAT_ID,"text":text,"message_thread_id":TOPIC},timeout=15)
                resp=r.json()
                if resp.get('ok'): return True
                logger.warning(f"Telegram error ({attempt+1}): {resp.get('description','?')}")
            except requests.exceptions.Timeout:
                logger.warning(f"Telegram timeout ({attempt+1})"); time.sleep(3); continue
            except Exception as e: logger.warning(f"Telegram error ({attempt+1}): {e}")
            time.sleep(2)
        return False

    def _export_to_github(self):
        token=GITHUB_TOKEN
        if not token:
            logger.info("GitHub export skipped: GITHUB_TOKEN not set")
            return
        try:
            hist=self.result_history; n=len(hist); sc=hist.count('S'); bc=hist.count('B')
            max_s=max_b=cs2=cb2=0
            for r in hist:
                if r=='S': cs2+=1; cb2=0; max_s=max(max_s,cs2)
                else: cb2+=1; cs2=0; max_b=max(max_b,cb2)
            cur_side=hist[-1] if hist else '?'; cur_len=0
            for r in reversed(hist):
                if r==cur_side: cur_len+=1
                else: break
            last20=hist[-20:] if n>=20 else hist; l20s=last20.count('S'); l20b=last20.count('B')
            pred_acc={}
            for mode,log in self.predictor_log.items():
                if len(log)>=5:
                    correct=sum(1 for p,a in log if p==a)
                    pred_acc[mode]={'accuracy':round(correct/len(log),4),'total':len(log),'correct':correct}
            def top5(key):
                d={}
                for k,v in sorted(self.calibrated_patterns.get(key,{}).items(),key=lambda x:x[1][1],reverse=True)[:5]:
                    d[k]={'direction':v[0],'confidence':v[1],'count':v[2]}
                return d
            total_t=self.wins+self.losses_total; win_rate=round(self.wins/total_t*100,1) if total_t>0 else 0
            pred_total=self.pred_count_b+self.pred_count_s
            export={'version':VERSION,'exported_at':datetime.datetime.utcnow().isoformat()+'Z',
                    'last_sent_sig':self.last_sent_sig,'last_sent_time':self.last_sent_time,
                    'phase':self._get_phase(),'total_results':self.total_results,'rolling_window':n,
                    'wins':self.wins,'losses_total':self.losses_total,'win_rate_pct':win_rate,
                    'consecutive_losses':self.consecutive_losses,
                    'prediction_distribution':{'b_predictions':self.pred_count_b,'s_predictions':self.pred_count_s,
                        'b_pred_pct':round(self.pred_count_b/pred_total*100,1) if pred_total>0 else 0},
                    'overall':{'small_count':sc,'big_count':bc,'small_pct':round(sc/n*100,1) if n else 0,'big_pct':round(bc/n*100,1) if n else 0},
                    'last20':{'results':''.join(last20),'small':l20s,'big':l20b,'small_pct':round(l20s/len(last20)*100,1) if last20 else 0},
                    'current_streak':{'side':cur_side,'length':cur_len},'max_streaks':{'max_small':max_s,'max_big':max_b},
                    'last10_results':''.join(hist[-10:]) if n>=10 else ''.join(hist),
                    'predictor_accuracy':pred_acc,
                    'top_patterns':{'seq3':top5('3'),'seq4':top5('4'),'seq5':top5('5'),'streak':top5('streak')},
                    'anti_momentum':{'best_window':self.calibrated_patterns.get('best_anti_w',10),'best_accuracy':self.calibrated_patterns.get('best_anti_acc',0)},
                    'bias_monitor':{'b_pct':self.calibrated_patterns.get('b_pct',50.0),'s_pct':self.calibrated_patterns.get('s_pct',50.0)},
                    'reversal_points':self.calibrated_patterns.get('rev_points',{})}
            export_json=json.dumps(export,indent=2); sha=None
            try:
                r=requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{EXPORT_FILE}",
                    headers={'Authorization':f'token {token}'},timeout=10)
                if r.status_code==200: sha=r.json().get('sha')
            except: pass
            payload={'message':f'{VERSION} export: {self.total_results} results W{self.wins}/L{self.losses_total} ({win_rate}%)',
                     'content':base64.b64encode(export_json.encode()).decode()}
            if sha: payload['sha']=sha
            r=requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{EXPORT_FILE}",
                headers={'Authorization':f'token {token}','Content-Type':'application/json'},json=payload,timeout=15)
            if r.status_code in (200,201): logger.info(f"GitHub export OK: {self.total_results} results W{self.wins}/L{self.losses_total}")
            else: logger.warning(f"GitHub export failed: {r.status_code}")
        except Exception as e: logger.warning(f"GitHub export error: {e}")

    def run(self):
        logger.info(f"Wave Up Bot {VERSION} Running...")
        while True:
            try:
                games=self.get_live_data()
                if not games or len(games)<ANTI_MOM_W: time.sleep(10); continue
                latest=games[0]
                try:
                    raw_issue=str(latest.get('issueNumber','')); issue=normalize_issue(raw_issue)
                    current_num=int(latest.get('number',-1))
                except: time.sleep(5); continue
                if current_num<0: time.sleep(5); continue
                if self.last_issue==issue: time.sleep(5); continue
                actual='B' if current_num>=5 else 'S'
                logger.info(f"Trx {issue}: {current_num}({actual})")
                if (self.last_pred_issue and normalize_issue(self.last_pred_issue)==issue and self.last_prediction):
                    self._add_result(actual); self._log_prediction(self.last_prediction,actual)
                    if self.last_pred_mode: self._log_predictor(self.last_pred_mode,self.last_prediction,actual)
                    self._update_reversal_state(actual)
                    if self.last_prediction==actual:
                        self.pre_win_loss_streak=self.consecutive_losses; self.last_win_side=actual
                        self.consecutive_losses=0; self.bet_counter=0; self.post_win_rounds=POST_WIN_ROUNDS
                        self.wins+=1
                        if self.last_sent_win!=issue:
                            win_sent=self.send_msg("\U0001f308\U0001f3c6\U0001f947W I N\U0001f37e\U0001f37a\U0001f943\U0001f377\U0001f378\U0001f379\U0001f37b\U0001f942")
                            if win_sent: self.last_sent_win=issue
                        self.mini_calibrate(label="post-win")
                    else:
                        self.consecutive_losses+=1; self.losses_total+=1
                        if self.post_win_rounds>0: self.post_win_rounds-=1
                        self._check_accuracy_floor()
                    self.last_prediction=None; self.last_pred_issue=None; self.last_pred_mode=None
                    if self._should_calibrate(): self.calibrate()
                    self._save_state()
                next_issue_full=normalize_issue(str(int(issue)+1))
                now=time.time()
                if self.last_sent_sig==next_issue_full:
                    logger.info(f"Already sent {next_issue_full[-3:]}, skip")
                    self.last_issue=issue; self._save_state(); time.sleep(5); continue
                if (now-self.last_sent_time)<SIGNAL_COOLDOWN:
                    logger.info(f"Cooldown {now-self.last_sent_time:.0f}s, skip")
                    self.last_issue=issue; self._save_state(); time.sleep(5); continue
                prediction,mode,status,rev_suffix=self.predict(games)
                if prediction is None:
                    self.last_issue=issue; self._save_state(); time.sleep(5); continue
                pred_text="BIG" if prediction=='B' else "SMALL"
                next_issue=next_issue_full[-3:]; self.bet_counter=self.consecutive_losses+1
                line1=f"\U0001f3afTrx {next_issue} \u2708\ufe0f {pred_text} {self.bet_counter} \u2708\ufe0f\U0001f340"
                line2=f"\U0001f4ca Wave Up {{{mode}}} [{status}]"
                if rev_suffix: line2+=f" {rev_suffix}"
                signal_msg=f"{line1}\n{line2}"
                sent=self.send_msg(signal_msg)
                if sent:
                    self.last_sent_sig=next_issue_full; self.last_sent_time=now
                    self.last_prediction=prediction; self.last_pred_issue=next_issue_full
                    self.last_pred_mode=mode
                    logger.info(f"Signal: Trx {next_issue} {pred_text} [{mode}] W{self.wins}/L{self.losses_total}")
                self.last_issue=issue; self._save_state(); time.sleep(5)
            except KeyboardInterrupt: logger.info("Stopped"); raise
            except Exception as e: logger.error(f"Loop error: {e}"); time.sleep(10)

def main():
    bot=WaveUpBot()
    try:
        if not bot.bootstrap_history(): logger.warning("Bootstrap failed, continuing in Phase 1")
    except Exception as e: logger.warning(f"Bootstrap exception: {e}")
    bot.run()

if __name__=="__main__":
    main()
