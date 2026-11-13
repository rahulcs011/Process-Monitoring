#!/usr/bin/env python3
"""Entry point.

    python main.py                      # open the GUI
    python main.py --cli schedule       # compare all algorithms in the terminal
    python main.py --cli monitor        # top processes
    python main.py --cli tree           # process tree
    python main.py --cli real --algo rr # schedule real child processes
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from procsched.cli import main
        main(sys.argv[2:])
    else:
        from procsched.gui import main
        main()
