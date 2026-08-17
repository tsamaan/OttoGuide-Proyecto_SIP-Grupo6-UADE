"""Legacy posture-changing HIL script, permanently disabled.

OttoGuide never changes robot posture. Use the Unitree operator remote for
all posture operations. This script intentionally initializes no SDK.
"""

import sys


def main() -> int:
    print("PROGRAMMATIC_POSTURE_CHANGE_PROHIBITED_USE_OPERATOR_REMOTE", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
