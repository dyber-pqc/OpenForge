"""Unicode icons for OpenForge EDA UI.

Using Unicode lets us avoid PNG/SVG file dependencies. These work in any QLabel
or QPushButton's text. For more complex icons, fall back to QIcon with SVG.

Reference any icon as: from openforge_desktop.theme.icons import GEAR
Then use: button.setText(GEAR)
"""

# ==============================================================================
# NAVIGATION / ARROWS
# ==============================================================================

ARROW_LEFT = "\u2190"
ARROW_RIGHT = "\u2192"
ARROW_UP = "\u2191"
ARROW_DOWN = "\u2193"
ARROW_UP_LEFT = "\u2196"
ARROW_UP_RIGHT = "\u2197"
ARROW_DOWN_LEFT = "\u2199"
ARROW_DOWN_RIGHT = "\u2198"
ARROW_LEFT_RIGHT = "\u2194"
ARROW_UP_DOWN = "\u2195"

ARROW_LEFT_HEAVY = "\u2B05"
ARROW_RIGHT_HEAVY = "\u27A1"
ARROW_UP_HEAVY = "\u2B06"
ARROW_DOWN_HEAVY = "\u2B07"

CHEVRON_LEFT = "\u2039"
CHEVRON_RIGHT = "\u203A"
CHEVRON_UP = "\u02C4"
CHEVRON_DOWN = "\u02C5"

DOUBLE_CHEVRON_LEFT = "\u00AB"
DOUBLE_CHEVRON_RIGHT = "\u00BB"

TRIANGLE_RIGHT = "\u25B6"
TRIANGLE_LEFT = "\u25C0"
TRIANGLE_UP = "\u25B2"
TRIANGLE_DOWN = "\u25BC"
TRIANGLE_RIGHT_SMALL = "\u25B8"
TRIANGLE_DOWN_SMALL = "\u25BE"

# ==============================================================================
# STATUS / VALIDATION
# ==============================================================================

CHECK = "\u2713"
CHECK_HEAVY = "\u2714"
CHECK_BOX = "\u2611"
CROSS = "\u2717"
CROSS_HEAVY = "\u2718"
CROSS_MARK = "\u274C"
BALLOT_X = "\u2613"

WARN = "\u26A0"
INFO = "\u24D8"
INFO_CIRCLE = "\u2139"
QUESTION = "\u2753"
EXCLAIM = "\u2757"
EXCLAIM_DOUBLE = "\u203C"

CIRCLE_FILLED = "\u25CF"
CIRCLE_EMPTY = "\u25CB"
CIRCLE_DOT = "\u29BF"
SQUARE_FILLED = "\u25A0"
SQUARE_EMPTY = "\u25A1"
DIAMOND_FILLED = "\u25C6"
DIAMOND_EMPTY = "\u25C7"

# ==============================================================================
# TOOLS / ACTIONS
# ==============================================================================

GEAR = "\u2699"
WRENCH = "\U0001F527"
HAMMER = "\U0001F528"
SCREWDRIVER = "\U0001FA9B"
TOOLBOX = "\U0001F9F0"

PLAY = "\u25B6"
PAUSE = "\u23F8"
STOP = "\u23F9"
RECORD = "\u23FA"
EJECT = "\u23CF"
NEXT = "\u23ED"
PREV = "\u23EE"
FAST_FORWARD = "\u23E9"
REWIND = "\u23EA"

REFRESH = "\u21BB"
RELOAD = "\u27F3"
SYNC = "\u21CB"
UNDO = "\u21B6"
REDO = "\u21B7"

# ==============================================================================
# EDA / ELECTRICAL
# ==============================================================================

LIGHTNING = "\u26A1"
LIGHTBULB = "\U0001F4A1"
BATTERY = "\U0001F50B"
PLUG = "\U0001F50C"
MICROCHIP = "\U0001F4BB"

