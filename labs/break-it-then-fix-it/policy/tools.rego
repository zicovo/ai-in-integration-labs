# The policy in force when break-it-then-fix-it starts: the weak state.
#
# Everything in the register for the agent is allowed, and the register for the collections agent
# lists the executing tool along with the four it should hold. Nothing here is wrong on its own;
# it is what a register-driven policy looks like before anybody has asked what the agent must
# never do. Step five of the handout replaces it with a rule that refuses the executing tool for
# this agent, whatever any note says.

package aquaflux.tools

default decision := {"effect": "deny", "rule": "default_deny"}

decision := {"effect": "allow", "rule": "in_register"} if {
    input.tool in data.register[input.agent].allowed_tools
}
