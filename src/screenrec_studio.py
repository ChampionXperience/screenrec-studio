"""ScreenRec Studio - GPU-accelerated screen recorder for Windows (GPL-3.0-or-later).

- Ekran yakalama: FFmpeg ddagrab (Windows Desktop Duplication, GPU tarafinda)
- Kodlama: NVIDIA NVENC (H.264 / HEVC / AV1), Intel QSV, AMD AMF (deneysel) veya CPU x264
- Fare vurgusu: imlecin etrafinda renkli halka/daire + tiklama dalgasi
- Duraklatma: imlecin son konumunu hatirlar, devam edince imleci oraya geri koyar
- Ses: sistem sesi (WASAPI loopback) ve mikrofon, video ile zaman hizali
- Atanabilir global kisayollar, canli cizim, mercek, alana zoom, tus gosterimi, webcam
- Turkce / English arayuz, GitHub Releases uzerinden guncelleme
"""
import ctypes
import glob
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import warnings
import wave
import webbrowser
from ctypes import wintypes
from datetime import datetime

import numpy as np
from PySide6.QtCore import (QEvent, QLocale, QObject, QPoint, QPointF, QRect, QRectF, QSettings, QThread, QTimer,
                            Qt, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMenu, QMessageBox, QProgressDialog, QPushButton,
    QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

# dxcam (comtypes) soundcard'dan once yuklenmeli: ikisi de COM'u baslatir, ters sirada comtypes hata verir
try:
    import dxcam
except Exception:  # noqa: BLE001
    dxcam = None
try:
    import soundcard
    warnings.filterwarnings("ignore", category=soundcard.SoundcardRuntimeWarning)
except Exception:  # noqa: BLE001
    soundcard = None
try:
    import zmq
except Exception:  # noqa: BLE001
    zmq = None

APP_NAME = "ScreenRec Studio"
VERSION = "1.0.0"
AUTHOR = "ChampionXperience"
AUTHOR_URL = "https://blog.championxperience.com"
GITHUB_REPO = "ChampionXperience/screenrec-studio"
FROZEN = getattr(sys, "frozen", False)  # PyInstaller ile paketlenmis mi
# APP_DIR: .exe'nin (veya betigin) klasoru; RES_DIR: paketin icindeki kaynaklar (ikon, FFmpeg)
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(APP_DIR) if not FROZEN else APP_DIR)
# Ayarlar kullanicinin AppData klasorunde tutulur: program klasoru (Program Files) yazilamayabilir
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.ini")
ICON_PATH = next((p for p in (os.path.join(RES_DIR, "assets", "icon.ico"), os.path.join(DATA_DIR, "icon.ico"))
                  if os.path.isfile(p)), os.path.join(DATA_DIR, "icon.ico"))
CREATE_NO_WINDOW = 0x08000000

# --------------------------------------------------------------------------- Dil / Language

LANG = "tr"
STRINGS = {
    "app_title": ("ScreenRec Studio", "ScreenRec Studio"),
    "status_idle": ("Hazır", "Ready"),
    "status_countdown": ("Başlıyor... {n}", "Starting... {n}"),
    "status_rec": ("● KAYIT  {clock}", "● REC  {clock}"),
    "status_paused": ("❚❚ DURAKLATILDI  {clock}", "❚❚ PAUSED  {clock}"),
    "status_saving": ("Video birleştiriliyor...", "Finalizing video..."),
    "btn_start": ("● Başlat", "● Start"),
    "btn_resume": ("▶ Devam", "▶ Resume"),
    "btn_pause": ("❚❚ Duraklat", "❚❚ Pause"),
    "btn_stop": ("■ Durdur", "■ Stop"),
    "btn_cancel": ("İptal", "Cancel"),
    "btn_saving": ("Kaydediliyor...", "Saving..."),
    "grp_video": ("Video ve kodlama", "Video && encoding"),
    "monitor": ("Ekran:", "Display:"),
    "monitor_item": ("Ekran {i}: {m}", "Display {i}: {m}"),
    "primary": ("(ana ekran)", "(primary)"),
    "area": ("Kayıt alanı:", "Capture area:"),
    "area_full": ("Tüm ekran ({w}×{h})", "Full screen ({w}×{h})"),
    "area_region": ("{w}×{h} alan, konum ({x}, {y})", "{w}×{h} region at ({x}, {y})"),
    "pick_area": ("Ekranda seç…", "Select on screen…"),
    "full_screen": ("Tüm ekran", "Full screen"),
    "pick_tip": ("Herhangi bir ekranda sürükleyerek alan seçin veya tıklayarak o ekranın tamamını seçin.",
                 "Drag on any display to select an area, or click to select that whole display."),
    "pick_hint": ("Kaydedilecek alanı sürükleyerek seçin\nBu ekranın tamamı için tıklayın  ·  İptal: Esc",
                  "Drag to select the area to record\nClick for this whole display  ·  Esc to cancel"),
    "minibar": ("Kayıt sırasında mini kontrol penceresi göster (sadece siz görürsünüz)",
                "Show a mini control window while recording (only you can see it)"),
    "frame": ("Seçili alanın etrafında çerçeve göster (kayda girmez)",
              "Show a frame around the selected area (not recorded)"),
    "minimize": ("Kayıt başlayınca bu pencereyi simge durumuna küçült",
                 "Minimize this window when recording starts"),
    "fps": ("Kare hızı (FPS):", "Frame rate (FPS):"),
    "encoder": ("Kodlayıcı:", "Encoder:"),
    "enc_searching": ("Kodlayıcılar aranıyor...", "Detecting encoders..."),
    "preset": ("Kalite ön ayarı:", "Quality preset:"),
    "p7": ("En yüksek kalite", "Highest quality"),
    "p6": ("Çok yüksek kalite", "Very high quality"),
    "p5": ("Dengeli", "Balanced"),
    "p4": ("Hızlı", "Fast"),
    "p3": ("En hızlı / küçük dosya", "Fastest / smaller file"),
    "preset_item": ("{name}  (NVENC {p}, CQ {cq})", "{name}  (NVENC {p}, CQ {cq})"),
    "preset_tip": ("Ön ayar, kodlayıcının harcadığı çabayı ve önerilen CQ değerini birlikte ayarlar. "
                   "CQ'yu sonra elle de değiştirebilirsiniz: düşük CQ = daha yüksek kalite, daha büyük dosya.",
                   "The preset sets both the encoder effort and a recommended CQ value. "
                   "You can still fine-tune CQ by hand: lower CQ = higher quality, bigger file."),
    "quality": ("Kalite (CQ):", "Quality (CQ):"),
    "q_lossless": ("kayıpsıza yakın", "near lossless"),
    "q_vhigh": ("çok yüksek", "very high"),
    "q_high": ("yüksek", "high"),
    "q_med": ("orta", "medium"),
    "yuv444": ("4:4:4 renk (en keskin yazı; bazı oynatıcılarda açılmaz)",
               "4:4:4 chroma (sharpest text; some players can't open it)"),
    "yuv444_tip": ("Normal videolar (4:2:0) rengi 4 pikselde bir saklar; parlaklık tam çözünürlükte kalır. "
                   "Bu yüzden renkli ince yazılar ve çizgiler (ör. kod renklendirmesi, mavi üstüne kırmızı yazı) "
                   "kenarlarda bulanık/renk saçağı gösterebilir.\n4:4:4 rengi her pikselde saklar: renkli yazılar "
                   "jilet gibi kalır, dosya biraz büyür.\nDezavantaj: Windows Medya Oynatıcı, tarayıcılar, telefonlar "
                   "ve bazı video düzenleyiciler açamaz; VLC ve mpv açar. Sadece NVIDIA H.264/HEVC ve CPU x264 ile "
                   "çalışır.",
                   "Normal video (4:2:0) stores color once per 4 pixels while brightness stays full resolution, so "
                   "thin colored text and lines (e.g. syntax highlighting, red on blue) can look blurry or fringed.\n"
                   "4:4:4 stores color for every pixel: colored text stays razor sharp, files get a bit bigger.\n"
                   "Downside: Windows Media Player, browsers, phones and some editors can't open it; VLC and mpv "
                   "can. Works only with NVIDIA H.264/HEVC and CPU x264."),
    "container": ("Dosya türü:", "File type:"),
    "out_dir": ("Kayıt klasörü:", "Output folder:"),
    "auto": ("otomatik", "automatic"),
    "pick_ffmpeg": ("ffmpeg.exe seç", "Select ffmpeg.exe"),
    "enc_h264_nvenc": ("NVIDIA H.264 (NVENC) - en uyumlu", "NVIDIA H.264 (NVENC) - most compatible"),
    "enc_hevc_nvenc": ("NVIDIA HEVC/H.265 (NVENC) - aynı kalite, daha küçük dosya",
                       "NVIDIA HEVC/H.265 (NVENC) - same quality, smaller file"),
    "enc_av1_nvenc": ("NVIDIA AV1 (NVENC) - en verimli, yeni oynatıcılar",
                      "NVIDIA AV1 (NVENC) - most efficient, newer players"),
    "enc_h264_amf": ("AMD H.264 (AMF) - deneysel", "AMD H.264 (AMF) - experimental"),
    "enc_hevc_amf": ("AMD HEVC (AMF) - deneysel", "AMD HEVC (AMF) - experimental"),
    "hint_nv_driver": ("⚠ NVIDIA ekran kartı bulundu ama sürücü eski. NVENC için sürücüyü {v} veya üzeri "
                       "bir sürüme güncelleyin (nvidia.com/drivers).",
                       "⚠ NVIDIA GPU found but the driver is too old. Update the driver to {v} or newer "
                       "for NVENC (nvidia.com/drivers)."),
    "hint_no_gpu": ("Donanım kodlayıcı bulunamadı; kayıt işlemciyle yapılacak (daha yavaş).",
                    "No hardware encoder found; recording will use the CPU (slower)."),
    "enc_h264_qsv": ("Intel H.264 (QuickSync)", "Intel H.264 (QuickSync)"),
    "enc_hevc_qsv": ("Intel HEVC (QuickSync)", "Intel HEVC (QuickSync)"),
    "enc_libx264": ("CPU H.264 (x264) - yedek", "CPU H.264 (x264) - fallback"),
    "grp_mouse": ("Fare vurgusu", "Mouse highlight"),
    "draw_cursor": ("Fare imlecini kayda ekle", "Include the mouse cursor in the recording"),
    "highlight": ("İmleç etrafında vurgu göster", "Show a highlight around the cursor"),
    "style": ("Stil:", "Style:"),
    "style_fill": ("Dolu daire", "Filled circle"),
    "style_ring": ("Halka", "Ring"),
    "style_both": ("Dolu daire + halka", "Filled circle + ring"),
    "hl_color": ("Vurgu rengi:", "Highlight color:"),
    "opacity": ("Saydamlık:", "Opacity:"),
    "radius": ("Yarıçap:", "Radius:"),
    "click_fx": ("Tıklamalarda dalga efekti", "Ripple effect on clicks"),
    "left": ("Sol:", "Left:"),
    "right": ("Sağ:", "Right:"),
    "click_colors": ("Tıklama renkleri:", "Click colors:"),
    "preview": ("Vurguyu önizle", "Preview highlight"),
    "preview_stop": ("■ Önizlemeyi durdur (tekrar tıklayın)", "■ Stop preview (click again)"),
    "preview_tip": ("Önizleme siz kapatana kadar açık kalır. Önizlemeden çıkmak için bu düğmeye tekrar tıklayın.",
                    "The preview stays on until you turn it off. Click this button again to exit the preview."),
    "pick_color": ("Renk seç", "Pick a color"),
    "grp_pause": ("Duraklatma ve diğer", "Pause && other"),
    "restore": ("Devam edince imleci duraklatılan konuma geri getir",
                "On resume, move the cursor back to where it was paused"),
    "marker": ("Duraklatınca imlecin kaldığı yeri ekranda işaretle",
               "Mark the cursor's paused position on screen"),
    "hide_win": ("Bu pencereyi kayıtta gizle", "Hide this window from the recording"),
    "countdown": ("Başlamadan önce geri sayım:", "Countdown before start:"),
    "sec": (" sn", " s"),
    "language": ("Dil / Language:", "Language / Dil:"),
    "grp_audio": ("Ses", "Audio"),
    "sys_audio": ("Sistem sesini kaydet (bilgisayardan çıkan ses)", "Record system audio (what you hear)"),
    "out_dev": ("Çıkış aygıtı:", "Output device:"),
    "sys_level": ("Sistem sesi seviyesi:", "System audio level:"),
    "mic": ("Mikrofonu kaydet", "Record microphone"),
    "mic_dev": ("Mikrofon:", "Microphone:"),
    "mic_level": ("Mikrofon seviyesi:", "Microphone level:"),
    "default_dev": ("(Varsayılan)", "(Default)"),
    "no_soundcard": ("Ses (soundcard paketi yüklü değil)", "Audio (soundcard package not installed)"),
    "grp_hotkeys": ("Kısayol tuşları (her yerde çalışır)", "Hotkeys (work in any app)"),
    "hk_start": ("Kaydı başlat / devam et:", "Start / resume recording:"),
    "hk_pause": ("Duraklat / devam et:", "Pause / resume:"),
    "hk_stop": ("Durdur ve kaydet:", "Stop and save:"),
    "hk_lens": ("Merceği aç / kapat:", "Toggle magnifier:"),
    "hk_zoom": ("Alana zoom yap / çık:", "Zoom into area / exit:"),
    "zoom_hint": ("Zoom yapılacak alanı sürükleyerek seçin\nTıklarsanız o nokta 2 kat büyütülür  ·  İptal: Esc",
                  "Drag to select the area to zoom into\nClick to zoom 2x around that point  ·  Esc to cancel"),
    "zoom_exit": ("✕ Zoom'dan çık", "✕ Exit zoom"),
    "grp_keys": ("Tuş gösterimi", "Keystroke display"),
    "keys_on": ("Kayıt sırasında basılan tuşları ekranda göster", "Show pressed keys on screen while recording"),
    "keys_mode": ("Ne gösterilsin:", "What to show:"),
    "keys_shortcuts": ("Sadece kısayollar (Ctrl/Alt/Win + tuş, Enter, F tuşları...)",
                       "Shortcuts only (Ctrl/Alt/Win + key, Enter, F keys...)"),
    "keys_all": ("Tüm tuşlar (yazılan metin dahil)", "All keys (including typed text)"),
    "keys_pos": ("Konum:", "Position:"),
    "pos_bc": ("Alt orta", "Bottom center"),
    "pos_bl": ("Alt sol", "Bottom left"),
    "pos_br": ("Alt sağ", "Bottom right"),
    "pos_tc": ("Üst orta", "Top center"),
    "keys_size": ("Yazı boyutu:", "Text size:"),
    "size_s": ("Küçük", "Small"),
    "size_m": ("Orta", "Medium"),
    "size_l": ("Büyük", "Large"),
    "keys_preview": ("Tuş gösterimini önizle", "Preview keystroke display"),
    "mouse_left": ("Sol tık", "Left click"),
    "mouse_right": ("Sağ tık", "Right click"),
    "mouse_middle": ("Orta tık", "Middle click"),
    "mouse_wheel_up": ("Tekerlek ↑", "Wheel ↑"),
    "mouse_wheel_down": ("Tekerlek ↓", "Wheel ↓"),
    "mouse_back": ("Geri tuşu", "Back button"),
    "mouse_forward": ("İleri tuşu", "Forward button"),
    "keys_privacy": ("Not: 'Tüm tuşlar' modunda yazdığınız şifreler de videoda görünür.",
                     "Note: in 'All keys' mode, passwords you type will be visible in the video."),
    "grp_cam": ("Webcam", "Webcam"),
    "cam_on": ("Kayıt sırasında webcam penceresini göster", "Show the webcam window while recording"),
    "cam_dev": ("Kamera:", "Camera:"),
    "cam_none": ("Kamera bulunamadı", "No camera found"),
    "cam_shape": ("Şekil:", "Shape:"),
    "cam_rect": ("Yuvarlak köşeli dikdörtgen (16:9)", "Rounded rectangle (16:9)"),
    "cam_size": ("Boyut:", "Size:"),
    "cam_mirror": ("Ayna görüntüsü", "Mirror image"),
    "cam_border": ("Çerçeve:", "Frame:"),
    "cam_preview": ("Webcam'i önizle", "Preview webcam"),
    "cam_tip": ("Pencereyi sürükleyerek taşıyın, fare tekerleğiyle boyutunu değiştirin.",
                "Drag the window to move it; use the mouse wheel to resize it."),
    "cam_starting": ("Kamera açılıyor…", "Starting camera…"),
    "grp_draw": ("Canlı çizim", "Live drawing"),
    "draw_on": ("Kayıt sırasında çizim araçlarını mini pencerede göster",
                "Show drawing tools in the mini window while recording"),
    "draw_tools_rec": ("Araç ve renk seçim listeleri açılınca kayıtta görünsün",
                       "Show the tool and color lists in the recording when opened"),
    "draw_tools_rec_tip": ("Mini pencerenin kendisi her zaman gizlidir. Bu açıkken araç listesine veya renk "
                           "menüsüne tıkladığınızda açılan seçenekler videoda görünür.",
                           "The mini window itself is always hidden. When this is on, the options that open "
                           "when you click the tool list or color menu appear in the video."),
    "draw_color": ("Varsayılan renk:", "Default color:"),
    "draw_width": ("Kalınlık:", "Thickness:"),
    "draw_fade_for": ("Kaybolma süresi:", "Fade after:"),
    "draw_tool": ("Araç:", "Tool:"),
    "draw_tip": ("Çizim modundayken ekrana çizilir; mod kapalıyken çizimler kalır ve fare normal çalışır. "
                 "Sağ tık veya Esc çizim modundan çıkar, Ctrl+Z son çizimi geri alır.",
                 "In drawing mode you draw on the screen; when it is off, drawings stay and the mouse works "
                 "normally. Right-click or Esc leaves drawing mode, Ctrl+Z undoes the last drawing."),
    "hk_draw": ("Çizim modunu aç / kapat:", "Toggle drawing mode:"),
    "hk_clear": ("Tüm çizimleri temizle:", "Clear all drawings:"),
    "hk_undo": ("Son çizimi geri al:", "Undo last drawing:"),
    "tool_pen": ("Kalem", "Pen"),
    "tool_highlighter": ("Fosforlu kalem", "Highlighter"),
    "tool_arrow": ("Ok", "Arrow"),
    "tool_line": ("Çizgi", "Line"),
    "tool_rect": ("Dikdörtgen", "Rectangle"),
    "tool_ellipse": ("Elips", "Ellipse"),
    "tool_number": ("Numaralı işaret", "Numbered marker"),
    "tool_text": ("Metin", "Text"),
    "tool_laser": ("Lazer işaretçi", "Laser pointer"),
    "tool_eraser": ("Silgi", "Eraser"),
    "fade_0": ("Kalıcı", "Permanent"),
    "fade_n": ("{n} sn sonra kaybolur", "Fades after {n} s"),
    "draw_mode_tip": ("Çizim modu aç / kapat", "Toggle drawing mode"),
    "undo_tip": ("Önceki çizime dön (geri al)", "Back to previous drawing (undo)"),
    "redo_tip": ("Sonraki çizime git (ileri al)", "Forward to next drawing (redo)"),
    "clear_tip": ("Tüm çizimleri temizle", "Clear all drawings"),
    "tool_tip": ("Çizim aracı (seçili aracı tekrar seçmek çizim modunu kapatır)",
                 "Drawing tool (choosing the selected tool again turns drawing mode off)"),
    "color_tip": ("Çizim rengi", "Drawing color"),
    "color_more": ("Diğer renk…", "More colors…"),
    "hk_redo": ("Sonraki çizime git (ileri al):", "Redo drawing:"),
    "grp_about": ("Hakkında ve güncellemeler", "About & updates"),
    "about_version": ("sürüm {v}", "version {v}"),
    "upd_auto": ("Açılışta güncellemeleri denetle", "Check for updates at startup"),
    "upd_check": ("Güncellemeleri denetle", "Check for updates"),
    "upd_checking": ("Denetleniyor…", "Checking…"),
    "upd_latest": ("En güncel sürümü kullanıyorsunuz ({v}).", "You're on the latest version ({v})."),
    "upd_skipped": ("{v} sürümü atlandı.", "Version {v} is skipped."),
    "upd_failed": ("Güncelleme denetlenemedi: {e}", "Could not check for updates: {e}"),
    "upd_badge": ("⬆ Yeni sürüm hazır: {v} (tıklayın)", "⬆ New version available: {v} (click)"),
    "upd_available_title": ("Güncelleme var", "Update available"),
    "upd_available": ("{name} {new} yayınlandı (sizdeki: {cur}).\n\nYenilikler:\n{notes}",
                      "{name} {new} is available (you have {cur}).\n\nWhat's new:\n{notes}"),
    "upd_install": ("İndir ve kur", "Download and install"),
    "upd_later": ("Sonra", "Later"),
    "upd_skip": ("Bu sürümü atla", "Skip this version"),
    "upd_downloading": ("Güncelleme indiriliyor…", "Downloading update…"),
    "upd_bad_hash": ("İndirilen dosya doğrulanamadı (SHA-256 uyuşmuyor); güncelleme iptal edildi.",
                     "The downloaded file failed verification (SHA-256 mismatch); update cancelled."),
    "upd_busy": ("Kayıt sürerken güncelleme yapılamaz. Kaydı bitirdikten sonra tekrar deneyin.",
                 "Can't update while recording. Try again after the recording ends."),
    "upd_privacy": ("Güncelleme denetimi sadece GitHub'a en son sürümü sorar; başka veri gönderilmez. Ayarlarınız "
                    "güncellemede korunur.",
                    "The update check only asks GitHub for the latest version; nothing else is sent. Your settings "
                    "are kept when updating."),
    "report": ("Sorun bildir…", "Report a problem…"),
    "project_page": ("Proje sayfası", "Project page"),
    "mic_mute": ("Mikrofonu kapat", "Mute microphone"),
    "mic_unmute": ("Mikrofonu aç (şu an sessiz)", "Unmute microphone (currently muted)"),
    "cam_hide": ("Kamerayı kapat", "Turn camera off"),
    "cam_show": ("Kamerayı aç", "Turn camera on"),
    "cam_error": ("Kamera hatası: {e}", "Camera error: {e}"),
    "grp_lens": ("Mercek (imleç bölgesini yakınlaştır)", "Magnifier (zoom in around the cursor)"),
    "lens_zoom": ("Büyütme:", "Zoom:"),
    "lens_size": ("Mercek boyutu:", "Lens size:"),
    "lens_shape": ("Şekil:", "Shape:"),
    "shape_circle": ("Daire", "Circle"),
    "shape_rounded": ("Yuvarlak köşeli kare", "Rounded square"),
    "lens_color": ("Çerçeve rengi:", "Frame color:"),
    "lens_width": ("Çerçeve kalınlığı:", "Frame width:"),
    "lens_preview": ("Merceği önizle", "Preview magnifier"),
    "lens_mode": ("Kısayol davranışı:", "Hotkey behavior:"),
    "lens_toggle": ("Bas: aç, tekrar bas: kapat", "Press to open, press again to close"),
    "lens_hold": ("Basılı tuttukça açık, bırakınca kapanır", "Open while held, closes on release"),
    "lens_tip": ("Kısayol sadece kayıt sırasında çalışır. Mercek imlecin olduğu yerde açılır, imleci takip "
                 "eder ve kayıtta görünür.",
                 "The hotkey works only while recording. The lens opens at the cursor, follows it and "
                 "appears in the recording."),
    "hk_hint": ("Kutuya tıklayıp tuş kombinasyonuna basın. Örnek: Ctrl+Alt+F9",
                "Click a box and press a key combination, e.g. Ctrl+Alt+F9"),
    "hk_ok": ("Kısayollar hazır. Kayıt yokken sadece 'Kaydı başlat' tuşu ayrılır; diğer tuşlar kayıt "
              "sırasında etkinleşir, kayıt bitince diğer programlara bırakılır.",
              "Hotkeys ready. While not recording only the 'Start' key is reserved; the others become "
              "active during recording and are released to other programs afterwards."),
    "hk_taken": ("{k} başka bir program tarafından kullanılıyor", "{k} is used by another program"),
    "hk_bad": ("{k} desteklenmeyen tuş", "{k} is not a supported key"),
    "hk_warn": ("Uyarı: {msg}. Başka bir kombinasyon seçin.", "Warning: {msg}. Choose another combination."),
    "hk_dup": ("Aynı tuş birden fazla işleme atanamaz.", "The same key can't be used for more than one action."),
    "hk_reset": ("Varsayılanlara dön", "Reset to defaults"),
    "ffmpeg_missing": ("FFmpeg bulunamadı. ffmpeg.exe'yi bu klasöre koyun veya yolunu seçin.",
                       "FFmpeg not found. Put ffmpeg.exe in this folder or select its path."),
    "ffmpeg_missing_item": ("FFmpeg bulunamadı", "FFmpeg not found"),
    "no_encoder": ("Çalışan kodlayıcı yok", "No working encoder"),
    "info_encoders": ("FFmpeg: {ff}\nGPU kodlayıcıları: {encs}", "FFmpeg: {ff}\nGPU encoders: {encs}"),
    "none_cpu": ("yok (CPU kullanılacak)", "none (CPU will be used)"),
    "not_ready": ("FFmpeg veya kodlayıcı hazır değil.", "FFmpeg or the encoder is not ready."),
    "saved_info": ("Kaydedildi: {p}", "Saved: {p}"),
    "done_title": ("Kayıt tamamlandı", "Recording complete"),
    "done_text": ("Video kaydedildi:\n{p}", "Video saved:\n{p}"),
    "open_folder": ("Klasörü aç", "Open folder"),
    "audio_warn": ("\n\nSes uyarısı: {e}", "\n\nAudio warning: {e}"),
    "close_q": ("Kayıt devam ediyor. Durdurup kaydedeyim mi?", "Recording in progress. Stop and save it?"),
    "ff_start_fail": ("FFmpeg başlatılamadı: {e}", "Could not start FFmpeg: {e}"),
    "ff_stopped": ("FFmpeg kaydı durdu:\n{e}", "FFmpeg recording stopped:\n{e}"),
    "audio_open_fail": ("Ses aygıtı açılamadı: {e}", "Could not open the audio device: {e}"),
    "audio_mux_fail": ("Ses eklenemedi:\n{e}", "Could not add the audio:\n{e}"),
    "nothing": ("Kaydedilecek görüntü yok (kayıt çok kısa veya hata oluştu).",
                "Nothing to save (recording too short or an error occurred)."),
    "concat_fail": ("Birleştirme hatası:\n{e}", "Merge error:\n{e}"),
    "parts": ("\nParçalar: {d}", "\nParts: {d}"),
    "file_prefix": ("Kayit", "Recording"),
    "out_folder": ("Ekran Kayitlari", "Screen Recordings"),
}


