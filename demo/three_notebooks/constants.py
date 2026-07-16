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
COMMANDS = (
    "plan",
    "auth",
    "auth-check",
    "login",
    "prepare",
    "assignments",
    "configure",
    "verify-upload",
)
