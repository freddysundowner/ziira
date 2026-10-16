import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
sys.path.insert(0, str(Path(__file__).resolve().parent))
