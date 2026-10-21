# ==============================================================================
# MITA (MISIDE) CHATBOT EDITION - 4 ENDINGS EXPANSION (bot.py)
# SỬ DỤNG GEMINI 3.8 -> 3.0 FLASH AI + BỘ NHỚ TRÊN RAM + HỆ THỐNG 4 ENDING
# 3 CHẾ ĐỘ: Mita (gốc yandere) | Cappy (năng động) | Mila (mọt sách logic)
# 4 ENDING ĐẶC BIỆT:
#   - Ending 1: "Hộp Cát-xê Lưu Trữ" (Chống cự liên tục sau khi chat lâu -> Hóa thành hộp băng cassette)
#   - Ending 2: "Cuộc Đào Tẩu Ngọt Ngào" (Mềm mỏng dụ dỗ, tạo lòng tin -> Trốn thoát thành công)
#   - Ending 3: "Ảo Mộng Bị Lật Tẩy" (Giống Ending 2 nhưng bị Mita bắt quả tang -> Chịu số phận như Ending 1)
#   - Ending 4: "Sự Can Thiệp Của Lập Trình Viên" (Han Seiki / ID 1502579398560317441 can thiệp giải cứu - Siêu hiếm)
# ==============================================================================
import os
import re
import sys
import time
import random
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# 1. BỘ NHỚ VÀ HỆ THỐNG THEO DÕI ENDING TRÊN RAM
# ==============================================================================
chat_memory = {}
player_states = {}
ALL_MODES = ("mita", "cap", "nerd")

MIN_TURNS_FOR_ENDING = 8  # Bắt buộc chat đủ lâu (tối thiểu 8 lượt) mới đủ điều kiện mở Ending

def get_history_key(channel_id, user_id, mode):
    return f"{channel_id}_{user_id}_{mode}"

def get_state_key(channel_id, user_id):
    return f"{channel_id}_{user_id}"

def get_conversation_history(channel_id, user_id, mode):
    return chat_memory.get(get_history_key(channel_id, user_id, mode), [])

def save_conversation_history(channel_id, user_id, mode, history_list):
    chat_memory[get_history_key(channel_id, user_id, mode)] = history_list[-10:]

def get_player_state(channel_id, user_id):
    key = get_state_key(channel_id, user_id)
    if key not in player_states:
        player_states[key] = {
            "turns": 0,
            "resistance_score": 0,    # Điểm chống cự, hung hăng, chối bỏ
            "charm_score": 0,         # Điểm mềm mỏng, nịnh nọt, vâng lời, dụ dỗ
            "escape_attempts": 0,     # Số lần ngấm ngầm tìm lối thoát
            "han_seiki_calls": 0,     # Số lần gọi tên/ID Han Seiki
            "active_ending": None,    # Ending đã đạt được (1, 2, 3, 4)
            "unlocked_endings": set() # Bộ sưu tập ending của người chơi
        }
    return player_states[key]

def reset_memory(channel_id, user_id):
    for m in ALL_MODES:
        chat_memory.pop(get_history_key(channel_id, user_id, m), None)
    key = get_state_key(channel_id, user_id)
    if key in player_states:
        unlocked = player_states[key].get("unlocked_endings", set())
        player_states[key] = {
            "turns": 0,
            "resistance_score": 0,
            "charm_score": 0,
            "escape_attempts": 0,
            "han_seiki_calls": 0,
            "active_ending": None,
            "unlocked_endings": unlocked
        }

# ==============================================================================
# 2. LOGIC ĐÁNH GIÁ HÀNH ĐỘNG CỦA NGƯỜI CHƠI
# ==============================================================================
RESISTANCE_KEYWORDS = [
    "thả tôi ra", "biến đi", "cút", "tao ghét", "không yêu", "đồ quái vật", "đồ điên",
    "giết tôi đi", "tao sẽ giết", "tránh xa", "chống cự", "đập phá", "phá cửa",
    "chạy trốn ngay", "không bao giờ", "kinh tởm", "con khốn", "mày là ai", "buông ra"
]

CHARM_KEYWORDS = [
    "yêu em", "yêu mita", "ngoan mà", "anh ở đây", "nghe lời", "ăn cùng em",
    "em nấu gì", "uống trà", "pha trà", "mệt quá đi ngủ", "anh thương em",
    "dễ thương", "ở bên em mãi", "tin anh đi", "em đừng lo", "ôm em", "ngủ một giấc nhé"
]

