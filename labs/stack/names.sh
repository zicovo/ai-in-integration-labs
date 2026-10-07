#!/usr/bin/env bash
# The labs by name, paired with the module each belongs to (ADR-030). The participant sees the
# name: the folder under labs/, the smoke test's argument, the handout's title and file. The
# module id is the maintainers' key. The source of each pair is content/modules/<id>/module.yaml,
# labs[].id; this is the shell's copy, and `npm run validate` fails when the two disagree.
LABS="a-02:one-governed-call b-01:index-the-manuals b-02:ground-the-answer c-02:expose-one-operation d-02:carry-the-authority d-03:block-the-call d-04:reconstruct-one-transaction e-03:survive-the-crash f-01:break-it-then-fix-it"

lab_name() {   # a module id or a lab name -> the lab name; anything else fails
  local pair
  for pair in $LABS; do
    case "$1" in "${pair%%:*}"|"${pair#*:}") echo "${pair#*:}"; return 0 ;; esac
  done
  return 1
}
