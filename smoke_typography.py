"""Check bundled font use, glyph coverage and actual native controls."""
import hashlib
import json

from PySide6 import QtCore, QtGui
from PySide6.QtTest import QTest

from ui_fonts import UI_FAMILY, NUMBER_FAMILY, font_directory, number_font


def run_typography(app, window, folder, check):
    manifest = json.loads((font_directory() / "sources.json").read_text(encoding="utf-8"))
    check("bundled_font_assets_and_licenses_match_source", all(hashlib.sha256((font_directory() / f["file"]).read_bytes()).hexdigest() == f["sha256"] for f in manifest["files"]))
    check("both_bundled_font_families_loaded", app.property("pidBundledFonts") == {UI_FAMILY: True, NUMBER_FAMILY: True})
    check("native_navigation_uses_new_chinese_font", QtGui.QFontInfo(window.navigation.headings["工作台"].font()).family() == UI_FAMILY)
    raw = QtGui.QRawFont.fromFont(window.navigation.headings["工作台"].font())
    check("bundled_chinese_font_covers_ui_glyphs", all(raw.supportsCharacter(ord(c)) for c in "波形图串口调参实验记录看板模型连接回读"))
    check("number_font_uses_tabular_inter_digits", QtGui.QFontInfo(number_font()).family() == NUMBER_FAMILY and number_font().featureValue(QtGui.QFont.Tag.fromString("tnum")) == 1)
    window.navigation.navigate("tuning")
    QTest.qWait(380)
    check("pid_inputs_use_inter_font", QtGui.QFontInfo(window.spins["kp"].font()).family() == NUMBER_FAMILY)
    area = window.control_dock.widget()
    check("new_font_does_not_clip_parameter_controls", area.horizontalScrollBar().maximum() == 0)
    check("chart_ticks_use_inter_font", QtGui.QFontInfo(window.plot.getAxis("bottom").style["tickFont"]).family() == NUMBER_FAMILY)
    window.navigation.navigate("scope")
    QTest.qWait(380)
    window.grab().save(str(folder / "typography-scope.png"))
