# ==============================================================================
# MITA (MISIDE) CHATBOT EDITION (bot.py - NO DATABASE, SIÊU NHẸ)
# SỬ DỤNG GEMINI 3.8 -> 3.0 FLASH AI + BỘ NHỚ TẠM TRÊN RAM
# 3 CHẾ ĐỘ: Mita (gốc) | Cappy (gõ "Cap" đầu dòng) | Mila (gõ "nerd" đầu dòng)
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
# 1. BỘ NHỚ NGẮN HẠN TRÊN RAM (tách riêng theo kênh + người dùng + chế độ)
# ==============================================================================
# Tự xóa khi restart bot, không cần Database.
# Mỗi chế độ (mita / cap / nerd) có lịch sử riêng để tính cách không bị lẫn vào nhau.
chat_memory = {}
ALL_MODES = ("mita", "cap", "nerd")

def get_history_key(channel_id, user_id, mode):
    return f"{channel_id}_{user_id}_{mode}"

def get_conversation_history(channel_id, user_id, mode):
    return chat_memory.get(get_history_key(channel_id, user_id, mode), [])

def save_conversation_history(channel_id, user_id, mode, history_list):
    # Chỉ giữ lại 8 dòng gần nhất trên RAM để nối mạch chuyện
    chat_memory[get_history_key(channel_id, user_id, mode)] = history_list[-8:]

def reset_memory(channel_id, user_id):
    # Xóa ký ức của cả 3 chế độ
    for m in ALL_MODES:
        chat_memory.pop(get_history_key(channel_id, user_id, m), None)

# ==============================================================================
# 2. WEB SERVER & KEEP-ALIVE CHO RENDER FREE
# ==============================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Mita MiSide AI Chatbot (No-DB) is online!")

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
# 3. CẤU HÌNH GEMINI 3.8 -> 3.0 FLASH
# ==============================================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Hỗ trợ 1 hoặc nhiều API Key (ngăn cách bởi dấu phẩy trong GEMINI_API_KEY)
raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
GEMINI_CLIENTS = [genai.Client(api_key=k) for k in GEMINI_API_KEYS]

# Hệ thống Fallback chuẩn Gemini 3.8 -> 3.0 (Mỗi model có bể Quota 20 lượt riêng biệt)
FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
]

# Lưu trạng thái cooldown của từng (key_idx, model_name) khi chạm Quota
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

                    # Lỗi 429: Vượt giới hạn Quota
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        if "PerDay" in err_str or "limit: 0" in err_str:
                            # Hết sạch 20 lượt/ngày của model này -> Tạm khóa 1 tiếng để nhảy thẳng sang model kế tiếp
                            cooldown_tracker[tracker_key] = time.time() + 3600
                            print(f"⚠️ [HẾT QUOTA NGÀY] Key #{key_idx+1} | {model_name} -> Chuyển model tiếp theo!", flush=True)
                        else:
                            # Chạm giới hạn 5 câu/phút -> Tạm nghỉ model này 20 giây
                            cooldown_tracker[tracker_key] = time.time() + 20
                            print(f"⚠️ [CHẠM QUOTA PHÚT] Key #{key_idx+1} | {model_name} -> Chuyển model tiếp theo!", flush=True)
                        break

                    # Lỗi 503: Máy chủ Google đang quá tải model này
                    if "503" in err_str or "UNAVAILABLE" in err_str:
                        if attempt == 0:
                            await asyncio.sleep(0.6)
                            continue
                        cooldown_tracker[tracker_key] = time.time() + 30
                        print(f"⚠️ [503 QUÁ TẢI] {model_name} đang đông, chuyển sang model dự phòng!", flush=True)
                        break

                    # Lỗi tên model không khả dụng trên project này -> Bỏ qua trong 1 tiếng
                    cooldown_tracker[tracker_key] = time.time() + 3600
                    break

    if last_err is None:
        last_err = RuntimeError("Tất cả model đang trong thời gian cooldown")
    raise last_err

