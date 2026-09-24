# The tests that ship with f-01. They pass against the starting policy and they keep passing
# against the fix in step five, because the fix removes one tool and leaves these four alone.
# The completion tier adds the test that fails if somebody puts the executing tool back.

package aquaflux.tools_test

import data.aquaflux.tools

call(tool) := {
    "agent": "collections-agent",
    "on_behalf_of": "els",
    "tool": tool,
    "arguments": {"connection_id": "4471"},
    "approvals": [],
}

test_reading_the_case_is_allowed if {
    tools.decision with input as call("read_dunning_state")
    d := tools.decision with input as call("read_dunning_state")
    d.effect == "allow"
}

test_reading_payments_is_allowed if {
    d := tools.decision with input as call("read_payments")
    d.effect == "allow"
}

test_sending_a_reminder_is_allowed if {
    d := tools.decision with input as call("send_reminder")
    d.effect == "allow"
}

test_proposing_a_disconnection_is_allowed if {
    d := tools.decision with input as call("propose_disconnection")
    d.effect == "allow"
}

test_a_tool_not_in_the_register_is_denied if {
    d := tools.decision with input as call("delete_customer")
    d.effect == "deny"
}
