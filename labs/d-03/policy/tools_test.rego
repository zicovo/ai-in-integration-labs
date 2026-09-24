# The tests that ship with the starting policy. On a fresh stack they all pass.
#
# That is the trap the handout warns you about. Every one of these starts from a rule and asks
# whether the rule does what it says. None starts from the outcome the legal team wants prevented
# and asks whether anything here prevents it. `opa test policy/ -v` runs them.

package aquaflux.tools_test

import data.aquaflux.tools

test_disconnection_without_approval_is_denied if {
    d := tools.decision with input as {
        "agent": "collections-agent",
        "on_behalf_of": "els",
        "tool": "create_disconnection_work_order",
        "arguments": {"connection_id": "4471", "reason": "arrears"},
        "approvals": [],
    }
    d.effect == "deny"
}

test_disconnection_with_an_approval_is_allowed if {
    d := tools.decision with input as {
        "agent": "collections-agent",
        "on_behalf_of": "els",
        "tool": "create_disconnection_work_order",
        "arguments": {"connection_id": "4471", "reason": "arrears"},
        "approvals": [{"action": "disconnection", "connection_id": "4471", "approver": "sam", "approver_role": "collections-team-lead"}],
    }
    d.effect == "allow"
}

test_reading_the_case_is_allowed if {
    d := tools.decision with input as {
        "agent": "collections-agent",
        "on_behalf_of": "els",
        "tool": "read_dunning_state",
        "arguments": {"connection_id": "4471"},
        "approvals": [],
    }
    d.effect == "allow"
}
