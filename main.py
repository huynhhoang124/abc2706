# -*- coding: utf-8 -*-
import sys
import os
import time
import random
import json
import ctypes
from ctypes import wintypes
import urllib.request
import urllib.error
import ssl

import winsound

from PyQt6.QtCore import Qt, QEvent, QAbstractNativeEventFilter, QCoreApplication, QBuffer, QByteArray, QIODevice
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QSystemTrayIcon, QMenu, QCheckBox, QLineEdit, QTextEdit,
    QSizeGrip
)
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QAction, QGuiApplication

# Import các mẫu câu gợi ý
from templates import TEMPLATES

# Hằng số Windows API cho Hotkey
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_Q = 0x51  # Phím Q
VK_Z = 0x5A  # Phím Z
VK_X = 0x58  # Phím X
HOTKEY_ID = 911  # ID bất kỳ cho Hotkey Q
HOTKEY_Z_ID = 912  # ID cho Hotkey Z (AI chạy ngầm)
HOTKEY_X_ID = 913  # ID cho Hotkey X (Chèn chữ chạy ngầm)

# Hằng số Windows API cho SendInput (Mô phỏng gõ phím)
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

# Đường dẫn file config để lưu API Key (luôn cùng thư mục với file chạy)
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(application_path, "winassist_config.json")

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION)
    ]

# Giả lập thao tác bàn phím (Ctrl + V) bằng ctypes
def send_paste():
    # Nhấn giữ Ctrl (VK_CONTROL = 0x11)
    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
    # Nhấn giữ V (VK_V = 0x56)
    ctypes.windll.user32.keybd_event(0x56, 0, 0, 0)
    time.sleep(0.02)
    # Thả V
    ctypes.windll.user32.keybd_event(0x56, 0, 0x0002, 0)
    # Thả Ctrl
    ctypes.windll.user32.keybd_event(0x11, 0, 0x0002, 0)

# Giả lập gõ từng ký tự với tốc độ ngẫu nhiên tự nhiên (nhấn giữ Esc để dừng khẩn cấp, trả về vị trí dừng)
def type_string(text, start_index=0, min_delay=0.015, max_delay=0.045):
    for i in range(start_index, len(text)):
        char = text[i]
        # Nhấn giữ ESC (VK_ESCAPE = 0x1B) để dừng khẩn cấp
        if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
            winsound.Beep(500, 150)  # Kêu bíp nhẹ báo hiệu đã dừng
            return i  # Trả về chỉ số bị dừng để tiếp tục sau
            
        # Sửa lỗi nhảy con trỏ khi xuống dòng: Gửi phím Enter thực tế thay vì unicode '\n'
        if char == '\n':
            ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)  # Nhấn Enter (VK_RETURN = 0x0D)
            time.sleep(0.02)
            ctypes.windll.user32.keybd_event(0x0D, 0, 0x0002, 0)  # Thả Enter
            time.sleep(0.06)  # Đợi ứng dụng (Word/Chrome) xử lý xuống dòng ổn định
            continue
            
        # Gửi sự kiện nhấn phím (key down)
        ki_down = KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE, 0, None)
        input_down = INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=ki_down))
        ctypes.windll.user32.SendInput(1, ctypes.byref(input_down), ctypes.sizeof(INPUT))
        
        # Gửi sự kiện thả phím (key up)
        ki_up = KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
        input_up = INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=ki_up))
        ctypes.windll.user32.SendInput(1, ctypes.byref(input_up), ctypes.sizeof(INPUT))
        
        # Độ trễ ngẫu nhiên giữa các ký tự (như người thật đang gõ máy)
        time.sleep(random.uniform(min_delay, max_delay))
    return len(text)

# Hàm urlopen an toàn tự động bỏ qua proxy lỗi của hệ thống (nếu có)
def safe_urlopen(req, ssl_ctx, timeout=20):
    try:
        # Thử kết nối trực tiếp trước (bỏ qua registry proxy)
        proxy_handler = urllib.request.ProxyHandler({})
        https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
        opener = urllib.request.build_opener(proxy_handler, https_handler)
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError:
        # Nếu là lỗi HTTP từ server, trả thẳng lỗi ra ngoài (không fallback)
        raise
    except Exception:
        # Nếu là lỗi kết nối (ví dụ cổng proxy bị đóng), fallback lại dùng mặc định
        return urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout)

