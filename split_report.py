import re

with open("app/services/report_service.py", "r", encoding="utf-8") as f:
    orig = f.read()

idx = orig.find("def _build_section_01")

part_1 = orig[:idx].rstrip() + "\n"
part_2 = orig[idx:]

imports = """
from app.services.report_builders import (
    _build_section_01, _build_section_02, _build_section_03,
    _build_section_04, _build_section_05, _build_section_06,
    _build_section_07, _build_section_08, _build_section_09,
    _build_section_10, _build_section_11, _build_section_12,
    _build_section_13, _build_section_14, _build_section_consortium,
    _fmt_amount
)
"""

new_part_1 = part_1.replace("from app.engines.scoring_engine import compute_pure_scorecard", "from app.engines.scoring_engine import compute_pure_scorecard\n" + imports)

with open("app/services/report_service.py", "w", encoding="utf-8") as f:
    f.write(new_part_1)

builders_content = '"""\napp/services/report_builders.py\nPure functions for generating Markdown report sections.\n"""\nfrom datetime import datetime, date\n\n' + part_2

with open("app/services/report_builders.py", "w", encoding="utf-8") as f:
    f.write(builders_content)

print("Split accomplished")
