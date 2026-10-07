#!/usr/bin/env bash
# The labs by name, and the module each one belongs to. The participant sees names: the folder
# under labs/, the smoke test's argument, the handout's title. The module id is the maintainers'
# key, in curriculum/map.yaml, the decks and the decision records. curriculum/map.yaml carries the
# same pairs as `lab:` fields, and verify.sh fails when this table, that file and labs/ disagree.
lab_name() {   # module id -> lab name; a name passes through unchanged
  case "$1" in
    a-02) echo one-governed-call ;;
    b-01) echo index-the-manuals ;;
    b-02) echo ground-the-assistant ;;
    c-02) echo expose-one-operation ;;
    d-02) echo carry-the-authority ;;
    d-03) echo block-the-call ;;
    d-04) echo reconstruct-one-transaction ;;
    e-03) echo survive-the-crash ;;
    f-01) echo break-it-then-fix-it ;;
    one-governed-call) echo one-governed-call ;;
    index-the-manuals) echo index-the-manuals ;;
    ground-the-assistant) echo ground-the-assistant ;;
    expose-one-operation) echo expose-one-operation ;;
    carry-the-authority) echo carry-the-authority ;;
    block-the-call) echo block-the-call ;;
    reconstruct-one-transaction) echo reconstruct-one-transaction ;;
    survive-the-crash) echo survive-the-crash ;;
    break-it-then-fix-it) echo break-it-then-fix-it ;;
    *) return 1 ;;
  esac
}
lab_module() { # lab name -> module id
  case "$1" in
    one-governed-call) echo a-02 ;;
    index-the-manuals) echo b-01 ;;
    ground-the-assistant) echo b-02 ;;
    expose-one-operation) echo c-02 ;;
    carry-the-authority) echo d-02 ;;
    block-the-call) echo d-03 ;;
    reconstruct-one-transaction) echo d-04 ;;
    survive-the-crash) echo e-03 ;;
    break-it-then-fix-it) echo f-01 ;;
    *) return 1 ;;
  esac
}