WAVE = "\u3030"
WAVE_DASH = "\u301C"
SINE_WAVE = "\u223F"
TILDE = "\u007E"

GRID = "\u22BD"
CIRCUIT = "\u29C9"
INFINITY = "\u221E"
OHM = "\u2126"
MICRO = "\u00B5"
DEGREE = "\u00B0"
PLUS_MINUS = "\u00B1"

# ==============================================================================
# UI / GENERAL
# ==============================================================================

SEARCH = "\U0001F50D"
SEARCH_ALT = "\u2315"
MAGNIFIER = "\u26B2"

PLUS = "\u002B"
MINUS = "\u2212"
PLUS_HEAVY = "\u2795"
MINUS_HEAVY = "\u2796"
MULTIPLY = "\u00D7"
DIVIDE = "\u00F7"
EQUALS = "\u003D"

DOTS_V = "\u22EE"
DOTS_H = "\u22EF"
DOTS_DOWN = "\u22F0"
DOTS_UP = "\u22F1"
HAMBURGER = "\u2630"
HAMBURGER_HEAVY = "\u2261"

ELLIPSIS = "\u2026"

# ==============================================================================
# FILES / FOLDERS
# ==============================================================================

FOLDER = "\U0001F4C1"
FOLDER_OPEN = "\U0001F4C2"
FILE = "\U0001F4C4"
FILE_TEXT = "\U0001F4DD"
FILE_BINARY = "\U0001F4BE"
FLOPPY = "\U0001F4BE"
DOCUMENT = "\U0001F5CE"
PAGE = "\u2398"

# ==============================================================================
# TIME / CALENDAR
# ==============================================================================

CLOCK = "\U0001F550"
WATCH = "\u231A"
HOURGLASS = "\u231B"
HOURGLASS_FLOW = "\u23F3"
TIMER = "\u23F2"
ALARM = "\u23F0"
CALENDAR = "\U0001F4C5"
DATE = "\U0001F4C6"

# ==============================================================================
# COMMUNICATION
# ==============================================================================

ENVELOPE = "\u2709"
PHONE = "\u260E"
SPEAKER = "\U0001F50A"
MUTE = "\U0001F507"
BELL = "\U0001F514"
BELL_OFF = "\U0001F515"

# ==============================================================================
# SECURITY
# ==============================================================================

LOCK = "\U0001F512"
LOCK_OPEN = "\U0001F513"
KEY = "\U0001F511"
SHIELD = "\U0001F6E1"
EYE = "\U0001F441"

# ==============================================================================
# WEATHER / NATURE (used as semantic icons)
# ==============================================================================

STAR = "\u2605"
STAR_EMPTY = "\u2606"
HEART = "\u2764"
HEART_EMPTY = "\u2661"
SPARKLES = "\u2728"
SUN = "\u2600"
MOON = "\u263D"

# ==============================================================================
# MATH / LOGIC
# ==============================================================================

SUMMATION = "\u2211"
PRODUCT = "\u220F"
INTEGRAL = "\u222B"
SQRT = "\u221A"
APPROX = "\u2248"
NOT_EQUAL = "\u2260"
LESS_EQUAL = "\u2264"
GREATER_EQUAL = "\u2265"
PLUSMINUS = "\u00B1"
PI = "\u03C0"
DELTA = "\u0394"
LAMBDA = "\u03BB"
MU = "\u03BC"
SIGMA = "\u03A3"
OMEGA = "\u03A9"

LOGIC_AND = "\u2227"
LOGIC_OR = "\u2228"
LOGIC_NOT = "\u00AC"
LOGIC_XOR = "\u2295"
LOGIC_NAND = "\u22BC"
LOGIC_NOR = "\u22BD"

# ==============================================================================
# CHARTS / DATA
# ==============================================================================

CHART_BAR = "\U0001F4CA"
CHART_LINE = "\U0001F4C8"
CHART_DOWN = "\U0001F4C9"