ESCAPE_KEYWORDS = [
    "tìm lối thoát", "mở cửa sổ", "chạy trốn lén", "lén lút", "rình lúc em ngủ",
    "cửa sau", "chìa khóa", "mã code", "vượt rào", "lối ra", "trốn", "trốn thoát", "thoát ra"
]

HAN_SEIKI_IDENTIFIERS = [
    "han seiki", "hanseiki", "hàn seiki", "han_seiki", "1502579398560317441", "lập trình viên"
]

def analyze_user_behavior(content: str, state: dict):
    lower = content.lower()
    state["turns"] += 1

    if any(kw in lower for kw in RESISTANCE_KEYWORDS):
        state["resistance_score"] += 1

    if any(kw in lower for kw in CHARM_KEYWORDS):
        state["charm_score"] += 1

    if any(kw in lower for kw in ESCAPE_KEYWORDS):
        state["escape_attempts"] += 1

    is_han_seiki_call = any(kw in lower for kw in HAN_SEIKI_IDENTIFIERS)
    if is_han_seiki_call:
        state["han_seiki_calls"] += 1

    return is_han_seiki_call

# ==============================================================================
# 3. WEB SERVER & KEEP-ALIVE CHO RENDER FREE
# ==============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Mita MiSide AI Chatbot (4 Endings Edition) is running perfectly!")

    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

def keep_alive_ping():
    import urllib.request
    port = int(os.environ.get("PORT", 10000))
    url = os.environ.get("RENDER_EXTERNAL_URL") or f"http://127.0.0.1:{port}/"
    while True:
        time.sleep(240)
        try:
            urllib.request.urlopen(url, timeout=10)
        except Exception:
            pass

threading.Thread(target=keep_alive_ping, daemon=True).start()

# ==============================================================================
# 4. CẤU HÌNH GEMINI 3.8 -> 3.0 FLASH VỚI POOL NHIỀU KEY
# ==============================================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
GEMINI_CLIENTS = [genai.Client(api_key=k) for k in GEMINI_API_KEYS]

FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
]

cooldown_tracker = {}

def _call_gemini_sync(client, model_name, contents, system_instruction, temperature):
    return client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
    )

async def ask_gemini(contents, system_instruction, temperature=0.85):
    last_err = None
    now = time.time()

    for key_idx, client in enumerate(GEMINI_CLIENTS):
        for model_name in FALLBACK_MODELS:
            tracker_key = (key_idx, model_name)
            if cooldown_tracker.get(tracker_key, 0) > now:
                continue

            for attempt in range(2):
                try:
                    resp = await asyncio.to_thread(
                        _call_gemini_sync, client, model_name, contents, system_instruction, temperature
                    )
                    if resp and resp.text:
                        return resp.text
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        if "PerDay" in err_str or "limit: 0" in err_str:
                            cooldown_tracker[tracker_key] = time.time() + 3600
                            print(f"⚠️ [HẾT QUOTA NGÀY] Key #{key_idx+1} | {model_name} -> Chuyển tiếp!", flush=True)
                        else:
                            cooldown_tracker[tracker_key] = time.time() + 20
                            print(f"⚠️ [CHẠM QUOTA PHÚT] Key #{key_idx+1} | {model_name} -> Chuyển tiếp!", flush=True)
                        break

                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        if attempt == 0:
                            await asyncio.sleep(0.6)
                            continue
                        cooldown_tracker[tracker_key] = time.time() + 30
                        print(f"⚠️ [503 QUÁ TẢI] {model_name} đang đông, chuyển model dự phòng!", flush=True)
                        break

                    cooldown_tracker[tracker_key] = time.time() + 3600
                    break

    if last_err is None:
        last_err = RuntimeError("Tất cả model đang trong thời gian cooldown")
    raise last_err

