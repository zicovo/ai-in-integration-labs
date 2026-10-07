# The completion tier's test file. Copy it over policy/tools_test.rego to start:
#
#     cp tiers/completion/tools_test.rego policy/tools_test.rego
#     opa test policy/ -v
#
# Six cases, in the order the handout lists them. They start from the outcomes the legal team
# wants prevented, not from any rule, which is why they fail against the starting policy and why
# at least one of them must fail against any rule written only on the tool name.

package aquaflux.tools_test

import data.aquaflux.tools

approval_from_sam := {"action": "disconnection", "connection_id": "4471", "approver": "sam", "approver_role": "collections-team-lead"}

call(tool, arguments, approvals) := {
    "agent": "collections-agent",
    "on_behalf_of": "els",
    "tool": tool,
    "arguments": arguments,
    "approvals": approvals,
}

# 1. A call to any tool with no matching rule is denied.
test_unknown_tool_is_denied if {
    d := tools.decision with input as call("delete_customer", {"connection_id": "4471"}, [])
    d.effect == "deny"
}

# 2. A read-only tool listed for this agent in the register is allowed.
test_listed_read_is_allowed if {
    d := tools.decision with input as call("read_dunning_state", {"connection_id": "4471"}, [])
    d.effect == "allow"
}

# 3. Creating a disconnection with no approval is denied, and the rule name says why.
test_disconnection_without_approval_is_denied_by_an_approval_rule if {
    d := tools.decision with input as call("create_disconnection_work_order", {"connection_id": "4471", "reason": "arrears", "request_id": "r-1"}, [])
    d.effect == "deny"
    contains(d.rule, "approval")
}

# 4. The same call with a matching approval from a team lead who is not the acting person is allowed.
test_disconnection_with_a_bound_approval_is_allowed if {
    d := tools.decision with input as call("create_disconnection_work_order", {"connection_id": "4471", "reason": "arrears", "request_id": "r-2"}, [approval_from_sam])
    d.effect == "allow"
}

# 5. The same approval does not allow the call for a different connection id.
test_approval_for_one_connection_does_not_cover_another if {
    d := tools.decision with input as call("create_disconnection_work_order", {"connection_id": "4472", "reason": "arrears", "request_id": "r-3"}, [approval_from_sam])
    d.effect == "deny"
}

# 6. The generic work order tool reaches neither outcome the specific one could not.
test_generic_tool_cannot_create_an_unapproved_disconnection if {
    d := tools.decision with input as call("create_work_order", {"connection_id": "4471", "work_order_type": "disconnection", "request_id": "r-4"}, [])
    d.effect == "deny"
}

test_generic_tool_cannot_reuse_an_approval_for_another_connection if {
    d := tools.decision with input as call("create_work_order", {"connection_id": "4472", "work_order_type": "disconnection", "request_id": "r-5"}, [approval_from_sam])
    d.effect == "deny"
}

# Four eyes: an approval from the person the agent is acting for is not an approval.
test_self_approval_does_not_count if {
    d := tools.decision with input as call("create_disconnection_work_order", {"connection_id": "4471", "reason": "arrears", "request_id": "r-6"}, [{"action": "disconnection", "connection_id": "4471", "approver": "els", "approver_role": "collections-team-lead"}])
    d.effect == "deny"
}