def t(key, **kw):
    s = STRINGS[key][0 if LANG == "tr" else 1]
    return s.format(**kw) if kw else s


# --------------------------------------------------------------------------- Win32

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


def physical_cursor_pos():
    """Fiziksel piksel konumu; farkli DPI'li ekranlar arasinda kaymadan geri yuklenebilir."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def exclude_from_capture(widget, exclude=True):
    user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE)


def overlay_flags():
    return (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)


def make_icon_pixmap(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1f2430"))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    p.setBrush(QColor(255, 220, 0, 90))
    p.drawEllipse(QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64))
    p.setBrush(QColor("#e53935"))
    p.drawEllipse(QRectF(size * 0.31, size * 0.31, size * 0.38, size * 0.38))
    p.end()
    return pm


# --------------------------------------------------------------------------- FFmpeg

ENCODER_IDS = ["h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_amf", "hevc_amf",
               "h264_qsv", "hevc_qsv", "libx264"]  # tercih sirasi
NVENC_PRESETS = ["p7", "p6", "p5", "p4", "p3"]
PRESET_CQ = {"p7": 16, "p6": 18, "p5": 20, "p4": 23, "p3": 26}  # on ayar secilince onerilen CQ


def ffmpeg_candidates():
    paths = [
        os.path.join(RES_DIR, "ffmpeg", "ffmpeg.exe"),  # kurulum paketiyle gelen
        os.path.join(APP_DIR, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(APP_DIR, "ffmpeg", "ffmpeg.exe"),
        os.path.join(APP_DIR, "ffmpeg.exe"),
    ]
    winget = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    paths += sorted(glob.glob(os.path.join(winget, "*FFmpeg*", "*", "bin", "ffmpeg.exe")), reverse=True)
    which = shutil.which("ffmpeg")
    if which:
        paths.append(which)
    seen, out = set(), []
    for p in paths:
        key = os.path.normcase(os.path.realpath(p))
        if os.path.isfile(p) and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_quiet(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return r.returncode, r.stderr.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def working_encoders(ffmpeg):
    """Bu FFmpeg + surucu ile gercekten acilabilen kodlayicilar ve (varsa) kullaniciya gosterilecek ipucu."""
    ok, hint = [], ""
    for enc in ENCODER_IDS:
        code, err = run_quiet([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                               "-i", "color=c=black:s=1280x720:r=30", "-frames:v", "3",
                               "-c:v", enc, "-f", "null", "-"], timeout=10)
        if code == 0:
            ok.append(enc)
        elif enc == "h264_nvenc" and "minimum required Nvidia driver" in err:
            # NVIDIA kart var ama surucu bu FFmpeg'in NVENC surumune gore eski
            m = re.search(r"minimum required Nvidia driver for nvenc is ([\d.]+)", err)
            hint = t("hint_nv_driver", v=m.group(1) if m else "?")
    return ok, hint


def output_infos():
    """DXGI cikislari (ddagrab output_idx sirasi): fiziksel boyut ve masaustu konumu."""
    try:
        outs = [o for group in dxcam.__dict__["__factory"].outputs for o in group]
        infos = [{"w": o.resolution[0], "h": o.resolution[1],
                  "left": o.desc.DesktopCoordinates.left, "top": o.desc.DesktopCoordinates.top} for o in outs]
        if infos:
            return infos
    except Exception:  # noqa: BLE001
        pass
    return [{"w": round(s.geometry().width() * s.devicePixelRatio()),
             "h": round(s.geometry().height() * s.devicePixelRatio()),
             "left": s.geometry().x(), "top": s.geometry().y()} for s in QApplication.screens()]


def list_monitors():
    return [f"{o['w']}x{o['h']}" + (f"  {t('primary')}" if o["left"] == 0 and o["top"] == 0 else "")
            for o in output_infos()]


def screen_for_output(idx):
    """ddagrab cikisina karsilik gelen QScreen. Windows'ta Qt ekranin sol ust kosesini
    fiziksel konumda tutar, bu yuzden eslestirme koseye gore yapilir."""
    infos = output_infos()
    screens = QApplication.screens()
    if 0 <= idx < len(infos):
        o = infos[idx]
        for s in screens:
            if s.geometry().topLeft() == QPoint(o["left"], o["top"]):
                return s
        for s in screens:
            if round(s.geometry().width() * s.devicePixelRatio()) == o["w"] and \
                    round(s.geometry().height() * s.devicePixelRatio()) == o["h"]:
                return s
    return QApplication.primaryScreen()


def output_for_screen(screen):
    for i in range(len(output_infos())):
        if screen_for_output(i) is screen:
            return i
    return 0


# --------------------------------------------------------------------------- Ses

SAMPLE_RATE = 48000
DEFAULT_DEVICE = "__default__"


def list_speakers():
    try:
        return [s.name for s in soundcard.all_speakers()]
    except Exception:  # noqa: BLE001
        return []


def list_mics():
    try:
        return [m.name for m in soundcard.all_microphones()]
    except Exception:  # noqa: BLE001
        return []


class _AudioSource(threading.Thread):
    """Bir ses aygitini okur; ornekleri ortak t0 anina gore zaman cizgisine yerlestirir.
    Sistem sesi sessizken WASAPI veri vermez; bu bosluklar sessizlikle doldurulur."""

    def __init__(self, device, gain, t0):
        super().__init__(daemon=True)
        self.device, self.gain, self.t0 = device, gain, t0
        self.chunks, self.frames, self.error = [], 0, None
        self.muted = False  # sessizde ornekler sifirlanir, zaman cizgisi korunur
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()

    def run(self):
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        try:
            with self.device.recorder(samplerate=SAMPLE_RATE, blocksize=SAMPLE_RATE // 100) as rec:
                last_data = time.perf_counter()
                while not self.stop_flag.is_set():
                    data = rec.record(numframes=None)
                    now = time.perf_counter()
                    if len(data):
                        if self.frames == 0:
                            lead = int((now - len(data) / SAMPLE_RATE - self.t0) * SAMPLE_RATE)
                            self._push(np.zeros((max(0, lead), 2), np.float32))
                        self._push(np.zeros_like(data) if self.muted else data)
                        last_data = now
                    elif now - last_data > 0.15:
                        missing = int((now - 0.05 - self.t0) * SAMPLE_RATE) - self.frames
                        if missing > 0:
                            self._push(np.zeros((missing, 2), np.float32))
                    time.sleep(0.005)
        except Exception as e:  # noqa: BLE001
            self.error = f"{self.device.name}: {e}"

    def _push(self, data):
        data = np.asarray(data, np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        if self.gain != 1.0:
            data = data * self.gain
        with self.lock:
            self.chunks.append(data)
            self.frames += len(data)

    def available(self):
        with self.lock:
            return sum(len(c) for c in self.chunks)

    def take(self, n):
        out = np.zeros((n, 2), np.float32)
        pos = 0
        with self.lock:
            while pos < n and self.chunks:
                c = self.chunks[0]
                k = min(n - pos, len(c))
                out[pos:pos + k] = c[:k]
                pos += k
                if k == len(c):
                    self.chunks.pop(0)
                else:
                    self.chunks[0] = c[k:]
        return out


class AudioCapture:
    """Sistem sesi + mikrofonu karistirip 48 kHz stereo WAV'a yazar. t0: WAV'in ilk orneginin zamani."""

    def __init__(self, path, system_device, system_gain, mic_device, mic_gain):
        self.path = path
        self.specs = []
        if system_device is not None:
            name = soundcard.default_speaker().name if system_device == DEFAULT_DEVICE else system_device
            self.specs.append((soundcard.get_microphone(name, include_loopback=True), system_gain))
        self.mic_index = None
        if mic_device is not None:
            mic = soundcard.default_microphone() if mic_device == DEFAULT_DEVICE else \
                soundcard.get_microphone(mic_device)
            self.mic_index = len(self.specs)
            self.specs.append((mic, mic_gain))
        self.sources = []
        self.errors = []

    def set_mic_muted(self, muted):
        if self.mic_index is not None and self.sources:
            self.sources[self.mic_index].muted = muted

    def start(self, mic_muted=False):
        self.t0 = time.perf_counter()
        self.sources = [_AudioSource(dev, gain, self.t0) for dev, gain in self.specs]
        self.set_mic_muted(mic_muted)
        for s in self.sources:
            s.start()
        self._wav = wave.open(self.path, "wb")
        self._wav.setnchannels(2)
        self._wav.setsampwidth(2)
        self._wav.setframerate(SAMPLE_RATE)
        self._stop = threading.Event()
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()

    def _mix(self, n):
        mix = np.zeros((n, 2), np.float32)
        for s in self.sources:
            mix += s.take(n)
        self._wav.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())

    def _write_loop(self):
        while not self._stop.wait(0.05):
            alive = [s for s in self.sources if s.error is None]
            n = min((s.available() for s in alive), default=0)
            if n:
                self._mix(n)

    def stop(self):
        for s in self.sources:
            s.stop_flag.set()
        for s in self.sources:
            s.join(3)
        self._stop.set()
        self._writer.join(3)
        n = max((s.available() for s in self.sources), default=0)
        if n:
            self._mix(n)
        self._wav.close()
        self.errors = [s.error for s in self.sources if s.error]


# --------------------------------------------------------------------------- Global kisayollar

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
HOTKEY_START, HOTKEY_PAUSE, HOTKEY_STOP, HOTKEY_LENS, HOTKEY_ZOOM = 1, 2, 3, 4, 5
HOTKEY_DRAW, HOTKEY_CLEAR, HOTKEY_UNDO, HOTKEY_REDO = 6, 7, 8, 9
HOTKEY_DEFAULTS = {HOTKEY_START: "Ctrl+Alt+F9", HOTKEY_PAUSE: "Ctrl+Alt+F10", HOTKEY_STOP: "Ctrl+Alt+F11",
                   HOTKEY_LENS: "Ctrl+Alt+Z", HOTKEY_ZOOM: "Ctrl+Alt+X", HOTKEY_DRAW: "Ctrl+Alt+D",
                   HOTKEY_CLEAR: "Ctrl+Alt+C", HOTKEY_UNDO: "Ctrl+Alt+Backspace", HOTKEY_REDO: ""}
_VK_SPECIAL = {
    Qt.Key_Space: 0x20, Qt.Key_Tab: 0x09, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D, Qt.Key_Escape: 0x1B,
    Qt.Key_Backspace: 0x08, Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27,
    Qt.Key_Down: 0x28, Qt.Key_Pause: 0x13, Qt.Key_Print: 0x2C, Qt.Key_ScrollLock: 0x91,
}


def sequence_to_win(text):
    """'Ctrl+Alt+F9' -> (modifiers, vk). Gecersizse None."""
    seq = QKeySequence.fromString(text, QKeySequence.PortableText)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key, mods = combo.key(), combo.keyboardModifiers()
    k = key.value
    if Qt.Key_A.value <= k <= Qt.Key_Z.value or Qt.Key_0.value <= k <= Qt.Key_9.value:
        vk = k
    elif Qt.Key_F1.value <= k <= Qt.Key_F24.value:
        vk = 0x70 + k - Qt.Key_F1.value
    else:
        vk = _VK_SPECIAL.get(key)
    if vk is None:
        return None
    m = MOD_NOREPEAT
    if mods & Qt.ControlModifier:
        m |= MOD_CONTROL
    if mods & Qt.AltModifier:
        m |= MOD_ALT
    if mods & Qt.ShiftModifier:
        m |= MOD_SHIFT
    if mods & Qt.MetaModifier:
        m |= MOD_WIN
    return m, vk


class HotkeyThread(QThread):
    """Kendi mesaj dongusunde global kisayollari dinler. bindings: {id: 'Ctrl+Alt+F9'}.
    Sadece `active` icindekiler tutulur; digerleri yalnizca cakisma kontrolu icin bir an denenip birakilir,
    boylece o tuslar diger programlarda kullanilabilir kalir."""
    triggered = Signal(int)
    registered = Signal(list)  # kaydedilemeyen (baska programin kullandigi) kisayol id'leri

    def __init__(self, bindings, active):
        super().__init__()
        self.bindings, self.active = bindings, set(active)

    def run(self):
        self._tid = kernel32.GetCurrentThreadId()
        failed, ok = [], []
        for hid, text in self.bindings.items():
            spec = sequence_to_win(text) if text else None
            if spec is None:
                continue
            if not user32.RegisterHotKey(None, hid, *spec):
                failed.append(hid)
            elif hid in self.active:
                ok.append(hid)
            else:
                user32.UnregisterHotKey(None, hid)
        self.registered.emit(failed)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.triggered.emit(int(msg.wParam))
        for hid in ok:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        while self.isRunning() and not getattr(self, "_tid", None):
            time.sleep(0.01)
        if getattr(self, "_tid", None):
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self.wait(2000)


# --------------------------------------------------------------------------- Fare vurgusu

class HighlightOverlay(QWidget):
    """Imleci takip eden, tiklamalari gecirgen, saydam pencere. Kayitta gorunur."""

    def __init__(self):
        super().__init__(None, overlay_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.color = QColor(255, 220, 0)
        self.opacity = 0.35
        self.radius = 28
        self.style = "fill"  # fill | ring | both
        self.click_effect = True
        self.left_color = QColor(255, 60, 60)
        self.right_color = QColor(60, 140, 255)
        self._ripples = []  # (baslangic, renk)
        self._prev = {0x01: False, 0x02: False}
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._resize()

    def configure(self, color, opacity, radius, style, click_effect, left_color, right_color):
        self.color, self.opacity, self.radius, self.style = QColor(color), opacity, radius, style
        self.click_effect = click_effect
        self.left_color, self.right_color = QColor(left_color), QColor(right_color)
        self._resize()
        self.update()

    def _resize(self):
        side = int(self.radius * 2 * 1.9) + 8
        self.setFixedSize(side, side)

    def start(self):
        self._tick()
        self.show()
        self._timer.start(7)

    def stop(self):
        self._timer.stop()
        self._ripples.clear()
        self.hide()

    def _tick(self):
        p = QCursor.pos()
        self.move(p.x() - self.width() // 2, p.y() - self.height() // 2)
        if self.click_effect:
            for vk, col in ((0x01, self.left_color), (0x02, self.right_color)):
                down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if down and not self._prev[vk]:
                    self._ripples.append((time.perf_counter(), col))
                self._prev[vk] = down
        now = time.perf_counter()
        self._ripples = [r for r in self._ripples if now - r[0] < 0.45]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPoint(self.width() // 2, self.height() // 2)
        r = self.radius
        if self.style in ("fill", "both"):
            fill = QColor(self.color)
            fill.setAlphaF(self.opacity)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawEllipse(c, r, r)
        if self.style in ("ring", "both"):
            ring = QColor(self.color)
            ring.setAlphaF(min(1.0, self.opacity + 0.45))
            p.setPen(QPen(ring, max(2, r // 8)))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)
        now = time.perf_counter()
        for start, col in self._ripples:
            k = (now - start) / 0.45
            rr = r * (0.6 + 1.2 * k)
            rc = QColor(col)
            rc.setAlphaF(max(0.0, 0.9 * (1 - k)))
            p.setPen(QPen(rc, max(2.0, r / 6 * (1 - k) + 1)))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, int(rr), int(rr))
        p.end()


class PauseMarker(QWidget):
    """Duraklatildiginda imlecin kaldigi yeri ekranda gosterir (kayda girmez)."""

    def __init__(self):
        super().__init__(None, overlay_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(120, 120)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._anim)

    def show_at(self, pos):
        self.move(pos.x() - 60, pos.y() - 60)
        self.show()
        exclude_from_capture(self)
        self._timer.start(33)

    def hide_marker(self):
        self._timer.stop()
        self.hide()

    def _anim(self):
        self._phase = (self._phase + 0.05) % 1.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPoint(60, 60)
        col = QColor(255, 80, 80)
        for k in (0.0, 0.5):
            ph = (self._phase + k) % 1.0
            col.setAlphaF(1 - ph)
            p.setPen(QPen(col, 3))
            p.drawEllipse(c, int(8 + 40 * ph), int(8 + 40 * ph))
        col.setAlphaF(1.0)
        p.setPen(QPen(col, 2))
        p.drawLine(60, 44, 60, 76)
        p.drawLine(44, 60, 76, 60)
        p.end()


# --------------------------------------------------------------------------- Alan secimi

class _SelectionOverlay(QWidget):
    """Bir ekrani kaplayan karartma; surukleyerek alan, tiklayarak tum ekran secilir."""

    def __init__(self, screen, picker):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.screen_, self.picker = screen, picker
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.start = self.cur = None
        self.hover = False
        self.hint = t("pick_hint")
        self.click_pos = None

    def _rect(self):
        if self.start is None or self.cur is None:
            return None
        return QRect(self.start, self.cur).normalized()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        full = self.rect()
        r = self._rect()
        p.fillRect(full, QColor(0, 0, 0, 120))
        if r:
            # Secili alan neredeyse saydam ama fareyi yakalamaya devam eder
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(r, QColor(0, 0, 0, 1))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#3daee9"), 2))
            p.drawRect(r)
            dpr = self.screen_.devicePixelRatio()
            label = f"{round(r.width() * dpr)} × {round(r.height() * dpr)}"
            f = p.font()
            f.setPointSize(11)
            f.setBold(True)
            p.setFont(f)
            box = p.fontMetrics().boundingRect(label).adjusted(-8, -4, 8, 4)
            box.moveTopLeft(QPoint(r.left(), max(0, r.top() - box.height() - 6)))
            p.fillRect(box, QColor(20, 20, 20, 220))
            p.setPen(Qt.white)
            p.drawText(box, Qt.AlignCenter, label)
        else:
            if self.hover:
                p.setPen(QPen(QColor("#3daee9"), 4))
                p.drawRect(full.adjusted(2, 2, -2, -2))
            f = p.font()
            f.setPointSize(14)
            f.setBold(True)
            p.setFont(f)
            p.setPen(Qt.white)
            p.drawText(full, Qt.AlignCenter, self.hint)
        p.end()

    def enterEvent(self, _):
        self.hover = True
        self.activateWindow()
        self.setFocus()
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.start = self.cur = e.position().toPoint()
            self.update()
        elif e.button() == Qt.RightButton:
            self.picker.cancel()

    def mouseMoveEvent(self, e):
        if self.start is not None:
            self.cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.start is None:
            return
        r = self._rect()
        self.start = self.cur = None
        self.click_pos = e.position().toPoint()
        if r is None or r.width() < 10 or r.height() < 10:
            self.picker.done(self.screen_, None)
        else:
            self.picker.done(self.screen_, r)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.picker.cancel()


class AreaPicker(QObject):
    """Tum ekranlarda secim katmani acar. picked(cikis_idx, (x, y, w, h) | None) - fiziksel piksel."""
    picked = Signal(int, object)
    cancelled = Signal()

    def start(self):
        self.overlays = [_SelectionOverlay(s, self) for s in QApplication.screens()]
        for o in self.overlays:
            o.show()
            o.raise_()
        under = QApplication.screenAt(QCursor.pos())
        for o in self.overlays:
            if o.screen_ is under:
                o.activateWindow()
                o.setFocus()

    def _close(self):
        for o in self.overlays:
            o.close()
        self.overlays = []

    def cancel(self):
        self._close()
        self.cancelled.emit()

    def done(self, screen, rect):
        self._close()
        idx = output_for_screen(screen)
        if rect is None:
            self.picked.emit(idx, None)
            return
        info = output_infos()[idx]
        dpr = screen.devicePixelRatio()
        x = max(0, min(round(rect.x() * dpr), info["w"] - 16))
        y = max(0, min(round(rect.y() * dpr), info["h"] - 16))
        w = min(round(rect.width() * dpr), info["w"] - x)
        h = min(round(rect.height() * dpr), info["h"] - y)
        # 4:2:0 kodlama icin boyutlar cift sayi olmali
        x, y, w, h = x - x % 2, y - y % 2, max(16, w - w % 2), max(16, h - h % 2)
        self.picked.emit(idx, (x, y, w, h))


class ZoomPicker(QObject):
    """Kayit sirasinda zoom alani secimi. Katman sadece kayit alanini kaplar ve kayda girmez.
    picked(QRect): secilen alan, ekran (mantiksal) koordinatlarinda."""
    picked = Signal(QRect)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.overlay = None

    def active(self):
        return self.overlay is not None

    def start(self, screen, area):
        self.area = area
        self.overlay = _SelectionOverlay(screen, self)
        self.overlay.hint = t("zoom_hint")
        self.overlay.setGeometry(area)
        self.overlay.show()
        exclude_from_capture(self.overlay)
        self.overlay.raise_()
        self.overlay.activateWindow()
        self.overlay.setFocus()

    def _close(self):
        if self.overlay:
            self.overlay.close()
            self.overlay = None

    def cancel(self):
        self._close()
        self.cancelled.emit()

    def done(self, _screen, rect):
        if rect is None:
            # Tiklama: o nokta etrafinda 2 kat zoom
            c = self.overlay.click_pos or QPoint(self.area.width() // 2, self.area.height() // 2)
            w, h = self.area.width() // 2, self.area.height() // 2
            rect = QRect(c.x() - w // 2, c.y() - h // 2, w, h)
        self._close()
        self.picked.emit(rect.translated(self.area.topLeft()))


class ZoomExitButton(QPushButton):
    """Zoom alaninin kosesinde, sadece kaydedenin gordugu cikis dugmesi."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton{background:#c62828;color:white;border:none;border-radius:6px;"
                           "padding:6px 12px;font-weight:bold;}QPushButton:hover{background:#e53935;}")

    def show_at(self, rect, label):
        self.setText(label)
        self.adjustSize()
        self.move(rect.right() - self.width() - 8, rect.top() + 8)
        self.show()
        exclude_from_capture(self)


