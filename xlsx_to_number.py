import subprocess
import platform
from pathlib import Path


def xlsx_to_numbers_preserve_formatting(xlsx_path, output_numbers_path):
    current_os = platform.system()
    if current_os != "Darwin":
        print(f"this must be run in MacOS, the current OS is {current_os}")
        return

    xlsx_path = Path(xlsx_path).expanduser().resolve()
    output_numbers_path = Path(output_numbers_path).expanduser().resolve()

    if not xlsx_path.exists():
        raise FileNotFoundError(f"Input file not found: {xlsx_path}")

    output_numbers_path.parent.mkdir(parents=True, exist_ok=True)

    applescript = f'''
    tell application "Numbers"
        activate
        open POSIX file "{xlsx_path}"
        delay 3
        tell front document
            save in POSIX file "{output_numbers_path}"
        end tell
        close front document saving yes
    end tell
    '''

    subprocess.run(["osascript", "-e", applescript], check=True)
    print(f"Saved: {output_numbers_path}")


if __name__ == "__main__":
    xlsx_to_numbers_preserve_formatting(
        "results.xlsx",
        "output.numbers"
    )
