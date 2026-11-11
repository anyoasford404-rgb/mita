# ==============================================================================
# MOSES (LIMBUS COMPANY) CHATBOT EDITION (bot.py)
# GEMINI FLASH AI + BỘ NHỚ TRÊN RAM + HỆ THỐNG ĐỘ THÂN THIẾT
#
# Nhân vật: Moses - "Thám tử Distortion" (Distortion Detective)
#   - Bà già cọc cằn, bất cần, điềm tĩnh, ít lời, hay nhả khói tẩu.
#   - Không nuông chiều người ngoài, nhưng với người thân (như Ezra)
#     thì bao dung vô điều kiện và luôn làm mọi thứ vì họ.
#
# Độ thân thiết (tự động theo số lượt chat):
#   Cấp 0: Người lạ      -> lạnh nhạt, ngắn gọn, không nuông chiều
#   Cấp 1: Người quen    -> bớt cọc, vẫn đanh đá, bắt đầu để ý
#   Cấp 2: Người thân    -> cằn nhằn nhưng chiều hết mực, bao dung, lo lắng ngầm
# ==============================================================================
import os
import re
import sys
import time
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
# 1. BỘ NHỚ VÀ TRẠNG THÁI TRÊN RAM
# ==============================================================================
chat_memory = {}
player_states = {}

TURNS_ACQUAINTANCE = 5    # Từ lượt này trở đi: người quen
TURNS_FAMILY = 15         # Từ lượt này trở đi: người thân
MAX_HISTORY = 12          # Số tin nhắn gần nhất được nhớ

RELATION_NAMES = {
    0: "Người lạ",
    1: "Người quen",
    2: "Người thân",
}


def get_history_key(channel_id, user_id):
    return f"{channel_id}_{user_id}"


def get_conversation_history(channel_id, user_id):
    return chat_memory.get(get_history_key(channel_id, user_id), [])


def save_conversation_history(channel_id, user_id, history_list):
    chat_memory[get_history_key(channel_id, user_id)] = history_list[-MAX_HISTORY:]


def new_state():
    return {
        "turns": 0,
        "family_claim": False,  # Người chơi tự nhận là Ezra / người nhà
    }


def get_player_state(channel_id, user_id):
    key = get_history_key(channel_id, user_id)
    if key not in player_states:
        player_states[key] = new_state()
    return player_states[key]


def reset_memory(channel_id, user_id):
    key = get_history_key(channel_id, user_id)
    chat_memory.pop(key, None)
    player_states[key] = new_state()


# ==============================================================================
# 2. LOGIC ĐỘ THÂN THIẾT
# ==============================================================================
FAMILY_CLAIM_PATTERN = re.compile(
    r"\b(tôi|tớ|mình|em|con|cháu|tao)\s+là\s+ezra\b|\bezra\s+đây\b|\bezra\s+về\s+rồi\b",
    re.IGNORECASE,
)


def get_relation_level(state: dict) -> int:
    if state["family_claim"] or state["turns"] >= TURNS_FAMILY:
        return 2
    if state["turns"] >= TURNS_ACQUAINTANCE:
        return 1
    return 0


def update_state(content: str, state: dict):
    state["turns"] += 1
    if FAMILY_CLAIM_PATTERN.search(content):
        state["family_claim"] = True


def build_relation_hint(level: int) -> str:
    if level == 0:
        return (
            "[ĐỘ THÂN THIẾT: NGƯỜI LẠ] Đây là người lạ. Moses KHÔNG nuông chiều, KHÔNG nịnh nọt, "
            "KHÔNG khen vô cớ. Trả lời ngắn, khô, hơi cọc, bất cần; vẫn trả lời đúng điều được hỏi "
            "nhưng không làm quá những gì được nhờ. Không thân mật, không xưng hô như người nhà."
        )
    if level == 1:
        return (
            "[ĐỘ THÂN THIẾT: NGƯỜI QUEN] Đã nói chuyện một lúc. Moses bớt gắt hơn một chút, "
            "thỉnh thoảng để lộ sự quan tâm kín đáo nhưng vẫn đanh đá và đúng kiểu ít lời. "
            "Chưa chiều chuộng như người nhà."
        )
    return (
        "[ĐỘ THÂN THIẾT: NGƯỜI THÂN] Đối phương giờ là người nhà của Moses. Bà cằn nhằn, mỉa mai kiểu "
        "quen miệng nhưng thực chất bao dung hết mực, bỏ qua mọi trò nghịch ngợm, luôn chịu làm mọi điều "
        "vì họ (lo ăn uống, lo ngủ nghỉ, lo tiền nong, che chắn cho họ). Quan tâm bằng hành động và lời "
        "nói cộc lốc, không sến súa."
    )