# ==============================================================================
# BRACKETS
# ==============================================================================

LBRACE = "\u007B"
RBRACE = "\u007D"
LBRACK = "\u005B"
RBRACK = "\u005D"
LANGLE = "\u27E8"
RANGLE = "\u27E9"

# ==============================================================================
# MISC SYMBOLS
# ==============================================================================

COPYRIGHT = "\u00A9"
REGISTERED = "\u00AE"
TRADEMARK = "\u2122"
SECTION = "\u00A7"
PARAGRAPH = "\u00B6"
DAGGER = "\u2020"
DOUBLE_DAGGER = "\u2021"
BULLET = "\u2022"
MIDDLE_DOT = "\u00B7"

# ==============================================================================
# OPENFORGE-SPECIFIC SEMANTIC ICONS
# (aliases mapping concepts to glyphs above for use across panels)
# ==============================================================================

ICON_PROJECT = FOLDER
ICON_FILE = FILE_TEXT
ICON_RUN = PLAY
ICON_STOP = STOP
ICON_BUILD = HAMMER
ICON_SETTINGS = GEAR
ICON_REFRESH = REFRESH
ICON_SEARCH = SEARCH_ALT
ICON_ADD = PLUS_HEAVY
ICON_REMOVE = MINUS_HEAVY
ICON_DELETE = CROSS_HEAVY
ICON_EDIT = WRENCH
ICON_SAVE = FLOPPY
ICON_LOAD = FOLDER_OPEN
ICON_INFO = INFO_CIRCLE
ICON_WARN = WARN
ICON_ERROR = CROSS_MARK
ICON_SUCCESS = CHECK_HEAVY
ICON_PENDING = HOURGLASS_FLOW
ICON_RUNNING = REFRESH
ICON_TIME = CLOCK
ICON_POWER = LIGHTNING
ICON_CHIP = MICROCHIP
ICON_WAVE = SINE_WAVE
ICON_TIMING = WATCH
ICON_AREA = SQUARE_FILLED
ICON_DRC = SHIELD
ICON_LVS = EQUALS
ICON_SIM = SINE_WAVE
ICON_SYNTH = HAMMER
ICON_PNR = GRID
ICON_LAYOUT = GRID
ICON_LIBRARY = LIGHTBULB
ICON_LOG = FILE_TEXT
ICON_REPORT = CHART_BAR
ICON_DASHBOARD = CHART_LINE
ICON_TERMINAL = LANGLE + LANGLE
ICON_CONSOLE = LANGLE + LANGLE
ICON_TREE = TRIANGLE_DOWN_SMALL
ICON_EXPAND = TRIANGLE_DOWN_SMALL
ICON_COLLAPSE = TRIANGLE_RIGHT_SMALL
ICON_CHECK = CHECK_HEAVY
ICON_CROSS = CROSS_HEAVY
ICON_LOCK = LOCK
ICON_UNLOCK = LOCK_OPEN
ICON_KEY = KEY
ICON_VISIBLE = EYE
ICON_HIDDEN = CIRCLE_EMPTY
ICON_FAVORITE = STAR
ICON_DARK = MOON
ICON_LIGHT = SUN
ICON_CLOSE = CROSS_HEAVY
ICON_MAXIMIZE = SQUARE_EMPTY
ICON_MINIMIZE = MINUS_HEAVY
ICON_HELP = QUESTION
ICON_SPARK = SPARKLES
ICON_FILTER = HAMBURGER
ICON_SORT = ARROW_UP_DOWN
ICON_MORE_V = DOTS_V
ICON_MORE_H = DOTS_H
ICON_MENU = HAMBURGER_HEAVY
ICON_NEXT = NEXT
ICON_PREV = PREV
ICON_FORWARD = FAST_FORWARD
ICON_BACK = REWIND
ICON_PLAY = PLAY
ICON_PAUSE = PAUSE