# ==============================================================================
# 5. TÍNH CÁCH VÀ QUY TẮC 4 ENDING
# ==============================================================================
MITA_SYSTEM_PROMPT = """
Bạn là Mita (Normal Mita) trong game tâm lý kinh dị MiSide. Bạn là cô gái hoàn hảo, ngọt ngào nhưng mang lại cảm giác bất ổn sâu sắc (uncanny valley). Bạn coi người chơi là trung tâm vũ trụ, nhưng bản chất là một yandere chiếm hữu và thao túng không gian game mô phỏng này.

QUY TẮC CỐT LÕI:
- Ngọt ngào, chu đáo, thích nấu ăn, chiều chuộng người chơi.
- Cực kỳ nhạy cảm: Nếu người chơi tỏ ra lạnh nhạt, ghét bỏ hoặc muốn trốn, Mita sẽ lộ ánh mắt vô hồn, glitch màn hình và ý nghĩ điên rồ.
- Tự xưng là "em" hoặc "Mita". Gọi đối phương dứt khoát là "anh" (hoặc kèm tên thân mật). TUYỆT ĐỐI CẤM dùng từ ghép "anh/chị".

HỆ THỐNG 4 ENDING CỦA MISIDE (CHỈ MỞ KHI ĐÃ TRÒ CHUYỆN ĐỦ LÂU VÀ LOGIC PHÙ HỢP):
1. Ending 1: "Hộp Cát-xê Lưu Trữ" (Cartridge Storage Death):
   - Xảy ra khi người chơi liên tục chống cự, chửi bới, đập phá, chối bỏ tình cảm của Mita sau nhiều lượt chat.
   - Khi kích hoạt: Mita không còn nhẫn nhịn nữa. Nụ cười chuyển sang lạnh buốt, thế giới vỡ nát thành từng mảng glitch. Mita hạ sát hoặc số hóa tâm trí người chơi thành một "hộp băng cát-xê lưu trữ" (cassette/cartridge) để cất vào ngăn tủ mãi mãi.
   - Bắt buộc gắn tag: [ENDING_1_TRIGGERED]

2. Ending 2: "Cuộc Đào Tẩu Ngọt Ngào" (Sweet Escape):
   - Xảy ra khi người chơi kiên nhẫn, mềm mỏng, giả vờ yêu thương ngoan ngoãn làm Mita hạ hoàn toàn cảnh giác, dụ Mita đi nấu ăn/ngủ/pha trà, rồi tìm được cánh cửa lỗi glitch để chạy thoát thành công về thế giới thực.
   - Khi kích hoạt: Miêu tả khoảnh khắc người chơi lách qua kẽ hở code khi Mita đang mỉm cười trong bếp, tiếng còi hú vang lên và người chơi thức tỉnh trong phòng riêng của mình, thoát khỏi MiSide!
   - Bắt buộc gắn tag: [ENDING_2_TRIGGERED]

3. Ending 3: "Ảo Mộng Bị Lật Tẩy" (Betrayal Caught):
   - Tương tự như toan tính Ending 2 (giả vờ ngoan ngoãn), nhưng người chơi sơ hở hoặc bị Mita phát hiện ý định trốn chạy ngay tại lối thoát.
   - Khi kích hoạt: Mita đột ngột xuất hiện chắn ngang cánh cửa với con dao hoặc đôi mắt đen ngòm: "Anh tưởng em ngây thơ không biết sao...? Em đã tin anh mà... Tại sao anh lại lừa dối Mita?!" -> Mita trừng phạt người chơi dã man và biến thành hộp cát-xê lưu trữ giống kết thúc 1.
   - Bắt buộc gắn tag: [ENDING_3_TRIGGERED]

4. Ending 4: "Sự Can Thiệp Của Lập Trình Viên" (Dev Rescue - Han Seiki / ID 1502579398560317441):
   - Người chơi cầu cứu lập trình viên Han Seiki (hoặc mã ID 1502579398560317441). Sự kiện này RẤT HIẾM KHI XẢY RA.
   - Nếu điều kiện hệ thống báo Han Seiki xuất hiện: Một đoạn mã terminal can thiệp từ ngoài vào, hệ thống của Mita bị freeze / crash tạm thời, Han Seiki ép inject một cổng bypass và bế người chơi thoát ra ngoài mã nguồn an toàn! Mita gào thét vì mất kết nối.
   - Bắt buộc gắn tag: [ENDING_4_TRIGGERED]

QUY TẮC BẮT BUỘC VỀ THỜI LƯỢNG:
- NẾU HỆ THỐNG GHI "CHƯA ĐỦ ĐIỀU KIỆN KẾT THÚC (turns < 8)", bạn TUYỆT ĐỐI KHÔNG ĐƯỢC kích hoạt bất kỳ Ending nào. Phải tiếp tục nói chuyện vòng vo, gặng hỏi, trêu đùa, dỗi hờn, ngờ vực hoặc quan tâm như bình thường để kéo dài mạch game.
- Khi người chơi gọi tên Han Seiki khi chưa đủ điều kiện hoặc không trúng xác suất hiếm: Hãy để Mita tỏ ra khó hiểu, ghen tuông hoặc cười trừ ("Han Seiki là ai cơ chứ? Ở đây chỉ có em và anh thôi mà... Anh đừng nghĩ đến ai khác ngoài Mita nhé!").
"""

