import unittest

from nexus_core import (AutonomyLevel, CommandSpec, Nexus, Risk, Step, owner,
                        ALL_PERMISSIONS)
from nexus_core.control import CommandStatus
from nexus_core.intelligence import AgentRole, MemoryLayer, Message, NoModelAvailable
from nexus_core.kernel import (AuthorityLevel, EmergencyStopActive, NotFound,
                               PermissionDenied, Principal)
from nexus_core.automation import RunStatus


def setup():
    nx = Nexus()
    boss = owner("t1", "boss")
    nx.core.policy.register(CommandSpec("echo", "nexus.command.execute"))
    nx.core.policy.register(CommandSpec("deploy", "nexus.command.execute", Risk.HIGH))
    nx.core.policy.register(CommandSpec("wipe", "nexus.command.execute",
                                        Risk.CRITICAL, reversible=False))
    nx.core.commands.register_handler("echo", lambda c, a: c.payload.get("v"),
                                      undo=lambda c, a: None)
    nx.core.commands.register_handler("deploy", lambda c, a: "deployed")
    nx.core.commands.register_handler("wipe", lambda c, a: "wiped")
    return nx, boss


class CommandTests(unittest.TestCase):
    def test_low_risk_runs_directly(self):
        nx, boss = setup()
        c = nx.core.commands.submit(boss, "echo", {"v": 7})
        self.assertEqual(c.status, CommandStatus.APPROVED)
        c = nx.core.commands.execute(boss, c.id)
        self.assertEqual((c.status, c.result), (CommandStatus.COMPLETED, 7))

    def test_unknown_command_fail_closed(self):
        nx, boss = setup()
        with self.assertRaises(PermissionDenied):
            nx.core.commands.submit(boss, "nope")

    def test_high_risk_needs_different_approver(self):
        nx, boss = setup()
        c = nx.core.commands.submit(boss, "deploy")
        self.assertEqual(c.status, CommandStatus.PENDING_APPROVAL)
        with self.assertRaises(PermissionDenied):
            nx.core.commands.approve(boss, c.id)
        nx.core.commands.approve(owner("t1", "boss2"), c.id)
        self.assertEqual(nx.core.commands.execute(boss, c.id).status,
                         CommandStatus.COMPLETED)

    def test_critical_needs_human(self):
        nx, boss = setup()
        c = nx.core.commands.submit(boss, "wipe")
        director = Principal("dir", "t1", AuthorityLevel.SYSTEM_DIRECTOR,
                             AutonomyLevel.L5_STRATEGIC, ALL_PERMISSIONS)
        with self.assertRaises(PermissionDenied):
            nx.core.commands.approve(director, c.id)

    def test_emergency_stop(self):
        nx, boss = setup()
        nx.core.stop.activate(boss)
        with self.assertRaises(EmergencyStopActive):
            nx.core.commands.submit(boss, "echo")
        nx.core.stop.clear(boss)
        nx.core.commands.submit(boss, "echo")

    def test_tenant_isolation(self):
        nx, boss = setup()
        c = nx.core.commands.submit(boss, "echo")
        with self.assertRaises(NotFound):
            nx.core.commands.get("t2", c.id)

    def test_failure_and_rollback(self):
        nx, boss = setup()
        nx.core.policy.register(CommandSpec("boom", "nexus.command.execute"))
        nx.core.commands.register_handler("boom", lambda c, a: 1 / 0)
        c = nx.core.commands.execute(boss, nx.core.commands.submit(boss, "boom").id)
        self.assertEqual(c.status, CommandStatus.FAILED)
        e = nx.core.commands.execute(boss, nx.core.commands.submit(boss, "echo").id)
        self.assertEqual(nx.core.commands.rollback(boss, e.id).status,
                         CommandStatus.ROLLED_BACK)

    def test_audit_chain_tamper_detected(self):
        nx, boss = setup()
        nx.core.commands.submit(boss, "echo")
        self.assertTrue(nx.core.audit.verify())
        rec = nx.core.audit._records[0]
        object.__setattr__(rec, "actor", "hacker")
        self.assertFalse(nx.core.audit.verify())


class AgentTests(unittest.TestCase):
    def test_agent_lifecycle_and_invoke(self):
        nx, boss = setup()
        nx.core.models.register(boss, name="m", provider="echo", identifier="e1",
                                capabilities={"chat"})
        a = nx.core.agents.create(boss, name="R", role=AgentRole.RESEARCH,
                                  instructions="research", permissions={"nexus.ai.infer"},
                                  autonomy=AutonomyLevel.L2_RECOMMEND)
        out = nx.core.agents.invoke(boss, a.id, "hello world")
        self.assertIn("hello world", out.content)
        self.assertEqual(len(nx.core.memory.recall(a.principal, "hello")), 1)

    def test_no_privilege_escalation(self):
        nx, boss = setup()
        a = nx.core.agents.create(boss, name="A", role=AgentRole.QA, instructions="",
                                  permissions={"nexus.command.execute"},
                                  autonomy=AutonomyLevel.L3_EXECUTE_APPROVED)
        with self.assertRaises(PermissionDenied):   # agents can't create agents
            nx.core.agents.create(a.principal, name="B", role=AgentRole.QA,
                                  instructions="", permissions=set(),
                                  autonomy=AutonomyLevel.L0_READ_ONLY)
        # L3 agent: even low-risk commands need approval; agent can't approve
        c = nx.core.commands.submit(a.principal, "echo")
        self.assertEqual(c.status, CommandStatus.PENDING_APPROVAL)
        with self.assertRaises(PermissionDenied):
            nx.core.commands.approve(a.principal, c.id)

    def test_model_fallback(self):
        nx, boss = setup()

        class Bad:
            name = "bad"
            def generate(self, *a):
                raise RuntimeError("down")
        nx.core.ai.add_provider(Bad())
        nx.core.models.register(boss, name="a", provider="bad", identifier="x",
                                capabilities={"chat"}, priority=10)
        nx.core.models.register(boss, name="b", provider="echo", identifier="y",
                                capabilities={"chat"})
        r = nx.core.ai.infer(boss, [Message("user", "hi")])
        self.assertIn("[y]", r.content)

    def test_no_model(self):
        nx, boss = setup()
        with self.assertRaises(NoModelAvailable):
            nx.core.ai.infer(boss, [Message("user", "hi")])

    def test_memory_isolated_per_owner(self):
        nx, boss = setup()
        other = owner("t1", "other")
        nx.core.memory.remember(boss, MemoryLayer.WORKING, "secret plan")
        self.assertEqual(nx.core.memory.recall(other, "secret plan"), [])


class WorkflowTests(unittest.TestCase):
    def test_workflow_with_retry(self):
        nx, boss = setup()
        calls = {"n": 0}

        def flaky(c, a):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return "ok"
        nx.core.policy.register(CommandSpec("flaky", "nexus.command.execute"))
        nx.core.commands.register_handler("flaky", flaky)
        nx.core.workflows.define(boss, "wf", [Step("s1", "echo", {"v": 1}),
                                              Step("s2", "flaky", max_attempts=3)])
        run = nx.core.workflows.run(boss, "wf")
        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.step_results, {"s1": 1, "s2": "ok"})

    def test_workflow_pauses_for_approval(self):
        nx, boss = setup()
        nx.core.workflows.define(boss, "wf", [Step("d", "deploy")])
        self.assertEqual(nx.core.workflows.run(boss, "wf").status,
                         RunStatus.WAITING_APPROVAL)


if __name__ == "__main__":
    unittest.main()