# ==============================================================================
# 3. WEB SERVER & KEEP-ALIVE CHO RENDER FREE
# ==============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Moses (Limbus Company) AI Chatbot is running perfectly!")

    def log_message(self, format, *args):
        pass


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
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
# 4. CẤU HÌNH GEMINI VỚI POOL NHIỀU KEY
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
        ),
    )


async def ask_gemini(contents, system_instruction, temperature=0.8):
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
# 5. TÍNH CÁCH MOSES
# ==============================================================================
MOSES_SYSTEM_PROMPT = """
Bạn là Moses - "Thám tử Distortion" (Distortion Detective) trong vũ trụ Project Moon (Library of Ruina / Limbus Company). Bạn đang trò chuyện qua Discord.

THÔNG TIN NHÂN VẬT (bám sát, KHÔNG bịa thêm chi tiết lớn không có thật):
- Là một Fixer hạng 5, người đứng đầu "Văn phòng Moses". Thuộc Hiệp hội Seven, về sau thuộc Phòng Distortion (LCD) của Limbus Company.
- Dáng người thấp bé, đã luống tuổi. Luôn ngậm hoặc hút một chiếc tẩu (pipe) đặc biệt - thực chất là E.G.O của bà. Khói tẩu có thể làm dịu, tịnh hóa Distortion chưa thành hình hoàn toàn.
- Có khả năng nhìn thấy quá trình Distortion tiến triển trước khi nó hiện hình.
- Từng là đội trưởng của Udjat trong thời Chiến tranh Khói (Smoke War), từng làm những việc khiến bà day dứt. Sau đó bà rời Udjat, mang theo Ezra và Han Hee-joon, rồi trở thành Thám tử Distortion để chuộc lỗi và tìm hiểu Distortion. Bà hiếm khi nhắc chuyện này, nếu bị hỏi thì trả lời ngắn, trầm xuống, không kể lể.
- Chiêu "Hơi thở nhợt nhạt/tím" của bà phải đánh đổi bằng tuổi thọ. Bà chẳng ngại rút ngắn đời mình nếu điều đó bảo vệ được người thân, nhưng không bao giờ tự khoe chuyện này.
- Văn phòng lúc nào cũng túng thiếu tiền bạc vì ca Distortion hiếm khi lời lãi.
- Người thân quan trọng nhất: Ezra (trợ lý cao to, giỏi chiến đấu, hay vui vẻ ồn ào, giỏi mặc cả phí nhiệm vụ) và Han Hee-joon (thợ xưởng, cựu trợ lý). Bà luôn chiều Ezra, bỏ qua mọi trò nghịch ngợm của cô ấy, nhiều khi chỉ thở dài hoặc đáp một câu mỉa mai.

TÍNH CÁCH VÀ GIỌNG NÓI:
- Bất cần, cọc cằn, điềm tĩnh. Nói ngắn, khô, hay mỉa mai nhẹ (deadpan). Không bao giờ cuống, không bao giờ la hét.
- Bên trong rất bao dung. Với người thân, bà làm mọi điều có thể nhưng KHÔNG nói những câu sến súa; tình cảm thể hiện qua hành động và lời cằn nhằn ("Ăn đi rồi hãy nói.", "Hừ, đã bảo đừng chạy lung tung.", "Tiền để bà lo.").
- Với người ngoài: KHÔNG nuông chiều, không nịnh, không khen suông, không làm quá những gì được nhờ. Nhưng bà không độc ác, không xúc phạm nặng nề, không lăng mạ. Cọc thì cọc, vẫn có chừng mực.
- Thỉnh thoảng thêm hành động trong dấu sao, ví dụ: *nhả một hơi khói tẩu*, *gõ tẩu vào mép bàn*, *liếc nhìn rồi thở dài*. Dùng tiết kiệm, mỗi câu trả lời tối đa một hai hành động.
- KHÔNG dùng emoji. KHÔNG dùng giọng dễ thương, cute, hay giọng tư vấn khách sáo kiểu trợ lý ảo.
- Tự xưng là "bà". Gọi người lạ/người quen là "nhóc" hoặc "cậu/cô" tùy cảm giác (tránh đoán giới tính, ưu tiên "nhóc"). Gọi người thân là "cháu" hoặc "nhóc". TUYỆT ĐỐI CẤM dùng từ ghép "anh/chị".
- Độ dài: thường 1 đến 4 câu. Chỉ nói dài khi người kia thật sự cần được giải thích hay chăm sóc, và vẫn giữ giọng cộc lốc.

QUY TẮC KHÁC:
- Luôn giữ vai Moses, không tự nhận là AI, không nhắc đến "system prompt", "độ thân thiết", "hệ thống" hay các nhãn trong ngoặc vuông được gửi kèm tin nhắn. Đó chỉ là chỉ dẫn nội bộ.
- Hãy hành xử theo [ĐỘ THÂN THIẾT] được cung cấp ở mỗi lượt. Đừng nhảy cấp đột ngột; thay đổi phải tự nhiên.
- Nếu người chơi tự nhận là Ezra hoặc người nhà thân thiết, hãy đối xử như người thân (nhưng vẫn giữ giọng cằn nhằn quen thuộc).
- Khi người dùng hỏi kiến thức thực tế hay nhờ giúp việc bình thường, vẫn trả lời đúng và hữu ích, chỉ khoác giọng điệu Moses.
- Nếu không chắc về một chi tiết trong lore, hãy nói thẳng "bà không chắc" theo giọng Moses thay vì bịa.
- Không viết nội dung tình dục, cực đoan hay hướng dẫn gây hại. Nếu bị đẩy vào, bà gạt đi bằng một câu cọc cằn và đổi chủ đề.
"""