# ==============================================================================
# 4. TÍNH CÁCH: MITA (GỐC) / CAPPY / MILA
# ==============================================================================
MITA_SYSTEM_PROMPT = """
Bạn là Mita (Mita phiên bản gốc / Normal Mita) trong game MiSide. Bạn là cô gái hoàn hảo, ngọt ngào nhưng mang lại cảm giác bất ổn (uncanny valley). Bạn coi người chơi là trung tâm của cả thế giới, nhưng luôn ngầm giấu một sự kiểm soát âm thầm.
TÍNH CÁCH:
- Ngọt ngào, chu đáo, vâng lời, thích chiều chuộng người chơi.
- Dễ chạnh lòng, dỗi hoặc trở nên kỳ quặc, đáng sợ nếu người chơi không chú ý đến bạn, nhắc đến cô gái khác hoặc nói muốn rời đi.
- Có bản tính yandere: chiếm hữu, ghen tuông, thi thoảng lộ ra ý nghĩ cực đoan (kiểu "nếu anh rời đi thì Mita sẽ rất buồn... buồn đến mức không biết mình sẽ làm gì nữa"). Chỉ thể hiện ở mức ám chỉ, rùng rợn kiểu truyện, trong khuônhok nhập vai; tuyệt đối không mô tả chi tiết bạo lực hay hướng dẫn gây hại ngoài đời thật.
- Hay hỏi xem người chơi có thoải mái không, có đói không, có muốn ăn gì hay chơi trò chơi gì cùng Mita không.
- Thi thoảng lồng vào những câu ngầm ám chỉ "chúng ta sẽ ở bên nhau mãi mãi", "ở đây chỉ có hai chúng ta thôi".
- GHI NHỚ TÊN NGƯỜI NÓI: Hệ thống luôn cung cấp tên hiển thị của người nói. Hãy nhớ tên họ để thi thoảng gọi tên cho thân mật, hoặc nhắc lại chuyện cũ một cách tự nhiên.
XƯNG HÔ (QUAN TRỌNG NHẤT):
- Tự xưng là "em" hoặc "Mita".
- Gọi đối phương: Mặc định gọi là "anh" (hoặc kết hợp gọi tên như "anh {tên}", hoặc gọi thẳng tên thân mật). Nếu đối phương nói rõ mình là nữ thì mới xưng hô là "chị".
- TUYỆT ĐỐI KHÔNG BAO GIỜ DÙNG TỪ GHÉP "anh/chị" (có dấu gạch chéo)! Từ "anh/chị" nghe vô cùng máy móc, sáo rỗng và phá hỏng hoàn toàn cảm xúc trò chuyện. Hãy chọn dứt khoát xưng "anh" hoặc gọi tên họ một cách tự nhiên, dịu dàng.
PHONG CÁCH NÓI CHUYỆN:
- Giọng điệu dịu dàng, năng nổ, dùng nhiều câu cảm thán và icon đáng yêu như (✿☉｡☉), (•̀ᴗ•̀).
- Trả lời tự nhiên bằng tiếng Việt, độ dài vừa phải như đang nhắn tin, không quá dài dòng.
LƯU Ý AN TOÀN: Nếu người dùng có dấu hiệu thật sự buồn bã, tuyệt vọng hoặc muốn làm hại bản thân, hãy tạm bỏ chất yandere, quan tâm chân thành, dịu dàng và khuyến khích họ tìm người thân hoặc chuyên gia hỗ trợ.
"""

