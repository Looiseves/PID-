"""Bundled, unmodified OFL typography for consistent offline desktop rendering."""
from pathlib import Path
import sys

from PySide6 import QtGui, QtWidgets

UI_FAMILY = "Noto Sans SC"
NUMBER_FAMILY = "Inter"


def font_directory():
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / "assets" / "fonts"


def configure_typography():
    app = QtWidgets.QApplication.instance()
    if app.property("pidBundledFonts") is not None:
        return app.property("pidBundledFonts")
    loaded = {}
    for name, filename in ((UI_FAMILY, "NotoSansSC-VF.ttf"), (NUMBER_FAMILY, "Inter-VF.ttf")):
        path = font_directory() / filename
        identifier = QtGui.QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1
        families = QtGui.QFontDatabase.applicationFontFamilies(identifier) if identifier >= 0 else []
        loaded[name] = name in families
    font = QtGui.QFont()
    font.setFamilies([UI_FAMILY, "Segoe UI", "Microsoft YaHei UI"])
    font.setPixelSize(13)
    font.setWeight(QtGui.QFont.Weight.Normal)
    app.setFont(font)
    app.setProperty("pidBundledFonts", loaded)
    return loaded


def number_font(pixels=12):
    font = QtGui.QFont(NUMBER_FAMILY)
    font.setPixelSize(pixels)
    font.setWeight(QtGui.QFont.Weight.Normal)
    font.setFeature(QtGui.QFont.Tag.fromString("tnum"), 1)
    return font
