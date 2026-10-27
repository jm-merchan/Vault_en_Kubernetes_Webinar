#!/usr/bin/env python3
"""Generate vault-benchmark Transit HCL with a fixed-size encrypt batch_input."""
from __future__ import annotations

import argparse
import base64
from pathlib import Path


TEMPLATE = """\
duration        = "60s"
report_mode     = "terse"
random_mounts   = false
cleanup         = false
disable_http2   = true
workers         = {workers}

test "transit_encrypt" "batch_encrypt" {{
  mount_name = "transit"
  weight = 95
  config {{
    use_existing_mount = true
    payload_len = 19
    keys {{
      name = "orders"
      type = "aes256-gcm96"
    }}
    encrypt {{
      name = "orders"
      batch_input = [
{batch_lines}
      ]
    }}
  }}
}}

test "transit_decrypt" "batch_decrypt" {{
  mount_name = "transit"
  weight = 5
  config {{
    use_existing_mount = true
    payload_len = 19
    keys {{
      name = "orders"
      type = "aes256-gcm96"
    }}
    decrypt {{
      name = "orders"
    }}
  }}
}}
"""


def plaintext_b64(n: int) -> str:
    # Same synthetic PAN pattern as vb-transit-1000.hcl / batch_input.json demos.
    pan = f"4000 0000 0000 {n:04d}"
    return base64.b64encode(pan.encode()).decode()


def render(count: int, workers: int = 10) -> str:
    lines = [
        f'        {{ plaintext = "{plaintext_b64(i)}" }}'
        + ("," if i < count else "")
        for i in range(1, count + 1)
    ]
    return TEMPLATE.format(workers=workers, batch_lines="\n".join(lines))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("count", type=int, nargs="+", help="batch_input sizes to generate")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = p.parse_args()
    for count in args.count:
        out = args.out_dir / f"vb-transit-{count}.hcl"
        out.write_text(render(count, args.workers))
        print(f"wrote {out} ({count} items)")


if __name__ == "__main__":
    main()
