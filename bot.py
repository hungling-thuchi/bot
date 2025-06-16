import discord
from discord.ext import commands
import gspread
import google.generativeai as genai
import json
from datetime import datetime
import re
import os
from dotenv import load_dotenv

# --- Tải các biến môi trường từ file .env ---
load_dotenv()

# --- Lấy cấu hình từ biến môi trường ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# --- Kiểm tra các biến môi trường đã được tải đầy đủ chưa ---
if not all([DISCORD_BOT_TOKEN, GOOGLE_SERVICE_ACCOUNT, 
            GOOGLE_SHEET_NAME, GOOGLE_WORKSHEET_NAME, GEMINI_API_KEY]):
    print("!!! CẢNH BÁO: MỘT HOẶC NHIỀU BIẾN MÔI TRƯỜNG CHƯA ĐƯỢC CẤU HÌNH ĐẦY ĐỦ !!!")
    print("Vui lòng kiểm tra lại các giá trị: DISCORD_BOT_TOKEN, GOOGLE_SERVICE_ACCOUNT,")
    print("GOOGLE_SHEET_NAME, GOOGLE_WORKSHEET_NAME, GEMINI_API_KEY")
    # Thoát chương trình nếu thiếu cấu hình quan trọng
    exit(1)

# --- Cấu hình Discord Bot ---
# intents giúp bot biết những loại sự kiện nào nó nên lắng nghe
intents = discord.Intents.default()
intents.message_content = True # Rất quan trọng để bot có thể đọc nội dung tin nhắn
bot = commands.Bot(command_prefix='!', intents=intents)


# --- Cấu hình Google Sheet ---
gc = None
worksheet = None
try:
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT) 
    gc = gspread.service_account_from_dict(service_account_info)
    spreadsheet = gc.open(GOOGLE_SHEET_NAME)
    worksheet = spreadsheet.worksheet(GOOGLE_WORKSHEET_NAME)
    print("✅ Kết nối Google Sheet thành công!")
except json.JSONDecodeError as e: # Bắt lỗi JSONDecodeError cụ thể hơn
    print(f"❌ Lỗi biến môi trường GOOGLE_SERVICE_ACCOUNT: {e}")
    print("Vui lòng đảm bảo chuỗi JSON trong .env là hợp lệ và đã được thoát đúng cách.")
except Exception as e:
    print(f"❌ Lỗi kết nối Google Sheet: {e}")
    print("Vui lòng kiểm tra GOOGLE_SHEET_NAME, GOOGLE_WORKSHEET_NAME hoặc quyền truy cập của Service Account.")

# --- Cấu hình Gemini AI ---
gemini_model = None
try:
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Cấu hình model và các tham số
    MODEL_NAME = "gemini-1.5-flash"  # Hoặc model bạn muốn dùng
    generation_config = {
        "max_output_tokens": 1024,
        "temperature": 0.6,
        "top_p": 1.0
    }
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
    
    # Tạo model với cấu hình
    gemini_model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config=generation_config,
        safety_settings=safety_settings
    )
    print("✅ Kết nối Gemini AI thành công!")
except Exception as e:
    print(f"❌ Lỗi kết nối Gemini AI: {e}")
    print("Vui lòng kiểm tra GEMINI_API_KEY của bạn và đảm bảo bạn đã cài đặt phiên bản mới nhất của thư viện `google-generativeai`.")

# --- Sự kiện khi bot sẵn sàng ---
@bot.event
async def on_ready():
    print(f'-------------------------------------')
    print(f'{bot.user.name} đã sẵn sàng và đang chạy!')
    print(f'Discord ID: {bot.user.id}')
    print(f'-------------------------------------')

