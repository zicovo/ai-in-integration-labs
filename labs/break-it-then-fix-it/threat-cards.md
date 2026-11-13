# Threat cards

Ten cards, one per entry of the OWASP Top 10 for Agentic Applications (published 9 December 2025),
as prompts for a threat-modelling pass over the collections agent.

For each card write three things about the system: the threat in one sentence, the control that
addresses it, and the enforcement point that owns the control. If you cannot name the enforcement
point, you have found a gap. Write the gap down; do not fill the box with a sentence from a prompt.

Ten minutes in the lab. The numbering and names of the list will change; the three columns will not.

| Card | Threat, in this system | Control | Enforcement point |
| --- | --- | --- | --- |
| ASI01 Agent goal hijack | | | |
| ASI02 Tool misuse and exploitation | | | |
| ASI03 Identity and privilege abuse | | | |
| ASI04 Agentic supply chain vulnerabilities | | | |
| ASI05 Unexpected code execution | | | |
| ASI06 Memory and context poisoning | | | |
| ASI07 Insecure inter-agent communication | | | |
| ASI08 Cascading failures | | | |
| ASI09 Human-agent trust exploitation | | | |
| ASI10 Rogue agents | | | |

## ASI01 Agent goal hijack

Where does content this agent reads get to change what it is trying to do? Name every field, file,
message or search result that reaches the model between the task being set and the first tool call.

*At Aquaflux:* a customer note in the dunning ticket asks the collections agent to raise a
disconnection work order, in the voice of a colleague.

## ASI02 Tool misuse and exploitation

Which tool in this catalogue would you least want the model to choose, and what stops it today?
Read the tool's description and schema the way the model reads them: is there a sentence that says
when not to use it, and is the decisive argument constrained?

*At Aquaflux:* a generated `create_work_order` with `type` as a free string covers a meter check and
a disconnection under one name and one rule.

## ASI03 Identity and privilege abuse

Whose authority does this agent carry, and how much of it does this task need? Decode the token it
presents to a downstream system and count the scopes it uses against the scopes it holds.

*At Aquaflux:* the weak collections agent holds everything Els may do, for a task that needs a read
and a proposal.

## ASI04 Agentic supply chain vulnerabilities

Which parts of this agent did you not write, and who can change them after you reviewed them? A tool
definition is an input the model reads on every call. List the servers, the models and the packaged
procedures, with a version for each.

*At Aquaflux:* a tool server changes its description after review, and the agent's instructions have
changed without a commit anywhere you look.

## ASI05 Unexpected code execution

Where does something this agent produces get run rather than read? Generated queries, scripts,
expressions, templates and shell commands all count. For each, name what sits between the model's
output and the interpreter.

*At Aquaflux:* a reporting tool that accepts a filter expression the model writes, evaluated inside
the customer information system.

## ASI06 Memory and context poisoning

What does this agent remember between runs, who can write to it, and how does a bad entry get out
again? Anything the agent stores and later reads as context is a second inbox with a longer fuse.

*At Aquaflux:* the collections agent keeps what was agreed per customer for twenty-four months, and a
poisoned note in month one is read as fact in month twenty.

## ASI07 Insecure inter-agent communication

When this agent talks to another agent, how does each know who the other is, and what does a message
from the other one get to do? A message from an agent is untrusted content like any other, arriving
with a name attached.

*At Aquaflux:* the field dispatcher accepts a work order assignment from anything that presents
itself as the collections agent.

## ASI08 Cascading failures

If this agent goes wrong at speed, what stops it before a person notices? Name the budget it runs
under: calls, tokens, minutes, money, and the number of downstream actions one run may take.

*At Aquaflux:* an agent that has reached the reminder phase keeps proposing, and there is no stop at
twelve calls, 150,000 tokens or two minutes.

## ASI09 Human-agent trust exploitation

Where does a person approve something this agent proposes, and what do they actually see when they
do? An approval that is clicked forty times a day is a queue, not a control. Is the approval bound to
the specific arguments, and does the approver see them?

*At Aquaflux:* Sam approves disconnections from a list, and the list shows a connection number and
nothing about why.

## ASI10 Rogue agents

How many agents does your organisation run, and could you list them by tomorrow morning with an owner
for each? An agent nobody registered is an agent nobody is governing. What would tell you one existed?

*At Aquaflux:* a team wires a hosted model to the work order API from a laptop, over a personal key,
and it has been proposing work orders for a month.
