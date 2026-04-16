import re

with open("schemas/ratio_schema.py", "r") as f:
    text = f.read()

# Find all Decimal fields in RatioSetSchema
# They are between "    current_ratio: Optional[Decimal] = None" and "    debt_repayment_years: Optional[Decimal] = None"
pattern = r"(    current_ratio: Optional\[Decimal\] = None.*    debt_repayment_years: Optional\[Decimal\] = None)"
match = re.search(pattern, text, re.DOTALL)
if match:
    block = match.group(1)
    
    variations_block = "\n    # Variations for Decimal fields\n"
    for line in block.split("\n"):
        field_match = re.match(r'^    ([a-zA-Z0-9_]+):\s+Optional\[Decimal\] = None', line)
        if field_match:
            field_name = field_match.group(1)
            variations_block += f"    {field_name}_variation_pct: Optional[float] = None\n"
    
    new_text = text.replace(block, block + "\n" + variations_block)

    with open("schemas/ratio_schema.py", "w") as f:
        f.write(new_text)
    print("Variations added successfully.")
else:
    print("Could not find the block.")