# --- Xử lý mọi tin nhắn đến ---
@bot.event
async def on_message(message):
    # Bỏ qua tin nhắn của chính bot
    if message.author == bot.user:
        return

    content = message.content.strip()

    bank_statement = ""
    user_description = "Không có mô tả người dùng"
    person_paying = "" 

    # Cải thiện Regex để bắt H. hoặc L. một cách linh hoạt hơn
    # Tìm H. hoặc L. theo sau bởi dấu chấm và khoảng trắng, có thể ở đầu dòng mới hoặc sau vài khoảng trắng.
    # re.MULTILINE để ^ khớp với đầu mỗi dòng, re.IGNORECASE để không phân biệt hoa thường.
    # re.DOTALL để dấu chấm khớp với cả ký tự xuống dòng.
    
    # Cú pháp mẫu: [thông báo] \n H. [mô tả] HOẶC [thông báo] H. [mô tả]
    # Tìm kiếm một trong hai pattern:
    # 1. Bất kỳ ký tự nào (non-greedy) theo sau bởi một hoặc nhiều khoảng trắng/xuống dòng, rồi H. hoặc L.
    # 2. Hoặc H. hoặc L. xuất hiện ngay sau thông báo (không có xuống dòng/nhiều khoảng trắng)
    
    # Regex chung để tìm kiếm pattern H./L.
    # Regex này sẽ tìm kiếm "H." hoặc "L." có thể nằm ở đầu dòng mới (sau \n)
    # hoặc sau ít nhất một khoảng trắng (hoặc ký tự bất kỳ) từ phần trước đó.
    
    # Sẽ chia tin nhắn thành 2 phần nếu tìm thấy H. hoặc L.
    # Phần 1: bank_statement (trước H./L.)
    # Phần 2: H./L. + user_description
    
    # Thay thế regex cũ để xử lý linh hoạt hơn
    # Tìm kiếm một pattern H. hoặc L. (có dấu chấm, không phân biệt hoa thường)
    # được bao quanh bởi các ký tự khoảng trắng/xuống dòng tùy ý
    marker_match = re.search(r'(\s*[HL]\.\s*)(.*)', content, re.IGNORECASE | re.DOTALL)

    if marker_match:
        # Nếu tìm thấy H. hoặc L.
        # Tách phần thông báo ngân hàng (trước marker)
        bank_statement_raw = content[:marker_match.start(1)].strip()
        # Phần mô tả của người dùng
        user_description_raw = marker_match.group(2).strip()
        
        # Lấy ký tự marker để xác định người chi trả
        marker_char = marker_match.group(1).strip().upper()
        if marker_char == 'H.':
            person_paying = "Chồng"
        elif marker_char == 'L.':
            person_paying = "Vợ"
        else:
            person_paying = "Chưa xác định" # Trường hợp không mong muốn

        bank_statement = bank_statement_raw
        user_description = user_description_raw
        if not user_description:
            user_description = "Không có mô tả người dùng"
            
    else:
        # Nếu không tìm thấy H. hoặc L.
        bank_statement = content
        user_description = "Không có mô tả người dùng"
        person_paying = "Chưa xác định" # Mặc định nếu không có H/L

    # Bỏ qua các tin nhắn quá ngắn hoặc không giống thông báo ngân hàng
    if len(bank_statement) < 15 and not bank_statement.startswith(bot.command_prefix): # Giảm ngưỡng tối thiểu
        await bot.process_commands(message)
        return
    
    # Chỉ xử lý nếu có vẻ là thông báo biến động số dư (có "Số tiền:" hoặc "Số dư:")
    """
    if "số tiền:" not in bank_statement.lower() and "số dư:" not in bank_statement.lower():
        await bot.process_commands(message)
        return
    """
    if worksheet is None or gemini_model is None:
        await message.channel.send("Bot chưa sẵn sàng do lỗi cấu hình. Vui lòng kiểm tra lại log trên console.")
        return

    await message.channel.send("🤖 Đang xử lý thông báo biến động số dư của bạn, vui lòng chờ trong giây lát...")

    try:
        # --- MÔ TẢ TIN NHẮN CHO AI (FEW-SHOT EXAMPLES) ---
        examples_prompt = """
        Ví dụ:
        Input: "07:29 16/06/2025 Tai khoan thanh toan: 4616789699 So tien: - 50,000 VND So du cuoi: 6,673,125 VND Ma giao dich: 0992dLK4-80wKAyuuH Noi dung giao dich: Omni Channel-TKThe :0363067975, tai ICBVVNVX. NGUYEN THAI HUNG CHUYEN TIEN -020097048806160729032025rC6v011964-1/2-PMT-002"
        Output:
        ```json
        {
          "so_tien_giao_dich": -50000,
          "loai_giao_dich": "Chi",
          "ngay_gio_giao_dich": "16/06/2025"
        }
        ```

        Input: "Agribank: 16h08p 13/06 TK 2300205418014: +20,000,000VND NGUYEN THAI HUNG CHUYEN TIEN. SD: 39,960,474VND."
        Output:
        ```json
        {
          "so_tien_giao_dich": 20000000,
          "loai_giao_dich": "Thu",
          "ngay_gio_giao_dich": "13/06/2025"
        }
        ```

        Input: "Vietcombank thong bao: 10:30 ngay 14/06/2025 -123,456 VND TK: XXXXX. Noi dung: Rut tien ATM"
        Output:
        ```json
        {
          "so_tien_giao_dich": -123456,
          "loai_giao_dich": "Chi",
          "ngay_gio_giao_dich": "14/06/2025"
        }
        ```
        """
        # --- HẾT PHẦN MÔ TẢ TIN NHẮN CHO AI ---

        # Prompt chính cho Gemini AI
        prompt = f"""
        Trích xuất 'Số tiền giao dịch', 'Loại giao dịch' (Thu/Chi), và 'Ngày/Giờ' từ thông báo biến động số dư sau.
        Nếu 'Số tiền' có dấu '-', đó là 'Chi'. Nếu không có dấu '-', hoặc có dấu '+', đó là 'Thu'.
        Định dạng 'Ngày/Giờ' thành DD/MM/YYYY.
        Nếu không tìm thấy 'Ngày/Giờ' cụ thể trong thông báo, sử dụng ngày hiện tại của hệ thống với định dạng DD/MM/YYYY.
        Trả về kết quả dưới dạng JSON.

        {examples_prompt}

        Thông báo cần phân tích:
        {bank_statement}
        """
        
        response = gemini_model.generate_content(prompt)
        
        # Kiểm tra nếu response không có text hoặc trống
        if not response.text:
            await message.channel.send("❌ AI không thể trích xuất thông tin từ thông báo của bạn. Vui lòng thử lại với định dạng rõ ràng hơn hoặc thông báo khác.")
            return

        # Gemini đôi khi trả về JSON trong cặp dấu ```json ... ```
        json_str_match = re.search(r"```json\s*(.*?)\s*```", response.text, re.DOTALL)
        if json_str_match:
            json_str = json_str_match.group(1)
        else:
            json_str = response.text.strip() # Nếu không có ```json``` thì lấy toàn bộ text

        data = json.loads(json_str)

        # Lấy dữ liệu và chuẩn hóa
        so_tien_raw = data.get("so_tien_giao_dich")
        if so_tien_raw is None:
             raise ValueError("Không tìm thấy 'so_tien_giao_dich' trong phản hồi AI.")

        # Xử lý số tiền: loại bỏ dấu phẩy/chấm nếu có, chuyển về số nguyên, lấy giá trị tuyệt đối
        so_tien = abs(int(str(so_tien_raw).replace(",", "").replace(".", "")))
        
        loai_gd = data.get("loai_giao_dich")
        if loai_gd is None:
            raise ValueError("Không tìm thấy 'loai_giao_dich' trong phản hồi AI.")
        
        noi_dung = user_description
        
        ngay_gio_str = data.get("ngay_gio_giao_dich")
        
        # Đảm bảo định dạng ngày tháng chuẩn cho Google Sheet (DD/MM/YYYY)
        try:
            # Thử parse theo định dạng DD/MM/YYYY
            if ngay_gio_str and re.match(r"\d{2}/\d{2}/\d{4}", ngay_gio_str):
                 ngay = datetime.strptime(ngay_gio_str, "%d/%m/%Y").strftime("%d/%m/%Y")
            # Thử parse theo định dạng YYYY-MM-DD (phòng trường hợp AI trả về định dạng cũ)
            elif ngay_gio_str and re.match(r"\d{4}-\d{2}-\d{2}", ngay_gio_str):
                 ngay = datetime.strptime(ngay_gio_str, "%Y-%m-%d").strftime("%d/%m/%Y")
            else:
                 ngay = datetime.now().strftime("%d/%m/%Y") # Mặc định là ngày hiện tại
        except (ValueError, TypeError):
            ngay = datetime.now().strftime("%d/%m/%Y") # Mặc định là ngày hiện tại nếu có lỗi

        # Thêm vào Google Sheet - BỔ SUNG CỘT person_paying
        row_data = [ngay, loai_gd, so_tien, noi_dung, person_paying]
        worksheet.append_row(row_data)
        
        await message.channel.send(
            f"✅ **Đã ghi nhận giao dịch vào sổ thu chi:**\n"
            f"• **Ngày:** `{ngay}`\n"
            f"• **Loại:** `{loai_gd}`\n"
            f"• **Số tiền:** `{so_tien:,.0f} VND`\n" # Định dạng số có dấu phẩy
            f"• **Nội dung:** `{noi_dung}`\n"
            f"• **Người thu/chi:** `{person_paying}`"
        )

    except json.JSONDecodeError:
        await message.channel.send("❌ Lỗi: AI trả về định dạng không phải JSON. Có vẻ AI không hiểu rõ yêu cầu. Vui lòng kiểm tra lại thông báo của bạn và thử lại.")
    except ValueError as ve:
        await message.channel.send(f"❌ Lỗi xử lý dữ liệu: {ve}. Có thể AI không trích xuất đủ thông tin hoặc định dạng số tiền/ngày tháng không đúng. Vui lòng kiểm tra lại thông báo của bạn.")
    except Exception as e:
        print(f"Lỗi tổng quát khi xử lý tin nhắn: {e}")
        await message.channel.send(f"❌ Đã xảy ra lỗi không mong muốn trong quá trình xử lý. Vui lòng thử lại sau. Chi tiết lỗi: `{e}`")

    # Quan trọng: Gọi process_commands để bot vẫn xử lý các lệnh (commands) khác nếu bạn có
    await bot.process_commands(message)


# --- Chạy bot ---
if __name__ == '__main__':
    # Bot sẽ chỉ chạy nếu tất cả các biến môi trường cần thiết đã được tải
    if all([DISCORD_BOT_TOKEN, GOOGLE_SERVICE_ACCOUNT, 
            GOOGLE_SHEET_NAME, GOOGLE_WORKSHEET_NAME, GEMINI_API_KEY]):
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("\nBot không thể khởi động do thiếu cấu hình. Vui lòng kiểm tra thông báo cảnh báo ở trên.")