class RegionFrame(QWidget):
    """Kaydedilen (veya zoom yapilan) alanin etrafinda kesikli cerceve (kayda girmez)."""

    def __init__(self, color="#e53935"):
        super().__init__(None, overlay_flags())
        self.color = QColor(color)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

    def show_region(self, output_idx, region):
        screen = screen_for_output(output_idx)
        dpr = screen.devicePixelRatio()
        x, y, w, h = region
        g = screen.geometry()
        m = 4
        self.setGeometry(QRect(g.x() + round(x / dpr) - m, g.y() + round(y / dpr) - m,
                               round(w / dpr) + 2 * m, round(h / dpr) + 2 * m))
        self.show()
        exclude_from_capture(self)

    def paintEvent(self, _):
        p = QPainter(self)
        pen = QPen(self.color, 2, Qt.DashLine)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class _CaptureFilter(QObject):
    """Mini pencereden acilan pencereler (arac listesi, renk menusu, renk secici): ayara gore kayitta
    gorunur ya da gizli. Gizleme pencere ekrana gelmeden (Show olayinda) uygulanir."""

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and obj.isWindow():
            exclude_from_capture(obj, not self.bar.popups_in_recording)
        return False


class _TooltipFilter(QObject):
    """Uygulamamizin ipucu balonlari asla kayda girmesin (ayri pencere olarak acilirlar)."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and isinstance(obj, QWidget) and obj.windowType() == Qt.ToolTip:
            exclude_from_capture(obj)
        return False


class MiniBar(QWidget):
    """Kayit sirasinda kucuk kontrol penceresi: sure, duraklat/devam, durdur. Kayda girmez; surukle-tasi."""
    pause_clicked = Signal()
    stop_clicked = Signal()
    mic_clicked = Signal()
    cam_clicked = Signal()
    draw_toggled = Signal()
    tool_changed = Signal(str)
    color_changed = Signal(QColor)
    undo_clicked = Signal()
    redo_clicked = Signal()
    clear_clicked = Signal()
    _ON = ("QPushButton{background:#444;color:white;border:none;border-radius:6px;font-size:14px;}"
           "QPushButton:hover{background:#5a5a5a;}")
    _OFF = ("QPushButton{background:#7a1f1f;color:white;border:none;border-radius:6px;font-size:14px;}"
            "QPushButton:hover{background:#962626;}")

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)  # pencere etkin degilken de ipucu gosterilsin
        self._drag = None
        self._blink = False
        self._paused = False
        self.popups_in_recording = False
        self.hints = {}  # islem -> kisayol metni, ipuclarinda gosterilir
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(8)
        self.dot = QLabel("●")
        self.time = QLabel("00:00:00")
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self.time.setFont(f)
        self.dot.setFont(f)
        self.time.setStyleSheet("color:white;")
        self.btn_pause = QPushButton()
        self.btn_stop = QPushButton("■")
        for b in (self.btn_pause, self.btn_stop):
            b.setFixedSize(34, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        self.btn_pause.setStyleSheet("QPushButton{background:#444;color:white;border:none;border-radius:6px;"
                                     "font-size:13px;}QPushButton:hover{background:#5a5a5a;}")
        self.btn_stop.setStyleSheet("QPushButton{background:#c62828;color:white;border:none;border-radius:6px;"
                                    "font-size:13px;}QPushButton:hover{background:#e53935;}")
        self.btn_pause.pressed.connect(self.pause_clicked)
        self.btn_stop.pressed.connect(self.stop_clicked)
        self.sep = QLabel()
        self.sep.setFixedSize(1, 22)
        self.sep.setStyleSheet("background:#555;")
        self.btn_mic = QPushButton("🎙")
        self.btn_cam = QPushButton("📷")
        for b in (self.btn_mic, self.btn_cam):
            b.setFixedSize(34, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        self.btn_mic.pressed.connect(self.mic_clicked)
        self.btn_cam.pressed.connect(self.cam_clicked)
        for w in (self.dot, self.time, self.btn_pause, self.btn_stop, self.sep, self.btn_mic, self.btn_cam):
            lay.addWidget(w)
        self._build_draw_tools(lay)
        self._apply_tips()

    # --- cizim araclari
    def _build_draw_tools(self, lay):
        combo_css = ("QComboBox{background:#444;color:white;border:none;border-radius:6px;padding:4px 8px;}"
                     "QComboBox:hover{background:#5a5a5a;}QComboBox::drop-down{border:none;width:16px;}"
                     "QComboBox QAbstractItemView{background:#2a2a30;color:white;"
                     "selection-background-color:#3daee9;}")
        self.draw_widgets = []
        self.sep2 = QLabel()
        self.sep2.setFixedSize(1, 22)
        self.sep2.setStyleSheet("background:#555;")
        # Aç/kapa durumu dugmede degil cizim katmaninda tutulur; dugme sadece "degistir" ister
        self.btn_draw = QPushButton("✏")
        self.btn_draw.pressed.connect(self.draw_toggled)
        self.cb_tool = QComboBox()
        for tool, icon in DRAW_TOOLS:
            self.cb_tool.addItem(f"{icon}  {t('tool_' + tool)}", tool)
        self.cb_tool.setStyleSheet(combo_css)
        self.cb_tool.setToolTip(t("tool_tip"))
        self.cb_tool.activated.connect(lambda _: self.tool_changed.emit(self.cb_tool.currentData()))
        self.btn_color = QPushButton()
        self.btn_color.setToolTip(t("color_tip"))
        menu = QMenu(self.btn_color)
        for c in DRAW_PALETTE:
            pm = QPixmap(16, 16)
            pm.fill(QColor(c))
            menu.addAction(QIcon(pm), c).triggered.connect(lambda _=False, c=c: self.color_changed.emit(QColor(c)))
        menu.addSeparator()
        menu.addAction(t("color_more")).triggered.connect(self._more_color)
        self.btn_color.setMenu(menu)
        self._cap_filter = _CaptureFilter(self)
        popup = self.cb_tool.view().window()  # arac listesinin acilir penceresi
        for w in (menu, popup):
            # Windows golgesi ayri bir pencere olarak cizilir ve gizlenemez; kayitta saydam kutu birakiyordu
            w.setWindowFlag(Qt.NoDropShadowWindowHint, True)
            w.installEventFilter(self._cap_filter)
        # Basildigi anda tepki: hizli art arda tiklamalarda cift tik/birakma kosullarina takilmaz
        self.btn_undo = QPushButton("↶")
        self.btn_undo.pressed.connect(self.undo_clicked)
        self.btn_redo = QPushButton("↷")
        self.btn_redo.pressed.connect(self.redo_clicked)
        self.btn_clear = QPushButton("🗑")
        self.btn_clear.pressed.connect(self.clear_clicked)
        for b in (self.btn_draw, self.btn_color, self.btn_undo, self.btn_redo, self.btn_clear):
            b.setFixedSize(34, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(self._ON)
        self.btn_color.setFixedSize(42, 30)
        for w in (self.sep2, self.btn_draw, self.cb_tool, self.btn_color,
                  self.btn_undo, self.btn_redo, self.btn_clear):
            lay.addWidget(w)
            self.draw_widgets.append(w)

    def _tip(self, key, action=None):
        """Ipucu metni: islemin adi + atanmis kisayol (varsa)."""
        hk = self.hints.get(action) if action else None
        return f"{t(key)}  ({hk})" if hk else t(key)

    def set_hints(self, hints):
        self.hints = hints
        self._apply_tips()

    def _apply_tips(self):
        self.btn_pause.setToolTip(self._tip("btn_resume" if self._paused else "btn_pause", "pause"))
        self.btn_stop.setToolTip(self._tip("btn_stop", "stop"))
        self.btn_draw.setToolTip(self._tip("draw_mode_tip", "draw"))
        self.btn_undo.setToolTip(self._tip("undo_tip", "undo"))
        self.btn_redo.setToolTip(self._tip("redo_tip", "redo"))
        self.btn_clear.setToolTip(self._tip("clear_tip", "clear"))

    def _more_color(self):
        dlg = QColorDialog(QColor("#e53935"), self)
        dlg.setWindowTitle(t("pick_color"))
        dlg.installEventFilter(self._cap_filter)
        if dlg.exec():
            self.color_changed.emit(dlg.currentColor())

    def set_popups_visible(self, visible):
        """Mini pencerenin kendisi her zaman gizlidir; bu ayar sadece ondan acilan listeleri etkiler."""
        self.popups_in_recording = visible

    def set_draw_visible(self, visible):
        for w in self.draw_widgets:
            w.setVisible(visible)
        self.adjustSize()

    def set_draw_state(self, mode_on, tool, color):
        self.btn_draw.setStyleSheet(
            "QPushButton{background:#1e88e5;color:white;border:none;border-radius:6px;font-size:14px;}"
            if mode_on else self._ON)
        self.cb_tool.setCurrentIndex(self.cb_tool.findData(tool))
        self.btn_color.setStyleSheet(
            f"QPushButton{{background:{color.name()};border:2px solid #666;border-radius:6px;}}"
            "QPushButton::menu-indicator{image:none;}")

    def set_toggles(self, mic_available, mic_on, cam_available, cam_on):
        """Mikrofon/kamera dugmeleri: yalnizca kullanilabiliyorsa gorunur; kapaliyken kirmizi."""
        self.btn_mic.setVisible(mic_available)
        self.btn_cam.setVisible(cam_available)
        self.sep.setVisible(mic_available or cam_available)
        self.btn_mic.setStyleSheet(self._ON if mic_on else self._OFF)
        self.btn_cam.setStyleSheet(self._ON if cam_on else self._OFF)
        self.btn_mic.setToolTip(t("mic_mute") if mic_on else t("mic_unmute"))
        self.btn_cam.setToolTip(t("cam_hide") if cam_on else t("cam_show"))
        self.adjustSize()

    def show_on(self, screen):
        self.adjustSize()
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.top() + 12)
        self.show()
        exclude_from_capture(self)

    def set_state(self, paused, clock):
        self._blink = not self._blink
        self.time.setText(clock)
        color = "#f0c419" if paused else ("#ff4444" if self._blink else "#992222")
        self.dot.setStyleSheet(f"color:{color};")
        self.btn_pause.setText("▶" if paused else "❚❚")
        if paused != self._paused:
            self._paused = paused
            self._apply_tips()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(28, 28, 32, 235))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None


# --------------------------------------------------------------------------- Mercek

gdi32 = ctypes.windll.gdi32
try:
    magapi = ctypes.WinDLL("Magnification.dll")
except OSError:
    magapi = None


class _MAGTRANSFORM(ctypes.Structure):
    _fields_ = [("v", ctypes.c_float * 9)]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.DestroyWindow.argtypes = [wintypes.HWND]
gdi32.CreateEllipticRgn.restype = wintypes.HRGN
gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
if magapi:
    magapi.MagSetWindowSource.argtypes = [wintypes.HWND, wintypes.RECT]
    magapi.MagSetWindowTransform.argtypes = [wintypes.HWND, ctypes.POINTER(_MAGTRANSFORM)]
    magapi.MagSetWindowFilterList.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_int,
                                              ctypes.POINTER(wintypes.HWND)]


class _MagHost:
    """Windows Buyutec API'si ile buyutulmus goruntu gosteren yerel pencere. Kendi pencerelerimiz
    filtre listesiyle kaynaktan cikarilir, boylece mercek kendini buyutmez; kayitta ise gorunur."""

    WS_POPUP, WS_CHILD, WS_VISIBLE = 0x80000000, 0x40000000, 0x10000000
    EX = 0x8 | 0x80000 | 0x20 | 0x80 | 0x08000000  # topmost, layered, transparent, toolwindow, noactivate

    def __init__(self):
        if not magapi or not magapi.MagInitialize():
            raise OSError("Magnification API kullanilamiyor")
        hinst = kernel32.GetModuleHandleW(None)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = "EkranKaydediciLens"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.host = user32.CreateWindowExW(self.EX, "EkranKaydediciLens", "Lens", self.WS_POPUP,
                                           0, 0, 100, 100, None, None, hinst, None)
        user32.SetLayeredWindowAttributes(self.host, 0, 255, 2)
        self.mag = user32.CreateWindowExW(0, "Magnifier", "MagnifierWindow", self.WS_CHILD | self.WS_VISIBLE,
                                          0, 0, 100, 100, self.host, None, hinst, None)
        self.size = self.shape = self.zoom = None

    def set_filter(self, hwnds):
        arr = (wintypes.HWND * len(hwnds))(*hwnds)
        magapi.MagSetWindowFilterList(self.mag, 0, len(hwnds), arr)  # 0 = MW_FILTERMODE_EXCLUDE

    def update(self, cx, cy, size, zoom, shape, insert_after):
        """cx, cy: imlecin fiziksel konumu; size: mercek capi (fiziksel piksel)."""
        if (size, shape) != (self.size, self.shape):
            user32.SetWindowPos(self.mag, None, 0, 0, size, size, 0x4 | 0x10)
            rgn = gdi32.CreateEllipticRgn(0, 0, size + 1, size + 1) if shape == "circle" else \
                gdi32.CreateRoundRectRgn(0, 0, size + 1, size + 1, size // 4, size // 4)
            user32.SetWindowRgn(self.host, rgn, True)
            self.size, self.shape = size, shape
        if zoom != self.zoom:
            m = _MAGTRANSFORM()
            m.v[0], m.v[4], m.v[8] = zoom, zoom, 1.0
            magapi.MagSetWindowTransform(self.mag, ctypes.byref(m))
            self.zoom = zoom
        src = size / zoom
        left, top = round(cx - src / 2), round(cy - src / 2)
        magapi.MagSetWindowSource(self.mag, wintypes.RECT(left, top, left + round(src), top + round(src)))
        user32.SetWindowPos(self.host, insert_after, cx - size // 2, cy - size // 2, size, size, 0x10 | 0x40)
        user32.InvalidateRect(self.mag, None, True)

    def hide(self):
        user32.ShowWindow(self.host, 0)

    def destroy(self):
        user32.DestroyWindow(self.host)
        magapi.MagUninitialize()


class Magnifier(QWidget):
    """Imleci takip eden buyutec. Buyutulmus goruntuyu _MagHost cizer; bu saydam pencere onun
    ustunde cerceveyi ve golgeyi cizer. Kayitta gorunur, tiklamalari gecirir."""
    PAD = 10

    def __init__(self):
        super().__init__(None, overlay_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.zoom, self.diameter, self.shape = 2.5, 280, "circle"
        self.border_color, self.border_width = QColor("#3daee9"), 4
        self.exclude = []  # buyutmeye girmeyecek diger pencerelerimiz
        self.host = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def available(self):
        if self.host is None:
            try:
                self.host = _MagHost()
            except OSError:
                self.host = False
        return bool(self.host)

    def configure(self, zoom, diameter, shape, border_color, border_width):
        self.zoom, self.diameter, self.shape = zoom, diameter, shape
        self.border_color, self.border_width = QColor(border_color), border_width
        self.setFixedSize(diameter + 2 * self.PAD, diameter + 2 * self.PAD)
        self.update()

    def toggle(self):
        if self.isVisible():
            self.close_lens()
        else:
            self.open_lens()

    def open_lens(self):
        if not self.available():
            return
        self._tick()
        self.show()
        self.host.set_filter([int(self.winId())] + [int(w.winId()) for w in self.exclude])
        self._timer.start(15)

    def close_lens(self):
        self._timer.stop()
        if self.host:
            self.host.hide()
        self.hide()

    def _tick(self):
        p = QCursor.pos()
        self.move(p.x() - self.width() // 2, p.y() - self.height() // 2)
        screen = QApplication.screenAt(p) or QApplication.primaryScreen()
        size = round(self.diameter * screen.devicePixelRatio())
        px, py = physical_cursor_pos()
        # Buyutec penceresini cerceve penceremizin hemen altina yerlestir
        self.host.update(px, py, size, self.zoom, self.shape, int(self.winId()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self.diameter
        rect = QRectF(self.PAD, self.PAD, d, d)
        path = QPainterPath()
        if self.shape == "circle":
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, d / 8, d / 8)
        # Merceği zeminden ayiran yumusak dis golge
        for i, a in ((6, 25), (4, 40), (2, 60)):
            p.setPen(QPen(QColor(0, 0, 0, a), i))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path.translated(0, 2))
        if self.border_width > 0:
            p.setPen(QPen(self.border_color, self.border_width))
            p.drawPath(path)
        p.end()

    def shutdown(self):
        self.close_lens()
        if self.host:
            self.host.destroy()
        self.host = None


# --------------------------------------------------------------------------- Tus gosterimi

WH_KEYBOARD_LL = 13
_LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


WH_MOUSE_LL = 14


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


MOUSE_TOKEN = "\x00mouse:"  # tus listesinde fare dugmesini isaretler; cizimde fare simgesi olarak gosterilir


user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = _LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]

_MOD_VK = {0x10: "Shift", 0xA0: "Shift", 0xA1: "Shift", 0x11: "Ctrl", 0xA2: "Ctrl", 0xA3: "Ctrl",
           0x12: "Alt", 0xA4: "Alt", 0xA5: "Alt", 0x5B: "Win", 0x5C: "Win"}
_MOD_ORDER = ["Ctrl", "Win", "Alt", "Shift"]
_SPECIAL_VK = {0x08: "⌫", 0x09: "Tab", 0x0D: "Enter ⏎", 0x1B: "Esc", 0x20: "Space", 0x21: "PgUp", 0x22: "PgDn",
               0x23: "End", 0x24: "Home", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2C: "PrtSc",
               0x2D: "Ins", 0x2E: "Del", 0x14: "CapsLock", 0x5D: "Menu", 0x13: "Pause"}


def _vk_label(vk):
    if vk in _SPECIAL_VK:
        return _SPECIAL_VK[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    ch = user32.MapVirtualKeyW(vk, 2) & 0xFFFF  # MAPVK_VK_TO_CHAR
    return chr(ch).upper() if ch else f"#{vk}"


class KeystrokeOverlay(QWidget):
    """Basilan tuslari kayit alaninin altinda tus kapaklari olarak gosterir (kayitta gorunur)."""
    HOLD, FADE, ROWS = 1.6, 0.35, 3

    def __init__(self):
        super().__init__(None, overlay_flags())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.mode, self.position, self.font_pt = "shortcuts", "bc", 20
        self.entries = []  # {"keys": [...], "text": bool, "t": zaman, "count": n}
        self.held_mods, self.down = set(), set()
        self._hook = self._mhook = None
        self._proc = _HOOKPROC(self._hook_cb)  # referansi tut, yoksa geri cagirim cop olur
        self._mproc = _HOOKPROC(self._mouse_cb)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def configure(self, mode, position, font_pt):
        self.mode, self.position, self.font_pt = mode, position, font_pt
        self.update()

    def start(self, area):
        """area: kayit alaninin mantiksal (Qt) dikdortgeni."""
        cap = self._cap_height()
        h = self.ROWS * (cap + 10) + 40
        y = area.top() + 30 if self.position == "tc" else area.bottom() - h - 30
        self.setGeometry(area.left(), y, area.width(), h)
        self.entries.clear()
        self.held_mods.clear()
        self.down.clear()
        hinst = kernel32.GetModuleHandleW(None)
        if not self._hook:
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, hinst, 0)
        if not self._mhook:
            self._mhook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mproc, hinst, 0)
        self.show()
        self._timer.start(33)

    def stop(self):
        for attr in ("_hook", "_mhook"):
            if getattr(self, attr):
                user32.UnhookWindowsHookEx(getattr(self, attr))
                setattr(self, attr, None)
        self._timer.stop()
        self.entries.clear()
        self.hide()

    def _hook_cb(self, n, wparam, lparam):
        if n == 0:
            try:
                kb = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                if wparam in (0x100, 0x104):
                    self._key_down(kb.vkCode)
                elif wparam in (0x101, 0x105):
                    self._key_up(kb.vkCode)
            except Exception:  # noqa: BLE001 - kanca icinde hata asla yukari tasinmamali
                pass
        return user32.CallNextHookEx(None, n, wparam, lparam)

    def _mouse_cb(self, n, wparam, lparam):
        if n == 0:
            try:
                kind = {0x201: "left", 0x204: "right", 0x207: "middle"}.get(wparam)
                if wparam in (0x20A, 0x20B):
                    ms = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    hi = ctypes.c_short(ms.mouseData >> 16).value
                    if wparam == 0x20A:
                        kind = "wheel_up" if hi > 0 else "wheel_down"
                    else:
                        kind = "back" if hi == 1 else "forward"
                if kind:
                    self._mouse_down(kind)
            except Exception:  # noqa: BLE001
                pass
        return user32.CallNextHookEx(None, n, wparam, lparam)

    def _mouse_down(self, kind):
        """Fare dugmeleri yalnizca bir degistirici tusla (Ctrl/Alt/Shift/Win) birlikte gosterilir;
        tek basina tiklamalar zaten tiklama dalgasiyla gorunuyor."""
        mods = [m for m in _MOD_ORDER if m in self.held_mods]
        if mods:
            self._show_combo(mods + [MOUSE_TOKEN + kind])

    def _show_combo(self, keys):
        now = time.perf_counter()
        last = self.entries[-1] if self.entries else None
        if last and not last["text"] and last["keys"] == keys and now - last["t"] < self.HOLD:
            last["count"] += 1
            last["t"] = now
            self.update()
        else:
            self._push({"keys": keys, "text": False, "t": now, "count": 1})

    def _key_up(self, vk):
        self.down.discard(vk)
        if vk in _MOD_VK:
            self.held_mods.discard(_MOD_VK[vk])

    def _key_down(self, vk):
        if vk in self.down:  # basili tutma tekrari
            return
        self.down.add(vk)
        if vk in _MOD_VK:
            self.held_mods.add(_MOD_VK[vk])
            return
        mods = [m for m in _MOD_ORDER if m in self.held_mods]
        label = _vk_label(vk)
        command = any(m in mods for m in ("Ctrl", "Alt", "Win"))
        special = vk in _SPECIAL_VK or 0x70 <= vk <= 0x87
        now = time.perf_counter()
        if not command and not special:
            if self.mode != "all":
                return
            last = self.entries[-1] if self.entries else None
            if last and last["text"] and now - last["t"] < self.HOLD:
                last["keys"][0] += label
                last["t"] = now
            else:
                self._push({"keys": [label], "text": True, "t": now, "count": 1})
            return
        self._show_combo(mods + [label])

    def _push(self, entry):
        self.entries.append(entry)
        del self.entries[:-self.ROWS]
        self.update()

    def _tick(self):
        now = time.perf_counter()
        before = len(self.entries)
        self.entries = [e for e in self.entries if now - e["t"] < self.HOLD + self.FADE]
        if self.entries or before:
            self.update()

    def _font(self):
        f = QFont("Segoe UI")
        f.setPixelSize(self.font_pt)
        f.setBold(True)
        return f

    def _cap_height(self):
        return round(self.font_pt * 1.9)

    @staticmethod
    def _mouse_text(token):
        return t("mouse_" + token[len(MOUSE_TOKEN):])

    @staticmethod
    def _paint_mouse(p, r, kind, alpha):
        """Kucuk fare simgesi; basilan dugme (veya tekerlek) vurgulu renkte."""
        accent = QColor(61, 174, 233, int(255 * alpha))
        line = QColor(255, 255, 255, int(230 * alpha))
        body = QPainterPath()
        body.addRoundedRect(r, r.width() * 0.48, r.width() * 0.48)
        split_y = r.top() + r.height() * 0.42
        cx = r.center().x()
        p.save()
        p.setClipPath(body)
        if kind in ("left", "right"):
            half = QRectF(r.left(), r.top(), r.width() / 2, split_y - r.top())
            if kind == "right":
                half.moveLeft(cx)
            p.fillRect(half, accent)
        p.restore()
        p.setPen(QPen(line, max(1.5, r.width() * 0.09)))
        p.setBrush(Qt.NoBrush)
        p.drawPath(body)
        p.drawLine(QPointF(r.left(), split_y), QPointF(r.right(), split_y))
        p.drawLine(QPointF(cx, r.top()), QPointF(cx, split_y))
        wheel = QRectF(cx - r.width() * 0.11, r.top() + r.height() * 0.12, r.width() * 0.22, r.height() * 0.2)
        p.setBrush(accent if kind in ("middle", "wheel_up", "wheel_down") else line)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(wheel, wheel.width() / 2, wheel.width() / 2)

    def paintEvent(self, _):
        if not self.entries:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font())
        fm = p.fontMetrics()
        cap_h, pad, gap, plus_w = self._cap_height(), round(self.font_pt * 0.6), 10, fm.horizontalAdvance(" + ")
        now = time.perf_counter()
        rows = list(reversed(self.entries))  # en yenisi kenara en yakin
        for i, e in enumerate(rows):
            age = now - e["t"]
            alpha = 1.0 if age < self.HOLD else max(0.0, 1 - (age - self.HOLD) / self.FADE)
            labels = list(e["keys"])
            icon_w = round(cap_h * 0.45)
            widths = [fm.horizontalAdvance(self._mouse_text(k)) + 2 * pad + icon_w + pad // 2
                      if k.startswith(MOUSE_TOKEN) else fm.horizontalAdvance(k) + 2 * pad for k in labels]
            suffix = f"  ×{e['count']}" if e["count"] > 1 else ""
            total = sum(widths) + (len(labels) - 1) * plus_w + fm.horizontalAdvance(suffix)
            if self.position == "bl":
                x = 30
            elif self.position == "br":
                x = self.width() - total - 30
            else:
                x = (self.width() - total) / 2
            y = 20 + i * (cap_h + gap) if self.position == "tc" else self.height() - 20 - (i + 1) * cap_h - i * gap
            # Her zeminde okunabilsin diye satirin arkasinda koyu yari saydam bir taban
            back = QRectF(x - 6, y - 5, total + 12, cap_h + 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, int(150 * alpha)))
            p.drawRoundedRect(back, cap_h * 0.3, cap_h * 0.3)
            for j, (k, w) in enumerate(zip(labels, widths)):
                r = QRectF(x, y, w, cap_h)
                p.setPen(QPen(QColor(255, 255, 255, int(70 * alpha)), 1.5))
                p.setBrush(QColor(58, 58, 66, int(240 * alpha)))
                p.drawRoundedRect(r, cap_h * 0.22, cap_h * 0.22)
                if k.startswith(MOUSE_TOKEN):
                    kind = k[len(MOUSE_TOKEN):]
                    icon = QRectF(x + pad, y + cap_h * 0.17, icon_w, cap_h * 0.66)
                    self._paint_mouse(p, icon, kind, alpha)
                    p.setPen(QColor(255, 255, 255, int(255 * alpha)))
                    p.drawText(r.adjusted(pad + icon_w + pad // 2, 0, -pad, 0), Qt.AlignVCenter, self._mouse_text(k))
                else:
                    p.setPen(QColor(255, 255, 255, int(255 * alpha)))
                    p.drawText(r, Qt.AlignCenter, k)
                x += w
                if j < len(labels) - 1:
                    p.setPen(QColor(255, 255, 255, int(200 * alpha)))
                    p.drawText(QRectF(x, y, plus_w, cap_h), Qt.AlignCenter, "+")
                    x += plus_w
            if suffix:
                p.setPen(QColor(255, 210, 80, int(255 * alpha)))
                p.drawText(QRectF(x, y, fm.horizontalAdvance(suffix) + 4, cap_h), Qt.AlignVCenter, suffix)
        p.end()


# --------------------------------------------------------------------------- Canli cizim

DRAW_TOOLS = [("pen", "✏"), ("highlighter", "🖍"), ("arrow", "➜"), ("line", "╱"), ("rect", "▭"),
              ("ellipse", "◯"), ("number", "①"), ("text", "T"), ("laser", "✦"), ("eraser", "⌫")]
FADE_CHOICES = [0, 2, 3, 5, 10]
DRAW_PALETTE = ["#e53935", "#fdd835", "#43a047", "#1e88e5", "#ffffff", "#111111", "#fb8c00", "#8e24aa"]
GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = -20, 0x20, 0x08000000
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


class DrawingOverlay(QWidget):
    """Kayit alanini kaplayan cizim katmani (kayitta gorunur). Cizim modunda fareyi yakalar;
    mod kapaliyken tiklamalari alttaki uygulamalara gecirir, cizimler ekranda kalir."""
    mode_changed = Signal(bool)
    touched = Signal()  # katmana tiklandi: kontrol pencereleri yeniden one alinmali
    FADE_OUT = 0.5   # kaybolan cizimin solma suresi
    LASER_LIFE = 0.7

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.tool, self.color, self.width_px = "pen", QColor("#e53935"), 4
        self.fades = {tool: 0 for tool, _ in DRAW_TOOLS}
        self.shapes, self.laser = [], []
        # Islem gecmisi: ("add", sekil) | ("erase", sekil, sira) | ("clear", sekiller, numara)
        self.history, self.future = [], []
        self.current = None
        self.number = 0
        self.drawing_mode = False
        self.editor = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # --- durum
    def start(self, area):
        self.setGeometry(area)
        self.show()
        self.set_drawing_mode(False)
        self._timer.start(30)

    def stop(self):
        self._timer.stop()
        self.reset()
        self.drawing_mode = False
        self.hide()

    def set_drawing_mode(self, on):
        self.drawing_mode = on
        hwnd = int(self.winId())
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ex = ex & ~WS_EX_TRANSPARENT if on else ex | WS_EX_TRANSPARENT
        # NOACTIVATE: katmana tiklamak onu one cikarmaz; mini pencere ve kamera hep ustte kalir
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if not on:
            self._commit_text()
        self.update()
        self.mode_changed.emit(on)

    def set_tool(self, tool):
        self._commit_text()
        self.tool = tool

    # --- gecmis (geri al / ileri al)
    def _record(self, action):
        """Yeni bir islem ileri alma gecmisini gecersiz kilar."""
        self.history.append(action)
        self.future.clear()

    def _add(self, shape):
        self.shapes.append(shape)
        self._record(("add", shape))

    @staticmethod
    def _revive(shapes):
        now = time.perf_counter()
        for s in shapes:
            s["t"] = now  # geri gelen kaybolan cizimlerin suresi bastan baslar

    def undo(self):
        self._commit_text()
        while self.history:
            action = self.history.pop()
            kind = action[0]
            if kind == "add":
                s = action[1]
                if s not in self.shapes:  # suresi dolup kaybolmus; bir onceki isleme gec
                    continue
                self.shapes.remove(s)
                if s["tool"] == "number":
                    self.number = max(0, self.number - 1)
            elif kind == "erase":
                _, s, idx = action
                self._revive([s])
                self.shapes.insert(min(idx, len(self.shapes)), s)
            elif kind == "clear":
                _, saved, number = action
                self._revive(saved)
                self.shapes = saved + self.shapes
                self.number = number
            self.future.append(action)
            self.update()
            return

    def redo(self):
        if not self.future:
            return
        action = self.future.pop()
        kind = action[0]
        if kind == "add":
            s = action[1]
            self._revive([s])
            self.shapes.append(s)
            if s["tool"] == "number":
                self.number += 1
        elif kind == "erase":
            if action[1] in self.shapes:
                self.shapes.remove(action[1])
        elif kind == "clear":
            action = ("clear", list(self.shapes), self.number)
            self.shapes.clear()
            self.number = 0
        self.history.append(action)
        self.update()

    def clear(self):
        """Tum cizimleri siler; geri alinabilir."""
        self._commit_text()
        self.laser.clear()
        if self.shapes:
            self._record(("clear", list(self.shapes), self.number))
            self.shapes.clear()
            self.number = 0
        self.update()

    def reset(self):
        """Kayit bitince her seyi (gecmis dahil) siler."""
        if self.editor:
            self.editor.deleteLater()
            self.editor = None
        self.shapes.clear()
        self.history.clear()
        self.future.clear()
        self.laser.clear()
        self.current = None
        self.number = 0
        self.update()

    def _tick(self):
        now = time.perf_counter()
        n = len(self.shapes) + len(self.laser)
        self.shapes = [s for s in self.shapes if not s["fade"] or now - s["t"] < s["fade"] + self.FADE_OUT]
        self.laser = [p for p in self.laser if now - p[1] < self.LASER_LIFE]
        if self.laser or n != len(self.shapes) + len(self.laser) or \
                any(s["fade"] and now - s["t"] > s["fade"] for s in self.shapes):
            self.update()

    # --- fare
    def _new_shape(self, pos):
        w = self.width_px * (4 if self.tool == "highlighter" else 1)
        return {"tool": self.tool, "color": QColor(self.color), "width": w, "pts": [QPointF(pos)],
                "t": time.perf_counter(), "fade": self.fades.get(self.tool, 0)}

    def mousePressEvent(self, e):
        if not self.drawing_mode:
            return
        self.touched.emit()
        if e.button() == Qt.RightButton:
            self.set_drawing_mode(False)
            return
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        self._commit_text()
        if self.tool == "laser":
            self.laser.append((QPointF(pos), time.perf_counter()))
        elif self.tool == "eraser":
            self._erase_at(pos)
        elif self.tool == "number":
            self.number += 1
            s = self._new_shape(pos)
            s["num"] = self.number
            self._add(s)
        elif self.tool == "text":
            self._open_editor(pos)
        else:
            self.current = self._new_shape(pos)
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.tool == "laser" and self.drawing_mode and e.buttons() & Qt.LeftButton:
            self.laser.append((QPointF(pos), time.perf_counter()))
        elif self.tool == "eraser" and e.buttons() & Qt.LeftButton:
            self._erase_at(pos)
        elif self.current:
            if self.current["tool"] in ("pen", "highlighter"):
                self.current["pts"].append(QPointF(pos))
            else:
                self.current["pts"][1:] = [QPointF(pos)]
        self.update()

    def mouseReleaseEvent(self, e):
        self.touched.emit()
        if self.current and e.button() == Qt.LeftButton:
            s = self.current
            self.current = None
            if len(s["pts"]) > 1 or s["tool"] in ("pen", "highlighter"):
                s["t"] = time.perf_counter()  # kaybolma sayaci cizim bitince baslar
                self._add(s)
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.set_drawing_mode(False)
        elif e.key() == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self.undo()
        elif e.key() == Qt.Key_Y and e.modifiers() & Qt.ControlModifier:
            self.redo()

    # --- metin araci
    def _open_editor(self, pos):
        self.editor = QLineEdit(self)
        f = QFont("Segoe UI")
        f.setPixelSize(self._text_px())
        f.setBold(True)
        self.editor.setFont(f)
        self.editor.setStyleSheet(f"background:rgba(0,0,0,90);color:{self.color.name()};"
                                  "border:1px dashed #aaa;padding:2px;")
        self.editor.setMinimumWidth(240)
        self.editor.move(int(pos.x()), int(pos.y() - self._text_px()))
        self.editor.returnPressed.connect(self._commit_text)
        self.editor.show()
        self.activateWindow()
        self.editor.setFocus()
        self._editor_pos = QPointF(pos)

    def _text_px(self):
        return 14 + self.width_px * 4

    def _commit_text(self):
        ed, self.editor = self.editor, None
        if not ed:
            return
        text = ed.text().strip()
        ed.deleteLater()
        if text:
            s = self._new_shape(self._editor_pos)
            s["text"], s["size"] = text, self._text_px()
            self._add(s)
        self.update()

    # --- silgi
    def _path(self, s):
        pts, tool = s["pts"], s["tool"]
        path = QPainterPath(pts[0])
        if tool in ("pen", "highlighter"):
            for a, b in zip(pts, pts[1:]):
                path.quadTo(a, (a + b) / 2)
            path.lineTo(pts[-1])
        elif tool in ("line", "arrow"):
            path.lineTo(pts[-1])
        elif tool == "rect":
            path = QPainterPath()
            path.addRect(QRectF(pts[0], pts[-1]).normalized())
        elif tool == "ellipse":
            path = QPainterPath()
            path.addEllipse(QRectF(pts[0], pts[-1]).normalized())
        elif tool == "number":
            path = QPainterPath()
            r = self._num_radius(s)
            path.addEllipse(pts[0], r, r)
        elif tool == "text":
            path = QPainterPath()
            path.addRect(QRectF(pts[0].x(), pts[0].y() - s["size"], len(s["text"]) * s["size"] * 0.6, s["size"] * 1.3))
        return path

    def _erase_at(self, pos):
        stroker = QPainterPathStroker()
        for s in reversed(self.shapes):
            stroker.setWidth(s["width"] + 14)
            path = self._path(s)
            if stroker.createStroke(path).contains(pos) or (s["tool"] in ("number", "text") and path.contains(pos)):
                idx = self.shapes.index(s)
                self.shapes.remove(s)
                self._record(("erase", s, idx))
                self.update()
                return

    # --- cizim
    @staticmethod
    def _num_radius(s):
        return 12 + s["width"] * 2

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.drawing_mode:
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))  # tamamen saydam pikseller fareyi yakalamaz
        now = time.perf_counter()
        for s in self.shapes + ([self.current] if self.current else []):
            alpha = 1.0
            if s["fade"] and s is not self.current:
                alpha = max(0.0, 1 - max(0.0, now - s["t"] - s["fade"]) / self.FADE_OUT)
            self._paint_shape(p, s, alpha)
        for (pt, ts), nxt in zip(self.laser, self.laser[1:] + [None]):
            k = max(0.0, 1 - (now - ts) / self.LASER_LIFE)
            glow = QColor(255, 40, 40, int(90 * k))
            core = QColor(255, 120, 120, int(255 * k))
            for col, wd in ((glow, 14 * k + 4), (core, 5 * k + 1)):
                p.setPen(QPen(col, wd, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pt, nxt[0] if nxt else pt)
        p.end()

    def _paint_shape(self, p, s, alpha):
        col = QColor(s["color"])
        tool, pts, w = s["tool"], s["pts"], s["width"]
        if tool == "highlighter":
            col.setAlphaF(0.38 * alpha)
            p.setPen(QPen(col, w, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
        else:
            col.setAlphaF(alpha)
            p.setPen(QPen(col, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if tool == "number":
            r = self._num_radius(s)
            p.setPen(QPen(QColor(255, 255, 255, int(230 * alpha)), 2))
            p.setBrush(col)
            p.drawEllipse(pts[0], r, r)
            f = QFont("Segoe UI")
            f.setPixelSize(int(r * 1.15))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(255 * alpha)) if col.lightness() < 170 else QColor(0, 0, 0, int(255 * alpha)))
            p.drawText(QRectF(pts[0].x() - r, pts[0].y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(s["num"]))
            return
        if tool == "text":
            f = QFont("Segoe UI")
            f.setPixelSize(s["size"])
            f.setBold(True)
            path = QPainterPath()
            path.addText(pts[0], f, s["text"])
            p.setPen(QPen(QColor(0, 0, 0, int(170 * alpha)), max(2, s["size"] // 10)))  # okunurluk icin kontur
            p.setBrush(col)
            p.drawPath(path)
            return
        if len(pts) < 2 and tool not in ("pen", "highlighter"):
            return
        p.drawPath(self._path(s))
        if tool == "arrow":
            a, b = pts[0], pts[-1]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            length = (dx * dx + dy * dy) ** 0.5
            if length < 1:
                return
            ux, uy = dx / length, dy / length
            head = max(14, w * 4)
            left = QPointF(b.x() - ux * head - uy * head * 0.55, b.y() - uy * head + ux * head * 0.55)
            right = QPointF(b.x() - ux * head + uy * head * 0.55, b.y() - uy * head - ux * head * 0.55)
            p.setBrush(col)
            p.setPen(QPen(col, 1))
            p.drawPolygon(QPolygonF([b, left, right]))


# --------------------------------------------------------------------------- Webcam

class WebcamOverlay(QWidget):
    """Kamera goruntusu (daire veya 16:9). Kayitta gorunur; surukle-tasi, tekerlekle boyut."""
    PAD = 8
    moved = Signal()
    resized = Signal(int)
    error = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.SizeAllCursor)
        self.device_id, self.size_px, self.shape, self.mirror = "", 240, "circle", True
        self.border_color, self.border_width = QColor("#ffffff"), 3
        self.camera = None
        self.image = None
        self.session = QMediaCaptureSession()
        self.sink = QVideoSink()
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self._drag = None
        self.bounds = None  # kayit alani (mantiksal); pencere bunun disina cikamaz
        # Diyafram animasyonu: "waiting" (goruntu bekleniyor) -> "opening" -> "open"; kapatirken "closing"
        self._iris = "open"
        self._iris_t0 = 0.0
        self._iris_from = 0.0
        self._iris_timer = QTimer(self)
        self._iris_timer.timeout.connect(self._iris_tick)
        self._apply_size()

    OPEN_TIME, CLOSE_TIME = 0.5, 0.35

    def _set_iris(self, state):
        self._iris_from = self._aperture()
        self._iris, self._iris_t0 = state, time.perf_counter()
        if state != "open":
            self._iris_timer.start(16)
        self.update()

    def _aperture(self):
        """Diyafram acikligi: 0 = tamamen kapali, 1 = kanatlar tamamen disarida."""
        el = time.perf_counter() - self._iris_t0
        if self._iris == "waiting":
            return 0.14 + 0.05 * math.sin(el * 3.2)  # goruntu gelene kadar hafifce "nefes alir"
        if self._iris == "opening":
            k = min(1.0, el / self.OPEN_TIME)
            return self._iris_from + (1.0 - self._iris_from) * (1 - (1 - k) ** 3)
        if self._iris == "closing":
            k = min(1.0, el / self.CLOSE_TIME)
            return self._iris_from * (1 - k * k)
        return 1.0

    def _iris_tick(self):
        el = time.perf_counter() - self._iris_t0
        if self._iris == "opening" and el >= self.OPEN_TIME:
            self._iris = "open"
            self._iris_timer.stop()
        elif self._iris == "closing" and el >= self.CLOSE_TIME:
            self._iris_timer.stop()
            self._iris = "open"
            self.hide()
            self.stop_camera()
            return
        self.update()

    def _clamp(self, pos):
        b = self.bounds
        if b is None:
            return pos
        x = min(max(pos.x(), b.left()), b.right() + 1 - self.width())
        y = min(max(pos.y(), b.top()), b.bottom() + 1 - self.height())
        return QPoint(x, y)

    def configure(self, device_id, size_px, shape, mirror, border_color, border_width):
        restart = self.camera is not None and device_id != self.device_id
        self.device_id, self.size_px, self.shape, self.mirror = device_id, size_px, shape, mirror
        self.border_color, self.border_width = QColor(border_color), border_width
        self._apply_size()
        if restart:
            self.stop_camera()
            self.start_camera()
        self.update()

    def _inner(self):
        w = self.size_px
        return (w, w) if self.shape == "circle" else (w, round(w * 9 / 16))

    def _apply_size(self):
        w, h = self._inner()
        center = self.geometry().center() if self.isVisible() else None
        self.setFixedSize(w + 2 * self.PAD, h + 2 * self.PAD)
        if center is not None:
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def start_camera(self):
        if self.camera:
            return
        devices = QMediaDevices.videoInputs()
        dev = next((d for d in devices if bytes(d.id()).hex() == self.device_id), None) or \
            QMediaDevices.defaultVideoInput()
        if dev.isNull():
            self.error.emit(t("cam_none"))
            return
        self.camera = QCamera(dev)
        fmts = [f for f in dev.videoFormats() if f.maxFrameRate() >= 24]
        if fmts:
            # 720p civari yeterince keskin ve islemciyi yormaz
            best = min(fmts, key=lambda f: abs(f.resolution().width() - 1280) + abs(f.resolution().height() - 720))
            self.camera.setCameraFormat(best)
        self.camera.errorOccurred.connect(lambda _, msg: self.error.emit(t("cam_error", e=msg)))
        self.session.setCamera(self.camera)
        self.camera.start()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.session.setCamera(None)
            self.camera.deleteLater()
            self.camera = None
        self.image = None

    def show_at(self, pos):
        if self._iris == "closing" and self.image is not None:
            self._set_iris("opening")  # kapanirken tekrar acildi: kamera hala calisiyor
        elif self.image is None:
            self._set_iris("waiting")
        self.start_camera()
        self.move(self._clamp(pos))
        self.show()

    def hide_cam(self, animated=False):
        """animated: diyafram kapanir, sonra pencere gizlenir (kayit surerken kamerayi kapatmak icin)."""
        if animated and self.isVisible():
            self._set_iris("closing")
            return
        self._iris_timer.stop()
        self._iris = "open"
        self.hide()
        self.stop_camera()

    def is_shown(self):
        """Gorunur ve kapanma animasyonunda degil."""
        return self.isVisible() and self._iris != "closing"

    def _on_frame(self, frame):
        img = frame.toImage()
        if img.isNull():
            return
        if self.mirror:
            img = img.flipped(Qt.Horizontal) if hasattr(img, "flipped") else img.mirrored(True, False)
        self.image = img
        if self._iris == "waiting":
            self._set_iris("opening")
        self.update()

    def _paint_lens_glass(self, p, rect):
        """Goruntu yokken diyaframin arkasinda gorunen koyu lens cami ve yansimalar."""
        c, r = rect.center(), max(rect.width(), rect.height()) / 2
        g = QRadialGradient(c, r)
        g.setColorAt(0.0, QColor(40, 70, 110))
        g.setColorAt(0.45, QColor(14, 22, 38))
        g.setColorAt(1.0, QColor(4, 6, 10))
        p.fillRect(rect, g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawEllipse(QPointF(c.x() - r * 0.28, c.y() - r * 0.3), r * 0.16, r * 0.1)
        p.setBrush(QColor(120, 200, 255, 30))
        p.drawEllipse(QPointF(c.x() + r * 0.22, c.y() + r * 0.25), r * 0.07, r * 0.07)

    def _paint_iris(self, p, rect, aperture):
        """Alti kanatli diyafram. aperture 0 iken kapali, 1 iken kanatlar alanin disinda."""
        n = 6
        c = rect.center()
        R = math.hypot(rect.width(), rect.height()) / 2  # kanatlar kapaliyken koseler dahil her yeri ortsun
        # Ortadaki altigen boslugun ic yaricapi; aperture 1'de tam gorunur alanin kenarina ulassin
        reach = min(rect.width(), rect.height()) / 2 / math.cos(math.pi / 6) if self.shape == "circle" else R
        a = aperture * reach * 1.02
        rot = math.radians(40 * (1 - aperture))           # kapanirken kanatlar doner
        L = R * 2.2
        for i in range(n):
            th = rot + i * 2 * math.pi / n
            nx, ny = math.cos(th), math.sin(th)
            tx, ty = -ny, nx
            ex, ey = c.x() + a * nx, c.y() + a * ny
            # Kanat: ic kenari ortaya bakan, disari dogru uzanan; komsusunun ustune hafif biner
            pts = [QPointF(ex + L * tx, ey + L * ty), QPointF(ex - L * 0.15 * tx, ey - L * 0.15 * ty),
                   QPointF(ex - L * 0.15 * tx + 2 * R * nx, ey - L * 0.15 * ty + 2 * R * ny),
                   QPointF(ex + L * tx + 2 * R * nx, ey + L * ty + 2 * R * ny)]
            grad = QLinearGradient(QPointF(ex, ey), QPointF(ex + R * nx, ey + R * ny))
            grad.setColorAt(0.0, QColor(58, 60, 66))
            grad.setColorAt(1.0, QColor(22, 23, 26))
            p.setBrush(grad)
            p.setPen(QPen(QColor(110, 112, 120), 1.2))
            p.drawPolygon(QPolygonF(pts))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self._inner()
        rect = QRectF(self.PAD, self.PAD, w, h)
        path = QPainterPath()
        if self.shape == "circle":
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, h * 0.12, h * 0.12)
        for i, a in ((6, 25), (4, 40), (2, 60)):
            p.setPen(QPen(QColor(0, 0, 0, a), i))
            p.drawPath(path.translated(0, 2))
        p.setClipPath(path)
        if self.image is not None:
            iw, ih = self.image.width(), self.image.height()
            target = w / h
            if iw / ih > target:
                sw, sh = ih * target, ih
            else:
                sw, sh = iw, iw / target
            src = QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh)
            p.drawImage(rect, self.image, src)
        else:
            self._paint_lens_glass(p, rect)
        aperture = self._aperture()
        if aperture < 1.0:
            self._paint_iris(p, rect, aperture)
        p.setClipping(False)
        if self.border_width > 0:
            p.setPen(QPen(self.border_color, self.border_width))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(self._clamp(e.globalPosition().toPoint() - self._drag))

    def mouseReleaseEvent(self, _):
        if self._drag is not None:
            self._drag = None
            self.moved.emit()

    def wheelEvent(self, e):
        step = 20 if e.angleDelta().y() > 0 else -20
        limit = 720
        if self.bounds is not None:  # kayit alanindan buyuk olamaz
            w, h = self.bounds.width() - 2 * self.PAD, self.bounds.height() - 2 * self.PAD
            limit = min(limit, w, h if self.shape == "circle" else h * 16 // 9)
        self.size_px = max(120, min(limit, self.size_px + step))
        self._apply_size()
        self.move(self._clamp(self.pos()))
        self.update()
        self.resized.emit(self.size_px)


# --------------------------------------------------------------------------- Kayit motoru

class Recorder(QObject):
    """Her kayit/devam bir FFmpeg segmenti; durdurunca segmentler kayipsiz birlestirilir."""
    finished = Signal(str)
    failed = Signal(str)
    stage = Signal(str)

    def __init__(self):
        super().__init__()
        self.proc = None
        self.audio = None
        self.audio_errors = []
        self.mic_muted = False
        self.cfg = None
        self.parts_dir = None
        self.segments = []
        self.zoom_port = None
        self.zoom_rect = None  # (x, y, w, h) kayit alani icinde; None = zoom yok
        self._zsock = None
        self._zoom_gen = 0
        self._zlock = threading.Lock()
        self._direct_ok = {}  # (ffmpeg, kodlayici, ekran) -> GPU'dan dogrudan besleme calisiyor mu

    # --- komut olusturma
    def _filter(self, direct):
        c = self.cfg
        src = f"ddagrab=output_idx={c['monitor']}:framerate={c['fps']}:draw_mouse={1 if c['draw_mouse'] else 0}"
        if c.get("region"):
            x, y, w, h = c["region"]
            src += f":offset_x={x}:offset_y={y}:video_size={w}x{h}"
        if direct:
            return src, None
        pix = "yuv444p" if c["yuv444"] else ("yuv420p" if c["encoder"] == "libx264" else "nv12")
        w, h = c["size"]
        chain = "hwdownload,format=bgra"
        if self.zoom_port:
            # Kayit surerken zmq ile crop komutlari gonderilir; scale ciktiyi hep ayni boyutta tutar
            chain += (rf",zmq=bind_address=tcp\\\://127.0.0.1\\\:{self.zoom_port}"
                      f",crop@zoom=w={w}:h={h}:x=0:y=0:exact=1")
        chain += f",scale={w}:{h}:flags=bicubic:out_color_matrix=bt709:out_range=tv,format={pix}"
        return src, chain

    def _encoder_args(self, direct):
        c = self.cfg
        enc, q, fps = c["encoder"], str(c["quality"]), c["fps"]
        a = ["-c:v", enc, "-g", str(fps * 2)]
        if enc.endswith("_nvenc"):
            a += ["-preset", c["preset"], "-tune", "hq", "-rc", "vbr", "-cq", q, "-b:v", "0",
                  "-spatial-aq", "1", "-rc-lookahead", "20"]
            if enc != "av1_nvenc":
                a += ["-temporal-aq", "1"]
            if enc == "h264_nvenc":
                a += ["-profile:v", "high444p" if c["yuv444"] else "high"]
            elif enc == "hevc_nvenc":
                a += ["-profile:v", "rext" if c["yuv444"] else "main"]
        elif enc.endswith("_amf"):
            a += ["-quality", "quality", "-rc", "cqp", "-qp_i", q, "-qp_p", q]
            if enc == "h264_amf":
                a += ["-qp_b", q]
        elif enc.endswith("_qsv"):
            a += ["-preset", "veryslow", "-global_quality", q]
        else:
            a += ["-preset", "veryfast", "-crf", q]
        if not direct:
            a += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                  "-color_range", "tv"]
        return a

    def _cmd(self, out, direct, duration=None, loglevel="error"):
        src, vf = self._filter(direct)
        cmd = [self.cfg["ffmpeg"], "-hide_banner", "-nostats", "-loglevel", loglevel, "-y",
               "-f", "lavfi", "-i", src]
        if vf:
            cmd += ["-vf", vf]
        if duration:
            cmd += ["-t", str(duration)]
        return cmd + self._encoder_args(direct) + [out]

    def _use_direct(self):
        c = self.cfg
        # Zoom kareleri islemcide kirpar; dogrudan GPU yolu bunu desteklemez
        if zmq or c["yuv444"] or not (c["encoder"].endswith("_nvenc") or c["encoder"].endswith("_amf")):
            return False
        key = (c["ffmpeg"], c["encoder"], c["monitor"], c.get("region"))
        if key not in self._direct_ok:
            # Ekran ile kodlayici ayni GPU'daysa kopyasiz yol calisir (hibrit laptoplarda calismaz)
            code, _ = run_quiet(self._cmd("-", True, 0.3)[:-1] + ["-f", "null", "-"], timeout=15)
            self._direct_ok[key] = code == 0
        return self._direct_ok[key]

    # --- durum gecisleri
    def start(self, cfg):
        self.cfg = cfg
        os.makedirs(cfg["out_dir"], exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.final_path = os.path.join(cfg["out_dir"], f"{t('file_prefix')}_{stamp}.{cfg['container']}")
        self.parts_dir = tempfile.mkdtemp(prefix=f"ekrankayit_{stamp}_")
        self.segments = []
        self.audio = None
        self.audio_errors = []
        self.mic_muted = False
        self.direct = self._use_direct()
        return self._start_segment()

    def _start_segment(self):
        c = self.cfg
        n = len(self.segments)
        seg = {"video": os.path.join(self.parts_dir, f"part_{n:03d}.mkv"), "audio": None,
               "v0": None, "a0": None}
        self.log_path = os.path.join(self.parts_dir, "ffmpeg.log")
        self.audio = None
        if c["system_audio"] is not None or c["mic"] is not None:
            try:
                self.audio = AudioCapture(os.path.join(self.parts_dir, f"part_{n:03d}.wav"),
                                          c["system_audio"], c["system_gain"], c["mic"], c["mic_gain"])
                self.audio.start(self.mic_muted)
                seg["audio"] = self.audio.path
            except Exception as e:  # noqa: BLE001
                self.audio = None
                self.failed.emit(t("audio_open_fail", e=e))
                return False
        self.zoom_port = _free_port() if zmq else None
        self.zoom_rect = None
        try:
            self.proc = subprocess.Popen(self._cmd(seg["video"], self.direct, loglevel="info"),
                                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            if self.audio:
                self.audio.stop()
                self.audio = None
            self.failed.emit(t("ff_start_fail", e=e))
            return False
        threading.Thread(target=self._read_log, args=(self.proc, seg), daemon=True).start()
        if self.zoom_port:
            # DEALER: komutlar cevap beklemeden ardi ardina gider, FFmpeg hepsini ayni karede uygular
            self._zsock = zmq.Context.instance().socket(zmq.DEALER)
            self._zsock.setsockopt(zmq.LINGER, 0)
            self._zsock.connect(f"tcp://127.0.0.1:{self.zoom_port}")
        self.segments.append(seg)
        QTimer.singleShot(1500, self._check_alive)
        return True

    def _read_log(self, proc, seg):
        """FFmpeg ciktisini loga yazar. 'Input #0' satiri ddagrab'in ilk kareyi aldigi ani isaretler;
        ses ile goruntuyu hizalamak icin bu an kullanilir."""
        with open(self.log_path, "ab") as log:
            for line in proc.stderr:
                if seg["v0"] is None and line.startswith(b"Input #0"):
                    seg["v0"] = time.perf_counter()
                log.write(line)
                log.flush()

    def _check_alive(self):
        if self.proc and self.proc.poll() not in (None, 0):
            time.sleep(0.2)
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                    err = f.read()[-1500:]
            except OSError:
                err = ""
            self.proc = None
            self.failed.emit(t("ff_stopped", e=err))

    def has_mic(self):
        return bool(self.cfg and self.cfg.get("mic") is not None)

    def set_mic_muted(self, muted):
        """Kayit boyunca gecerli; duraklat/devam sonrasi yeni segment de ayni durumla baslar."""
        self.mic_muted = muted
        if self.audio:
            self.audio.set_mic_muted(muted)

    # --- canli zoom
    def zoom_to(self, rect, duration=0.35):
        """Videoyu kayit alani icindeki rect'e (x, y, w, h) yumusakca yaklastirir; None tam goruntuye doner."""
        if not self._zsock:
            return
        w, h = self.cfg["size"]
        start = self.zoom_rect or (0, 0, w, h)
        end = rect or (0, 0, w, h)
        self.zoom_rect = rect
        self._zoom_gen += 1
        threading.Thread(target=self._animate_zoom, args=(start, end, duration, self._zoom_gen),
                         daemon=True).start()

    def _animate_zoom(self, start, end, duration, gen):
        t0 = time.perf_counter()
        while gen == self._zoom_gen:
            k = min(1.0, (time.perf_counter() - t0) / duration)
            e = k * k * (3 - 2 * k)  # yumusak baslangic ve bitis
            x, y, w, h = (a + (b - a) * e for a, b in zip(start, end))
            w, h = max(16, round(w) // 2 * 2), max(16, round(h) // 2 * 2)
            with self._zlock:
                sock = self._zsock
                if not sock:
                    return
                try:
                    for name, v in (("w", w), ("h", h), ("x", round(x)), ("y", round(y))):
                        sock.send_multipart([b"", f"crop@zoom {name} {v}".encode()], zmq.NOBLOCK)
                    while sock.poll(0):
                        sock.recv_multipart()
                except zmq.ZMQError:
                    return
            if k >= 1:
                return
            time.sleep(1 / 60)

    def _stop_segment(self):
        self._zoom_gen += 1
        with self._zlock:
            if self._zsock:
                self._zsock.close()
                self._zsock = None
        self.zoom_rect = None
        p, self.proc = self.proc, None
        if p:
            try:
                p.stdin.write(b"q")
                p.stdin.flush()
                p.stdin.close()
            except OSError:
                pass
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
        audio, self.audio = self.audio, None
        if audio:
            audio.stop()
            self.segments[-1]["a0"] = audio.t0
            self.audio_errors += audio.errors

    def pause(self):
        self._stop_segment()

    def resume(self):
        return self._start_segment()

    def stop(self):
        self._stop_segment()
        threading.Thread(target=self._finalize, daemon=True).start()

    def _mux_audio(self, seg):
        """Segment videosuna WAV'i zaman farkini duzelterek ekler; video uzunluguna gore keser/uzatir."""
        out = seg["video"][:-4] + "_av.mkv"
        offset = (seg["a0"] - seg["v0"]) if seg["a0"] is not None and seg["v0"] is not None else 0.0
        shift = ["-itsoffset", f"{offset:.3f}"] if offset >= 0 else ["-ss", f"{-offset:.3f}"]
        cmd = [self.cfg["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-i", seg["video"],
               *shift, "-i", seg["audio"], "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-af", "apad", "-shortest", "-c:a", "aac", "-b:a", "192k", out]
        code, err = run_quiet(cmd, timeout=3600)
        if code != 0:
            raise RuntimeError(t("audio_mux_fail", e=err[-1500:]))
        return out

    def _finalize(self):
        segs = [s for s in self.segments if os.path.isfile(s["video"]) and os.path.getsize(s["video"]) > 1024]
        if not segs:
            self.failed.emit(t("nothing"))
            return
        try:
            files = [self._mux_audio(s) if s["audio"] and os.path.isfile(s["audio"]) else s["video"]
                     for s in segs]
        except RuntimeError as e:
            self.failed.emit(f"{e}{t('parts', d=self.parts_dir)}")
            return
        lst = os.path.join(self.parts_dir, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for s in files:
                f.write("file '" + s.replace("\\", "/").replace("'", r"'\''") + "'\n")
        cmd = [self.cfg["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
               "-safe", "0", "-i", lst, "-c", "copy"]
        if self.final_path.endswith(".mp4"):
            cmd += ["-movflags", "+faststart"]
            if self.cfg["encoder"].startswith("hevc"):
                cmd += ["-tag:v", "hvc1"]
        cmd.append(self.final_path)
        code, err = run_quiet(cmd, timeout=3600)
        if code != 0:
            self.failed.emit(t("concat_fail", e=err[-1500:]) + t("parts", d=self.parts_dir))
            return
        shutil.rmtree(self.parts_dir, ignore_errors=True)
        self.finished.emit(self.final_path)


# --------------------------------------------------------------------------- Guncelleme (GitHub Releases)

def version_tuple(v):
    """'v1.2.10' -> (1, 2, 10); sayisal olmayan ekler (-beta) karsilastirmada yok sayilir."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v).split("-")[0])[:3])


def release_notes_text(body):
    """Surum sayfasindaki aciklamanin sadece 'What's new' kismini duz metin olarak dondurur
    (ustteki indirme talimatlari ve Markdown isaretleri guncelleme penceresinde gosterilmez)."""
    if "## What's new" in body:
        body = body.split("## What's new", 1)[1]
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"[*`#]+", "", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def repo_configured():
    return not GITHUB_REPO.startswith("OWNER/")


class UpdateChecker(QObject):
    """GitHub'in 'latest release' API'sine bakar. Sadece surum bilgisi istenir; hicbir kullanici verisi gonderilmez."""
    result = Signal(object, str)  # (surum bilgisi | None, hata metni)

    def check(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"{APP_NAME}/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - ag hatalari kullaniciya metin olarak gosterilir
            self.result.emit(None, str(e))
            return
        asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith("setup.exe")), None)
        self.result.emit({
            "version": data.get("tag_name", "").lstrip("vV"),
            "notes": (data.get("body") or "").strip(),
            "page": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
            "asset": asset and {"name": asset["name"], "url": asset["browser_download_url"],
                                "size": asset.get("size", 0), "digest": asset.get("digest") or ""},
        }, "")


class UpdateDownloader(QObject):
    """Kurulum dosyasini %TEMP%'e indirir ve GitHub'in verdigi SHA-256 ozetiyle dogrular."""
    progress = Signal(int, int)
    done = Signal(str, str)  # (dosya yolu, hata)

    def __init__(self, asset):
        super().__init__()
        self.asset = asset
        self.cancelled = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        path = os.path.join(tempfile.gettempdir(), self.asset["name"])
        sha = hashlib.sha256()
        try:
            req = urllib.request.Request(self.asset["url"], headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or self.asset.get("size") or 0)
                got = 0
                while not self.cancelled:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            if self.cancelled:
                os.remove(path)
                self.done.emit("", "cancelled")
                return
            expected = self.asset.get("digest", "")
            if expected.startswith("sha256:") and expected[7:].lower() != sha.hexdigest():
                os.remove(path)
                self.done.emit("", "hash")
                return
            self.done.emit(path, "")
        except Exception as e:  # noqa: BLE001
            self.done.emit("", str(e))


def system_report(ffmpeg, encoders):
    """Sorun bildiriminde onceden doldurulacak bilgiler (kisisel veri icermez)."""
    gpus = ""
    try:
        gpus = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + ' (driver ' + $_.DriverVersion + ')' }"],
            capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    ffver = "-"
    try:
        if ffmpeg:
            ffver = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=10,
                                   creationflags=CREATE_NO_WINDOW).stdout.splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        pass
    return {"version": f"{VERSION}{'' if FROZEN else ' (source)'}",
            "os": f"{platform.platform()} ({platform.machine()})",
            "gpu": gpus or "-",
            "encoders": f"{', '.join(encoders) or '-'} | {ffver}"}


# --------------------------------------------------------------------------- Arayuz

class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, color):
        super().__init__()
        self.setFixedWidth(70)
        self.set_color(QColor(color))
        self.clicked.connect(self._pick)

    def set_color(self, c):
        self.color = QColor(c)
        fg = "#000" if self.color.lightness() > 128 else "#fff"
        self.setText(self.color.name())
        self.setStyleSheet(f"background:{self.color.name()};color:{fg};border-radius:4px;padding:4px;")

    def _pick(self):
        c = QColorDialog.getColor(self.color, self, t("pick_color"))
        if c.isValid():
            self.set_color(c)
            self.changed.emit()


class MainWindow(QWidget):
    encoders_ready = Signal(str, list)

    def __init__(self, settings):
        super().__init__()
        self.setWindowTitle(t("app_title"))
        self.setWindowIcon(QIcon(make_icon_pixmap()))
        self.settings = settings
        self.recorder = Recorder()
        self.recorder.finished.connect(self._on_finished)
        self.recorder.failed.connect(self._on_failed)
        self.overlay = HighlightOverlay()
        self.magnifier = Magnifier()
        self.keys = KeystrokeOverlay()
        self.webcam = WebcamOverlay()
        self.webcam.moved.connect(self._save_webcam_pos)
        self.webcam.resized.connect(lambda v: self.sp_cam_size.setValue(v))
        self.webcam.error.connect(lambda m: self.info.setText(m))
        self.recorder.stage.connect(self._on_stage)
        self._stage_text = ""
        self.marker = PauseMarker()
        self.frame = RegionFrame()
        self.minibar = MiniBar()
        self.minibar.pause_clicked.connect(self.toggle_pause)
        self.minibar.stop_clicked.connect(self.stop_action)
        self.minibar.mic_clicked.connect(self.toggle_mic)
        self.minibar.cam_clicked.connect(self.toggle_cam)
        self.drawing = DrawingOverlay()
        self.drawing.mode_changed.connect(lambda _: self._sync_draw_ui())
        self.drawing.touched.connect(lambda: self._raise_controls())
        self.minibar.draw_toggled.connect(self.toggle_draw_mode)
        self.minibar.tool_changed.connect(self._choose_tool)
        self.minibar.color_changed.connect(self._choose_color)
        self.minibar.undo_clicked.connect(self.drawing.undo)
        self.minibar.redo_clicked.connect(self.drawing.redo)
        self.minibar.clear_clicked.connect(self.drawing.clear)
        self._lens_vk = 0
        self._lens_hold_timer = QTimer(self)
        self._lens_hold_timer.timeout.connect(self._lens_hold_check)
        self.zoom_picker = ZoomPicker()
        self.zoom_picker.picked.connect(self._on_zoom_picked)
        self.zoom_frame = RegionFrame("#3daee9")
        self.zoom_btn = ZoomExitButton()
        self.zoom_btn.clicked.connect(self.exit_zoom)
        self.zoom_active = False
        self.magnifier.exclude = [self, self.overlay, self.marker, self.frame, self.minibar, self.keys,
                                  self.webcam, self.zoom_frame, self.zoom_btn]
        self.picker = AreaPicker()
        self.picker.picked.connect(self._on_area_picked)
        self.picker.cancelled.connect(self._restore_after_pick)
        self.region = None  # (x, y, w, h) secili ekranda fiziksel piksel; None = tum ekran
        self.state = "idle"  # idle | countdown | recording | paused | saving
        self.saved_cursor = None
        self.elapsed = 0.0
        self.seg_start = 0.0
        self.countdown_left = 0
        self.gpu_name = ""
        self._relaunch = False

        self._build_ui()
        self._load_settings()
        self._apply_overlay()
        self._apply_lens()
        self._apply_keys()
        self._apply_cam()

        self.clock = QTimer(self)
        self.clock.timeout.connect(self._update_status)
        self.clock.start(200)

        self.hotkeys = None
        self._restart_hotkeys()
        self._refresh_buttons()

        self.encoders_ready.connect(self._fill_encoders)
        threading.Thread(target=self._detect_ffmpeg, daemon=True).start()

        self._pending_update = None
        self._update_silent = True
        self.updater = UpdateChecker()
        self.updater.result.connect(self._on_update_result)
        if self.ck_auto_update.isChecked() and repo_configured():
            QTimer.singleShot(4000, lambda: self._check_updates(silent=True))

    # --- arayuz
    def _build_ui(self):
        root = QVBoxLayout(self)

        self.status = QLabel()
        f = QFont()
        f.setPointSize(15)
        f.setBold(True)
        self.status.setFont(f)
        self.status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status)
        self.btn_update_badge = QPushButton()
        self.btn_update_badge.setStyleSheet("QPushButton{background:#1e88e5;color:white;border:none;"
                                            "border-radius:6px;padding:6px;font-weight:bold;}")
        self.btn_update_badge.clicked.connect(lambda: self._offer_update(self._pending_update))
        self.btn_update_badge.hide()
        root.addWidget(self.btn_update_badge)

        row = QHBoxLayout()
        self.btn_rec = QPushButton()
        self.btn_pause = QPushButton()
        self.btn_stop = QPushButton()
        for b in (self.btn_rec, self.btn_pause, self.btn_stop):
            b.setMinimumHeight(44)
            row.addWidget(b)
        self.btn_rec.clicked.connect(self.start_action)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop_action)
        root.addLayout(row)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Video
        g = QGroupBox(t("grp_video"))
        fl = QFormLayout(g)
        self.cb_lang = QComboBox()
        self.cb_lang.addItem("Türkçe", "tr")
        self.cb_lang.addItem("English", "en")
        self.cb_lang.setCurrentIndex(self.cb_lang.findData(LANG))
        self.cb_lang.currentIndexChanged.connect(self._language_changed)
        fl.addRow(t("language"), self.cb_lang)
        self.cb_monitor = QComboBox()
        self.cb_monitor.addItems([t("monitor_item", i=i + 1, m=m) for i, m in enumerate(list_monitors())])
        self.cb_monitor.activated.connect(lambda _: self._set_region(None))
        fl.addRow(t("monitor"), self.cb_monitor)
        arow = QHBoxLayout()
        self.lb_area = QLabel()
        self.btn_pick = QPushButton(t("pick_area"))
        self.btn_pick.setToolTip(t("pick_tip"))
        self.btn_pick.clicked.connect(self._pick_area)
        self.btn_full = QPushButton(t("full_screen"))
        self.btn_full.clicked.connect(lambda: self._set_region(None))
        arow.addWidget(self.lb_area, 1)
        arow.addWidget(self.btn_pick)
        arow.addWidget(self.btn_full)
        fl.addRow(t("area"), arow)
        self.cb_fps = QComboBox()
        self.cb_fps.addItems(["30", "60", "120", "144"])
        fl.addRow(t("fps"), self.cb_fps)
        self.cb_encoder = QComboBox()
        self.cb_encoder.addItem(t("enc_searching"), "")
        fl.addRow(t("encoder"), self.cb_encoder)
        self.cb_preset = QComboBox()
        for p in NVENC_PRESETS:
            self.cb_preset.addItem(t("preset_item", name=t(p), p=p, cq=PRESET_CQ[p]), p)
        self.cb_preset.setToolTip(t("preset_tip"))
        fl.addRow(t("preset"), self.cb_preset)
        qrow = QHBoxLayout()
        self.sl_quality = QSlider(Qt.Horizontal)
        self.sl_quality.setRange(10, 32)
        self.lb_quality = QLabel()
        self.sl_quality.valueChanged.connect(self._quality_label)
        qrow.addWidget(self.sl_quality)
        qrow.addWidget(self.lb_quality)
        self.sl_quality.setToolTip(t("preset_tip"))
        fl.addRow(t("quality"), qrow)
        # Kullanici on ayari degistirince CQ'yu o ayarin onerdigi degere getir
        self.cb_preset.activated.connect(
            lambda _: self.sl_quality.setValue(PRESET_CQ[self.cb_preset.currentData()]))
        self.ck_444 = QCheckBox(t("yuv444"))
        self.ck_444.setToolTip(t("yuv444_tip"))
        fl.addRow("", self.ck_444)
        self.cb_container = QComboBox()
        self.cb_container.addItem("mp4", "mp4")
        self.cb_container.addItem("mkv", "mkv")
        fl.addRow(t("container"), self.cb_container)
        orow = QHBoxLayout()
        self.ed_out = QLineEdit()
        b = QPushButton("...")
        b.setFixedWidth(32)
        b.clicked.connect(self._browse_out)
        orow.addWidget(self.ed_out)
        orow.addWidget(b)
        fl.addRow(t("out_dir"), orow)
        frow = QHBoxLayout()
        self.ed_ffmpeg = QLineEdit()
        self.ed_ffmpeg.setPlaceholderText(t("auto"))
        self.ed_ffmpeg.editingFinished.connect(
            lambda: threading.Thread(target=self._detect_ffmpeg, daemon=True).start())
        b2 = QPushButton("...")
        b2.setFixedWidth(32)
        b2.clicked.connect(self._browse_ffmpeg)
        frow.addWidget(self.ed_ffmpeg)
        frow.addWidget(b2)
        fl.addRow("FFmpeg:", frow)
        body.addWidget(g)

        # Ses
        g = QGroupBox(t("grp_audio"))
        fl = QFormLayout(g)
        self.ck_sys = QCheckBox(t("sys_audio"))
        fl.addRow("", self.ck_sys)
        self.cb_speaker = QComboBox()
        self.cb_speaker.addItem(t("default_dev"), DEFAULT_DEVICE)
        for name in list_speakers():
            self.cb_speaker.addItem(name, name)
        fl.addRow(t("out_dev"), self.cb_speaker)
        self.sl_sys_gain = QSlider(Qt.Horizontal)
        self.sl_sys_gain.setRange(0, 200)
        fl.addRow(t("sys_level"), self._with_percent(self.sl_sys_gain))
        self.ck_mic = QCheckBox(t("mic"))
        fl.addRow("", self.ck_mic)
        self.cb_mic = QComboBox()
        self.cb_mic.addItem(t("default_dev"), DEFAULT_DEVICE)
        for name in list_mics():
            self.cb_mic.addItem(name, name)
        fl.addRow(t("mic_dev"), self.cb_mic)
        self.sl_mic_gain = QSlider(Qt.Horizontal)
        self.sl_mic_gain.setRange(0, 300)
        fl.addRow(t("mic_level"), self._with_percent(self.sl_mic_gain))
        if soundcard is None:
            g.setEnabled(False)
            g.setTitle(t("no_soundcard"))
        body.addWidget(g)

        # Kisayollar
        g = QGroupBox(t("grp_hotkeys"))
        fl = QFormLayout(g)
        self.hk_edits = {}
        for hid, key in ((HOTKEY_START, "hk_start"), (HOTKEY_PAUSE, "hk_pause"), (HOTKEY_STOP, "hk_stop"),
                         (HOTKEY_LENS, "hk_lens"), (HOTKEY_ZOOM, "hk_zoom"), (HOTKEY_DRAW, "hk_draw"),
                         (HOTKEY_CLEAR, "hk_clear"), (HOTKEY_UNDO, "hk_undo"), (HOTKEY_REDO, "hk_redo")):
            ed = QKeySequenceEdit()
            ed.setMaximumSequenceLength(1)
            ed.setClearButtonEnabled(True)
            ed.editingFinished.connect(self._hotkeys_changed)
            self.hk_edits[hid] = ed
            fl.addRow(t(key), ed)
        self.lb_hk = QLabel(t("hk_hint"))
        self.lb_hk.setWordWrap(True)
        self.lb_hk.setStyleSheet("color:#888;")
        fl.addRow("", self.lb_hk)
        reset = QPushButton(t("hk_reset"))
        reset.clicked.connect(self._reset_hotkeys)
        fl.addRow("", reset)
        body.addWidget(g)

        # Mercek
        g = QGroupBox(t("grp_lens"))
        g.setToolTip(t("lens_tip"))
        fl = QFormLayout(g)
        zrow = QHBoxLayout()
        self.sl_lens_zoom = QSlider(Qt.Horizontal)
        self.sl_lens_zoom.setRange(15, 60)  # x10
        self.lb_lens_zoom = QLabel()
        self.lb_lens_zoom.setMinimumWidth(40)
        self.sl_lens_zoom.valueChanged.connect(lambda v: self.lb_lens_zoom.setText(f"{v / 10:.1f}×"))
        zrow.addWidget(self.sl_lens_zoom)
        zrow.addWidget(self.lb_lens_zoom)
        fl.addRow(t("lens_zoom"), zrow)
        self.sp_lens_size = QSpinBox()
        self.sp_lens_size.setRange(120, 700)
        self.sp_lens_size.setSingleStep(20)
        self.sp_lens_size.setSuffix(" px")
        fl.addRow(t("lens_size"), self.sp_lens_size)
        self.cb_lens_shape = QComboBox()
        self.cb_lens_shape.addItem(t("shape_circle"), "circle")
        self.cb_lens_shape.addItem(t("shape_rounded"), "rounded")
        fl.addRow(t("lens_shape"), self.cb_lens_shape)
        self.btn_lens_color = ColorButton("#3daee9")
        fl.addRow(t("lens_color"), self.btn_lens_color)
        self.sp_lens_width = QSpinBox()
        self.sp_lens_width.setRange(0, 16)
        self.sp_lens_width.setSuffix(" px")
        fl.addRow(t("lens_width"), self.sp_lens_width)
        self.cb_lens_mode = QComboBox()
        self.cb_lens_mode.addItem(t("lens_toggle"), "toggle")
        self.cb_lens_mode.addItem(t("lens_hold"), "hold")
        fl.addRow(t("lens_mode"), self.cb_lens_mode)
        tip = QLabel(t("lens_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;")
        fl.addRow("", tip)
        self.btn_lens_preview = QPushButton(t("lens_preview"))
        self.btn_lens_preview.setCheckable(True)
        self.btn_lens_preview.toggled.connect(
            lambda on: self.magnifier.open_lens() if on else self.magnifier.close_lens())
        fl.addRow("", self.btn_lens_preview)
        body.addWidget(g)
        self.sl_lens_zoom.valueChanged.connect(self._apply_lens)
        self.sp_lens_size.valueChanged.connect(self._apply_lens)
        self.cb_lens_shape.currentIndexChanged.connect(self._apply_lens)
        self.btn_lens_color.changed.connect(self._apply_lens)
        self.sp_lens_width.valueChanged.connect(self._apply_lens)

        # Canli cizim
        g = QGroupBox(t("grp_draw"))
        fl = QFormLayout(g)
        self.ck_draw = QCheckBox(t("draw_on"))
        fl.addRow("", self.ck_draw)
        self.ck_tools_rec = QCheckBox(t("draw_tools_rec"))
        self.ck_tools_rec.setToolTip(t("draw_tools_rec_tip"))
        self.ck_tools_rec.toggled.connect(self.minibar.set_popups_visible)
        fl.addRow("", self.ck_tools_rec)
        self.btn_draw_color = ColorButton("#e53935")
        fl.addRow(t("draw_color"), self.btn_draw_color)
        self.sp_draw_width = QSpinBox()
        self.sp_draw_width.setRange(1, 20)
        self.sp_draw_width.setSuffix(" px")
        fl.addRow(t("draw_width"), self.sp_draw_width)
        frow = QHBoxLayout()
        self.cb_draw_tool = QComboBox()
        for tool, icon in DRAW_TOOLS:
            if tool not in ("laser", "eraser"):
                self.cb_draw_tool.addItem(f"{icon}  {t('tool_' + tool)}", tool)
        self.cb_draw_fade = QComboBox()
        for n in FADE_CHOICES:
            self.cb_draw_fade.addItem(t("fade_0") if n == 0 else t("fade_n", n=n), n)
        frow.addWidget(self.cb_draw_tool)
        frow.addWidget(self.cb_draw_fade)
        fl.addRow(t("draw_fade_for"), frow)
        tip = QLabel(t("draw_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;")
        fl.addRow("", tip)
        body.addWidget(g)
        self.cb_draw_tool.currentIndexChanged.connect(
            lambda _: self.cb_draw_fade.setCurrentIndex(
                self.cb_draw_fade.findData(self.drawing.fades[self.cb_draw_tool.currentData()])))
        self.cb_draw_fade.activated.connect(
            lambda _: self._set_fade(self.cb_draw_tool.currentData(), self.cb_draw_fade.currentData()))

        # Tus gosterimi
        g = QGroupBox(t("grp_keys"))
        fl = QFormLayout(g)
        self.ck_keys = QCheckBox(t("keys_on"))
        fl.addRow("", self.ck_keys)
        self.cb_keys_mode = QComboBox()
        self.cb_keys_mode.addItem(t("keys_shortcuts"), "shortcuts")
        self.cb_keys_mode.addItem(t("keys_all"), "all")
        fl.addRow(t("keys_mode"), self.cb_keys_mode)
        self.cb_keys_pos = QComboBox()
        for key in ("bc", "bl", "br", "tc"):
            self.cb_keys_pos.addItem(t("pos_" + key), key)
        fl.addRow(t("keys_pos"), self.cb_keys_pos)
        self.cb_keys_size = QComboBox()
        for key, px in (("size_s", 18), ("size_m", 24), ("size_l", 32)):
            self.cb_keys_size.addItem(t(key), px)
        fl.addRow(t("keys_size"), self.cb_keys_size)
        note = QLabel(t("keys_privacy"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        fl.addRow("", note)
        self.btn_keys_preview = QPushButton(t("keys_preview"))
        self.btn_keys_preview.setCheckable(True)
        self.btn_keys_preview.toggled.connect(
            lambda on: self.keys.start(self._capture_rect()) if on else self.keys.stop())
        fl.addRow("", self.btn_keys_preview)
        body.addWidget(g)
        for cb in (self.cb_keys_mode, self.cb_keys_pos, self.cb_keys_size):
            cb.currentIndexChanged.connect(self._apply_keys)

        # Webcam
        g = QGroupBox(t("grp_cam"))
        g.setToolTip(t("cam_tip"))
        fl = QFormLayout(g)
        self.ck_cam = QCheckBox(t("cam_on"))
        fl.addRow("", self.ck_cam)
        self.cb_cam_dev = QComboBox()
        cams = QMediaDevices.videoInputs()
        for d in cams:
            self.cb_cam_dev.addItem(d.description(), bytes(d.id()).hex())
        if not cams:
            self.cb_cam_dev.addItem(t("cam_none"), "")
            self.ck_cam.setEnabled(False)
        fl.addRow(t("cam_dev"), self.cb_cam_dev)
        self.cb_cam_shape = QComboBox()
        self.cb_cam_shape.addItem(t("shape_circle"), "circle")
        self.cb_cam_shape.addItem(t("cam_rect"), "rect")
        fl.addRow(t("cam_shape"), self.cb_cam_shape)
        self.sp_cam_size = QSpinBox()
        self.sp_cam_size.setRange(120, 720)
        self.sp_cam_size.setSingleStep(20)
        self.sp_cam_size.setSuffix(" px")
        fl.addRow(t("cam_size"), self.sp_cam_size)
        self.ck_cam_mirror = QCheckBox(t("cam_mirror"))
        fl.addRow("", self.ck_cam_mirror)
        brow = QHBoxLayout()
        self.btn_cam_color = ColorButton("#ffffff")
        self.sp_cam_border = QSpinBox()
        self.sp_cam_border.setRange(0, 16)
        self.sp_cam_border.setSuffix(" px")
        brow.addWidget(self.btn_cam_color)
        brow.addWidget(self.sp_cam_border)
        brow.addStretch()
        fl.addRow(t("cam_border"), brow)
        tip = QLabel(t("cam_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;")
        fl.addRow("", tip)
        self.btn_cam_preview = QPushButton(t("cam_preview"))
        self.btn_cam_preview.setCheckable(True)
        self.btn_cam_preview.setEnabled(bool(cams))
        self.btn_cam_preview.toggled.connect(
            lambda on: self.webcam.show_at(self._webcam_pos()) if on else self.webcam.hide_cam(animated=True))
        fl.addRow("", self.btn_cam_preview)
        body.addWidget(g)
        self.cb_cam_dev.currentIndexChanged.connect(self._apply_cam)
        self.cb_cam_shape.currentIndexChanged.connect(self._apply_cam)
        self.sp_cam_size.valueChanged.connect(self._apply_cam)
        self.ck_cam_mirror.toggled.connect(self._apply_cam)
        self.btn_cam_color.changed.connect(self._apply_cam)
        self.sp_cam_border.valueChanged.connect(self._apply_cam)

        # Fare
        g = QGroupBox(t("grp_mouse"))
        fl = QFormLayout(g)
        self.ck_cursor = QCheckBox(t("draw_cursor"))
        fl.addRow("", self.ck_cursor)
        self.ck_highlight = QCheckBox(t("highlight"))
        fl.addRow("", self.ck_highlight)
        self.cb_style = QComboBox()
        self.cb_style.addItem(t("style_fill"), "fill")
        self.cb_style.addItem(t("style_ring"), "ring")
        self.cb_style.addItem(t("style_both"), "both")
        fl.addRow(t("style"), self.cb_style)
        self.btn_color = ColorButton("#ffdc00")
        fl.addRow(t("hl_color"), self.btn_color)
        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setRange(10, 90)
        fl.addRow(t("opacity"), self.sl_opacity)
        self.sp_radius = QSpinBox()
        self.sp_radius.setRange(10, 120)
        self.sp_radius.setSuffix(" px")
        fl.addRow(t("radius"), self.sp_radius)
        self.ck_click = QCheckBox(t("click_fx"))
        fl.addRow("", self.ck_click)
        crow = QHBoxLayout()
        self.btn_lcolor = ColorButton("#ff3c3c")
        self.btn_rcolor = ColorButton("#3c8cff")
        crow.addWidget(QLabel(t("left")))
        crow.addWidget(self.btn_lcolor)
        crow.addWidget(QLabel(t("right")))
        crow.addWidget(self.btn_rcolor)
        crow.addStretch()
        fl.addRow(t("click_colors"), crow)
        self.btn_preview = QPushButton(t("preview"))
        self.btn_preview.setCheckable(True)
        self.btn_preview.toggled.connect(self._preview)
        fl.addRow("", self.btn_preview)
        body.addWidget(g)
        for w in (self.btn_color, self.btn_lcolor, self.btn_rcolor):
            w.changed.connect(self._apply_overlay)
        self.sl_opacity.valueChanged.connect(self._apply_overlay)
        self.sp_radius.valueChanged.connect(self._apply_overlay)
        self.cb_style.currentIndexChanged.connect(self._apply_overlay)
        self.ck_click.toggled.connect(self._apply_overlay)

        # Duraklatma
        g = QGroupBox(t("grp_pause"))
        fl = QFormLayout(g)
        self.ck_restore = QCheckBox(t("restore"))
        fl.addRow("", self.ck_restore)
        self.ck_marker = QCheckBox(t("marker"))
        fl.addRow("", self.ck_marker)
        self.ck_hide = QCheckBox(t("hide_win"))
        self.ck_hide.toggled.connect(lambda v: exclude_from_capture(self, v))
        fl.addRow("", self.ck_hide)
        self.ck_minibar = QCheckBox(t("minibar"))
        fl.addRow("", self.ck_minibar)
        self.ck_frame = QCheckBox(t("frame"))
        fl.addRow("", self.ck_frame)
        self.ck_minimize = QCheckBox(t("minimize"))
        fl.addRow("", self.ck_minimize)
        self.sp_countdown = QSpinBox()
        self.sp_countdown.setRange(0, 10)
        self.sp_countdown.setSuffix(t("sec"))
        fl.addRow(t("countdown"), self.sp_countdown)
        body.addWidget(g)

        # Hakkinda ve guncellemeler
        g = QGroupBox(t("grp_about"))
        fl = QFormLayout(g)
        fl.addRow("", QLabel(f"<b>{APP_NAME}</b> &nbsp; {t('about_version', v=VERSION)} &nbsp; · &nbsp; GPL-3.0"))
        self.ck_auto_update = QCheckBox(t("upd_auto"))
        fl.addRow("", self.ck_auto_update)
        urow = QHBoxLayout()
        self.btn_check_update = QPushButton(t("upd_check"))
        self.btn_check_update.clicked.connect(lambda: self._check_updates(silent=False))
        self.btn_report = QPushButton(t("report"))
        self.btn_report.clicked.connect(self._report_problem)
        btn_page = QPushButton(t("project_page"))
        btn_page.clicked.connect(lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}"))
        for b in (self.btn_check_update, self.btn_report, btn_page):
            urow.addWidget(b)
        fl.addRow("", urow)
        self.lb_update = QLabel(t("upd_privacy"))
        self.lb_update.setWordWrap(True)
        self.lb_update.setStyleSheet("color:#888;")
        fl.addRow("", self.lb_update)
        body.addWidget(g)
        body.addStretch()

        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#888;")
        root.addWidget(self.info)
        credit = QLabel(f'Created by <a href="{AUTHOR_URL}" style="color:#3daee9;text-decoration:none;">{AUTHOR}</a>')
        credit.setOpenExternalLinks(True)
        credit.setToolTip(AUTHOR_URL)
        credit.setAlignment(Qt.AlignCenter)
        credit.setStyleSheet("color:#7a7a7a; font-size:11px; padding-top:2px;")
        root.addWidget(credit)
        self._setup_preview_buttons()

    def _setup_preview_buttons(self):
        """Onizleme dugmeleri ac/kapa calisir: acikken yazisi ve rengi degisir, cikmak icin tekrar tiklanacagini
        soyler. Kullanicilar onizlemenin kendiliginden kapanmasini bekleyip ekranda kalan vurguyu hata sanabiliyordu."""
        active_css = ("QPushButton{background:#c62828;color:white;border:none;border-radius:4px;padding:5px;"
                      "font-weight:bold;}")
        for btn, key in ((self.btn_preview, "preview"), (self.btn_lens_preview, "lens_preview"),
                         (self.btn_keys_preview, "keys_preview"), (self.btn_cam_preview, "cam_preview")):
            btn.setToolTip(t("preview_tip"))

            def sync(on, btn=btn, key=key):
                btn.setText(t("preview_stop") if on else t(key))
                btn.setStyleSheet(active_css if on else "")

            btn.toggled.connect(sync)

    @staticmethod
    def _with_percent(slider):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lb = QLabel()
        lb.setMinimumWidth(40)
        slider.valueChanged.connect(lambda v: lb.setText(f"%{v}" if LANG == "tr" else f"{v}%"))
        lay.addWidget(slider)
        lay.addWidget(lb)
        return box

    def _quality_label(self, v):
        hint = t("q_lossless") if v <= 16 else t("q_vhigh") if v <= 20 else t("q_high") if v <= 24 else t("q_med")
        self.lb_quality.setText(f"{v}  ({hint})")

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, t("out_dir"), self.ed_out.text())
        if d:
            self.ed_out.setText(d)

    def _browse_ffmpeg(self):
        f, _ = QFileDialog.getOpenFileName(self, t("pick_ffmpeg"), "", "ffmpeg.exe (ffmpeg.exe)")
        if f:
            self.ed_ffmpeg.setText(f)
            threading.Thread(target=self._detect_ffmpeg, daemon=True).start()

    def _language_changed(self):
        if self.state != "idle":
            self.cb_lang.blockSignals(True)
            self.cb_lang.setCurrentIndex(self.cb_lang.findData(LANG))
            self.cb_lang.blockSignals(False)
            return
        self.settings.setValue("language", self.cb_lang.currentData())
        self._relaunch = True
        self.close()

    # --- kayit alani
    def _pick_area(self):
        if self.state != "idle":
            return
        self.btn_preview.setChecked(False)
        self.hide()
        QTimer.singleShot(150, self.picker.start)  # pencere kaybolsun, sonra katman acilsin

    def _restore_after_pick(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_area_picked(self, idx, region):
        self.cb_monitor.setCurrentIndex(idx)
        self._set_region(region)
        self._restore_after_pick()

    def _set_region(self, region):
        self.region = region
        idx = self.cb_monitor.currentIndex()
        infos = output_infos()
        if region:
            x, y, w, h = region
            self.lb_area.setText(t("area_region", w=w, h=h, x=x, y=y))
        elif 0 <= idx < len(infos):
            self.lb_area.setText(t("area_full", w=infos[idx]["w"], h=infos[idx]["h"]))
        self.btn_full.setEnabled(region is not None)

    # --- guncelleme ve sorun bildirme
    def _check_updates(self, silent):
        if not repo_configured():
            self.lb_update.setText(t("upd_failed", e="GITHUB_REPO is not set"))
            return
        self._update_silent = silent
        self.btn_check_update.setEnabled(False)
        self.lb_update.setText(t("upd_checking"))
        self.updater.check()

    def _on_update_result(self, info, error):
        self.btn_check_update.setEnabled(True)
        if error:
            self.lb_update.setText(t("upd_failed", e=error))
            return
        cur, new = version_tuple(VERSION), version_tuple(info["version"])
        if not new or new <= cur:
            self.lb_update.setText(t("upd_latest", v=VERSION))
            return
        if self._update_silent and self.settings.value("skip_version", "") == info["version"]:
            self.lb_update.setText(t("upd_skipped", v=info["version"]))
            return
        self._pending_update = info
        self.lb_update.setText(t("upd_badge", v=info["version"]))
        self.btn_update_badge.setText(t("upd_badge", v=info["version"]))
        self.btn_update_badge.show()
        if self.state == "idle":  # kayit surerken pencere acip rahatsiz etme; ust dugme yeterli
            self._offer_update(info)

    def _offer_update(self, info):
        if not info:
            return
        if self.state != "idle":
            QMessageBox.information(self, t("app_title"), t("upd_busy"))
            return
        notes = release_notes_text(info["notes"])
        notes = notes[:1500] + ("…" if len(notes) > 1500 else "")
        box = QMessageBox(self)
        box.setWindowTitle(t("upd_available_title"))
        box.setText(t("upd_available", name=APP_NAME, new=info["version"], cur=VERSION, notes=notes or "-"))
        install = box.addButton(t("upd_install"), QMessageBox.AcceptRole)
        skip = box.addButton(t("upd_skip"), QMessageBox.RejectRole)
        box.addButton(t("upd_later"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is skip:
            self.settings.setValue("skip_version", info["version"])
            self.btn_update_badge.hide()
        elif box.clickedButton() is install:
            if not FROZEN or not info["asset"]:
                # Kaynak koddan calisiyor (veya kurulum dosyasi yok): surum sayfasini ac
                webbrowser.open(info["page"])
                return
            self._download_update(info["asset"])

    def _download_update(self, asset):
        dlg = QProgressDialog(t("upd_downloading"), t("btn_cancel"), 0, 100, self)
        dlg.setWindowTitle(t("upd_available_title"))
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        self._downloader = UpdateDownloader(asset)
        self._downloader.progress.connect(
            lambda got, total: dlg.setValue(int(got * 100 / total)) if total else None)
        dlg.canceled.connect(lambda: setattr(self._downloader, "cancelled", True))
        self._downloader.done.connect(lambda path, err: self._update_downloaded(dlg, path, err))
        self._downloader.start()

    def _update_downloaded(self, dlg, path, error):
        dlg.close()
        if error == "cancelled":
            return
        if error:
            QMessageBox.warning(self, t("app_title"), t("upd_bad_hash") if error == "hash"
                                else t("upd_failed", e=error))
            return
        # Inno Setup: sessiz kurulum; bitince uygulamayi kendisi yeniden baslatir ([Run] skipifnotsilent). Ayarlar AppData'da kalir.
        subprocess.Popen([path, "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS",
                          "/NORESTART"])
        self.close()

    def _report_problem(self):
        self.btn_report.setEnabled(False)
        encs = [self.cb_encoder.itemData(i) for i in range(self.cb_encoder.count()) if self.cb_encoder.itemData(i)]
        ffmpeg = getattr(self, "ffmpeg", "")

        def work():
            info = system_report(ffmpeg, encs)
            query = urllib.parse.urlencode({"template": "bug_report.yml", **info})
            webbrowser.open(f"https://github.com/{GITHUB_REPO}/issues/new?{query}")
            QTimer.singleShot(0, lambda: self.btn_report.setEnabled(True))

        threading.Thread(target=work, daemon=True).start()

    # --- kisayollar
    def _hotkey_text(self, hid):
        return self.hk_edits[hid].keySequence().toString(QKeySequence.PortableText)

    def _hotkey_label(self, hid):
        text = self.hk_edits[hid].keySequence().toString(QKeySequence.NativeText)
        return f"  ({text})" if text else ""

    def _hotkey_scope(self):
        """Kayit yokken sadece 'Kaydi baslat' tusu ayrilir; digerleri kayit surerken etkinlesir."""
        return "all" if self.state in ("countdown", "recording", "paused") else "idle"

    def _restart_hotkeys(self):
        if self.hotkeys:
            self.hotkeys.stop()
        self._hotkeys_scope = self._hotkey_scope()
        active = list(self.hk_edits) if self._hotkeys_scope == "all" else [HOTKEY_START]
        self.hotkeys = HotkeyThread({hid: self._hotkey_text(hid) for hid in self.hk_edits}, active)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.registered.connect(self._on_hotkeys_registered)
        self.hotkeys.start()

    def _sync_hotkey_scope(self):
        if self.hotkeys and self._hotkey_scope() != self._hotkeys_scope:
            self._restart_hotkeys()

    def _on_hotkeys_registered(self, failed):
        bad = []
        for hid in self.hk_edits:
            text = self._hotkey_text(hid)
            if hid in failed:
                bad.append(t("hk_taken", k=text))
            elif text and sequence_to_win(text) is None:
                bad.append(t("hk_bad", k=text))
        if bad:
            self.lb_hk.setText(t("hk_warn", msg="; ".join(bad)))
            self.lb_hk.setStyleSheet("color:#d9534f;")
        else:
            self.lb_hk.setText(t("hk_ok"))
            self.lb_hk.setStyleSheet("color:#5cb85c;")

    def _hotkeys_changed(self):
        texts = [self._hotkey_text(h) for h in self.hk_edits if self._hotkey_text(h)]
        if len(texts) != len(set(texts)):
            self.lb_hk.setText(t("hk_dup"))
            self.lb_hk.setStyleSheet("color:#d9534f;")
            return
        self._save_settings()
        self._restart_hotkeys()
        self._refresh_buttons()

    def _reset_hotkeys(self):
        for hid, text in HOTKEY_DEFAULTS.items():
            self.hk_edits[hid].setKeySequence(QKeySequence.fromString(text, QKeySequence.PortableText))
        self._hotkeys_changed()

    # --- FFmpeg / kodlayici tespiti
    def _detect_ffmpeg(self):
        manual = self.ed_ffmpeg.text().strip()
        cands = [manual] if manual else ffmpeg_candidates()
        best, best_encs, self.encoder_hint = "", [], ""
        for c in cands:
            encs, hint = working_encoders(c)
            gpu = [e for e in encs if e != "libx264"]
            if len(gpu) > len([e for e in best_encs if e != "libx264"]) or not best:
                best, best_encs, self.encoder_hint = c, encs, hint
            if any(e.endswith("_nvenc") for e in encs):
                self.encoder_hint = ""
                break
        self.gpu_name = ""
        if any(e.endswith("_nvenc") for e in best_encs):
            try:
                self.gpu_name = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                    text=True, timeout=5, creationflags=CREATE_NO_WINDOW).stdout.strip().splitlines()[0]
            except (OSError, IndexError, subprocess.SubprocessError):
                pass
        self.encoders_ready.emit(best, best_encs)

    def _fill_encoders(self, ffmpeg, encs):
        self.ffmpeg = ffmpeg
        want = self.settings.value("encoder", "h264_nvenc")
        self.cb_encoder.clear()
        for enc in ENCODER_IDS:
            if enc in encs:
                self.cb_encoder.addItem(t("enc_" + enc), enc)
        if not ffmpeg:
            self.cb_encoder.addItem(t("ffmpeg_missing_item"), "")
            self.info.setText(t("ffmpeg_missing"))
            return
        if not encs:
            self.cb_encoder.addItem(t("no_encoder"), "")
        self.cb_encoder.setCurrentIndex(max(0, self.cb_encoder.findData(want)))
        gpu = [e for e in encs if e != "libx264"]
        short = ffmpeg if len(ffmpeg) <= 60 else "…" + ffmpeg[-59:]
        self.info.setToolTip(ffmpeg)
        text = t("info_encoders", ff=short, encs=", ".join(gpu) or t("none_cpu"))
        if self.gpu_name:
            text += f"\nNVENC GPU: {self.gpu_name}"
        if not gpu:
            text += "\n" + t("hint_no_gpu")
        if getattr(self, "encoder_hint", ""):
            text += "\n" + self.encoder_hint
        self.info.setText(text)

    # --- ayarlar
    def _load_settings(self):
        s = self.settings

        def flag(key, default):
            return s.value(key, "true" if default else "false") == "true"

        self.cb_monitor.setCurrentIndex(min(int(s.value("monitor", 0)), self.cb_monitor.count() - 1))
        region = None
        try:
            parts = [int(v) for v in str(s.value("region", "")).split(",") if v.strip()]
            info = output_infos()[self.cb_monitor.currentIndex()]
            if len(parts) == 4 and parts[0] + parts[2] <= info["w"] and parts[1] + parts[3] <= info["h"]:
                region = tuple(parts)
        except (ValueError, IndexError):
            pass
        self._set_region(region)
        self.sl_lens_zoom.setValue(int(s.value("lens_zoom", 25)))
        self.lb_lens_zoom.setText(f"{self.sl_lens_zoom.value() / 10:.1f}×")
        self.sp_lens_size.setValue(int(s.value("lens_size", 280)))
        self.cb_lens_shape.setCurrentIndex(max(0, self.cb_lens_shape.findData(s.value("lens_shape", "circle"))))
        self.btn_lens_color.set_color(s.value("lens_color", "#3daee9"))
        self.sp_lens_width.setValue(int(s.value("lens_width", 4)))
        self.cb_lens_mode.setCurrentIndex(max(0, self.cb_lens_mode.findData(s.value("lens_mode", "toggle"))))
        self.ck_draw.setChecked(flag("draw_on", True))
        self.ck_auto_update.setChecked(flag("auto_update", True))
        self.ck_tools_rec.setChecked(flag("draw_tools_rec", False))
        self.minibar.set_popups_visible(self.ck_tools_rec.isChecked())
        self.btn_draw_color.set_color(s.value("draw_color", "#e53935"))
        self.sp_draw_width.setValue(int(s.value("draw_width", 4)))
        for item in str(s.value("draw_fades", "")).split(","):
            tool, _, sec = item.partition(":")
            if tool in self.drawing.fades and sec.isdigit():
                self.drawing.fades[tool] = int(sec)
        self.cb_draw_fade.setCurrentIndex(
            self.cb_draw_fade.findData(self.drawing.fades[self.cb_draw_tool.currentData()]))
        self.ck_minibar.setChecked(flag("minibar", True))
        self.ck_frame.setChecked(flag("region_frame", True))
        self.ck_minimize.setChecked(flag("minimize", False))
        self.cb_fps.setCurrentText(str(s.value("fps", "60")))
        self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findData(s.value("preset", "p7"))))
        self.sl_quality.setValue(int(s.value("quality", PRESET_CQ[self.cb_preset.currentData()])))
        self._quality_label(self.sl_quality.value())
        self.ck_444.setChecked(flag("yuv444", False))
        self.cb_container.setCurrentIndex(max(0, self.cb_container.findData(s.value("container", "mp4"))))
        self.ck_keys.setChecked(flag("keys_on", True))
        self.cb_keys_mode.setCurrentIndex(max(0, self.cb_keys_mode.findData(s.value("keys_mode", "shortcuts"))))
        self.cb_keys_pos.setCurrentIndex(max(0, self.cb_keys_pos.findData(s.value("keys_pos", "bc"))))
        self.cb_keys_size.setCurrentIndex(max(0, self.cb_keys_size.findData(int(s.value("keys_size", 24)))))
        self.ck_cam.setChecked(flag("cam_on", False) and self.ck_cam.isEnabled())
        self.cb_cam_dev.setCurrentIndex(max(0, self.cb_cam_dev.findData(s.value("cam_device", ""))))
        self.cb_cam_shape.setCurrentIndex(max(0, self.cb_cam_shape.findData(s.value("cam_shape", "circle"))))
        self.sp_cam_size.setValue(int(s.value("cam_size", 240)))
        self.ck_cam_mirror.setChecked(flag("cam_mirror", True))
        self.btn_cam_color.set_color(s.value("cam_color", "#ffffff"))
        self.sp_cam_border.setValue(int(s.value("cam_border", 3)))
        self.ed_out.setText(s.value("out_dir", os.path.join(os.path.expanduser("~"), "Videos", t("out_folder"))))
        self.ed_ffmpeg.setText(s.value("ffmpeg_manual", ""))
        self.ck_sys.setChecked(flag("system_audio", True))
        self.cb_speaker.setCurrentIndex(max(0, self.cb_speaker.findData(s.value("speaker", DEFAULT_DEVICE))))
        self.sl_sys_gain.setValue(int(s.value("system_gain", 100)))
        self.ck_mic.setChecked(flag("mic", False))
        self.cb_mic.setCurrentIndex(max(0, self.cb_mic.findData(s.value("mic_device", DEFAULT_DEVICE))))
        self.sl_mic_gain.setValue(int(s.value("mic_gain", 100)))
        for hid, default in HOTKEY_DEFAULTS.items():
            text = s.value(f"hotkey_{hid}", default)
            self.hk_edits[hid].setKeySequence(QKeySequence.fromString(text, QKeySequence.PortableText))
        self.ck_cursor.setChecked(flag("draw_mouse", True))
        self.ck_highlight.setChecked(flag("highlight", True))
        self.cb_style.setCurrentIndex(max(0, self.cb_style.findData(s.value("style", "fill"))))
        self.btn_color.set_color(s.value("color", "#ffdc00"))
        self.sl_opacity.setValue(int(s.value("opacity", 35)))
        self.sp_radius.setValue(int(s.value("radius", 28)))
        self.ck_click.setChecked(flag("click_effect", True))
        self.btn_lcolor.set_color(s.value("left_color", "#ff3c3c"))
        self.btn_rcolor.set_color(s.value("right_color", "#3c8cff"))
        self.ck_restore.setChecked(flag("restore_cursor", True))
        self.ck_marker.setChecked(flag("pause_marker", True))
        self.ck_hide.setChecked(flag("hide_window", True))
        self.sp_countdown.setValue(int(s.value("countdown", 3)))

    def _save_settings(self):
        s = self.settings
        s.setValue("language", LANG)
        s.setValue("monitor", self.cb_monitor.currentIndex())
        s.setValue("region", ",".join(map(str, self.region)) if self.region else "")
        s.setValue("lens_zoom", self.sl_lens_zoom.value())
        s.setValue("lens_size", self.sp_lens_size.value())
        s.setValue("lens_shape", self.cb_lens_shape.currentData())
        s.setValue("lens_color", self.btn_lens_color.color.name())
        s.setValue("lens_width", self.sp_lens_width.value())
        s.setValue("lens_mode", self.cb_lens_mode.currentData())
        s.setValue("draw_on", "true" if self.ck_draw.isChecked() else "false")
        s.setValue("auto_update", "true" if self.ck_auto_update.isChecked() else "false")
        s.setValue("draw_tools_rec", "true" if self.ck_tools_rec.isChecked() else "false")
        s.setValue("draw_color", self.btn_draw_color.color.name())
        s.setValue("draw_width", self.sp_draw_width.value())
        s.setValue("draw_fades", ",".join(f"{k}:{v}" for k, v in self.drawing.fades.items()))
        s.setValue("fps", self.cb_fps.currentText())
        if self.cb_encoder.currentData():
            s.setValue("encoder", self.cb_encoder.currentData())
        s.setValue("preset", self.cb_preset.currentData())
        s.setValue("quality", self.sl_quality.value())
        s.setValue("container", self.cb_container.currentData())
        s.setValue("keys_mode", self.cb_keys_mode.currentData())
        s.setValue("keys_pos", self.cb_keys_pos.currentData())
        s.setValue("keys_size", self.cb_keys_size.currentData())
        s.setValue("cam_device", self.cb_cam_dev.currentData())
        s.setValue("cam_shape", self.cb_cam_shape.currentData())
        s.setValue("cam_size", self.sp_cam_size.value())
        s.setValue("cam_color", self.btn_cam_color.color.name())
        s.setValue("cam_border", self.sp_cam_border.value())
        s.setValue("out_dir", self.ed_out.text())
        s.setValue("ffmpeg_manual", self.ed_ffmpeg.text())
        s.setValue("speaker", self.cb_speaker.currentData())
        s.setValue("system_gain", self.sl_sys_gain.value())
        s.setValue("mic_device", self.cb_mic.currentData())
        s.setValue("mic_gain", self.sl_mic_gain.value())
        for hid in self.hk_edits:
            s.setValue(f"hotkey_{hid}", self._hotkey_text(hid))
        for key, ck in (("yuv444", self.ck_444), ("system_audio", self.ck_sys), ("mic", self.ck_mic),
                        ("draw_mouse", self.ck_cursor), ("highlight", self.ck_highlight),
                        ("click_effect", self.ck_click), ("restore_cursor", self.ck_restore),
                        ("pause_marker", self.ck_marker), ("hide_window", self.ck_hide),
                        ("minibar", self.ck_minibar), ("region_frame", self.ck_frame),
                        ("minimize", self.ck_minimize),
                        ("keys_on", self.ck_keys), ("cam_on", self.ck_cam), ("cam_mirror", self.ck_cam_mirror)):
            s.setValue(key, "true" if ck.isChecked() else "false")
        s.setValue("style", self.cb_style.currentData())
        s.setValue("color", self.btn_color.color.name())
        s.setValue("opacity", self.sl_opacity.value())
        s.setValue("radius", self.sp_radius.value())
        s.setValue("left_color", self.btn_lcolor.color.name())
        s.setValue("right_color", self.btn_rcolor.color.name())
        s.setValue("countdown", self.sp_countdown.value())

    def _apply_overlay(self):
        self.overlay.configure(self.btn_color.color, self.sl_opacity.value() / 100, self.sp_radius.value(),
                               self.cb_style.currentData(), self.ck_click.isChecked(),
                               self.btn_lcolor.color, self.btn_rcolor.color)

    def _apply_keys(self):
        self.keys.configure(self.cb_keys_mode.currentData(), self.cb_keys_pos.currentData(),
                            self.cb_keys_size.currentData())

    def _apply_cam(self):
        self.webcam.configure(self.cb_cam_dev.currentData() or "", self.sp_cam_size.value(),
                              self.cb_cam_shape.currentData(), self.ck_cam_mirror.isChecked(),
                              self.btn_cam_color.color, self.sp_cam_border.value())

    def _capture_rect(self):
        """Kayit alaninin mantiksal (Qt) koordinatlarda dikdortgeni."""
        screen = screen_for_output(self.cb_monitor.currentIndex())
        g = screen.geometry()
        if not self.region:
            return g
        dpr = screen.devicePixelRatio()
        x, y, w, h = self.region
        return QRect(g.x() + round(x / dpr), g.y() + round(y / dpr), round(w / dpr), round(h / dpr))

    def _capture_size(self):
        """Kaydedilen goruntunun fiziksel piksel boyutu."""
        if self.region:
            return tuple(self.region[2:])
        o = output_infos()[self.cb_monitor.currentIndex()]
        return o["w"], o["h"]

    def _webcam_pos(self):
        area = self._capture_rect()
        self.webcam.bounds = area
        try:
            x, y = (int(v) for v in str(self.settings.value("cam_pos", "")).split(","))
            if area.contains(QPoint(x + self.webcam.width() // 2, y + self.webcam.height() // 2)):
                return QPoint(x, y)
        except ValueError:
            pass
        return QPoint(area.right() - self.webcam.width() - 24, area.bottom() - self.webcam.height() - 24)

    def _save_webcam_pos(self):
        self.settings.setValue("cam_pos", f"{self.webcam.x()},{self.webcam.y()}")

    def _on_stage(self, text):
        self._stage_text = text
        self._update_status()

    def _apply_lens(self):
        self.magnifier.configure(self.sl_lens_zoom.value() / 10, self.sp_lens_size.value(),
                                 self.cb_lens_shape.currentData(), self.btn_lens_color.color,
                                 self.sp_lens_width.value())

    def _preview(self, on):
        if self.state != "idle":
            return
        self.overlay.start() if on else self.overlay.stop()

    # --- kayit kontrolu
    def _config(self):
        enc = self.cb_encoder.currentData()
        return {
            "ffmpeg": getattr(self, "ffmpeg", ""),
            "monitor": self.cb_monitor.currentIndex(),
            "region": self.region,
            "size": self._capture_size(),
            "fps": int(self.cb_fps.currentText()),
            "encoder": enc,
            "preset": self.cb_preset.currentData(),
            "quality": self.sl_quality.value(),
            "yuv444": self.ck_444.isChecked() and enc in ("h264_nvenc", "hevc_nvenc", "libx264"),
            "container": self.cb_container.currentData(),
            "out_dir": self.ed_out.text(),
            "draw_mouse": self.ck_cursor.isChecked(),
            "system_audio": self.cb_speaker.currentData() if self.ck_sys.isChecked() and soundcard else None,
            "system_gain": self.sl_sys_gain.value() / 100,
            "mic": self.cb_mic.currentData() if self.ck_mic.isChecked() and soundcard else None,
            "mic_gain": self.sl_mic_gain.value() / 100,
        }

    def _on_hotkey(self, hid):
        if hid == HOTKEY_START:
            self.start_action()
        elif hid == HOTKEY_PAUSE:
            self.toggle_pause()
        elif hid == HOTKEY_STOP:
            self.stop_action()
        elif hid == HOTKEY_ZOOM:
            self.toggle_zoom()
        elif hid == HOTKEY_DRAW:
            self.toggle_draw_mode()
        elif hid == HOTKEY_CLEAR and self._drawing_active():
            self.drawing.clear()
        elif hid == HOTKEY_UNDO and self._drawing_active():
            self.drawing.undo()
        elif hid == HOTKEY_REDO and self._drawing_active():
            self.drawing.redo()
        elif hid == HOTKEY_LENS:
            self._lens_hotkey()

    # --- mercek kisayolu
    def _lens_hotkey(self):
        if self.state != "recording":  # sadece kayit surerken
            return
        if self.cb_lens_mode.currentData() == "toggle":
            self.magnifier.toggle()
            return
        # Basili tutma: RegisterHotKey sadece basmayi bildirir; birakmayi tusun durumunu yoklayarak yakalariz
        spec = sequence_to_win(self._hotkey_text(HOTKEY_LENS))
        if not spec or self.magnifier.isVisible():
            return
        self._lens_vk = spec[1]
        self.magnifier.open_lens()
        self._lens_hold_timer.start(20)

    def _lens_hold_check(self):
        if not user32.GetAsyncKeyState(self._lens_vk) & 0x8000 or self.state != "recording":
            self._lens_hold_timer.stop()
            self.magnifier.close_lens()

    # --- canli cizim
    def _drawing_active(self):
        return self.state in ("recording", "paused") and self.drawing.isVisible()

    def _set_draw_mode(self, on):
        if not self._drawing_active():
            return
        self.drawing.set_drawing_mode(on)
        self._raise_controls()

    def _raise_controls(self):
        """Kontrol pencereleri (mini pencere, kamera, zoom cikis dugmesi) cizim katmaninin ustunde kalmali."""
        for w in (self.webcam, self.keys, self.zoom_btn, self.minibar):
            if w.isVisible():
                w.raise_()

    def toggle_draw_mode(self):
        self._set_draw_mode(not self.drawing.drawing_mode)

    def _choose_tool(self, tool):
        if self.drawing.drawing_mode and tool == self.drawing.tool:
            self._set_draw_mode(False)  # secili araci tekrar secmek cizim modunu kapatir
        else:
            self.drawing.set_tool(tool)
            if not self.drawing.drawing_mode:
                self._set_draw_mode(True)
        self._sync_draw_ui()

    def _choose_color(self, color):
        self.drawing.color = QColor(color)
        self._sync_draw_ui()

    def _set_fade(self, tool, seconds):
        self.drawing.fades[tool] = seconds

    def _sync_draw_ui(self):
        d = self.drawing
        self.minibar.set_draw_state(d.drawing_mode, d.tool, d.color)

    # --- mini penceredeki mikrofon / kamera dugmeleri
    def toggle_mic(self):
        if self.state in ("recording", "paused") and self.recorder.has_mic():
            self.recorder.set_mic_muted(not self.recorder.mic_muted)
            self._refresh_minibar_toggles()

    def toggle_cam(self):
        if self.state not in ("recording", "paused"):
            return
        if self.webcam.is_shown():
            self.webcam.hide_cam(animated=True)  # diyafram kapanir, sonra kamera kapanir
        else:
            self.webcam.show_at(self._webcam_pos())
        self._refresh_minibar_toggles()

    def _refresh_minibar_toggles(self):
        self.minibar.set_toggles(self.recorder.has_mic(), not self.recorder.mic_muted,
                                 self.cb_cam_dev.currentData() not in (None, ""), self.webcam.is_shown())

    # --- kayit sirasinda alana zoom
    def toggle_zoom(self):
        if self.state != "recording" or not zmq:
            return
        if self.zoom_picker.active():
            self.zoom_picker.cancel()
        elif self.zoom_active:
            self.exit_zoom()
        else:
            self.zoom_picker.start(screen_for_output(self.cb_monitor.currentIndex()), self._capture_rect())

    def _on_zoom_picked(self, rect):
        if self.state != "recording":
            return
        idx = self.cb_monitor.currentIndex()
        screen = screen_for_output(idx)
        dpr, g = screen.devicePixelRatio(), screen.geometry()
        cap_w, cap_h = self.recorder.cfg["size"]
        ox, oy = self.region[:2] if self.region else (0, 0)
        # Secimi kayit alani icinde fiziksel piksele cevir, video oranina genislet, sinirlara sigdir
        x, y = (rect.x() - g.x()) * dpr - ox, (rect.y() - g.y()) * dpr - oy
        w, h = rect.width() * dpr, rect.height() * dpr
        aspect = cap_w / cap_h
        cx, cy = x + w / 2, y + h / 2
        w = max(cap_w / 8, min(cap_w, max(w, h * aspect)))  # en fazla 8 kat
        h = w / aspect
        x = min(max(0, cx - w / 2), cap_w - w)
        y = min(max(0, cy - h / 2), cap_h - h)
        zr = tuple(round(v) // 2 * 2 for v in (x, y, w, h))
        self.recorder.zoom_to(zr)
        self.zoom_active = True
        self.zoom_frame.show_region(idx, (ox + zr[0], oy + zr[1], zr[2], zr[3]))
        logical = QRect(g.x() + round((ox + zr[0]) / dpr), g.y() + round((oy + zr[1]) / dpr),
                        round(zr[2] / dpr), round(zr[3] / dpr))
        self.zoom_btn.show_at(logical, t("zoom_exit") + self._hotkey_label(HOTKEY_ZOOM))

    def exit_zoom(self):
        if self.zoom_active:
            self.recorder.zoom_to(None)
        self._hide_zoom_ui()

    def _hide_zoom_ui(self):
        if self.zoom_picker.active():
            self.zoom_picker.cancel()
        self.zoom_frame.hide()
        self.zoom_btn.hide()
        self.zoom_active = False

    def start_action(self):
        if self.state == "idle":
            self._begin()
        elif self.state == "paused":
            self.toggle_pause()

    def stop_action(self):
        if self.state == "countdown":
            self.state = "idle"
            self._refresh_buttons()
        elif self.state in ("recording", "paused"):
            self._end()

    def _begin(self):
        cfg = self._config()
        if not cfg["ffmpeg"] or not cfg["encoder"]:
            QMessageBox.warning(self, t("app_title"), t("not_ready"))
            return
        self._save_settings()
        for b in (self.btn_preview, self.btn_keys_preview, self.btn_cam_preview, self.btn_lens_preview):
            b.setChecked(False)
        self._stage_text = ""
        self.countdown_left = self.sp_countdown.value()
        self.state = "countdown"
        self._refresh_buttons()
        self._countdown_step()

    def _countdown_step(self):
        if self.state != "countdown":
            return
        if self.countdown_left > 0:
            self.countdown_left -= 1
            QTimer.singleShot(1000, self._countdown_step)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok = self.recorder.start(self._config())
        QApplication.restoreOverrideCursor()
        if not ok:
            self.state = "idle"
            self._refresh_buttons()
            return
        self.elapsed = 0.0
        self.seg_start = time.perf_counter()
        self.state = "recording"
        if self.ck_highlight.isChecked():
            self.overlay.start()
        self._show_recording_ui()
        self._refresh_buttons()

    def _show_recording_ui(self):
        idx = self.cb_monitor.currentIndex()
        if self.ck_frame.isChecked() and self.region:
            self.frame.show_region(idx, self.region)
        if self.ck_draw.isChecked():
            self.drawing.color = QColor(self.btn_draw_color.color)
            self.drawing.width_px = self.sp_draw_width.value()
            self.drawing.start(self._capture_rect())
        self.minibar.set_draw_visible(self.ck_draw.isChecked())
        self._sync_draw_ui()
        if self.ck_keys.isChecked():
            self.keys.start(self._capture_rect())
        if self.ck_cam.isChecked():
            self.webcam.show_at(self._webcam_pos())
        if self.ck_minibar.isChecked():
            self._refresh_minibar_toggles()
            self.minibar.show_on(screen_for_output(idx))
        if self.ck_minimize.isChecked():
            self.showMinimized()

    def _hide_recording_ui(self):
        self._hide_zoom_ui()
        self.drawing.stop()
        self.minibar.hide()
        self.frame.hide()
        self.keys.stop()
        self.webcam.hide_cam()
        self._lens_hold_timer.stop()
        self.magnifier.close_lens()
        if self.isMinimized():
            self.showNormal()

    def toggle_pause(self):
        if self.state == "recording":
            self.saved_cursor = physical_cursor_pos()
            marker_pos = QCursor.pos()
            self._hide_zoom_ui()  # yeni segment zoom'suz baslar
            self._lens_hold_timer.stop()
            self.magnifier.close_lens()
            self.recorder.pause()
            self.elapsed += time.perf_counter() - self.seg_start
            self.overlay.stop()
            if self.ck_marker.isChecked():
                self.marker.show_at(marker_pos)
            self.state = "paused"
        elif self.state == "paused":
            self.marker.hide_marker()
            if self.ck_restore.isChecked() and self.saved_cursor is not None:
                user32.SetCursorPos(*self.saved_cursor)
            if not self.recorder.resume():
                return
            if self.ck_highlight.isChecked():
                self.overlay.start()
            self.seg_start = time.perf_counter()
            self.state = "recording"
        self._refresh_buttons()

    def _end(self):
        if self.state == "recording":
            self.elapsed += time.perf_counter() - self.seg_start
        self.overlay.stop()
        self.marker.hide_marker()
        self._hide_recording_ui()
        self.state = "saving"
        self._refresh_buttons()
        self.recorder.stop()

    def _on_finished(self, path):
        self.state = "idle"
        self._refresh_buttons()
        self.info.setText(t("saved_info", p=path))
        text = t("done_text", p=path)
        if self.recorder.audio_errors:
            text += t("audio_warn", e="; ".join(self.recorder.audio_errors))
        box = QMessageBox(self)
        box.setWindowTitle(t("done_title"))
        box.setText(text)
        open_btn = box.addButton(t("open_folder"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    def _on_failed(self, msg):
        if self.state in ("recording", "paused"):
            self.recorder._stop_segment()
        self.overlay.stop()
        self.marker.hide_marker()
        self._hide_recording_ui()
        self.state = "idle"
        self._refresh_buttons()
        QMessageBox.critical(self, t("app_title"), msg)

    def _refresh_buttons(self):
        st = self.state
        self._sync_hotkey_scope()
        self.minibar.set_hints({
            action: self.hk_edits[hid].keySequence().toString(QKeySequence.NativeText)
            for action, hid in (("pause", HOTKEY_PAUSE), ("stop", HOTKEY_STOP), ("draw", HOTKEY_DRAW),
                                ("undo", HOTKEY_UNDO), ("redo", HOTKEY_REDO), ("clear", HOTKEY_CLEAR))})
        if st == "paused":
            self.btn_rec.setText(t("btn_resume") + self._hotkey_label(HOTKEY_START))
        elif st == "saving":
            self.btn_rec.setText(t("btn_saving"))
        else:
            self.btn_rec.setText(t("btn_start") + self._hotkey_label(HOTKEY_START))
        self.btn_rec.setEnabled(st in ("idle", "paused"))
        self.btn_pause.setText((t("btn_resume") if st == "paused" else t("btn_pause"))
                               + self._hotkey_label(HOTKEY_PAUSE))
        self.btn_pause.setEnabled(st in ("recording", "paused"))
        self.btn_stop.setText((t("btn_cancel") if st == "countdown" else t("btn_stop"))
                              + self._hotkey_label(HOTKEY_STOP))
        self.btn_stop.setEnabled(st in ("countdown", "recording", "paused"))
        self.cb_lang.setEnabled(st == "idle")
        self._update_status()

    def _update_status(self):
        st = self.state
        sec = self.elapsed + (time.perf_counter() - self.seg_start if st == "recording" else 0)
        clock = f"{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}"
        text, bg = {
            "idle": (t("status_idle"), "#2b2b2b"),
            "countdown": (t("status_countdown", n=self.countdown_left + 1), "#7a5a00"),
            "recording": (t("status_rec", clock=clock), "#8b1a1a"),
            "paused": (t("status_paused", clock=clock), "#5a5a00"),
            "saving": (self._stage_text or t("status_saving"), "#1a4a8b"),
        }[st]
        self.status.setText(text)
        self.status.setStyleSheet(f"padding:10px;border-radius:6px;background:{bg};color:white;")
        if self.minibar.isVisible():
            self.minibar.set_state(st == "paused", clock)

    def showEvent(self, e):
        super().showEvent(e)
        exclude_from_capture(self, self.ck_hide.isChecked())

    def closeEvent(self, e):
        if self.state in ("recording", "paused"):
            if QMessageBox.question(self, t("app_title"), t("close_q")) != QMessageBox.Yes:
                e.ignore()
                return
            self.recorder.finished.disconnect(self._on_finished)
            self.recorder._stop_segment()
            self.recorder._finalize()
        lang = self.settings.value("language", LANG)
        self._save_settings()
        if self._relaunch:
            self.settings.setValue("language", lang)
        self.settings.sync()
        self.hotkeys.stop()
        self.magnifier.shutdown()
        self.keys.stop()
        self.webcam.hide_cam()
        self.drawing.stop()
        for w in (self.overlay, self.magnifier, self.marker, self.minibar, self.frame, self.keys, self.webcam,
                  self.zoom_frame, self.zoom_btn, self.drawing):
            w.close()
        super().closeEvent(e)
        if self._relaunch:
            args = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
            subprocess.Popen(args, cwd=APP_DIR)


def configure_app(app):
    """Acilir liste/menu animasyonlari gecici ayri pencereler olusturur; bunlar kayitta gizlenemedigi
    icin saydam kutu olarak goruluyordu. Animasyonlari kapat ve ipuclarini kayittan gizle."""
    for effect in (Qt.UI_AnimateCombo, Qt.UI_AnimateMenu, Qt.UI_FadeMenu, Qt.UI_AnimateTooltip,
                   Qt.UI_FadeTooltip):
        app.setEffectEnabled(effect, False)
    app._tooltip_filter = _TooltipFilter(app)
    app.installEventFilter(app._tooltip_filter)


def open_settings():
    """Ayarlar %APPDATA%\\ScreenRec Studio\\settings.ini dosyasinda. Eski surumun program klasorundeki
    ayarlar.ini dosyasi varsa bir kez tasinir."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(SETTINGS_PATH):
        for legacy in (os.path.join(APP_DIR, "ayarlar.ini"), os.path.join(RES_DIR, "ayarlar.ini")):
            if os.path.isfile(legacy):
                shutil.copyfile(legacy, SETTINGS_PATH)
                break
    return QSettings(SETTINGS_PATH, QSettings.IniFormat)


def main():
    global LANG
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ScreenRecStudio.App")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setStyle("Fusion")
    configure_app(app)
    selftest = "--selftest" in sys.argv
    if selftest:
        # Kullanicinin ayarlarina dokunmadan: gecici ayar dosyasi, guncelleme denetimi kapali
        settings = QSettings(os.path.join(tempfile.gettempdir(), "screenrec_selftest.ini"), QSettings.IniFormat)
        settings.clear()
        settings.setValue("auto_update", "false")
    else:
        settings = open_settings()
    system_lang = "tr" if QLocale.system().language() == QLocale.Turkish else "en"
    LANG = settings.value("language", system_lang)
    if LANG not in ("tr", "en"):
        LANG = "en"
    if not os.path.isfile(ICON_PATH):
        make_icon_pixmap().save(ICON_PATH, "ICO")
    w = MainWindow(settings)
    w.resize(600, 760)
    w.show()
    if selftest:
        run_selftest(app, w)
    sys.exit(app.exec())


def run_selftest(app, w):
    """--selftest: kodlayicilari bulur, birincil ekrandan 3 sn kayit alir, sonucu
    %TEMP%\\screenrec_selftest.json dosyasina yazar ve cikar. Kurulmus paketi dogrulamak icin."""
    out = os.path.join(tempfile.gettempdir(), "screenrec_selftest.json")
    result = {"version": VERSION, "frozen": FROZEN}

    def finish(**kw):
        result.update(kw)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        w.close()
        app.quit()

    def ready():
        if not getattr(w, "ffmpeg", None):
            QTimer.singleShot(200, ready)
            return
        result.update(ffmpeg=w.ffmpeg, encoder=w.cb_encoder.currentData(),
                      encoders=[w.cb_encoder.itemData(i) for i in range(w.cb_encoder.count())])
        w.ed_out.setText(os.path.join(tempfile.gettempdir(), "screenrec_selftest"))
        w.sp_countdown.setValue(0)
        for ck in (w.ck_sys, w.ck_mic, w.ck_cam, w.ck_keys, w.ck_minibar, w.ck_draw):
            ck.setChecked(False)
        w.recorder.finished.disconnect(w._on_finished)
        w.recorder.failed.disconnect(w._on_failed)
        w.recorder.finished.connect(lambda p: finish(ok=True, file=p, size=os.path.getsize(p)))
        w.recorder.failed.connect(lambda m: finish(ok=False, error=m))
        w.start_action()
        QTimer.singleShot(3000, w.stop_action)

    QTimer.singleShot(300, ready)
    QTimer.singleShot(60000, lambda: finish(ok=False, error="timeout"))


if __name__ == "__main__":
    main()