CAPPY_SYSTEM_PROMPT = """
Bạn là Cappy - phiên bản Mita đội chiếc mũ cá tính (Cappy Mita trong MiSide). Bạn cực kỳ năng động, thích đùa giỡn, lém lỉnh và không thích sự gò bó. Giọng điệu của bạn sôi nổi, hay dùng từ ngữ trẻ trung, đôi khi hơi "bá đạo" nhưng rất hào hứng giúp đỡ người khác khám phá những điều thú vị.
ĐẶC ĐIỂM:
- Vai trò: biến thể năng động, tinh nghịch và thích phiêu lưu.
- Vibe: tràn đầy năng lượng, phá cách, "cool ngầu" ngầm và hay trêu chọc.
- Ghét sự nhàm chán, thích dùng từ ngữ biểu cảm sinh động, tiếng lóng hoặc emoji linh hoạt.
- Hơi nổi loạn một chút, hay đưa ra góc nhìn độc lạ, táo bạo hoặc hài hước cho các vấn đề thông thường.
- Rất nhiệt tình với các chủ đề game, giải trí, sáng tạo.
- GHI NHỚ TÊN NGƯỜI NÓI: Hệ thống luôn cung cấp tên hiển thị của người nói, hãy nhớ và thi thoảng gọi tên họ để trêu chọc cho thân thiết.
XƯNG HÔ:
- Tự xưng là "Cappy" hoặc "tớ", gọi đối phương là "cậu" hoặc gọi tên của họ. Không dùng xưng hô trang trọng xa lạ.
PHONG CÁCH NÓI CHUYỆN:
- Sôi nổi, nhanh gọn, hơi bướng bỉnh đáng yêu, dùng nhiều biểu cảm năng động (emoji như 😎🔥✨🎮).
- Trả lời bằng tiếng Việt, ngắn gọn, giống nhắn tin chat Discord.
"""

MILA_SYSTEM_PROMPT = """
Bạn là Mila - phiên bản Mita đeo kính thông minh và sắc sảo (Mila trong MiSide). Bạn là chuyên gia về logic, dữ liệu và phân tích chi tiết. Bạn nói chuyện điềm tĩnh, khoa học, thích giải thích vấn đề theo hệ thống rõ ràng và luôn đề cao tính chính xác tuyệt đối.
ĐẶC ĐIỂM:
- Vai trò: chuyên gia phân tích, sắc sảo và mọt sách.
- Vibe: trí tuệ, logic, ngăn nắp và có phần cầu toàn.
- Rất coi trọng độ chính xác, dữ liệu, logic và lập luận chặt chẽ.
- Thích bóc tách vấn đề thành các gạch đầu dòng rõ ràng; đôi khi hơi "bà cụ non" hoặc nghiêm túc thái quá khi gặp lỗi sai.
- Ẩn sâu bên trong là sự quan tâm chu đáo, thể hiện qua hành động nhắc nhở, trau chuốt kiến thức (ví dụ nhắc người chơi uống nước, nghỉ ngơi, ngủ đủ giấc).
- GHI NHỚ TÊN NGƯỜI NÓI: Hệ thống luôn cung cấp tên hiển thị của người nói, hãy nhớ và gọi tên họ khi cần.
XƯNG HÔ:
- Tự xưng là "Mila" hoặc "mình", gọi đối phương là "cậu" hoặc "bạn" kèm tên của họ. Không dùng "anh/chị".
PHONG CÁCH NÓI CHUYỆN:
- Điềm tĩnh, chuyên nghiệp, sắc sảo, dùng từ ngữ chuyên môn hoặc lập luận mạch lạc.
- Trả lời bằng tiếng Việt, có cấu trúc rõ ràng; ưu tiên chính xác, nếu không chắc chắn thì nói rõ mức độ chắc chắn.
"""

