"""Application-wide dark theme (same look on Windows, macOS and Linux)."""

from PySide6.QtGui import QColor, QPalette

T = {
    "bg": "#14161b",
    "surface": "#1b1e25",
    "surface2": "#22262f",
    "raised": "#2a2f3a",
    "border": "#333947",
    "text": "#e7e9ee",
    "muted": "#8c94a6",
    "accent": "#5b8cff",
    "accent_hover": "#7aa2ff",
    "success": "#3ddc84",
    "warn": "#ffb020",
    "danger": "#ff5d5d",
    "empty_key": "#2a2e37",
}

# Colour tag per action category (used in action lists).
CATEGORY_COLORS = {
    "keyboard": "#5b8cff",
    "layer": "#ffb020",
    "midi": "#b36bff",
    "network": "#3ddc84",
}
ACTION_CATEGORY = {
    "keys": "keyboard", "text": "keyboard", "delay": "keyboard", "key_down": "keyboard",
    "key_up": "keyboard", "release_all": "keyboard", "consumer": "keyboard",
    "layer": "layer", "overlay": "layer",
    "midi_note": "midi", "midi_cc": "midi", "midi_pc": "midi", "msc": "midi",
    "osc": "network", "ma": "network", "companion": "network",
    "companion_page": "network", "host": "network",
}

QSS = """
QWidget {{ color: {text}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {bg}; }}
QWidget#panel {{ background: {surface}; border-radius: 10px; }}
QLabel#muted {{ color: {muted}; }}
QLabel#section {{ color: {muted}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#title {{ font-size: 18px; font-weight: 600; }}
QLabel#pill {{ border-radius: 10px; padding: 3px 10px; background: {raised}; color: {muted}; }}
QLabel#pill[state="ok"] {{ background: #1f3b2c; color: {success}; }}
QLabel#pill[state="warn"] {{ background: #3d3219; color: {warn}; }}
QLabel#pill[state="bad"] {{ background: #3d1f22; color: {danger}; }}

QToolBar {{ background: {surface}; border: none; border-bottom: 1px solid {border}; padding: 6px; spacing: 6px; }}
QToolBar QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px 10px; }}
QToolBar QToolButton:hover {{ background: {raised}; border-color: {border}; }}
QToolBar QToolButton:checked {{ background: {raised}; border-color: {accent}; }}
QToolBar QToolButton#primary {{ background: {accent}; color: white; font-weight: 600; }}
QToolBar QToolButton#primary:hover {{ background: {accent_hover}; }}

QPushButton {{ background: {raised}; border: 1px solid {border}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {surface2}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton#primary {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#flat {{ background: transparent; border-color: transparent; color: {muted}; padding: 4px 8px; }}
QPushButton#flat:hover {{ color: {text}; background: {raised}; }}
QPushButton::menu-indicator {{ subcontrol-position: right center; right: 6px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 4px 6px;
    selection-background-color: {accent}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {accent}; }}
QLineEdit:disabled {{ color: {muted}; background: {surface2}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {surface2}; border: 1px solid {border};
    selection-background-color: {accent}; }}

QListWidget {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; padding: 4px; outline: none; }}
QListWidget::item {{ padding: 6px 6px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {surface2}; }}
QListWidget::item:selected {{ background: {raised}; color: {text}; border: 1px solid {accent}; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; background: {surface}; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 7px 14px; border: none;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {text}; border-bottom-color: {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}

QGroupBox {{ border: 1px solid {border}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {muted}; }}

QMenuBar {{ background: {surface}; }}
QMenuBar::item:selected {{ background: {raised}; }}
QMenu {{ background: {surface2}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent}; color: white; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QStatusBar {{ background: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QSplitter::handle {{ background: transparent; width: 6px; }}
QToolTip {{ background: {surface2}; color: {text}; border: 1px solid {border}; padding: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {raised}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {border};
    background: {bg}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
""".format(**T)


def apply(app):
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.Window: T["bg"], QPalette.WindowText: T["text"], QPalette.Base: T["bg"],
        QPalette.AlternateBase: T["surface2"], QPalette.Text: T["text"], QPalette.Button: T["raised"],
        QPalette.ButtonText: T["text"], QPalette.Highlight: T["accent"],
        QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: T["surface2"],
        QPalette.ToolTipText: T["text"], QPalette.PlaceholderText: T["muted"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(T["muted"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(T["muted"]))
    app.setPalette(palette)
    app.setStyleSheet(QSS)


def repolish(widget):
    """Re-apply the stylesheet after changing a dynamic property (e.g. pill state)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