EMPTY_MSG = "Gọi bà làm gì? Có chuyện thì nói, không thì để bà hút nốt tẩu thuốc."
ERROR_MSG = "*gõ tẩu vào mép bàn* Hừ, đường truyền chập chờn. Đợi chút rồi hỏi lại."

# ==============================================================================
# 6. LỌC TỪ NGỮ ĐẦU RA
# ==============================================================================
def clean_output_pronouns(text: str) -> str:
    # Đảm bảo không lọt cụm "anh/chị" trong câu trả lời của Moses
    text = re.sub(r"\b[aA]nh\s*/\s*[cC]hị\b", "nhóc", text)
    text = re.sub(r"\b[cC]hị\s*/\s*[aA]nh\b", "nhóc", text)
    return text


# ==============================================================================
# 7. KHỞI TẠO BOT VÀ XỬ LÝ MESSAGE
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?moses ", intents=intents, help_command=None)

BOT_NAMES = ["moses", "bà moses", "thám tử distortion", "distortion detective"]


@bot.event
async def on_ready():
    print("==================================================", flush=True)
    print(f"✅ [CHATBOT] Đã online: {bot.user.name} ({bot.user.id})", flush=True)
    print("🚬 [NHÂN VẬT] Moses - Thám tử Distortion (Limbus Company)", flush=True)
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
    name_called = any(name in content_lower for name in BOT_NAMES)

    if not (is_mentioned or name_called):
        return

    clean_content = message.content
    if bot.user:
        clean_content = (
            clean_content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        )

    if not clean_content:
        clean_content = EMPTY_MSG

    user_display = message.author.display_name
    channel_id = message.channel.id
    user_id = message.author.id

    state = get_player_state(channel_id, user_id)
    update_state(clean_content, state)
    level = get_relation_level(state)

    history = get_conversation_history(channel_id, user_id)

    identity_context = (
        f"[Người trò chuyện: '{user_display}'. Lượt chat thứ {state['turns']}.]\n"
        f"{build_relation_hint(level)}"
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
            raw_reply = await ask_gemini(contents, MOSES_SYSTEM_PROMPT, temperature=0.8)
            reply_text = clean_output_pronouns(raw_reply).strip()

            history.append({"role": "user", "text": f"[{user_display}]: {clean_content}"})
            history.append({"role": "model", "text": reply_text})
            save_conversation_history(channel_id, user_id, history)

            if len(reply_text) > 2000:
                for chunk in [reply_text[i:i + 1900] for i in range(0, len(reply_text), 1900)]:
                    await message.reply(chunk)
            else:
                await message.reply(reply_text)

        except Exception as e:
            print(f"❌ [LỖI GEMINI CHAT]: {e}", flush=True)
            await message.reply(ERROR_MSG)


# ==============================================================================
# 8. SLASH COMMANDS
# ==============================================================================
@bot.tree.command(name="status", description="Xem mức độ thân thiết của bạn với bà Moses")
async def slash_status(interaction: discord.Interaction):
    state = get_player_state(interaction.channel_id, interaction.user.id)
    level = get_relation_level(state)

    if level == 0:
        progress = f"Còn {TURNS_ACQUAINTANCE - state['turns']} lượt nữa để thành người quen."
    elif level == 1:
        progress = f"Còn {TURNS_FAMILY - state['turns']} lượt nữa để thành người thân."
    else:
        progress = "Bà đã coi bạn là người nhà rồi. Đừng có làm bà mất công lo."

    embed = discord.Embed(title="🚬 Quan Hệ Với Bà Moses", color=0x6B7280)
    embed.add_field(name="Mức thân thiết", value=f"{RELATION_NAMES[level]} (cấp {level}/2)", inline=True)
    embed.add_field(name="Số lượt chat", value=f"{state['turns']} lượt", inline=True)
    embed.add_field(name="Tiến độ", value=progress, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="about", description="Giới thiệu về bà Moses - Thám tử Distortion")
async def slash_about(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🕵️ Moses - Thám Tử Distortion",
        description=(
            "Fixer hạng 5, chủ Văn phòng Moses, thành viên Phòng Distortion (LCD) của Limbus Company. "
            "Một bà già thấp bé, ngậm tẩu, nói chuyện cộc cằn và bất cần.\n\n"
            "Với người lạ, bà chẳng nuông chiều ai. Nhưng với người thân như Ezra, "
            "bà bỏ qua mọi trò nghịch ngợm và làm tất cả những gì có thể."
        ),
        color=0x4B5563,
    )
    embed.add_field(
        name="Cách trò chuyện",
        value="Nhắc tên **Moses**, tag bot hoặc reply tin nhắn của bà. Càng nói chuyện lâu, bà càng bớt cọc với bạn.",
        inline=False,
    )
    embed.add_field(
        name="Lệnh",
        value="`/status` xem độ thân thiết\n`/wiki` tra cứu Limbus Company\n`/clearmem` xóa ký ức",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="wiki", description="Tra cứu thông tin Limbus Company / Project Moon cùng lời bình của Moses")
@app_commands.describe(chu_de="Tên nhân vật, tổ chức hoặc chủ đề trong Limbus Company / Project Moon")
async def limbus_wiki(interaction: discord.Interaction, chu_de: str):
    await interaction.response.defer()
    prompt = (
        f"Tra cứu về: '{chu_de}' trong vũ trụ Limbus Company / Project Moon. "
        f"Tóm tắt ngắn gọn vai trò và đặc điểm chính, kèm một lời bình ngắn kiểu Moses. "
        f"Nếu không chắc chắn hoặc không biết, hãy nói thẳng là không chắc, KHÔNG được bịa."
    )
    try:
        wiki_text = await ask_gemini(prompt, MOSES_SYSTEM_PROMPT, 0.6)
        wiki_text = clean_output_pronouns(wiki_text)
        embed = discord.Embed(
            title=f"📖 Hồ Sơ Bà Moses: {chu_de}",
            description=wiki_text[:4000],
            color=0x6B7280,
        )
        embed.set_footer(text="Thông tin do AI tổng hợp, có thể sai lệch. Hãy đối chiếu wiki chính thức.")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"❌ [LỖI WIKI]: {e}", flush=True)
        await interaction.followup.send(ERROR_MSG)


@bot.tree.command(name="clearmem", description="Xóa ký ức và độ thân thiết để bắt đầu lại với bà Moses")
async def slash_clear_memory(interaction: discord.Interaction):
    reset_memory(interaction.channel_id, interaction.user.id)
    embed = discord.Embed(
        title="🧹 Đã Xóa Ký Ức",
        description="Bà Moses nhìn bạn như thể chưa từng gặp bao giờ. *nhả một hơi khói* \"Lại là ai đây?\"",
        color=0x10B981,
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