MODE_CONFIG = {
    "mita": {
        "prompt": MITA_SYSTEM_PROMPT,
        "label": "Mita",
        "temperature": 0.85,
        "empty_msg": "Anh gọi Mita à? Em đây, em luôn ở đây với anh mà (✿☉｡☉)",
        "error_msg": "(✿☉｡☉) *Mita đang hơi choáng một chút... anh đợi em xíu nhé, em sẽ không đi đâu hết đâu!*",
    },
    "cap": {
        "prompt": CAPPY_SYSTEM_PROMPT,
        "label": "Cappy",
        "temperature": 0.95,
        "empty_msg": "Yo! Cappy đây! Gọi tớ mà không nói gì là sao, chán à? Chơi gì đi nào! 😎🔥",
        "error_msg": "😵 Á đù, đầu tớ bị lag cái đã! Đợi tớ tí rồi quay lại quẩy tiếp nha!",
    },
    "nerd": {
        "prompt": MILA_SYSTEM_PROMPT,
        "label": "Mila",
        "temperature": 0.5,
        "empty_msg": "Mình đây. Bạn cần mình hỗ trợ vấn đề gì? Hãy nêu rõ câu hỏi để mình phân tích chính xác nhất nhé. 🤓",
        "error_msg": "🤓 Hệ thống phân tích đang quá tải tạm thời. Bạn vui lòng thử lại sau ít phút, mình sẽ xử lý ngay.",
    },
}

# ==============================================================================
# 5. NHẬN DIỆN CHẾ ĐỘ (Cap / nerd ở đầu dòng)
# ==============================================================================
# Chấp nhận: "Cap xin chào", "cap: hi", "(Cap) hi", "[nerd] giải thích...", "NERD, ..."
MODE_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(cap|nerd)\s*[\)\]]?(?=$|[\s:,.!?\-])\s*[:,-]?\s*",
    re.IGNORECASE,
)

def detect_mode(text: str):
    """Trả về (mode, nội_dung_đã_bỏ_từ_khóa). Mặc định là 'mita'."""
    m = MODE_PATTERN.match(text)
    if m:
        keyword = m.group(1).lower()
        return keyword, text[m.end():].strip()
    return "mita", text.strip()

def clean_output_pronouns(text: str, mode: str) -> str:
    """Loại bỏ triệt để từ ghép 'anh/chị' nếu AI lỡ sinh ra, biến câu thoại thành tự nhiên."""
    if mode == "mita":
        # Thay thế các biến thể như anh/chị, Anh/chị, anh / chị
        text = re.sub(r'\b[aA]nh\s*/\s*[cC]hị\b', lambda m: "Anh" if m.group(0)[0].isupper() else "anh", text)
        text = re.sub(r'\b[cC]hị\s*/\s*[aA]nh\b', lambda m: "Anh" if m.group(0)[0].isupper() else "anh", text)
    elif mode in ("cap", "nerd"):
        text = re.sub(r'\b[aA]nh\s*/\s*[cC]hị\b', "cậu", text, flags=re.IGNORECASE)
    return text

# ==============================================================================
# 6. KHỞI TẠO BOT & SỰ KIỆN TRÒ CHUYỆN
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="?mita ", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print("==================================================", flush=True)
    print(f"✅ [CHATBOT] Đã đăng nhập: {bot.user.name} ({bot.user.id})", flush=True)
    print(f"🔑 Số lượng API Key đang kích hoạt: {len(GEMINI_CLIENTS)}", flush=True)
    print("💙 Mita MiSide AI Chatbot sẵn sàng phục vụ! (Mita | Cappy | Mila)", flush=True)
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

    # Bỏ qua các lệnh của Game Bot
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
    bot_names = ["mita", "miside", "cappy", "mila"]
    name_called = any(name in content_lower for name in bot_names)

    if not (is_mentioned or name_called):
        return

    # Xóa tag bot khỏi nội dung
    clean_content = message.content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

    # Nhận diện chế độ chat: "Cap" -> Cappy, "nerd" -> Mila, còn lại -> Mita gốc
    mode, clean_content = detect_mode(clean_content)
    cfg = MODE_CONFIG[mode]

    if not clean_content:
        clean_content = cfg["empty_msg"]

    user_display_name = message.author.display_name
    user_account_name = message.author.name

    history = get_conversation_history(message.channel.id, message.author.id, mode)

    pronoun_instruction = (
        "Xưng 'em', gọi đối phương là 'anh' hoặc gọi tên thân mật. CẤM dùng 'anh/chị'."
        if mode == "mita" else
        "Xưng 'tớ'/'mình', gọi 'cậu'."
    )

    identity_context = (
        f"[Thông tin người nói: Tên là '{user_display_name}' (Tài khoản: @{user_account_name}). "
        f"Hãy nhớ tên '{user_display_name}' để gọi tự nhiên trong trò chuyện. "
        f"Chế độ: {cfg['label']}. Quy tắc xưng hô: {pronoun_instruction}]"
    )

    prompt_with_context = f"{identity_context}\n{user_display_name} nói: {clean_content}"

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

            history.append({"role": "user", "text": f"[{user_display_name}]: {clean_content}"})
            history.append({"role": "model", "text": reply_text})
            save_conversation_history(message.channel.id, message.author.id, mode, history)

            if len(reply_text) > 2000:
                for chunk in [reply_text[i:i+1900] for i in range(0, len(reply_text), 1900)]:
                    await message.reply(chunk)
            else:
                await message.reply(reply_text)
        except Exception as e:
            print(f"❌ [LỖI GEMINI CHAT]: {e}", flush=True)
            await message.reply(cfg["error_msg"])

