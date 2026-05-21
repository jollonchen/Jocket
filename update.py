with open("app.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_block = False
for i, line in enumerate(lines):
    if i == 1636: # line 1637 is 0-indexed 1636
        new_lines.append("if page != \"AI行情\":\n")
        new_lines.append("    with st.container(border=True):\n")
        in_block = True
    elif in_block and i >= 1709 and i <= 1717:
        pass # Skip the else: block which is lines 1710-1718
    elif in_block and i == 1718:
        new_lines.append("\n")
        in_block = False
    elif in_block:
        new_lines.append("    " + line)
    else:
        new_lines.append(line)

with open("app.py", "w") as f:
    f.writelines(new_lines)