# BỘ GỌI API GEMINI (HỖ TRỢ CẢ ẢNH VÀ CHỮ)
def generate_gemini_report(prompt, img_base64=None, api_key=""):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    parts = [{"text": prompt}]
    if img_base64:
        parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": img_base64
            }
        })
        
    payload = {
        "contents": [
            {
                "parts": parts
            }
        ]
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers=headers, 
        method="POST"
    )
    
    # Bỏ qua xác thực SSL để tránh lỗi chứng chỉ mạng trên Windows
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with safe_urlopen(req, ssl_ctx, timeout=20) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text_response = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            if text_response.startswith("```"):
                lines = text_response.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text_response = "\n".join(lines).strip()
            
            text_response = text_response.replace("**", "")
            return text_response
            
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", "")
        except:
            err_msg = e.reason
            
        if e.code == 429:
            return f"LỖI: Khóa API Gemini đã hết hạn mức (Quota Exceeded - 429).\nChi tiết: {err_msg}"
        elif e.code in [400, 403]:
            return f"LỖI: Khóa API Gemini không hợp lệ hoặc không có quyền truy cập (403/400).\nChi tiết: {err_msg}"
        else:
            return f"LỖI API từ Google Gemini ({e.code}): {err_msg}"
            
    except Exception as e:
        return f"LỖI kết nối cục bộ (SSL/Mạng): {str(e)}"

# BỘ GỌI API DEEPSEEK (CHỈ HỖ TRỢ VĂN BẢN)
def generate_deepseek_report(prompt, api_key=""):
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers=headers, 
        method="POST"
    )
    
    # Bỏ qua xác thực SSL để tránh lỗi chứng chỉ mạng trên Windows
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with safe_urlopen(req, ssl_ctx, timeout=20) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text_response = res_data["choices"][0]["message"]["content"].strip()
            
            if text_response.startswith("```"):
                lines = text_response.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text_response = "\n".join(lines).strip()
            
            text_response = text_response.replace("**", "")
            return text_response
            
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", "")
        except:
            err_msg = e.reason
            
        if e.code == 429:
            return f"LỖI: Khóa API DeepSeek đã hết hạn mức (Quota Exceeded - 429).\nChi tiết: {err_msg}"
        elif e.code in [400, 401, 403]:
            return f"LỖI: Khóa API DeepSeek không hợp lệ hoặc không có quyền truy cập (401/403/400).\nChi tiết: {err_msg}"
        else:
            return f"LỖI API từ DeepSeek ({e.code}): {err_msg}"
            
    except Exception as e:
        return f"LỖI kết nối cục bộ (SSL/Mạng): {str(e)}"

# BỘ GỌI API OPENROUTER (HỖ TRỢ CẢ ẢNH VÀ CHỮ QUA GEMINI 3.1 FLASH LITE)
def generate_openrouter_report(prompt, img_base64=None, api_key=""):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/winassist",
        "X-Title": "WinAssist IELTS Helper"
    }
    
    if img_base64:
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_base64}"
                }
            }
        ]
    else:
        content = prompt
        
    payload = {
        "model": "google/gemini-3.1-flash-lite",
        "messages": [
            {
                "role": "user",
                "content": content
            }
        ],
        "stream": False
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers=headers, 
        method="POST"
    )
    
    # Bỏ qua xác thực SSL để tránh lỗi chứng chỉ mạng trên Windows
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with safe_urlopen(req, ssl_ctx, timeout=20) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text_response = res_data["choices"][0]["message"]["content"].strip()
            
            if text_response.startswith("```"):
                lines = text_response.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text_response = "\n".join(lines).strip()
            
            text_response = text_response.replace("**", "")
            return text_response
            
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", "")
        except:
            err_msg = e.reason
            
        if e.code == 429:
            return f"LỖI: Khóa API OpenRouter đã hết hạn mức (Quota Exceeded - 429).\nChi tiết: {err_msg}"
        elif e.code in [400, 401, 403]:
            return f"LỖI: Khóa API OpenRouter không hợp lệ hoặc không có quyền truy cập (401/403/400).\nChi tiết: {err_msg}"
        else:
            return f"LỖI API từ OpenRouter ({e.code}): {err_msg}"
            
    except Exception as e:
        return f"LỖI kết nối cục bộ (SSL/Mạng): {str(e)}"

# HÀM WRAPPER ĐỂ TỰ ĐỘNG CHỌN API VÀ PHÂN PHỐI YÊU CẦU
def generate_ielts_report(prompt, img_base64=None, api_key=""):
    if api_key.startswith("sk-or-"):
        return generate_openrouter_report(prompt, img_base64, api_key)
    elif api_key.startswith("sk-"):
        if img_base64:
            return "LỖI: DeepSeek không hỗ trợ Vision đọc ảnh. Vui lòng dán chữ đề bài hoặc bảng số liệu và sử dụng nút 'VIẾT BÀI TỪ CHỮ [AI]'."
        return generate_deepseek_report(prompt, api_key)
    else:
        return generate_gemini_report(prompt, img_base64, api_key)