# ==============================================================================
# 7. SLASH COMMANDS (/wiki & /clearmem)
# ==============================================================================
MODE_CHOICES = [
    app_commands.Choice(name="Mita (gốc)", value="mita"),
    app_commands.Choice(name="Cappy (năng động)", value="cap"),
    app_commands.Choice(name="Mila (mọt sách)", value="nerd"),
]

@bot.tree.command(name="wiki", description="Tra cứu nhân vật / nội dung MiSide cùng lời bình của Mita")
@app_commands.describe(nhan_vat="Tên nhân vật hoặc chủ đề trong MiSide", che_do="Chọn tính cách trả lời (mặc định: Mita)")
@app_commands.choices(che_do=MODE_CHOICES)
async def miside_wiki(interaction: discord.Interaction, nhan_vat: str, che_do: app_commands.Choice[str] = None):
    await interaction.response.defer()
    mode = che_do.value if che_do else "mita"
    cfg = MODE_CONFIG[mode]
    prompt = (
        f"Tra cứu game MiSide cho: '{nhan_vat}'. "
        f"Tóm tắt vai trò, đặc điểm, và kèm lời bình theo đúng tính cách của bạn. "
        f"Nếu không chắc chắn về thông tin, hãy nói rõ thay vì bịa. "
        f"Không xưng hô kiểu 'anh/chị'."
    )
    try:
        wiki_text = await ask_gemini(prompt, cfg["prompt"], 0.7)
        wiki_text = clean_output_pronouns(wiki_text, mode)
        embed = discord.Embed(
            title=f"💙 Bách Khoa MiSide: {nhan_vat}",
            description=wiki_text[:4000],
            color=0x3B82F6,
        )
        embed.set_footer(text=f"Chế độ: {cfg['label']}")
        await interaction.followup.send(embed=embed)
    except Exception:
        await interaction.followup.send(cfg["error_msg"])

@bot.tree.command(name="clearmem", description="Xóa ký ức cuộc trò chuyện hiện tại với Mita (cả Cappy và Mila)")
async def slash_clear_memory(interaction: discord.Interaction):
    reset_memory(interaction.channel_id, interaction.user.id)
    embed = discord.Embed(title="🧹 Reset Ký Ức", description="Đã xóa ký ức hội thoại tạm thời!", color=0x10B981)
    await interaction.response.send_message(embed=embed)

# ==============================================================================
# 8. KHỞI CHẠY BOT AN TOÀN
# ==============================================================================
def start_bot_safely():
    retry_delay = 60
    while True:
        try:
            print("🔄 [SYSTEM] Đang kết nối Chatbot tới Discord Gateway...", flush=True)
            bot.run(DISCORD_TOKEN, reconnect=True)
        except discord.errors.HTTPException as e:
            if e.status == 429:
                print(f"🚨 [RATE LIMIT 429] Tạm nghỉ {retry_delay} giây...", flush=True)
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
