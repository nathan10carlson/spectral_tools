#!/bin/zsh
cd -- "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python app.py "$@"
elif [[ -x venv/bin/python ]]; then
  exec venv/bin/python app.py "$@"
else
  print "Create a virtual environment using the instructions in README.md."
  read "?Press Return to close."
  exit 1
fi
