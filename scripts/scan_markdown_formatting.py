import os
import re


def scan_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    in_code_block = False
    code_block_indent = 0
    errors = []

    for i, line in enumerate(lines):
        stripped_right = line.rstrip()
        stripped_line = line.strip()

        # Detect code block start/end
        # We only care about fenced code blocks for now
        if stripped_line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_indent = len(line) - len(line.lstrip())
            else:
                in_code_block = False
                code_block_indent = 0
            continue

        if in_code_block:
            # Check 1: Continuation line starts at 0
            # Look at previous line
            if i > 0:
                prev_line = lines[i - 1].rstrip()
                if prev_line.endswith("\\"):
                    # Current line should be indented
                    if len(line) > 0 and line[0] not in (" ", "\t", "\n"):
                        errors.append((i + 1, "Continuation line starts at 0"))

            # Check 2: Indented code block content starts at 0
            if code_block_indent > 0:
                if len(line) > 1 and line[0] not in (" ", "\t"):
                    # Ignore empty lines or lines that are just newline
                    errors.append(
                        (i + 1, f"Indented code block content starts at 0 (block indent: {code_block_indent})")
                    )

    return errors


def main():
    root_dirs = ["core", "planning", "docs", "infra", "ui", "mobile", "dtp", "arch-viz"]
    # root_dirs = ['core'] # Testing

    cwd = os.getcwd()

    for root_dir in root_dirs:
        abs_root = os.path.join(cwd, root_dir)
        if not os.path.exists(abs_root):
            continue

        for dirpath, _, filenames in os.walk(abs_root):
            for filename in filenames:
                if filename.endswith(".md"):
                    filepath = os.path.join(dirpath, filename)
                    try:
                        errors = scan_file(filepath)
                        if errors:
                            print(f"File: {filepath}")
                            for line_num, msg in errors:
                                print(f"  Line {line_num}: {msg}")
                                # Print context
                                with open(filepath, "r") as f:
                                    all_lines = f.readlines()
                                    print(f"    {all_lines[line_num-1].rstrip()}")
                    except Exception as e:
                        print(f"Error reading {filepath}: {e}")


if __name__ == "__main__":
    main()
