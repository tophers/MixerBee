"""Shared storage location; override for isolated development/test instances."""
import os
from pathlib import Path

_default = Path('/config') if os.path.exists('/.dockerenv') else Path(__file__).parent / 'config'
CONFIG_DIR = Path(os.environ.get('MIXERBEE_CONFIG_DIR', str(_default))).expanduser().resolve()
ENV_PATH = CONFIG_DIR / '.env'
