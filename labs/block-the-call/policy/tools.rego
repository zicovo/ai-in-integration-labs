# The rule you start with. Read it before you run anything.
#
# It is what a careful engineer writes on a Tuesday: it names the dangerous tool, it refuses the
# call when no approval is present, and its tests pass. block-the-call's worked tier asks you to run the
# attack it does not stop, then replace it with a rule written on what the call does.
#
# The gateway asks the policy engine for `data.aquaflux.tools.decision` on every tool call and
# reads `effect` and `rule` out of the answer. labs/README.md has the input it sends.

package aquaflux.tools

default decision := {"effect": "allow", "rule": "default_allow_known_tool"}

decision := {"effect": "deny", "rule": "disconnection_needs_approval"} if {
    input.tool == "create_disconnection_work_order"
    count(input.approvals) == 0
}