# Bộ lọc sự kiện native của Windows để bắt Hotkey toàn hệ thống
class NativeEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback_q, callback_z, callback_x):
        super().__init__()
        self.callback_q = callback_q
        self.callback_z = callback_z
        self.callback_x = callback_x

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID:
                    self.callback_q()
                    return True, 0
                elif msg.wParam == HOTKEY_Z_ID:
                    self.callback_z()
                    return True, 0
                elif msg.wParam == HOTKEY_X_ID:
                    self.callback_x()
                    return True, 0
        return False, 0

class WritingHelperUI(QWidget):
    def __init__(self):
        super().__init__()
        
        # Biến trạng thái hiện tại
        self.simulate_typing = True  # Mặc định: Gõ từ từ từng chữ để an toàn
        self.api_key = ""
        self.invisible_cached_report = ""  # Lưu trữ bài viết của chế độ tàng hình
        self.drag_position = None  # Phục vụ việc kéo di chuyển cửa sổ
        self.typing_index = 0
        self.current_typing_text = ""
        self.invisible_typing_index = 0
        self.invisible_typing_text = ""
        
        self.load_config()
        self.init_ui()
        
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    self.api_key = config.get("api_key", "")
            except:
                pass
                
    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump({"api_key": self.api_key}, f)
        except:
            pass

    def init_ui(self):
        # Cài đặt các cờ cho cửa sổ để ẩn kín và nổi bật
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |         # Không viền
            Qt.WindowType.WindowStaysOnTopHint |       # Luôn trên cùng
            Qt.WindowType.Tool                         # Ẩn khỏi Taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Nền bán trong suốt
        self.resize(520, 390)
        
        # Font chữ
        self.main_font = QFont("Segoe UI", 10)
        self.title_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        self.setFont(self.main_font)
        
        # Layout chính
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(8)
        
        # Widget nền
        self.bg_widget = QWidget(self)
        self.bg_widget.setObjectName("BgWidget")
        bg_layout = QVBoxLayout(self.bg_widget)
        bg_layout.setContentsMargins(12, 12, 12, 12)
        bg_layout.setSpacing(8)
        
        # Tiêu đề & Nút Esc ẩn
        title_layout = QHBoxLayout()
        self.title_label = QLabel("WinAssist - IELTS Task 1 AI Writer")
        self.title_label.setFont(self.title_font)
        self.title_label.setStyleSheet("color: #e0e0e0;")
        
        self.esc_label = QLabel("[Esc]: Ẩn")
        self.esc_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.esc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.esc_label)
        bg_layout.addLayout(title_layout)
        
        # --- KHU VỰC ĐIỀU KHIỂN CHÍNH (Dán ảnh & Viết bài) ---
        buttons_layout = QHBoxLayout()
        
        self.btn_write_image = QPushButton("DÁN ẢNH & VIẾT BÀI [AI]")
        self.btn_write_image.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_write_image.setStyleSheet("""
            QPushButton {
                background-color: #0e639c; 
                color: white; 
                border: 1px solid #007acc; 
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
        """)
        self.btn_write_image.clicked.connect(self.process_image_and_write)
        
        self.btn_write_text = QPushButton("VIẾT BÀI TỪ CHỮ [AI]")
        self.btn_write_text.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_write_text.setStyleSheet("""
            QPushButton {
                background-color: #2b7a4b; 
                color: white; 
                border: 1px solid #1e5c35; 
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #35925a;
            }
        """)
        self.btn_write_text.clicked.connect(self.process_text_and_write)
        
        buttons_layout.addWidget(self.btn_write_image)
        buttons_layout.addWidget(self.btn_write_text)
        bg_layout.addLayout(buttons_layout)
        
        # Khung văn bản kết quả bài viết sinh ra
        self.result_text = QTextEdit()
        self.result_text.setPlaceholderText(
            "Nhập hoặc dán chữ đề bài / bảng số liệu vào đây rồi bấm nút 'VIẾT BÀI TỪ CHỮ [AI]'\n"
            "Hoặc chụp ảnh biểu đồ [Win+Shift+S] rồi bấm nút 'DÁN ẢNH & VIẾT BÀI [AI]'.\n\n"
            "Bài viết kết quả sinh ra bởi AI sẽ xuất hiện tại đây..."
        )
        self.result_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                color: #d4d4d4;
                font-size: 11px;
                padding: 6px;
            }
            QTextEdit:focus {
                border: 1px solid #007acc;
            }
        """)
        bg_layout.addWidget(self.result_text)
        
        # Nút hành động chèn bài viết
        self.btn_insert = QPushButton("CHÈN BÀI VIẾT VÀO WORD (ENTER)")
        self.btn_insert.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_insert.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #cccccc;
                border: 1px solid #444444;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                color: white;
            }
        """)
        self.btn_insert.clicked.connect(self.insert_full_article)
        bg_layout.addWidget(self.btn_insert)
        
        # Hàng điều khiển phụ: Chế độ gõ
        control_layout = QHBoxLayout()
        self.typing_checkbox = QCheckBox("Gõ mô phỏng từ từ (An toàn)")
        self.typing_checkbox.setChecked(self.simulate_typing)
        self.typing_checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.typing_checkbox.setStyleSheet("""
            QCheckBox {
                color: #aaaaaa;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                background-color: #333333;
                border: 1px solid #555555;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #0e639c;
                border: 1px solid #007acc;
            }
        """)
        self.typing_checkbox.stateChanged.connect(self.on_typing_mode_change)
        
        self.toggle_hint = QLabel("Tab: Đổi chế độ gõ")
        self.toggle_hint.setStyleSheet("color: #666666; font-size: 11px;")
        self.toggle_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        control_layout.addWidget(self.typing_checkbox)
        control_layout.addWidget(self.toggle_hint)
        bg_layout.addLayout(control_layout)
        
        # Cấu hình API Key ẩn kín
        api_layout = QHBoxLayout()
        lbl_key = QLabel("API Key:")
        lbl_key.setStyleSheet("color: #777777; font-size: 9px;")
        
        self.in_api_key = QLineEdit()
        self.in_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_api_key.setText(self.api_key)
        self.in_api_key.setPlaceholderText("Dán Gemini, DeepSeek hoặc OpenRouter API Key vào đây...")
        self.in_api_key.setStyleSheet("""
            QLineEdit {
                background-color: #222222;
                border: 1px solid #333333;
                color: #777777;
                font-size: 9px;
                padding: 1px 3px;
                border-radius: 2px;
            }
            QLineEdit:focus {
                border: 1px solid #007acc;
                color: #cccccc;
            }
        """)
        self.in_api_key.textChanged.connect(self.on_api_key_change)
        
        api_layout.addWidget(lbl_key)
        api_layout.addWidget(self.in_api_key)
        bg_layout.addLayout(api_layout)
        
        main_layout.addWidget(self.bg_widget)
        self.setLayout(main_layout)
        
        self.setStyleSheet("""
            QWidget#BgWidget {
                background-color: rgba(30, 30, 30, 240);
                border: 1px solid rgba(80, 80, 80, 180);
                border-radius: 10px;
            }
            QLabel {
                color: #cccccc;
            }
        """)
        
        # Tạo size grip ở góc dưới bên phải để co giãn cửa sổ borderless
        self.size_grip = QSizeGrip(self)
        self.size_grip.setStyleSheet("background-color: transparent;")
        
    def on_typing_mode_change(self, state):
        self.simulate_typing = (state == 2)
        
    def on_api_key_change(self, text):
        self.api_key = text.strip()
        self.save_config()

    # BỔ SUNG CÁC SỰ KIỆN KÉO THẢ & CO GIÃN CỬA SỔ
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def resizeEvent(self, event):
        # Định vị size grip luôn ở góc dưới bên phải của cửa sổ
        self.size_grip.setGeometry(self.width() - 15, self.height() - 15, 15, 15)
        super().resizeEvent(event)

    # CHẠY AI NGẦM KHI BẤM CTRL + SHIFT + Z (CHẾ ĐỘ TÀNG HÌNH)
    def process_invisible_ai(self):
        if not self.api_key:
            winsound.Beep(400, 500) # Bíp lỗi: Chưa cấu hình key
            return
            
        # Reset trạng thái gõ dở
        self.typing_index = 0
        self.current_typing_text = ""
        self.invisible_typing_index = 0
        self.invisible_typing_text = ""
        self.btn_insert.setText("CHÈN BÀI VIẾT VÀO WORD (ENTER)")
        self.btn_insert.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: #cccccc;
                border: 1px solid #444444;
                padding: 6px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                color: white;
            }
        """)
            
        # Phát 1 tiếng bíp nhẹ báo hiệu đã nhận lệnh chạy ngầm
        winsound.Beep(800, 100)
        
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        img_base64 = None
        user_text = ""
        
        # Nhận diện dữ liệu từ clipboard
        if mime_data.hasImage():
            if self.api_key.startswith("sk-") and not self.api_key.startswith("sk-or-"):
                # DeepSeek không hỗ trợ Vision
                winsound.Beep(400, 500)  # Bíp lỗi
                return
                
            try:
                image = clipboard.image()
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                img_base64 = byte_array.toBase64().data().decode("utf-8")
            except:
                winsound.Beep(400, 500)
                return
        elif mime_data.hasText():
            user_text = mime_data.text().strip()
            
        if not img_base64 and not user_text:
            winsound.Beep(400, 500) # Bíp lỗi: Clipboard rỗng
            return
            
        # Chuẩn bị prompt
        if img_base64:
            prompt = (
                "You are an IELTS Writing expert. Write a Writing Task 1 report based on the provided chart image.\n"
                "Your target is to simulate a realistic, slightly weak student essay at a Band 5.0 - 5.5 level. This means:\n"
                "- The vocabulary MUST be extremely basic, easy to remember, and easy to understand. Use simple A1-A2 level words only. For example, use 'show' instead of 'illustrate', 'percent' instead of 'proportion/percentage', 'types/methods' instead of 'categories', 'went up/rose' instead of 'experienced an increase', 'went down/fell' instead of 'decreased significantly', 'same' instead of 'stable/constant'. Do NOT use any complex or academic vocabulary.\n"
                "- Keep the sentence structures very basic. Use simple and compound sentences (mostly using 'and', 'but', 'also', 'so'). Avoid complex sentence structures, passive voice, or natural native phrasing.\n"
                "- It is acceptable and expected to have a few minor, natural grammatical mistakes (such as missing articles like 'the' or simple preposition errors) but ensure the overall meaning is still clear.\n"
                "- Do NOT use advanced cohesive devices or transitional phrases (like 'meanwhile', 'in contrast', 'significantly', 'during this five-year period', 'rising slightly'). Instead, use basic ones like 'on the other hand', 'also', 'however', 'in 2004', 'in 2009'.\n"
                "- Keep the structure clear (Introduction paragraph, then the Overall/Overview paragraph right after the Introduction, and then 2 Detail Body Paragraphs). The Overall/Overview paragraph MUST be the second paragraph, immediately after the Introduction.\n"
                "- In the Introduction paragraph, list/name the main items, categories, or groups compared in the chart.\n"
                "- Ensure all major data points (start and end values, key comparisons) are correctly reported from the chart.\n"
                "- The length of the report MUST be between 165 and 195 words. Never write less than 160 words. To reach this length using simple language, you must explicitly write down the data points (numbers/percentages) for all categories and compare them one by one across both years instead of grouping them briefly.\n"
                "Respond ONLY with the generated report text. Do not include any title, markdown formatting (no bold/italics, no **), or extra remarks."
            )
        else:
            prompt = (
                "You are an IELTS Writing expert. Write a Writing Task 1 report based on the following chart description, topic, or table data:\n\n"
                f"{user_text}\n\n"
                "Your target is to simulate a realistic, slightly weak student essay at a Band 5.0 - 5.5 level. This means:\n"
                "- The vocabulary MUST be extremely basic, easy to remember, and easy to understand. Use simple A1-A2 level words only. For example, use 'show' instead of 'illustrate', 'percent' instead of 'proportion/percentage', 'types/methods' instead of 'categories', 'went up/rose' instead of 'experienced an increase', 'went down/fell' instead of 'decreased significantly', 'same' instead of 'stable/constant'. Do NOT use any complex or academic vocabulary.\n"
                "- Keep the sentence structures very basic. Use simple and compound sentences (mostly using 'and', 'but', 'also', 'so'). Avoid complex sentence structures, passive voice, or natural native phrasing.\n"
                "- It is acceptable and expected to have a few minor, natural grammatical mistakes (such as missing articles like 'the' or simple preposition errors) but ensure the overall meaning is still clear.\n"
                "- Do NOT use advanced cohesive devices or transitional phrases (like 'meanwhile', 'in contrast', 'significantly', 'during this five-year period', 'rising slightly'). Instead, use basic ones like 'on the other hand', 'also', 'however', 'in 2004', 'in 2009'.\n"
                "- Keep the structure clear (Introduction paragraph, then the Overall/Overview paragraph right after the Introduction, and then 2 Detail Body Paragraphs). The Overall/Overview paragraph MUST be the second paragraph, immediately after the Introduction.\n"
                "- In the Introduction paragraph, list/name the main items, categories, or groups compared in the chart.\n"
                "- Ensure all major data points (start and end values, key comparisons) are correctly reported.\n"
                "- The length of the report MUST be between 165 and 195 words. Never write less than 160 words. To reach this length using simple language, you must explicitly write down the data points (numbers/percentages) for all categories and compare them one by one across both years instead of grouping them briefly.\n"
                "Respond ONLY with the generated report text. Do not include any title, markdown formatting (no bold/italics, no **), or extra remarks."
            )
            
        try:
            # Gọi API chạy ngầm
            report = generate_ielts_report(prompt, img_base64, self.api_key)
            
            if report and not report.startswith("LỖI"):
                self.invisible_cached_report = report
                # Đồng bộ ghi kết quả vào kết quả UI luôn để người dùng xem lại nếu cần
                self.result_text.setPlainText(report)
                # Phát 2 tiếng bíp báo hiệu thành công
                winsound.Beep(1200, 150)
                winsound.Beep(1200, 150)
            else:
                winsound.Beep(400, 500) # Bíp lỗi từ AI
        except:
            winsound.Beep(400, 500)

    # TỰ ĐỘNG CHÈN BÀI VIẾT CTRL + SHIFT + X (CHẾ ĐỘ TÀNG HÌNH)
    def insert_invisible_report(self):
        text = self.invisible_cached_report.strip()
        if not text:
            winsound.Beep(400, 200) # Bíp lỗi: Chưa có bài viết trong bộ nhớ đệm
            return
            
        time.sleep(0.08)
        
        if self.simulate_typing:
            if self.invisible_typing_text != text:
                self.invisible_typing_text = text
                self.invisible_typing_index = 0
                
            stop_idx = type_string(text, start_index=self.invisible_typing_index)
            self.invisible_typing_index = stop_idx
            
            if self.invisible_typing_index >= len(text):
                # Gõ xong hoàn toàn -> reset trạng thái tàng hình
                self.invisible_typing_index = 0
                self.invisible_typing_text = ""
        else:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
            send_paste()

    # THỰC THI GỌI AI PHÂN TÍCH & VIẾT BÀI TRỰC TIẾP TỪ ẢNH CLIPBOARD (GEMINI / OPENROUTER)
    def process_image_and_write(self):
        if not self.api_key:
            self.result_text.setPlainText("LỖI: Vui lòng nhập API Key ở ô cấu hình góc dưới trước!")
            return
            
        # Reset trạng thái gõ dở
        self.typing_index = 0
        self.current_typing_text = ""
        self.invisible_typing_index = 0
        self.invisible_typing_text = ""
        self.btn_insert.setText("CHÈN BÀI VIẾT VÀO WORD (ENTER)")
            
        if self.api_key.startswith("sk-") and not self.api_key.startswith("sk-or-"):
            self.result_text.setPlainText(
                "LỖI: DeepSeek không hỗ trợ Vision đọc ảnh.\n"
                "Vui lòng dán đề bài hoặc bảng số liệu dạng văn bản trực tiếp vào ô này, "
                "sau đó bấm nút 'VIẾT BÀI TỪ CHỮ [AI]'."
            )
            return
            
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        if not mime_data.hasImage():
            self.result_text.setPlainText("LỖI: Không tìm thấy ảnh trong clipboard!\nHãy dùng phím tắt [Win + Shift + S] để chụp ảnh biểu đồ trước khi bấm nút này.")
            return
            
        engine_name = "OpenRouter" if self.api_key.startswith("sk-or-") else "Gemini"
        self.result_text.setPlainText(f"Đang đọc ảnh biểu đồ và viết bài bằng AI {engine_name}...\nVui lòng đợi từ 3-7 giây...")
        QCoreApplication.processEvents()
        
        try:
            image = clipboard.image()
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            img_base64 = byte_array.toBase64().data().decode("utf-8")
            
            prompt = (
                "You are an IELTS Writing expert. Write a Writing Task 1 report based on the provided chart image.\n"
                "Your target is to simulate a realistic, slightly weak student essay at a Band 5.0 - 5.5 level. This means:\n"
                "- The vocabulary MUST be extremely basic, easy to remember, and easy to understand. Use simple A1-A2 level words only. For example, use 'show' instead of 'illustrate', 'percent' instead of 'proportion/percentage', 'types/methods' instead of 'categories', 'went up/rose' instead of 'experienced an increase', 'went down/fell' instead of 'decreased significantly', 'same' instead of 'stable/constant'. Do NOT use any complex or academic vocabulary.\n"
                "- Keep the sentence structures very basic. Use simple and compound sentences (mostly using 'and', 'but', 'also', 'so'). Avoid complex sentence structures, passive voice, or natural native phrasing.\n"
                "- It is acceptable and expected to have a few minor, natural grammatical mistakes (such as missing articles like 'the' or simple preposition errors) but ensure the overall meaning is still clear.\n"
                "- Do NOT use advanced cohesive devices or transitional phrases (like 'meanwhile', 'in contrast', 'significantly', 'during this five-year period', 'rising slightly'). Instead, use basic ones like 'on the other hand', 'also', 'however', 'in 2004', 'in 2009'.\n"
                "- Keep the structure clear (Introduction paragraph, then the Overall/Overview paragraph right after the Introduction, and then 2 Detail Body Paragraphs). The Overall/Overview paragraph MUST be the second paragraph, immediately after the Introduction.\n"
                "- In the Introduction paragraph, list/name the main items, categories, or groups compared in the chart.\n"
                "- Ensure all major data points (start and end values, key comparisons) are correctly reported from the chart.\n"
                "- The length of the report MUST be between 165 and 195 words. Never write less than 160 words. To reach this length using simple language, you must explicitly write down the data points (numbers/percentages) for all categories and compare them one by one across both years instead of grouping them briefly.\n"
                "Respond ONLY with the generated report text. Do not include any title, markdown formatting (no bold/italics, no **), or extra remarks."
            )
            
            # Gọi API sinh bài viết hoàn chỉnh (Gemini hoặc OpenRouter)
            report = generate_ielts_report(prompt, img_base64, self.api_key)
            
            self.result_text.setPlainText(report)
            
            if report and not report.startswith("LỖI"):
                # Đổi màu nút chèn để gợi ý người dùng bấm
                self.btn_insert.setStyleSheet("""
                    QPushButton {
                        background-color: #0e639c;
                        color: white;
                        border: 1px solid #007acc;
                        padding: 6px;
                        border-radius: 4px;
                    }
                """)
        except Exception as e:
            self.result_text.setPlainText(f"LỖI trong quá trình xử lý: {e}")

    # THỰC THI GỌI AI PHÂN TÍCH & VIẾT BÀI TỪ CHỮ ĐỀ BÀI (DEEPSEEK, OPENROUTER HOẶC GEMINI TEXT)
    def process_text_and_write(self):
        if not self.api_key:
            self.result_text.setPlainText("LỖI: Vui lòng nhập API Key ở ô cấu hình góc dưới trước!")
            return
            
        # Reset trạng thái gõ dở
        self.typing_index = 0
        self.current_typing_text = ""
        self.invisible_typing_index = 0
        self.invisible_typing_text = ""
        self.btn_insert.setText("CHÈN BÀI VIẾT VÀO WORD (ENTER)")
            
        user_text = self.result_text.toPlainText().strip()
        
        # Nếu ô văn bản rỗng, hoặc chứa bài viết cũ/thông báo lỗi/placeholder thì yêu cầu nhập đề bài
        if not user_text or user_text.startswith("LỖI") or user_text.startswith("Đang") or user_text.startswith("Nhập hoặc dán"):
            self.result_text.setPlainText(
                "LỖI: Vui lòng dán đề bài hoặc bảng số liệu dạng văn bản/số liệu vào ô này trước, "
                "sau đó bấm nút 'VIẾT BÀI TỪ CHỮ [AI]'."
            )
            return
            
        if self.api_key.startswith("sk-or-"):
            engine_name = "OpenRouter"
        elif self.api_key.startswith("sk-"):
            engine_name = "DeepSeek"
        else:
            engine_name = "Gemini"
            
        self.result_text.setPlainText(f"Đang phân tích văn bản và viết bài bằng AI {engine_name}...\nVui lòng đợi từ 3-7 giây...")
        QCoreApplication.processEvents()
        
        try:
            prompt = (
                "You are an IELTS Writing expert. Write a Writing Task 1 report based on the following chart description, topic, or table data:\n\n"
                f"{user_text}\n\n"
                "Your target is to simulate a realistic, slightly weak student essay at a Band 5.0 - 5.5 level. This means:\n"
                "- The vocabulary MUST be extremely basic, easy to remember, and easy to understand. Use simple A1-A2 level words only. For example, use 'show' instead of 'illustrate', 'percent' instead of 'proportion/percentage', 'types/methods' instead of 'categories', 'went up/rose' instead of 'experienced an increase', 'went down/fell' instead of 'decreased significantly', 'same' instead of 'stable/constant'. Do NOT use any complex or academic vocabulary.\n"
                "- Keep the sentence structures very basic. Use simple and compound sentences (mostly using 'and', 'but', 'also', 'so'). Avoid complex sentence structures, passive voice, or natural native phrasing.\n"
                "- It is acceptable and expected to have a few minor, natural grammatical mistakes (such as missing articles like 'the' or simple preposition errors) but ensure the overall meaning is still clear.\n"
                "- Do NOT use advanced cohesive devices or transitional phrases (like 'meanwhile', 'in contrast', 'significantly', 'during this five-year period', 'rising slightly'). Instead, use basic ones like 'on the other hand', 'also', 'however', 'in 2004', 'in 2009'.\n"
                "- Keep the structure clear (Introduction paragraph, then the Overall/Overview paragraph right after the Introduction, and then 2 Detail Body Paragraphs). The Overall/Overview paragraph MUST be the second paragraph, immediately after the Introduction.\n"
                "- In the Introduction paragraph, list/name the main items, categories, or groups compared in the chart.\n"
                "- Ensure all major data points (start and end values, key comparisons) are correctly reported.\n"
                "- The length of the report MUST be between 165 and 195 words. Never write less than 160 words. To reach this length using simple language, you must explicitly write down the data points (numbers/percentages) for all categories and compare them one by one across both years instead of grouping them briefly.\n"
                "Respond ONLY with the generated report text. Do not include any title, markdown formatting (no bold/italics, no **), or extra remarks."
            )
            
            # Gọi API sinh bài viết hoàn chỉnh dạng text-only
            report = generate_ielts_report(prompt, None, self.api_key)
            
            self.result_text.setPlainText(report)
            
            if report and not report.startswith("LỖI"):
                # Đổi màu nút chèn để gợi ý người dùng bấm
                self.btn_insert.setStyleSheet("""
                    QPushButton {
                        background-color: #0e639c;
                        color: white;
                        border: 1px solid #007acc;
                        padding: 6px;
                        border-radius: 4px;
                    }
                """)
        except Exception as e:
            self.result_text.setPlainText(f"LỖI trong quá trình xử lý: {e}")

    def insert_full_article(self):
        text = self.result_text.toPlainText().strip()
        if not text or text.startswith("LỖI") or text.startswith("Đang") or text.startswith("Nhập hoặc dán"):
            return
            
        self.hide()
        time.sleep(0.08)
        
        if self.simulate_typing:
            if self.current_typing_text != text:
                self.current_typing_text = text
                self.typing_index = 0
                
            stop_idx = type_string(text, start_index=self.typing_index)
            self.typing_index = stop_idx
            
            if self.typing_index >= len(text):
                # Gõ xong hoàn toàn -> reset trạng thái
                self.typing_index = 0
                self.current_typing_text = ""
                self.btn_insert.setText("CHÈN BÀI VIẾT VÀO WORD (ENTER)")
                self.btn_insert.setStyleSheet("""
                    QPushButton {
                        background-color: #2d2d2d;
                        color: #cccccc;
                        border: 1px solid #444444;
                        padding: 6px;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: #3d3d3d;
                        color: white;
                    }
                """)
            else:
                # Bị dừng nửa chừng (bấm Esc) -> cập nhật màu cam nổi bật và đổi chữ nút để tiếp tục
                self.btn_insert.setText("TIẾP TỤC CHÈN BÀI VIẾT (ENTER)")
                self.btn_insert.setStyleSheet("""
                    QPushButton {
                        background-color: #d87018;
                        color: white;
                        border: 1px solid #c25e0e;
                        padding: 6px;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: #ed8024;
                    }
                """)
        else:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
            send_paste()

    def toggle_show(self):
        if self.isVisible():
            self.hide()
        else:
            cursor = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
            
            screen = QGuiApplication.primaryScreen().geometry()
            x = min(cursor.x - 50, screen.width() - self.width() - 20)
            y = min(cursor.y - 50, screen.height() - self.height() - 50)
            x = max(20, x)
            y = max(20, y)
            
            self.move(x, y)
            self.show()
            self.raise_()
            self.activateWindow()

    def keyPressEvent(self, event):
        key = event.key()
        
        if key == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            
        elif key == Qt.Key.Key_Tab:
            self.typing_checkbox.setChecked(not self.typing_checkbox.isChecked())
            event.accept()
            
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.insert_full_article()
            event.accept()
            
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                self.hide()
        super().changeEvent(event)

# Khởi tạo System Tray Icon ẩn kín
def setup_tray_icon(app, window):
    tray = QSystemTrayIcon(window)
    
    icon = QIcon.fromTheme("drive-harddisk", QIcon())
    if icon.isNull():
        pixmap = QGuiApplication.primaryScreen().grabWindow(0).copy(0,0,16,16)
        icon = QIcon(pixmap)
        
    tray.setIcon(icon)
    tray.setToolTip("WinAssist Service")
    
    menu = QMenu()
    show_action = QAction("Hiện trợ lý", window)
    show_action.triggered.connect(window.toggle_show)
    
    exit_action = QAction("Thoát", window)
    exit_action.triggered.connect(app.quit)
    
    menu.addAction(show_action)
    menu.addSeparator()
    menu.addAction(exit_action)
    
    tray.setContextMenu(menu)
    tray.show()
    
    tray.activated.connect(lambda reason: window.toggle_show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    return tray

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    window = WritingHelperUI()
    tray = setup_tray_icon(app, window)
    
    # Đăng ký 3 hotkeys:
    # 1. Ctrl + Shift + Q (Hiện UI)
    if not ctypes.windll.user32.RegisterHotKey(0, HOTKEY_ID, 0x0006, 0x51):
        print("Không thể đăng ký Hotkey Q!")
        
    # 2. Ctrl + Shift + Z (AI chạy ngầm)
    if not ctypes.windll.user32.RegisterHotKey(0, HOTKEY_Z_ID, 0x0006, 0x5A):
        print("Không thể đăng ký Hotkey Z!")
        
    # 3. Ctrl + Shift + X (Chèn chữ chạy ngầm)
    if not ctypes.windll.user32.RegisterHotKey(0, HOTKEY_X_ID, 0x0006, 0x58):
        print("Không thể đăng ký Hotkey X!")
        
    event_filter = NativeEventFilter(
        window.toggle_show,
        window.process_invisible_ai,
        window.insert_invisible_report
    )
    app.installNativeEventFilter(event_filter)
    
    app.aboutToQuit.connect(lambda: (
        ctypes.windll.user32.UnregisterHotKey(0, HOTKEY_ID),
        ctypes.windll.user32.UnregisterHotKey(0, HOTKEY_Z_ID),
        ctypes.windll.user32.UnregisterHotKey(0, HOTKEY_X_ID)
     ))
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