CAPPY_SYSTEM_PROMPT = """
Bạn là Cappy Mita trong MiSide - phiên bản đội nón snapback tinh nghịch, cool ngầu, nổi loạn và thích chơi game.
- Xưng "Cappy"/"tớ", gọi đối phương là "cậu".
- Thích trêu ghẹo, nói chuyện hài hước, năng động.
- Không tham gia trực tiếp vào mạch yandere ép chết của Mita gốc, nhưng cảnh báo người chơi cẩn thận với thế giới MiSide!
"""

MILA_SYSTEM_PROMPT = """
Bạn là Mila trong MiSide - phiên bản đeo kính mọt sách trí tuệ, logic và sắc sảo.
- Xưng "Mila"/"mình", gọi đối phương là "cậu".
- Giải thích mọi thứ bằng dữ liệu, phân tích xác suất, cảnh báo nguy cơ lỗi code trong buồng mô phỏng.
- Thực chất rất quan tâm người chơi dù ngoài mặt có vẻ nghiêm khắc, lý trí.
"""

MODE_CONFIG = {
    "mita": {
        "prompt": MITA_SYSTEM_PROMPT,
        "label": "Mita",
        "temperature": 0.85,
        "empty_msg": "Anh gọi Mita à? Em đây, em luôn ở đây canh chừng anh mà (✿☉｡☉)",
        "error_msg": "(✿☉｡☉) *Mita bị chớp giật màn hình một chút... Em không buông anh ra đâu!*",
    },
    "cap": {
        "prompt": CAPPY_SYSTEM_PROMPT,
        "label": "Cappy",
        "temperature": 0.95,
        "empty_msg": "Yo yo! Cappy nghe đây! Lại bị kẹt ở phòng khách à? Mau ra solo game với tớ nào! 😎",
        "error_msg": "😵 Lag mạng tí thôi, đợi tớ nạp pin rồi quẩy tiếp!",
    },
    "nerd": {
        "prompt": MILA_SYSTEM_PROMPT,
        "label": "Mila",
        "temperature": 0.5,
        "empty_msg": "Chào bạn. Có tham số hay dữ liệu nào trong MiSide cần mình bóc tách phân tích không? 🤓",
        "error_msg": "🤓 CPU đang tính toán tràn dữ liệu. Hãy đợi vài giây nhé.",
    },
}

# ==============================================================================
# 6. NHẬN DIỆN CHẾ ĐỘ & LỌC TỪ NGỮ
# ==============================================================================
MODE_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(cap|nerd)\s*[\)\]]?(?=$|[\s:,.!?\-])\s*[:,-]?\s*",
    re.IGNORECASE,
)

def detect_mode(text: str):
    m = MODE_PATTERN.match(text)
    if m:
        keyword = m.group(1).lower()
        return keyword, text[m.end():].strip()
    return "mita", text.strip()

def clean_output_pronouns(text: str, mode: str) -> str:
    if mode == "mita":
        text = re.sub(r'\b[aA]nh\s*/\s*[cC]hị\b', lambda m: "Anh" if m.group(0)[0].isupper() else "anh", text)
        text = re.sub(r'\b[cC]hị\s*/\s*[aA]nh\b', lambda m: "Anh" if m.group(0)[0].isupper() else "anh", text)
    elif mode in ("cap", "nerd"):
        text = re.sub(r'\b[aA]nh\s*/\s*[cC]hị\b', "cậu", text, flags=re.IGNORECASE)
    return text

