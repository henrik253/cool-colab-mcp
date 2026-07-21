"""Constants owned by this standalone example project."""

NOTEBOOK_COUNT = 3
CPU_PROFILE = "prototype-cpu"
GPU_PROFILE = "debug-gpu"
CPU_COUNT = 2
GPU_COUNT = 1
PLACEHOLDER_MARKER = "REPLACE_WITH"
RUNTIME_DIR = "/content/cool-colab-demo"
UPLOAD_FILENAME = "test-upload.txt"
NOTEBOOK_SUFFIX = ".ipynb"
NOTEBOOK_DIRS_ENV = "COOL_COLAB_MCP_NOTEBOOK_DIRS"
UPLOAD_DIRS_ENV = "COOL_COLAB_MCP_UPLOAD_DIRS"
RUNTIME_PROFILES = {CPU_PROFILE: "NONE", GPU_PROFILE: "T4"}
SIGN_IN_MARKER = "Sign in"
# Colab renders these menus signed in or out; their presence means the app shell is up,
# so SIGN_IN_MARKER's absence is meaningful rather than "the page has not painted yet".
APP_READY_MARKERS = ("Runtime", "Insert")
LOGIN_TIMEOUT_S = 1800
LOGIN_POLL_S = 3
COMMANDS = (
    "plan",
    "auth",
    "auth-check",
    "login",
    "check-login",
    "prepare",
    "assignments",
    "configure",
    "verify-upload",
    "run-notebooks",
    "run",
    "chrome",
    "export-session",
    "session-check",
)
# Attaching to the operator's own Chrome (see README "Using your own Chrome").
# Chrome refuses remote debugging on the default profile, so this uses its own
# profile directory — a normal, non-automated Chrome where Google sign-in works.
CHROME_DEBUG_PORT = 9222
CHROME_PROFILE_DIR = "chrome-profile"
CHROME_APP = "Google Chrome"  # macOS app name for `open -na`
CHROME_LINUX_BIN = "google-chrome"
# 127.0.0.1, not "localhost": Chrome binds the debug port on IPv4 only, while
# localhost may resolve to ::1 first and refuse the connection.
CDP_URL = f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
SESSION_CHECK_POLLS = 10
