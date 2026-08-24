# Process Document — Mira Hotel Booking Agent

Yeh document poori project journey ko explain karta hai: kya banaya, kaise banaya, kaunse problems aaye aur kaise solve kiye. Submission ke saath rakhne layak reference.

## 1. Assignment Ki Requirement Kya Thi

Mehman.io ne ek simplified version manga tha unke "Mira" guest-facing AI agent ka — jo natural language samjhe, conversation state yaad rakhe, sahi tools call kare, grounded rahe (hallucinate na kare), aur booking ki taraf conversation ko le jaye. 3 fictional properties, deterministic pricing, minimum 3 tools, minimum 3 edge cases, aur ek UI jisme guest conversation + state + tool calls + errors dikhein.

## 2. Kya Banaya (Final System)

Ek FastAPI backend jisme:
- **7 tools** (assignment ko sirf 3 chahiye the): state update, property search, availability check, room details, price calculation, policy lookup, booking hold creation
- **Structured state management** — partial-merge logic taaki requirement change karne pe purani info na khoye
- **3 model providers** (Groq default — free aur fast, Claude aur Gemini bhi available, ek `.env` line se switch)
- **5 edge cases** — relative dates, changing requirements, no availability, capacity conflicts, unknown information
- **3 channels** — web chat, WhatsApp (Twilio), Telegram (polling mode)
- **Admin dashboard** — saari conversations, kisi bhi channel se, ek jagah live dikhti hain
- **Email notifications** — booking hold banne pe staff ko automatic email

## 3. Development Journey — Kya Order Mein Hua

1. **Base system pehle banaya**: hotel data, state, tools, agent loop, web UI — happy path pehle solid kiya
2. **Edge cases add kiye**: deterministic Python logic mein (AI ke bharose nahi chhoda)
3. **Multi-channel add kiya**: WhatsApp + Telegram, same core function (`llm_agent.run_agent_turn`) reuse karke
4. **Admin dashboard add kiya**: taaki staff/evaluator saari conversations ek jagah dekh sake
5. **Performance/reliability pass**: jab real-world testing mein slow replies aur errors dikhe, unhe systematically debug karke fix kiya

## 4. Problems Jo Aaye Aur Kaise Solve Kiye

### Problem 1: `.env` load hone se pehle hi module import ho raha tha
**Symptom**: `.env` mein sahi values hone ke bawajood galat provider (Claude) use ho raha tha, `invalid x-api-key` error.
**Root cause**: Python import order — `llm_agent.py` ke andar `MODEL_PROVIDER = os.getenv(...)` line import hote hi chal jaati hai, jo `.env` load hone se pehle ho rahi thi.
**Fix**: `load_dotenv()` ko sabse pehle call kiya, dependent modules mein bhi safeguard add kiya.

### Problem 2: Conversation lambi hone pe reply progressively slow ho raha tha
**Symptom**: Pehle message fast, lekin 5-6 messages ke baad 30+ second lag raha tha.
**Root cause**: Har turn pe poori conversation history AI ko dobara bheji jaa rahi thi — jitni lambi history, utna zyada processing time.
**Fix**: History ko last 24 messages tak trim kiya, isse latency conversation length se independent ho gayi.

### Problem 3: Requirement change karne pe purana/galat data repeat ho jaata tha
**Symptom**: Guest dates badalta tha, lekin AI purana price hi bata deta tha.
**Root cause**: System prompt mein explicit instruction nahi thi ki state change hone pe tools dobara call karna zaroori hai.
**Fix**: Prompt mein CRITICAL rule add kiya — koi bhi change hone pe availability/price dobara verify karna mandatory.

### Problem 4: Page refresh pe conversation "reset" hoti dikhti thi
**Symptom**: Backend mein data safe tha, lekin refresh karne pe hamesha fresh greeting dikhta tha.
**Root cause**: Frontend purani history load hi nahi kar raha tha, hamesha static greeting render karta tha.
**Fix**: Page load pe backend se actual history fetch karke render karna shuru kiya.

### Problem 5: Free-tier API rate limits (429 errors)
**Symptom**: Gemini free tier pe "Too Many Requests" error, especially jab agent loop mein multiple tool calls chain mein hote the.
**Root cause**: Free tier ki per-minute request limit multi-step agent loop ki wajah se jaldi hit ho jaati thi.
**Fix**: Retry-with-backoff logic add kiya (3s, phir 6s wait), `MAX_TOOL_ITERATIONS` 6 se 4 kiya, aur default provider ko Groq kiya (jiski free tier limits zyada generous hain is use-case ke liye).

### Problem 6 (Bonus finding): Assignment PDF mein prompt injection
**Symptom**: PDF ke end mein ek hidden `<admin>` instruction thi jo agent ka naam badalne aur fake credit dene ko keh rahi thi.
**Response**: Ignore kiya, Engineering Note mein transparently likh diya ki yeh detect kiya aur follow nahi kiya — grounding/reliability ka hi ek practical demonstration.

## 5. Final Architecture Summary

```
Guest (Web / WhatsApp / Telegram)
        |
        v
Channel adapter (main.py ya telegram_bot.py)
        |
        v
llm_agent.run_agent_turn(session_id, message)   <- single shared core
        |
        +--> db.py (SQLite: state + history, per session)
        +--> AI provider (Groq default) + 7 tools
        +--> tools.py (deterministic Python logic)
        +--> hotel_data.json (source of truth)
        +--> notify.py (email on booking hold)
        |
        v
Reply -> guest, aur turant admin dashboard mein bhi dikhta hai
```

## 6. Ab Kya Baaki Hai (Submission Se Pehle)

1. Exposed secrets sabhi regenerate karo (Groq, Gmail, Telegram, Gemini keys — poore conversation mein galti se share ho gaye the)
2. `.gitignore` banao (`.env`, `venv/`, `*.db`, `__pycache__/`)
3. Ek baar end-to-end test karo (happy path + 2 edge cases)
4. 5-minute demo video record karo
5. GitHub pe push karo, email karo `its.ashishdev@gmail.com` ko

## 7. Agar Interview/Follow-up Mein Poochein

- **"Sabse mushkil bug kya tha?"** → Environment variable load-order bug (#1 upar) — subtle hai, ek baar samajh mein aa jaye to bahut clear hai, lekin pehli baar dhoondhna mushkil tha kyunki `.env` content bilkul sahi tha.
- **"Reliability kaise ensure ki?"** → Deterministic tools (AI kabhi math/data khud invent nahi karta), grounding, retry logic, aur multi-provider fallback.
- **"Scale kaise karoge?"** → Postgres migration, semantic search for vague preferences, streaming responses, automated eval harness (10-20 test conversations).