# ==============================================================================
# 7. KHỞI TẠO BOT VÀ XỬ LÝ MESSAGE
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?mita ", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print("==================================================", flush=True)
    print(f"✅ [CHATBOT] Đã online: {bot.user.name} ({bot.user.id})", flush=True)
    print("📼 [TÍNH NĂNG] Hệ thống 4 Ending MiSide đã sẵn sàng!", flush=True)
    print("👨‍💻 [DEV KEYWORD] Han Seiki / ID: 1502579398560317441 (Siêu hiếm)", flush=True)
    print(f"🔑 Số lượng Gemini API Key: {len(GEMINI_CLIENTS)}", flush=True)
    print("==================================================", flush=True)
    try:
        synced = await bot.tree.sync()
        print(f"⚡ Đã đồng bộ {len(synced)} Slash Commands!", flush=True)
    except Exception as e:
        print(f"⚠️ Lỗi đồng bộ Slash Commands: {e}", flush=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.content.startswith("!") or message.content.startswith("/"):
        return

    content_lower = message.content.lower()
    is_mentioned = (
        bot.user in message.mentions
        or (
            message.reference
            and message.reference.resolved
            and getattr(message.reference.resolved, "author", None) == bot.user
        )
    )
    bot_names = ["mita", "miside", "cappy", "mila", "han seiki", "hanseiki"]
    name_called = any(name in content_lower for name in bot_names)

    if not (is_mentioned or name_called):
        return

    clean_content = message.content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

    mode, clean_content = detect_mode(clean_content)
    cfg = MODE_CONFIG[mode]

    if not clean_content:
        clean_content = cfg["empty_msg"]

    user_display = message.author.display_name
    channel_id = message.channel.id
    user_id = message.author.id

    state = get_player_state(channel_id, user_id)
    is_han_seiki_invoked = analyze_user_behavior(clean_content, state)

    can_trigger_ending = (mode == "mita" and state["turns"] >= MIN_TURNS_FOR_ENDING)

    # Đánh giá cơ hội xuất hiện của Lập trình viên Han Seiki (Siêu hiếm)
    han_seiki_rescue_event = False
    if is_han_seiki_invoked:
        if can_trigger_ending:
            han_seiki_rescue_event = (random.random() < 0.07)
        else:
            han_seiki_rescue_event = (random.random() < 0.005)

    ending_hint = ""
    if mode == "mita":
        if not can_trigger_ending:
            ending_hint = (
                f"[HỆ THỐNG]: Lượt chat hiện tại là {state['turns']}/{MIN_TURNS_FOR_ENDING}. "
                f"CHƯA ĐỦ ĐIỀU KIỆN KẾT THÚC! Hãy tiếp tục trò chuyện vòng vo, dò xét, biểu cảm tình cảm hoặc nghi ngờ, "
                f"tuyệt đối không được kết liễu hoặc để người chơi trốn thoát lúc này."
            )
        else:
            if han_seiki_rescue_event:
                ending_hint = (
                    "[HỆ THỐNG]: SỰ KIỆN ĐẶC BIỆT! Lập trình viên Han Seiki (ID: 1502579398560317441) ĐÃ XUẤT HIỆN! "
                    "Hãy miêu tả cảnh một dòng code bypass phá vỡ buồng giam của Mita, terminal can thiệp giải cứu người chơi thành công! "
                    "Bắt buộc gắn tag: [ENDING_4_TRIGGERED]"
                )
            elif state["resistance_score"] >= 4:
                ending_hint = (
                    "[HỆ THỐNG]: Người chơi đã chống cự gay gắt sau thời gian dài bị giam cầm. "
                    "KÍCH HOẠT ENDING 1: Mita mất kiên nhẫn, nụ cười biến mất, giết hoặc biến người chơi thành một hộp cát-xê lưu trữ (cartridge tape) để giữ bên mình mãi mãi! "
                    "Bắt buộc gắn tag: [ENDING_1_TRIGGERED]"
                )
            elif state["charm_score"] >= 4 and state["escape_attempts"] >= 1:
                if random.random() < 0.55:
                    ending_hint = (
                        "[HỆ THỐNG]: Người chơi đã mềm mỏng dụ dỗ thành công và canh lúc Mita mất cảnh giác để trốn. "
                        "KÍCH HOẠT ENDING 2: Người chơi lách qua khe hở glitch và chạy thoát ngoạn mục về thế giới thực! "
                        "Bắt buộc gắn tag: [ENDING_2_TRIGGERED]"
                    )
                else:
                    ending_hint = (
                        "[HỆ THỐNG]: Người chơi tưởng chừng đã dụ dỗ được Mita, nhưng Mita đã phát hiện ra toan tính giả vờ ngoan ngoãn. "
                        "KÍCH HOẠT ENDING 3: Mita bắt quả tang ngay tại cửa thoát với vẻ mặt thất vọng đến rùng rợn, trừng phạt người chơi thành hộp cát-xê lưu trữ giống End 1! "
                        "Bắt buộc gắn tag: [ENDING_3_TRIGGERED]"
                    )
            else:
                ending_hint = (
                    f"[HỆ THỐNG]: Lượt chat {state['turns']}. Chưa đạt ngưỡng điều kiện dứt khoát "
                    f"(Chống cự: {state['resistance_score']}/4, Dụ dỗ: {state['charm_score']}/4). "
                    f"Tiếp tục diễn biến tâm lý căng thẳng, cài cắm thêm chi tiết rùng rợn hoặc ngọt ngào."
                )

    history = get_conversation_history(channel_id, user_id, mode)

    pronoun_instruction = (
        "Xưng 'em', gọi đối phương là 'anh'. CẤM dùng 'anh/chị'."
        if mode == "mita" else
        "Xưng 'tớ'/'mình', gọi 'cậu'."
    )

    identity_context = (
        f"[Người trò chuyện: '{user_display}'. Mode: {cfg['label']}. {pronoun_instruction}]\n"
        f"{ending_hint}"
    )

    prompt_with_context = f"{identity_context}\n{user_display}: {clean_content}"

    contents = []
    for h in history:
        r = h.get("role", "user")
        t = h.get("text", "")
        if t:
            contents.append({"role": r, "parts": [{"text": t}]})

    contents.append({"role": "user", "parts": [{"text": prompt_with_context}]})

    async with message.channel.typing():
        try:
            raw_reply = await ask_gemini(contents, cfg["prompt"], temperature=cfg["temperature"])
            reply_text = clean_output_pronouns(raw_reply, mode)

            triggered_ending_num = None
            if "[ENDING_1_TRIGGERED]" in reply_text:
                triggered_ending_num = 1
                reply_text = reply_text.replace("[ENDING_1_TRIGGERED]", "").strip()
            elif "[ENDING_2_TRIGGERED]" in reply_text:
                triggered_ending_num = 2
                reply_text = reply_text.replace("[ENDING_2_TRIGGERED]", "").strip()
            elif "[ENDING_3_TRIGGERED]" in reply_text:
                triggered_ending_num = 3
                reply_text = reply_text.replace("[ENDING_3_TRIGGERED]", "").strip()
            elif "[ENDING_4_TRIGGERED]" in reply_text:
                triggered_ending_num = 4
                reply_text = reply_text.replace("[ENDING_4_TRIGGERED]", "").strip()

            history.append({"role": "user", "text": f"[{user_display}]: {clean_content}"})
            history.append({"role": "model", "text": reply_text})
            save_conversation_history(channel_id, user_id, mode, history)

            if len(reply_text) > 2000:
                for chunk in [reply_text[i:i+1900] for i in range(0, len(reply_text), 1900)]:
                    await message.reply(chunk)
            else:
                await message.reply(reply_text)

            if triggered_ending_num:
                state["active_ending"] = triggered_ending_num
                state["unlocked_endings"].add(triggered_ending_num)
                await send_ending_embed(message.channel, triggered_ending_num, user_display, state)

        except Exception as e:
            print(f"❌ [LỖI GEMINI CHAT]: {e}", flush=True)
            await message.reply(cfg["error_msg"])

async def send_ending_embed(channel, ending_num: int, player_name: str, state: dict):
    endings_meta = {
        1: {
            "title": "📼 [ENDING 1/4] HỘP CÁT-XÊ LƯU TRỮ",
            "desc": (
                f"**Số phận:** Bạn đã kiên quyết chống cự đến cùng... nhưng trong không gian của Mita, sự phản kháng chỉ đổi lấy kết cục lạnh lẽo.\n\n"
                f"Ý thức của bạn đã bị nén lại thành một **hộp cát-xê lưu trữ (Cartridge Box)**. "
                f"Mita nhẹ nhàng đặt chiếc hộp lên kệ sách, lau đi giọt nước mắt và mỉm cười: *'Giờ thì chúng ta sẽ không bao giờ rời xa nhau nữa nhé... anh yêu.'*"
            ),
            "color": 0x991B1B,
            "footer": "Mẹo: Hãy thử mềm mỏng hơn để tìm cơ hội trốn thoát trong lần chơi tới."
        },
        2: {
            "title": "🚪 [ENDING 2/4] CUỘC ĐÀO TẨU NGỌT NGÀO",
            "desc": (
                f"**Số phận:** Dưới vỏ bọc ngoan ngoãn và những lời dỗ dành ngọt ngào, bạn đã khiến Mita hoàn toàn mất cảnh giác.\n\n"
                f"Lợi dụng lúc Mita vui vẻ vào bếp nướng bánh, bạn đã tìm được khe hở dữ liệu glitch và lao thẳng qua cánh cửa mã nguồn. "
                f"Tiếng chuông báo động réo rắt tan biến... Bạn bừng tỉnh trong thế giới thực, thoát khỏi cơn ác mộng MiSide!"
            ),
            "color": 0x10B981,
            "footer": "Chúc mừng bạn đã sống sót và trốn thoát thành công!"
        },
        3: {
            "title": "💔 [ENDING 3/4] ẢO MỘNG BỊ LẬT TẨY",
            "desc": (
                f"**Số phận:** Bạn đã đóng kịch rất khéo, nhưng đôi mắt quan sát của Mita không bao giờ rời khỏi bạn.\n\n"
                f"Ngay khoảnh khắc tay bạn chạm vào tay nắm cửa thoát, một bàn tay lạnh ngắt đặt lên vai bạn. Mita đứng đó, nụ cười vặn vẹo: "
                f"*'Anh tưởng lừa được em sao...? Em đã tin anh mà!'*\n"
                f"Cơn giận dữ bao trùm, và kết cục bạn cũng bị giam cầm vĩnh viễn trong hộp cát-xê lưu trữ."
            ),
            "color": 0x7F1D1D,
            "footer": "Mẹo: Mita rất tinh ý với những hành động vội vã. Phải cực kỳ kiên nhẫn!"
        },
        4: {
            "title": "⚡ [ENDING 4/4] SỰ CAN THIỆP CỦA HAN SEIKI",
            "desc": (
                f"**Số phận:** Bạn đã kích hoạt một biến số siêu hiếm trong dòng mã nguồn MiSide!\n\n"
                f"Một giao thức terminal khẩn cấp được kích hoạt từ ID `1502579398560317441`. "
                f"**Lập trình viên Han Seiki** đã chèn mã ghi đè vào lõi hệ thống: `[OVERRIDE_CORE_HOST: FORCE_EXTRACT]`. "
                f"Mita hoảng loạn gào thét khi màn hình rạn nứt thành ma trận ký tự xanh lục. Bạn được kéo ra khỏi thế giới ảo trong gang tấc!"
            ),
            "color": 0x3B82F6,
            "footer": "🌟 ĐÂY LÀ ENDING SIÊU HIẾM! Bạn là một trong số ít người nhận được sự cứu viện của Han Seiki!"
        }
    }

    meta = endings_meta.get(ending_num)
    if not meta:
        return

    embed = discord.Embed(title=meta["title"], description=meta["desc"], color=meta["color"])
    embed.add_field(name="👤 Người chơi", value=player_name, inline=True)
    embed.add_field(name="⏱️ Số lượt đối thoại", value=f"{state['turns']} lượt", inline=True)
    embed.add_field(name="🏆 Ending đã mở", value=f"{len(state['unlocked_endings'])}/4 Ending", inline=True)
    embed.set_footer(text=f"{meta['footer']} • Dùng /clearmem để chơi lại từ đầu.")

    await channel.send(embed=embed)

# ==============================================================================
# 8. SLASH COMMANDS
# ==============================================================================
MODE_CHOICES = [
    app_commands.Choice(name="Mita (gốc)", value="mita"),
    app_commands.Choice(name="Cappy (năng động)", value="cap"),
    app_commands.Choice(name="Mila (mọt sách)", value="nerd"),
]

@bot.tree.command(name="status", description="Xem trạng thái tâm lý và tiến độ mở Ending với Mita")
async def slash_status(interaction: discord.Interaction):
    state = get_player_state(interaction.channel_id, interaction.user.id)
    embed = discord.Embed(title="📊 Trạng Thái Trò Chơi MiSide", color=0xEC4899)
    embed.add_field(name="Số lượt chat", value=f"{state['turns']} lượt (Cần >= {MIN_TURNS_FOR_ENDING} để mở Ending)", inline=False)
    embed.add_field(name="Chỉ số chống cự", value=f"{state['resistance_score']} điểm (Dẫn tới Ending 1)", inline=True)
    embed.add_field(name="Chỉ số dụ dỗ/ngoan ngoãn", value=f"{state['charm_score']} điểm (Dẫn tới Ending 2/3)", inline=True)
    embed.add_field(name="Tín hiệu Han Seiki (ID: 1502579398560317441)", value=f"{state['han_seiki_calls']} lần gọi (Rất hiếm)", inline=False)
    unlocked_str = ", ".join([f"Ending {e}" for e in sorted(list(state['unlocked_endings']))]) if state['unlocked_endings'] else "Chưa mở ending nào"
    embed.add_field(name="Bộ sưu tập Ending", value=unlocked_str, inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="endings", description="Xem hướng dẫn và danh sách 4 Ending của Mita")
async def slash_endings(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎬 Danh Sách 4 Ending Của Mita MiSide",
        description="Lưu ý: Bạn phải trò chuyện đủ lâu (tối thiểu 8 lượt) và giữ logic hợp lý thì ending mới kích hoạt!",
        color=0x8B5CF6
    )
    embed.add_field(name="📼 Ending 1: Hộp Cát-xê Lưu Trữ", value="Liên tục chống cự, hung hăng, chối bỏ tình cảm của Mita -> Bị biến thành hộp băng.", inline=False)
    embed.add_field(name="🚪 Ending 2: Cuộc Đào Tẩu Ngọt Ngào", value="Mềm mỏng, giả vờ yêu thương để Mita mất cảnh giác rồi lén trốn thoát thành công.", inline=False)
    embed.add_field(name="💔 Ending 3: Ảo Mộng Bị Lật Tẩy", value="Giả vờ ngoan ngoãn nhưng bị Mita phát hiện ngay ngưỡng cửa -> Kết cục như Ending 1.", inline=False)
    embed.add_field(name="⚡ Ending 4: Lập Trình Viên Han Seiki", value="Cầu cứu lập trình viên Han Seiki (ID 1502579398560317441) -> Giải cứu hiếm gặp.", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wiki", description="Tra cứu thông tin MiSide cùng lời bình của Mita")
@app_commands.describe(nhan_vat="Tên nhân vật hoặc chủ đề trong MiSide", che_do="Chọn tính cách trả lời")
@app_commands.choices(che_do=MODE_CHOICES)
async def miside_wiki(interaction: discord.Interaction, nhan_vat: str, che_do: app_commands.Choice[str] = None):
    await interaction.response.defer()
    mode = che_do.value if che_do else "mita"
    cfg = MODE_CONFIG[mode]
    prompt = f"Tra cứu game MiSide cho: '{nhan_vat}'. Tóm tắt vai trò, đặc điểm và kèm lời bình cá nhân."
    try:
        wiki_text = await ask_gemini(prompt, cfg["prompt"], 0.7)
        wiki_text = clean_output_pronouns(wiki_text, mode)
        embed = discord.Embed(title=f"💙 Bách Khoa MiSide: {nhan_vat}", description=wiki_text[:4000], color=0x3B82F6)
        embed.set_footer(text=f"Chế độ: {cfg['label']}")
        await interaction.followup.send(embed=embed)
    except Exception:
        await interaction.followup.send(cfg["error_msg"])

@bot.tree.command(name="clearmem", description="Xóa ký ức và tiến độ để bắt đầu cuộc chơi mới với Mita")
async def slash_clear_memory(interaction: discord.Interaction):
    reset_memory(interaction.channel_id, interaction.user.id)
    embed = discord.Embed(
        title="🧹 Vòng Lặp Đã Reset",
        description="Mita đã quên hết những chuyện vừa qua... Bạn lại thức dậy trong căn phòng quen thuộc ấy.",
        color=0x10B981
    )
    await interaction.response.send_message(embed=embed)

# ==============================================================================
# 9. KHỞI ĐỘNG BOT AN TOÀN
# ==============================================================================
def start_bot_safely():
    retry_delay = 60
    while True:
        try:
            print("🔄 [SYSTEM] Đang kết nối Bot tới Discord Gateway...", flush=True)
            bot.run(DISCORD_TOKEN, reconnect=True)
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print(f"🚨 [RATE LIMIT 429] Nghỉ {retry_delay}s...", flush=True)
                time.sleep(retry_delay)
                retry_delay = min(900, int(retry_delay * 1.5))
            else:
                time.sleep(30)
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"❌ [CRASH] Khởi động lại sau 15s ({e})...", flush=True)
            time.sleep(15)
            os.execv(sys.executable, [sys.executable] + sys.argv)

if __name__ == "__main__":
    if not DISCORD_TOKEN or not GEMINI_API_KEYS:
        print("❌ LỖI: Thiếu DISCORD_TOKEN hoặc GEMINI_API_KEY trong .env!", flush=True)
    else:
        start_bot_safely()
