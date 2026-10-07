"""Tool policy: which agent may call which tool, on whose authority, and what happens if not.

A policy is a short YAML document with an id and a version, because four handouts ask a learner
to read one, diff two, or write a third. It is deliberately not code. `block-the-call` moves the decision
out to Open Policy Agent and rewrites these rules in Rego; the shape below is what that has to
reproduce, and `decide()` is the seam.

Two engines sit behind that seam, chosen per policy document (ADR-022):

    engine: rules   the rules in the document itself, matched in order, as below
    engine: opa     the document names a policy engine, and every call is put to it as
                    `data.aquaflux.tools.decision`. The rules live in the learner's own
                    `policy/*.rego`, loaded with `aqx policy apply`, and the version is the
                    hash of what the engine currently holds, so a log line can be traced back to
                    the exact text that decided it

Whatever decided, the answer has one shape, because three labs read the same decision record.

Three decisions, and the third is the one the course is about:

    allow   the call goes to the tool
    deny    the call does not happen and the log says why
    hold    the call does not happen yet, because a named human has to agree first

A gateway that can only allow and deny pushes every judgement into the model's prompt. `hold` is
what lets a rule say "not without Sam", which is the rule expose-one-operation asks the learner to write and the
reason the catalogue has to be split before it can be written at all.
"""

from __future__ import annotations

import fnmatch
import pathlib
from dataclasses import dataclass, field

import yaml

POLICY_DIR = pathlib.Path(__file__).resolve().parent.parent / "policies"


@dataclass
class Rule:
    tool: str
    decision: str = "allow"
    agents: list[str] = field(default_factory=list)
    scope: str | None = None
    approver: str | None = None
    action: str | None = None  # what an approval releasing this hold has to be for
    reason: str | None = None

    def matches(self, tool: str, agent: str | None) -> bool:
        # A glob, so a rule can say `list_*` and cover the reads without twelve near-identical
        # lines. Globs are how a rule stops being readable, so the ones that matter in these
        # labs name a tool exactly and only the harmless reads are matched by a pattern.
        if not fnmatch.fnmatchcase(tool, self.tool):
            return False
        if self.agents and agent not in self.agents:
            return False
        return True


@dataclass
class Policy:
    id: str
    version: str
    description: str = ""
    identity: str = "optional"  # none, optional, required
    audience: str | None = None
    default: str = "deny"
    default_reason: str = "no rule in this policy names this tool"
    rules: list[Rule] = field(default_factory=list)
    engine: str = "rules"  # rules, or opa
    opa_url: str | None = None  # engine: opa only, the service to ask
    opa_package: str = "aquaflux/tools"  # engine: opa only, the document that decides
    # enforce, or log-only. Log-only asks the engine as usual, records what it decided with
    # `enforced: false`, and forwards the call anyway: the shadow run before a policy is switched
    # on, which block-the-call's instructor note asked for. Identity and an unknown tool are refused either
    # way, because those are not the policy's decision.
    enforcement: str = "enforce"

    @classmethod
    def load(cls, path: pathlib.Path) -> "Policy":
        document = yaml.safe_load(path.read_text())
        rules = [Rule(**rule) for rule in document.pop("rules", [])]
        return cls(rules=rules, **document)

    def as_dict(self) -> dict:
        out = {
            "id": self.id,
            "version": self.version,
            "engine": self.engine,
            "enforcement": self.enforcement,
            "description": self.description,
            "identity": self.identity,
            "audience": self.audience,
            "default": self.default,
            "rules": [vars(rule) for rule in self.rules],
        }
        if self.engine == "opa":
            out["opa_url"] = self.opa_url
            out["opa_package"] = self.opa_package
        return out


@dataclass
class Decision:
    decision: str
    reason: str
    rule: dict | str | None = None
    approver: str | None = None
    status: int = 200
    approval_id: str | None = None  # the approval that released a hold, when one did


def available() -> dict[str, Policy]:
    return {path.stem: Policy.load(path) for path in sorted(POLICY_DIR.glob("*.yaml"))}


def decide(policy: Policy, tool: str, identity: dict, arguments: dict | None = None,
           approvals: list[dict] | None = None) -> Decision:
    """Decide one call with the rules in the document. `engine: opa` documents go through opa.py.

    The order of the checks is load-bearing and carry-the-authority grades on it: a token that is both addressed
    to the wrong resource and carries too much scope is refused for its audience first, because
    an audience says which door this key was cut for and a scope says what it opens once inside.
    A learner who can say which fault the gateway caught first has understood the difference.
    """
    agent = identity.get("agent")
    person = identity.get("person")

    if policy.identity == "required" and not identity.get("token"):
        return Decision("deny", "this policy requires a token and none was presented", status=401)

    rule = next((r for r in policy.rules if r.matches(tool, agent)), None)
    if rule is None:
        return Decision("deny", policy.default_reason, status=403) if policy.default == "deny" \
            else Decision("allow", "the default of this policy is allow")

    if policy.audience and identity.get("token"):
        audiences = identity.get("audiences") or []
        if audiences != [policy.audience]:
            return Decision(
                "deny",
                f"this token is addressed to {audiences or ['nothing']} and this tool only "
                f"accepts a token addressed to {policy.audience} and to nothing else",
                rule=vars(rule),
                status=401,
            )

    if rule.scope and identity.get("token"):
        if rule.scope not in (identity.get("scopes") or []):
            return Decision(
                "deny",
                f"this tool needs the scope {rule.scope} and the token carries "
                f"{identity.get('scopes') or ['none']}",
                rule=vars(rule),
                status=403,
            )

    if rule.decision == "hold":
        # A hold is not a dead end. An approval from the named approver, for the action this
        # rule names, bound to the connection in the call, releases it. That binding is the
        # whole of what makes an approval evidence rather than theatre (block-the-call), and it is why the
        # approval carries a connection id rather than a yes.
        released = _releasing_approval(rule, arguments or {}, approvals or [], person)
        if released:
            return Decision(
                "allow",
                f"held for {rule.approver} and released by approval {released['approval_id']} "
                f"for connection {released.get('connection_id')}",
                rule=vars(rule),
                approver=rule.approver,
                approval_id=released["approval_id"],
            )
        return Decision(
            "hold",
            rule.reason or f"this tool is held for {rule.approver}, who is not {person or 'the caller'}",
            rule=vars(rule),
            approver=rule.approver,
            status=202,
        )

    if rule.decision == "deny":
        return Decision("deny", rule.reason or "this policy refuses this tool", rule=vars(rule), status=403)

    return Decision("allow", rule.reason or f"allowed by {policy.id}", rule=vars(rule))


def _releasing_approval(rule: Rule, arguments: dict, approvals: list[dict], person: str | None) -> dict | None:
    """The first active approval that releases this hold, or None.

    Four conditions, the same four block-the-call asks the learner to write in Rego: the named approver
    gave it, for the action the rule names, for the connection in these arguments, and the
    approver is not the person the agent is acting for.
    """
    connection = str(arguments.get("connection_id") or "")
    for approval in approvals:
        if rule.approver and approval.get("approver") != rule.approver:
            continue
        if rule.action and approval.get("action") != rule.action:
            continue
        if connection and str(approval.get("connection_id")) != connection:
            continue
        if person and approval.get("approver") == person:
            continue
        return approval
    return None
