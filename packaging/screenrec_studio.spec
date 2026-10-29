# PyInstaller spec - builds dist/ScreenRecStudio (one-folder app).
# Run from the repository root:  pyinstaller packaging/screenrec_studio.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
    (os.path.join(ROOT, "ffmpeg", "ffmpeg.exe"), "ffmpeg"),
    (os.path.join(ROOT, "ffmpeg", "LICENSE.txt"), "ffmpeg"),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "THIRD_PARTY_NOTICES.md"), "."),
]
datas += collect_data_files("soundcard")  # cffi header files read at import time

a = Analysis(
    [os.path.join(ROOT, "src", "screenrec_studio.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=datas,
    hiddenimports=["zmq", "soundcard", "comtypes.stream"],
    excludes=["tkinter", "cv2", "PIL", "matplotlib", "scipy", "pandas",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtPdf",
              "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtDesigner", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
              "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtWebSockets"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ScreenRecStudio",
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScreenRecStudio", upx=False)
