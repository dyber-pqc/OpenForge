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

ARROW_LEFT_HEAVY = "\u2b05"
ARROW_RIGHT_HEAVY = "\u27a1"
ARROW_UP_HEAVY = "\u2b06"
ARROW_DOWN_HEAVY = "\u2b07"

CHEVRON_LEFT = "\u2039"
CHEVRON_RIGHT = "\u203a"
CHEVRON_UP = "\u02c4"
CHEVRON_DOWN = "\u02c5"

DOUBLE_CHEVRON_LEFT = "\u00ab"
DOUBLE_CHEVRON_RIGHT = "\u00bb"

TRIANGLE_RIGHT = "\u25b6"
TRIANGLE_LEFT = "\u25c0"
TRIANGLE_UP = "\u25b2"
TRIANGLE_DOWN = "\u25bc"
TRIANGLE_RIGHT_SMALL = "\u25b8"
TRIANGLE_DOWN_SMALL = "\u25be"

# ==============================================================================
# STATUS / VALIDATION
# ==============================================================================

CHECK = "\u2713"
CHECK_HEAVY = "\u2714"
CHECK_BOX = "\u2611"
CROSS = "\u2717"
CROSS_HEAVY = "\u2718"
CROSS_MARK = "\u274c"
BALLOT_X = "\u2613"

WARN = "\u26a0"
INFO = "\u24d8"
INFO_CIRCLE = "\u2139"
QUESTION = "\u2753"
EXCLAIM = "\u2757"
EXCLAIM_DOUBLE = "\u203c"

CIRCLE_FILLED = "\u25cf"
CIRCLE_EMPTY = "\u25cb"
CIRCLE_DOT = "\u29bf"
SQUARE_FILLED = "\u25a0"
SQUARE_EMPTY = "\u25a1"
DIAMOND_FILLED = "\u25c6"
DIAMOND_EMPTY = "\u25c7"

# ==============================================================================
# TOOLS / ACTIONS
# ==============================================================================

GEAR = "\u2699"
WRENCH = "\U0001f527"
HAMMER = "\U0001f528"
SCREWDRIVER = "\U0001fa9b"
TOOLBOX = "\U0001f9f0"

PLAY = "\u25b6"
PAUSE = "\u23f8"
STOP = "\u23f9"
RECORD = "\u23fa"
EJECT = "\u23cf"
NEXT = "\u23ed"
PREV = "\u23ee"
FAST_FORWARD = "\u23e9"
REWIND = "\u23ea"

REFRESH = "\u21bb"
RELOAD = "\u27f3"
SYNC = "\u21cb"
UNDO = "\u21b6"
REDO = "\u21b7"

# ==============================================================================
# EDA / ELECTRICAL
# ==============================================================================

LIGHTNING = "\u26a1"
LIGHTBULB = "\U0001f4a1"
BATTERY = "\U0001f50b"
PLUG = "\U0001f50c"
MICROCHIP = "\U0001f4bb"

WAVE = "\u3030"
WAVE_DASH = "\u301c"
SINE_WAVE = "\u223f"
TILDE = "\u007e"

GRID = "\u22bd"
CIRCUIT = "\u29c9"
INFINITY = "\u221e"
OHM = "\u2126"
MICRO = "\u00b5"
DEGREE = "\u00b0"
PLUS_MINUS = "\u00b1"

# ==============================================================================
# UI / GENERAL
# ==============================================================================

SEARCH = "\U0001f50d"
SEARCH_ALT = "\u2315"
MAGNIFIER = "\u26b2"

PLUS = "\u002b"
MINUS = "\u2212"
PLUS_HEAVY = "\u2795"
MINUS_HEAVY = "\u2796"
MULTIPLY = "\u00d7"
DIVIDE = "\u00f7"
EQUALS = "\u003d"

DOTS_V = "\u22ee"
DOTS_H = "\u22ef"
DOTS_DOWN = "\u22f0"
DOTS_UP = "\u22f1"
HAMBURGER = "\u2630"
HAMBURGER_HEAVY = "\u2261"

ELLIPSIS = "\u2026"

# ==============================================================================
# FILES / FOLDERS
# ==============================================================================

FOLDER = "\U0001f4c1"
FOLDER_OPEN = "\U0001f4c2"
FILE = "\U0001f4c4"
FILE_TEXT = "\U0001f4dd"
FILE_BINARY = "\U0001f4be"
FLOPPY = "\U0001f4be"
DOCUMENT = "\U0001f5ce"
PAGE = "\u2398"

# ==============================================================================
# TIME / CALENDAR
# ==============================================================================

CLOCK = "\U0001f550"
WATCH = "\u231a"
HOURGLASS = "\u231b"
HOURGLASS_FLOW = "\u23f3"
TIMER = "\u23f2"
ALARM = "\u23f0"
CALENDAR = "\U0001f4c5"
DATE = "\U0001f4c6"

# ==============================================================================
# COMMUNICATION
# ==============================================================================

ENVELOPE = "\u2709"
PHONE = "\u260e"
SPEAKER = "\U0001f50a"
MUTE = "\U0001f507"
BELL = "\U0001f514"
BELL_OFF = "\U0001f515"

# ==============================================================================
# SECURITY
# ==============================================================================

LOCK = "\U0001f512"
LOCK_OPEN = "\U0001f513"
KEY = "\U0001f511"
SHIELD = "\U0001f6e1"
EYE = "\U0001f441"

# ==============================================================================
# WEATHER / NATURE (used as semantic icons)
# ==============================================================================

STAR = "\u2605"
STAR_EMPTY = "\u2606"
HEART = "\u2764"
HEART_EMPTY = "\u2661"
SPARKLES = "\u2728"
SUN = "\u2600"
MOON = "\u263d"

# ==============================================================================
# MATH / LOGIC
# ==============================================================================

SUMMATION = "\u2211"
PRODUCT = "\u220f"
INTEGRAL = "\u222b"
SQRT = "\u221a"
APPROX = "\u2248"
NOT_EQUAL = "\u2260"
LESS_EQUAL = "\u2264"
GREATER_EQUAL = "\u2265"
PLUSMINUS = "\u00b1"
PI = "\u03c0"
DELTA = "\u0394"
LAMBDA = "\u03bb"
MU = "\u03bc"
SIGMA = "\u03a3"
OMEGA = "\u03a9"

LOGIC_AND = "\u2227"
LOGIC_OR = "\u2228"
LOGIC_NOT = "\u00ac"
LOGIC_XOR = "\u2295"
LOGIC_NAND = "\u22bc"
LOGIC_NOR = "\u22bd"

# ==============================================================================
# CHARTS / DATA
# ==============================================================================

CHART_BAR = "\U0001f4ca"
CHART_LINE = "\U0001f4c8"
CHART_DOWN = "\U0001f4c9"

# ==============================================================================
# BRACKETS
# ==============================================================================

LBRACE = "\u007b"
RBRACE = "\u007d"
LBRACK = "\u005b"
RBRACK = "\u005d"
LANGLE = "\u27e8"
RANGLE = "\u27e9"

# ==============================================================================
# MISC SYMBOLS
# ==============================================================================

COPYRIGHT = "\u00a9"
REGISTERED = "\u00ae"
TRADEMARK = "\u2122"
SECTION = "\u00a7"
PARAGRAPH = "\u00b6"
DAGGER = "\u2020"
DOUBLE_DAGGER = "\u2021"
BULLET = "\u2022"
MIDDLE_DOT = "\u00b7"

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
